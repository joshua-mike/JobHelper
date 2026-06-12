"""Remotive — keyless remote-jobs aggregator. https://remotive.com/api/remote-jobs"""
from __future__ import annotations

from ..models import RawJob
from ..util import get_logger, html_to_text
from .base import JobSource

log = get_logger()
URL = "https://remotive.com/api/remote-jobs"


class RemotiveSource(JobSource):
    name = "remotive"

    def fetch(self) -> list[RawJob]:
        data = self.fetcher.get_json(URL, params={"limit": self.cap})
        jobs: list[RawJob] = []
        for item in (data.get("jobs") or [])[: self.cap]:
            try:
                loc = item.get("candidate_required_location", "") or ""
                tags = list(item.get("tags") or [])
                for key in ("category", "job_type"):
                    if item.get(key):
                        tags.append(str(item[key]))
                jobs.append(RawJob(
                    source=self.name,
                    source_job_id=str(item.get("id", "")),
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    company=item.get("company_name", ""),
                    location=loc,
                    candidate_location=loc,
                    remote_type="remote",
                    description_raw=item.get("description", "") or "",
                    description_clean=html_to_text(item.get("description")),
                    date_posted=item.get("publication_date"),
                    tags=tags,
                    extra={"salary_text": item.get("salary")},
                ))
            except Exception as exc:
                log.warning("remotive: skipping bad record: %s", exc)
        log.info("remotive: %d jobs", len(jobs))
        return jobs
