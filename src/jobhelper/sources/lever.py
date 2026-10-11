"""Lever public Postings API (keyless).
GET https://api.lever.co/v0/postings/{site}?mode=json

The cap counts NEW postings only and is split across boards by
JobSource._share_fetched (ITEM-39)."""
from __future__ import annotations

from typing import Callable

from ..models import RawJob
from ..util import get_logger, html_to_text
from .base import JobSource

log = get_logger()
BASE = "https://api.lever.co/v0/postings"

_REMOTE_MAP = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite",
               "onsite": "onsite"}


class LeverSource(JobSource):
    name = "lever"

    def __init__(self, fetcher, cap: int, sites: list[str],
                 is_known: Callable[[str], bool] | None = None) -> None:
        super().__init__(fetcher, cap, is_known)
        self.sites = sites

    def fetch(self) -> list[RawJob]:
        return self._share_fetched(self.sites, self._fetch_board)

    def _fetch_board(self, site: str) -> list[RawJob]:
        """Every posting on one board, stored or not; [] if the fetch fails."""
        url = f"{BASE}/{site}"
        try:
            data = self.fetcher.get_json(url, params={"mode": "json"})
        except Exception as exc:
            log.warning("lever[%s]: fetch failed: %s", site, exc)
            return []
        if not isinstance(data, list):
            return []
        company = site.replace("-", " ").title()
        jobs: list[RawJob] = []
        for item in data:
            try:
                cats = item.get("categories") or {}
                loc = cats.get("location", "") or ""
                workplace = (item.get("workplaceType") or "").lower()
                remote = _REMOTE_MAP.get(workplace,
                                         "remote" if "remote" in loc.lower() else "unknown")
                created = item.get("createdAt")
                # Lever timestamps are epoch milliseconds.
                if isinstance(created, (int, float)):
                    created = created / 1000.0
                plain = item.get("descriptionPlain")
                jobs.append(RawJob(
                    source=self.name,
                    source_job_id=str(item.get("id", "")),
                    url=item.get("hostedUrl", "") or item.get("applyUrl", ""),
                    title=item.get("text", ""),
                    company=company,
                    location=loc,
                    candidate_location=loc,
                    remote_type=remote,
                    description_raw=item.get("description", "") or "",
                    description_clean=plain or html_to_text(item.get("description")),
                    date_posted=created,
                    tags=[v for v in (cats.get("team"), cats.get("commitment"),
                                      cats.get("department")) if v],
                    extra={"site": site},
                ))
            except Exception as exc:
                log.warning("lever[%s]: bad record: %s", site, exc)
        return jobs
