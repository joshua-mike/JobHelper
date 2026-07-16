"""Adzuna — keyed aggregator API (https://developer.adzuna.com/). ITEM-6.

The legal Indeed-equivalent lane: broad US aggregation for long-tail/SMB
coverage and harvester feedstock. Free self-service app_id/app_key; set in .env:
    ADZUNA_APP_ID=...
    ADZUNA_APP_KEY=...
Without keys the adapter logs a hint and returns no jobs.

Known API caveats, encoded here:
- Descriptions are TRUNCATED (~500 chars) — enough for the hard filter and
  discovery, but the LLM judge sees less text than for direct sources.
- `what_and=remote` requires the word in the FULL ad, but it may sit past the
  truncation point; remote_type is tagged only when "remote" is visible in the
  title/description/location we actually store (precision over recall — the
  remote-only hard filter drops what it can't confirm).
- `salary_is_predicted=1` marks Adzuna's own estimate, not a listed salary; it
  goes to extra["salary_predicted"], never into salary_min/max, so the salary
  floor never rejects on a guess.
- `redirect_url` is VOLATILE: it carries a per-request `se=` signature (and the
  format itself flips between land/ad/<id> and details/<id>), so the same ad
  re-fetched on a later run gets a different URL. volatile_url=True makes the
  dedupe identity source+ad-id instead of the URL.
"""
from __future__ import annotations

import os

from ..models import RawJob
from ..util import get_logger, html_to_text
from .base import Fetcher, JobSource

log = get_logger()
URL = "https://api.adzuna.com/v1/api/jobs/us/search/1"
REGISTER_URL = "https://developer.adzuna.com/"


class AdzunaSource(JobSource):
    name = "adzuna"

    def __init__(self, fetcher: Fetcher, cap: int = 400,
                 queries: list[str] | None = None, per_query: int = 50) -> None:
        super().__init__(fetcher, cap)
        self.queries = queries or []
        self.per_query = per_query

    def fetch(self) -> list[RawJob]:
        app_id = os.environ.get("ADZUNA_APP_ID", "").strip()
        app_key = os.environ.get("ADZUNA_APP_KEY", "").strip()
        if not (app_id and app_key):
            log.info("adzuna: ADZUNA_APP_ID/ADZUNA_APP_KEY not set — skipping "
                     "(free keys: %s)", REGISTER_URL)
            return []
        jobs: list[RawJob] = []
        seen: set[str] = set()
        for query in self.queries:
            try:
                data = self.fetcher.get_json(URL, params={
                    "app_id": app_id,
                    "app_key": app_key,
                    "what": query,
                    "what_and": "remote",
                    "results_per_page": min(self.per_query, 50),
                    "max_days_old": 30,
                    "sort_by": "date",
                })
            except Exception as exc:
                log.warning("adzuna: query %r failed: %s", query, exc)
                continue
            for item in (data or {}).get("results") or []:
                try:
                    job = self._parse(item, query)
                except Exception as exc:
                    log.warning("adzuna: skipping bad record: %s", exc)
                    continue
                if job and job.source_job_id not in seen:
                    seen.add(job.source_job_id)
                    jobs.append(job)
                if len(jobs) >= self.cap:
                    break
            if len(jobs) >= self.cap:
                break
        log.info("adzuna: %d jobs", len(jobs))
        return jobs

    def _parse(self, item: dict, query: str) -> RawJob | None:
        job_id = str(item.get("id") or "")
        if not job_id:
            return None
        title = item.get("title", "") or ""
        desc = item.get("description", "") or ""
        location = ((item.get("location") or {}).get("display_name")) or ""
        blob = f"{title} {desc} {location}".lower()

        predicted = str(item.get("salary_is_predicted") or "0") in ("1", "true")
        raw_min, raw_max = item.get("salary_min"), item.get("salary_max")
        salary_min = int(float(raw_min)) if (raw_min and not predicted) else None
        salary_max = int(float(raw_max)) if (raw_max and not predicted) else None

        tags = [query]
        category = (item.get("category") or {}).get("label")
        if category:
            tags.append(str(category))
        extra: dict = {"category": (item.get("category") or {}).get("tag")}
        if predicted and (raw_min or raw_max):
            extra["salary_predicted"] = {"min": raw_min, "max": raw_max}

        return RawJob(
            source=self.name,
            source_job_id=job_id,
            url=item.get("redirect_url", "") or "",
            title=title,
            company=((item.get("company") or {}).get("display_name")) or "",
            location=location,
            remote_type="remote" if "remote" in blob else "unknown",
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="USD" if (salary_min or salary_max) else None,
            description_raw=desc,
            description_clean=html_to_text(desc),
            date_posted=item.get("created"),
            tags=tags,
            extra=extra,
            volatile_url=True,  # redirect_url changes per fetch; see module doc
        )
