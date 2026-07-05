"""USAJOBS — the official federal-jobs API (data.usajobs.gov). The one keyed source.

Register free at https://developer.usajobs.gov/apirequest (self-service, no
approval step); the key arrives by email. Put in .env:
    USAJOBS_API_KEY=...
    USAJOBS_USER_AGENT=you@example.com   # the email you registered with
Without a key the adapter logs a hint and returns no jobs, so the daily run
still completes. RemoteIndicator=True scopes results server-side to
remote-eligible positions; an explicit RemoteIndicator=False in a record is
still respected when tagging remote_type.
"""
from __future__ import annotations

import os

from ..models import RawJob
from ..util import get_logger, html_to_text
from .base import Fetcher, JobSource

log = get_logger()
URL = "https://data.usajobs.gov/api/search"
REGISTER_URL = "https://developer.usajobs.gov/apirequest"


class USAJobsSource(JobSource):
    name = "usajobs"

    def __init__(self, fetcher: Fetcher, cap: int = 400,
                 queries: list[str] | None = None, per_query: int = 50) -> None:
        super().__init__(fetcher, cap)
        self.queries = queries or []
        self.per_query = per_query

    def fetch(self) -> list[RawJob]:
        key = os.environ.get("USAJOBS_API_KEY", "").strip()
        if not key:
            log.info("usajobs: USAJOBS_API_KEY not set — skipping (free key: %s)",
                     REGISTER_URL)
            return []
        headers = {
            "Authorization-Key": key,
            # USAJOBS asks that the User-Agent be the registered email address.
            "User-Agent": os.environ.get("USAJOBS_USER_AGENT", "").strip() or "jobhelper",
        }
        jobs: list[RawJob] = []
        seen: set[str] = set()
        for query in self.queries:
            try:
                data = self.fetcher.get_json(URL, params={
                    "Keyword": query,
                    "RemoteIndicator": "True",
                    "HiringPath": "public",
                    "ResultsPerPage": min(self.per_query, 500),
                }, headers=headers)
            except Exception as exc:
                log.warning("usajobs: query %r failed: %s", query, exc)
                continue
            items = ((data or {}).get("SearchResult") or {}) \
                .get("SearchResultItems") or []
            for item in items[: self.per_query]:
                try:
                    job = self._parse(item, query)
                except Exception as exc:
                    log.warning("usajobs: skipping bad record: %s", exc)
                    continue
                if job and job.source_job_id not in seen:
                    seen.add(job.source_job_id)
                    jobs.append(job)
                if len(jobs) >= self.cap:
                    break
            if len(jobs) >= self.cap:
                break
        log.info("usajobs: %d jobs", len(jobs))
        return jobs

    def _parse(self, item: dict, query: str) -> RawJob | None:
        d = item.get("MatchedObjectDescriptor") or {}
        job_id = str(d.get("PositionID") or item.get("MatchedObjectId") or "")
        if not job_id:
            return None
        details = (d.get("UserArea") or {}).get("Details") or {}
        salary_min, salary_max = _annual_salary(d.get("PositionRemuneration") or [])
        location = d.get("PositionLocationDisplay", "") or ""
        clearance = details.get("SecurityClearance") or ""
        parts = [details.get("JobSummary") or "",
                 d.get("QualificationSummary") or ""]
        if clearance:
            parts.append(f"Security clearance: {clearance}")
        description = "\n\n".join(p for p in parts if p)
        return RawJob(
            source=self.name,
            source_job_id=job_id,
            url=(d.get("PositionURI") or "").replace(":443/", "/"),
            title=d.get("PositionTitle", "") or "",
            company=d.get("OrganizationName", "") or d.get("DepartmentName", "")
                    or "US Federal Government",
            location=location,
            candidate_location=location,
            remote_type="unknown" if details.get("RemoteIndicator") is False
                        else "remote",
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="USD" if (salary_min or salary_max) else None,
            description_raw=description,
            description_clean=html_to_text(description),
            date_posted=d.get("PublicationStartDate"),
            tags=[query],
            extra={
                "department": d.get("DepartmentName"),
                "clearance": clearance or None,
                "close_date": d.get("ApplicationCloseDate"),
            },
        )


def _annual_salary(remuneration: list) -> tuple[int | None, int | None]:
    """Only annual ranges ('Per Year' / code PA) are comparable to salary_floor;
    hourly/bi-weekly federal pay bands are skipped rather than mis-scaled."""
    for r in remuneration:
        interval = (str(r.get("RateIntervalCode") or "") + " "
                    + str(r.get("Description") or "")).lower()
        if "pa" in interval.split() or "year" in interval:
            try:
                lo = int(float(r.get("MinimumRange")))
                hi = int(float(r.get("MaximumRange")))
                return (lo or None, hi or None)
            except (TypeError, ValueError):
                return (None, None)
    return (None, None)
