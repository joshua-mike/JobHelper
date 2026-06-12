"""Greenhouse public Job Board API (keyless).
GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
Pulls ALL of a company's published jobs; the hard filter drops non-remote ones."""
from __future__ import annotations

from ..models import RawJob
from ..util import get_logger, html_to_text
from .base import JobSource

log = get_logger()
BASE = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseSource(JobSource):
    name = "greenhouse"

    def __init__(self, fetcher, cap: int, tokens: list[str]) -> None:
        super().__init__(fetcher, cap)
        self.tokens = tokens

    def fetch(self) -> list[RawJob]:
        jobs: list[RawJob] = []
        for token in self.tokens:
            url = f"{BASE}/{token}/jobs"
            try:
                data = self.fetcher.get_json(url, params={"content": "true"})
            except Exception as exc:
                log.warning("greenhouse[%s]: fetch failed: %s", token, exc)
                continue
            company = token.replace("-", " ").title()
            for item in (data.get("jobs") or []):
                try:
                    loc = (item.get("location") or {}).get("name", "") or ""
                    remote = "remote" if "remote" in loc.lower() else "unknown"
                    jobs.append(RawJob(
                        source=self.name,
                        source_job_id=str(item.get("id", "")),
                        url=item.get("absolute_url", ""),
                        title=item.get("title", ""),
                        company=company,
                        location=loc,
                        candidate_location=loc,
                        remote_type=remote,
                        description_raw=item.get("content", "") or "",
                        description_clean=html_to_text(item.get("content")),
                        date_posted=item.get("updated_at"),
                        tags=[token],
                        extra={"board_token": token},
                    ))
                except Exception as exc:
                    log.warning("greenhouse[%s]: bad record: %s", token, exc)
        log.info("greenhouse: %d jobs from %d boards", len(jobs), len(self.tokens))
        return jobs[: self.cap]
