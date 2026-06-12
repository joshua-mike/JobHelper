"""Ashby public Job Board API (keyless).
GET https://api.ashbyhq.com/posting-api/job-board/{client}?includeCompensation=true"""
from __future__ import annotations

from ..models import RawJob
from ..util import get_logger, html_to_text
from .base import JobSource

log = get_logger()
BASE = "https://api.ashbyhq.com/posting-api/job-board"


class AshbySource(JobSource):
    name = "ashby"

    def __init__(self, fetcher, cap: int, clients: list[str]) -> None:
        super().__init__(fetcher, cap)
        self.clients = clients

    def fetch(self) -> list[RawJob]:
        jobs: list[RawJob] = []
        for client in self.clients:
            url = f"{BASE}/{client}"
            try:
                data = self.fetcher.get_json(url, params={"includeCompensation": "true"})
            except Exception as exc:
                log.warning("ashby[%s]: fetch failed: %s", client, exc)
                continue
            company = client.replace("-", " ").title()
            for item in (data.get("jobs") or []):
                try:
                    loc = item.get("location", "") or ""
                    is_remote = bool(item.get("isRemote"))
                    desc_html = item.get("descriptionHtml") or item.get("description")
                    jobs.append(RawJob(
                        source=self.name,
                        source_job_id=str(item.get("id", "")),
                        url=item.get("jobUrl", "") or item.get("applyUrl", ""),
                        title=item.get("title", ""),
                        company=company,
                        location=loc,
                        candidate_location=loc,
                        remote_type="remote" if is_remote else (
                            "remote" if "remote" in loc.lower() else "unknown"),
                        description_raw=desc_html or "",
                        description_clean=item.get("descriptionPlain") or html_to_text(desc_html),
                        date_posted=item.get("publishedAt") or item.get("publishedDate"),
                        tags=[v for v in (item.get("department"), item.get("team"),
                                          item.get("employmentType")) if v],
                        extra={"client": client},
                    ))
                except Exception as exc:
                    log.warning("ashby[%s]: bad record: %s", client, exc)
        log.info("ashby: %d jobs from %d boards", len(jobs), len(self.clients))
        return jobs[: self.cap]
