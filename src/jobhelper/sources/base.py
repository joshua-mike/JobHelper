"""JobSource interface + a polite HTTP fetcher (throttle, retry, debug cache)."""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..models import RawJob
from ..util import CACHE_DIR, get_logger, stable_hash

log = get_logger()

# A browser-like UA avoids trivial blocks on RemoteOK/Arbeitnow while staying honest
# about being a low-volume personal tool.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JobHelper/0.1 "
    "(personal job-search tool; low volume)"
)
_RETRY_STATUS = {429, 500, 502, 503, 504}


class Fetcher:
    """Shared HTTP client with per-host throttling and retry/backoff."""

    def __init__(self, delay: float = 1.0, timeout: float = 30.0,
                 use_cache: bool = False, max_retries: int = 3) -> None:
        self.delay = delay
        self.use_cache = use_cache
        self.max_retries = max_retries
        self._last: dict[str, float] = {}
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        last = self._last.get(host)
        if last is not None:
            wait = self.delay - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last[host] = time.monotonic()

    def _cache_path(self, url: str, params: dict | None):
        key = stable_hash(url, json.dumps(params or {}, sort_keys=True))
        return CACHE_DIR / f"{key}.json"

    def get_json(self, url: str, params: dict | None = None,
                 headers: dict | None = None) -> Any:
        cache = self._cache_path(url, params)
        if self.use_cache and cache.exists():
            log.debug("cache hit %s", url)
            return json.loads(cache.read_text(encoding="utf-8"))

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle(url)
            try:
                resp = self._client.get(url, params=params, headers=headers)
                if resp.status_code in _RETRY_STATUS:
                    wait = _retry_after(resp, attempt)
                    log.warning("%s -> HTTP %s, retry %d/%d in %.1fs", url,
                                resp.status_code, attempt, self.max_retries, wait)
                    time.sleep(wait)
                    continue
                if resp.status_code >= 400:
                    # Non-retryable client error (e.g. 404 bad slug) — fail fast.
                    raise RuntimeError(f"GET {url} -> HTTP {resp.status_code}")
                data = resp.json()
                try:  # write-through cache for debugging re-runs
                    cache.write_text(json.dumps(data), encoding="utf-8")
                except Exception:
                    pass
                return data
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                last_err = exc
                wait = 2 ** (attempt - 1)
                log.warning("%s -> %s, retry %d/%d in %.0fs", url, exc,
                            attempt, self.max_retries, wait)
                time.sleep(wait)
        raise RuntimeError(f"GET failed after {self.max_retries} tries: {url}") \
            from last_err


def _retry_after(resp: httpx.Response, attempt: int) -> float:
    ra = resp.headers.get("Retry-After")
    if ra and ra.isdigit():
        return min(float(ra), 30.0)
    return float(2 ** (attempt - 1))


class JobSource(ABC):
    """One adapter per source. fetch() yields normalized RawJob records."""
    name: str = "base"

    def __init__(self, fetcher: Fetcher, cap: int = 400) -> None:
        self.fetcher = fetcher
        self.cap = cap

    @abstractmethod
    def fetch(self) -> list[RawJob]:
        ...
