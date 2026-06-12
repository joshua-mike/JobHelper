"""Arbeitnow — keyless job board API. https://www.arbeitnow.com/api/job-board-api"""
from __future__ import annotations

from ..models import RawJob
from ..util import get_logger, html_to_text
from .base import JobSource

log = get_logger()
URL = "https://www.arbeitnow.com/api/job-board-api"


class ArbeitnowSource(JobSource):
    name = "arbeitnow"

    def fetch(self) -> list[RawJob]:
        data = self.fetcher.get_json(URL)
        jobs: list[RawJob] = []
        for item in (data.get("data") or [])[: self.cap]:
            try:
                is_remote = bool(item.get("remote"))
                loc = item.get("location", "") or ""
                tags = list(item.get("tags") or []) + list(item.get("job_types") or [])
                jobs.append(RawJob(
                    source=self.name,
                    source_job_id=str(item.get("slug", "")),
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    company=item.get("company_name", ""),
                    location=loc,
                    candidate_location=loc,
                    remote_type="remote" if is_remote else "unknown",
                    description_raw=item.get("description", "") or "",
                    description_clean=html_to_text(item.get("description")),
                    date_posted=item.get("created_at"),
                    tags=tags,
                ))
            except Exception as exc:
                log.warning("arbeitnow: skipping bad record: %s", exc)
        log.info("arbeitnow: %d jobs", len(jobs))
        return jobs
