"""RemoteOK — keyless remote-jobs API. https://remoteok.com/api

Note: the FIRST array element is legal/metadata, not a job, and must be skipped.
RemoteOK asks that you link back to the job (we always link to job.url)."""
from __future__ import annotations

from ..models import RawJob
from ..util import get_logger, html_to_text
from .base import JobSource

log = get_logger()
URL = "https://remoteok.com/api"


def _to_int(v):
    try:
        return int(v) if v not in (None, "", "0") else None
    except (TypeError, ValueError):
        return None


class RemoteOKSource(JobSource):
    name = "remoteok"

    def fetch(self) -> list[RawJob]:
        data = self.fetcher.get_json(URL)
        if not isinstance(data, list):
            log.warning("remoteok: unexpected response shape")
            return []
        jobs: list[RawJob] = []
        for item in data[: self.cap + 1]:
            # Skip the legal/metadata element (no 'id'/'position').
            if not isinstance(item, dict) or "id" not in item or "position" not in item:
                continue
            try:
                loc = item.get("location", "") or "Remote"
                url = item.get("url") or f"https://remoteok.com/remote-jobs/{item.get('id')}"
                jobs.append(RawJob(
                    source=self.name,
                    source_job_id=str(item.get("id", "")),
                    url=url,
                    title=item.get("position", ""),
                    company=item.get("company", ""),
                    location=loc,
                    candidate_location=loc,
                    remote_type="remote",
                    salary_min=_to_int(item.get("salary_min")),
                    salary_max=_to_int(item.get("salary_max")),
                    salary_currency="USD" if item.get("salary_min") else None,
                    description_raw=item.get("description", "") or "",
                    description_clean=html_to_text(item.get("description")),
                    date_posted=item.get("date") or item.get("epoch"),
                    tags=list(item.get("tags") or []),
                ))
            except Exception as exc:
                log.warning("remoteok: skipping bad record: %s", exc)
        log.info("remoteok: %d jobs", len(jobs))
        return jobs[: self.cap]
