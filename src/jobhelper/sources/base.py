"""JobSource interface + a polite HTTP fetcher (throttle, retry, debug cache)."""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Sequence
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
    """Shared HTTP client with per-host throttling, retry/backoff and a breaker."""

    def __init__(self, delay: float = 1.0, timeout: float = 30.0,
                 use_cache: bool = False, max_retries: int = 3,
                 host_fail_limit: int = 3) -> None:
        self.delay = delay
        self.use_cache = use_cache
        self.max_retries = max_retries
        self.host_fail_limit = host_fail_limit
        self._last: dict[str, float] = {}
        self._fails: dict[str, int] = {}
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def _host_is_down(self, host: str) -> bool:
        return self._fails.get(host, 0) >= self.host_fail_limit

    def _record(self, host: str, ok: bool) -> None:
        """Track consecutive give-ups per host so one dead tenant can't eat the run."""
        if ok:
            self._fails[host] = 0
            return
        self._fails[host] = self._fails.get(host, 0) + 1
        if self._fails[host] == self.host_fail_limit:
            log.warning("%s: %d consecutive failures, skipping this host for the "
                        "rest of the run", host, self.host_fail_limit)

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
        return self._send("GET", url, params=params, headers=headers)

    def post_json(self, url: str, json_body: dict, headers: dict | None = None) -> Any:
        """POST a JSON body and return parsed JSON (same throttle/retry/cache as GET).
        Cache key includes the body, so different POST payloads cache separately."""
        return self._send("POST", url, json_body=json_body, headers=headers)

    def _send(self, method: str, url: str, params: dict | None = None,
              json_body: dict | None = None, headers: dict | None = None) -> Any:
        cache = self._cache_path(url, params if params is not None else json_body)
        if self.use_cache and cache.exists():
            log.debug("cache hit %s", url)
            return json.loads(cache.read_text(encoding="utf-8"))

        host = urlsplit(url).netloc
        if self._host_is_down(host):
            raise RuntimeError(f"{host} marked down this run, skipped: {url}")

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle(url)
            # Workday/Cloudflare pin a client to one backend instance via __cflb +
            # wday_vps_cookie/PLAY_SESSION. Replaying those sends every retry back to
            # the same (possibly sick) instance, so a transient backend failure looks
            # like a total outage. Every source here is keyless, so drop the jar each
            # attempt and let the load balancer route us somewhere healthy.
            self._client.cookies.clear()
            try:
                if method == "POST":
                    resp = self._client.post(url, json=json_body, headers=headers)
                else:
                    resp = self._client.get(url, params=params, headers=headers)
                if resp.status_code in _RETRY_STATUS:
                    last_err = RuntimeError(f"HTTP {resp.status_code}")
                    if attempt == self.max_retries:
                        break
                    wait = _retry_after(resp, attempt)
                    log.warning("%s -> HTTP %s, retry %d/%d in %.1fs", url,
                                resp.status_code, attempt, self.max_retries, wait)
                    time.sleep(wait)
                    continue
                if resp.status_code >= 400:
                    # Non-retryable client error (e.g. 404 bad slug) — fail fast.
                    raise RuntimeError(f"{method} {url} -> HTTP {resp.status_code}")
                data = resp.json()
                try:  # write-through cache for debugging re-runs
                    cache.write_text(json.dumps(data), encoding="utf-8")
                except Exception:
                    pass
                self._record(host, True)
                return data
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                last_err = exc
                if attempt == self.max_retries:
                    break
                wait = 2 ** (attempt - 1)
                log.warning("%s -> %s, retry %d/%d in %.0fs", url, exc,
                            attempt, self.max_retries, wait)
                time.sleep(wait)
        self._record(host, False)
        raise RuntimeError(f"{method} failed after {self.max_retries} tries: "
                           f"{url} ({last_err})") from last_err


def _retry_after(resp: httpx.Response, attempt: int) -> float:
    ra = resp.headers.get("Retry-After")
    if ra and ra.isdigit():
        return min(float(ra), 30.0)
    return float(2 ** (attempt - 1))


class JobSource(ABC):
    """One adapter per source. fetch() yields normalized RawJob records."""
    name: str = "base"

    def __init__(self, fetcher: Fetcher, cap: int = 400,
                 is_known: Callable[[str], bool] | None = None) -> None:
        self.fetcher = fetcher
        self.cap = cap
        # job_hash -> already stored? The pipeline passes a DB lookup; without
        # one (Settings Verify) every posting is treated as new.
        self.is_known = is_known or (lambda _job_hash: False)

    @abstractmethod
    def fetch(self) -> list[RawJob]:
        ...

    def _share_cap(self, boards: Sequence[Any],
                   crawl: Callable[[Any, int], tuple[list[RawJob], int]]) -> list[RawJob]:
        """Crawl every board, giving each a fair share of the cap.

        Each board may take an equal share of what's left of the cap; one that
        needs less leaves the rest to the boards after it. `crawl(board, share)`
        returns up to `share` NEW postings and how many stored ones it skipped,
        so a share is spent only on new ones (ITEM-37, ITEM-39: first-come, the
        first boards in sources.yaml used all of it and the rest never landed).
        """
        jobs: list[RawJob] = []
        skipped = 0
        for i, board in enumerate(boards):
            left = self.cap - len(jobs)
            if left <= 0:  # only when cap < number of boards
                log.info("%s: hit cap %d; %d boards not crawled",
                         self.name, self.cap, len(boards) - i)
                break
            share = max(1, left // (len(boards) - i))
            new, board_skipped = crawl(board, share)
            jobs.extend(new)
            skipped += board_skipped
        log.info("%s: %d new jobs from %d boards (%d stored postings skipped)",
                 self.name, len(jobs), len(boards), skipped)
        return jobs

    def _share_fetched(self, boards: Sequence[str],
                       fetch_board: Callable[[str], list[RawJob]]) -> list[RawJob]:
        """Fetch every board whole, then split the cap max-min fairly over their
        NEW postings.

        `fetch_board(board)` returns all of a board's postings ([] on failure).
        Stored postings and repeats are dropped first, so the cap counts new ones
        only. Boards are then served smallest first, each taking its new postings
        or an equal share of what's left, whichever is less: what a small board
        doesn't need goes to the bigger ones wherever they sit in sources.yaml.
        Unlike _share_cap, every posting is already in hand here; _share_cap must
        settle a board's share before paying for its detail calls, so its unused
        share can only carry forward (ITEM-39).
        """
        seen: set[str] = set()
        fetched: list[tuple[str, list[RawJob], int]] = []  # board, new, stored skipped
        for board in boards:
            new: list[RawJob] = []
            skipped = 0
            for job in fetch_board(board):
                h = job.job_hash
                if h in seen:
                    continue
                seen.add(h)
                if self.is_known(h):
                    skipped += 1
                else:
                    new.append(job)
            fetched.append((board, new, skipped))

        kept = [0] * len(fetched)
        left = self.cap
        by_size = sorted(range(len(fetched)), key=lambda i: len(fetched[i][1]))
        for n, i in enumerate(by_size):
            kept[i] = min(len(fetched[i][1]), left // (len(by_size) - n))
            left -= kept[i]

        jobs: list[RawJob] = []
        for (board, new, skipped), k in zip(fetched, kept):
            if k < len(new):
                log.info("%s[%s]: %d new (share reached, %d more next run), %d stored skipped",
                         self.name, board, k, len(new) - k, skipped)
            else:
                log.info("%s[%s]: %d new, %d stored skipped",
                         self.name, board, k, skipped)
            jobs.extend(new[:k])
        log.info("%s: %d new jobs from %d boards (%d stored postings skipped)",
                 self.name, len(jobs), len(boards), sum(s for _, _, s in fetched))
        return jobs
