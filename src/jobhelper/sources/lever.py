"""Lever public Postings API (keyless).
GET https://api.lever.co/v0/postings/{site}?mode=json"""
from __future__ import annotations

from ..models import RawJob
from ..util import get_logger, html_to_text
from .base import JobSource

log = get_logger()
BASE = "https://api.lever.co/v0/postings"

_REMOTE_MAP = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite",
               "onsite": "onsite"}


class LeverSource(JobSource):
    name = "lever"

    def __init__(self, fetcher, cap: int, sites: list[str]) -> None:
        super().__init__(fetcher, cap)
        self.sites = sites

    def fetch(self) -> list[RawJob]:
        jobs: list[RawJob] = []
        for site in self.sites:
            url = f"{BASE}/{site}"
            try:
                data = self.fetcher.get_json(url, params={"mode": "json"})
            except Exception as exc:
                log.warning("lever[%s]: fetch failed: %s", site, exc)
                continue
            if not isinstance(data, list):
                continue
            company = site.replace("-", " ").title()
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
        log.info("lever: %d jobs from %d sites", len(jobs), len(self.sites))
        return jobs[: self.cap]
