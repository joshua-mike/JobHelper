"""Adzuna — keyed aggregator API (https://developer.adzuna.com/). ITEM-6, ITEM-40.

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

Paging (ITEM-40): a page holds at most 50 ads, newest first (sort_by=date),
and the page number is the last path segment (/search/1, /search/2, ...). The
50 newest ads of a query cover only 2-8 hours, so reading page 1 alone missed
most of each day's postings. Each query now pages back until a page's oldest
`created` predates the cutoff: the previous completed run's start minus
CUTOFF_OVERLAP (Adzuna indexes an ad hours after its `created`), or
max_age_days ago when there was no previous run. max_days_old bounds the
search to the same window. A query also stops at per_query rows read or at
its share of the call budget; a share a query doesn't use carries forward to
the queries after it. Stored postings and repeats across queries are skipped,
not returned.

per_source_cap does NOT apply here: a query's share of it filled after ~2
pages of a busy query, the next run's cutoff then moved past the unread rest
of the day, and those ads were never seen. max_calls x 50 rows a run is the
safety valve instead.

Call budget: the default key allows 25 hits/min, 250/day, 1,000/week and
2,500/month. max_calls counts pages (one call each), and every Fetcher retry
on a 429/5xx also counts against the key, so the default 75 keeps even 3
attempts per page under 250/day (and 75 pages a day under 2,500/month).
build_sources spaces calls MIN_INTERVAL apart for the per-minute limit.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..models import RawJob
from ..util import get_logger, html_to_text, parse_date
from .base import Fetcher, JobSource

log = get_logger()
HOST = "api.adzuna.com"
URL = f"https://{HOST}/v1/api/jobs/us/search"  # + "/{page}"
REGISTER_URL = "https://developer.adzuna.com/"
PAGE_MAX = 50              # results_per_page ceiling
MIN_INTERVAL = 2.5         # seconds between calls: 60s / 25 hits, plus a margin
DEFAULT_MAX_AGE_DAYS = 30
# An ad's `created` is >= 4.4h old when we first see it (median 6.8h, p90 10.9h
# over the 400 newest stored ads), so page back this far behind the last run.
CUTOFF_OVERLAP = timedelta(hours=12)


@dataclass
class _Run:
    """One fetch's state, shared across its queries."""
    params: dict[str, Any]
    cutoff: datetime
    calls_left: int
    queries_left: int
    seen: set[str] = field(default_factory=set)  # job_hashes met this run

    def next_allowance(self) -> int:
        """Calls the next query may make: an equal share of those left (at least
        1 while any are). What a query doesn't use carries forward."""
        allowance = (max(1, self.calls_left // self.queries_left)
                     if self.calls_left > 0 else 0)
        self.queries_left -= 1
        return allowance


class AdzunaSource(JobSource):
    """`cap` (per_source_cap) is accepted for the JobSource signature but not
    applied: per_query and max_calls bound the crawl (see module doc)."""
    name = "adzuna"

    def __init__(self, fetcher: Fetcher, cap: int = 400,
                 queries: list[str] | None = None, per_query: int = 500, *,
                 max_calls: int = 75, last_run_started: str | None = None,
                 max_age_days: int | None = None,
                 is_known: Callable[[str], bool] | None = None) -> None:
        super().__init__(fetcher, cap, is_known)
        self.queries = queries or []
        self.per_query = per_query          # rows read per query, across pages
        self.max_calls = max_calls          # API calls (pages) per run, across queries
        self.last_run_started = last_run_started
        self.max_age_days = int(max_age_days or DEFAULT_MAX_AGE_DAYS)

    def _cutoff(self, now: datetime) -> datetime:
        cutoff = now - timedelta(days=self.max_age_days)
        last = parse_date(self.last_run_started)
        if last is not None:
            cutoff = max(cutoff, last - CUTOFF_OVERLAP)
        return cutoff

    def fetch(self) -> list[RawJob]:
        app_id = os.environ.get("ADZUNA_APP_ID", "").strip()
        app_key = os.environ.get("ADZUNA_APP_KEY", "").strip()
        if not (app_id and app_key):
            log.info("adzuna: ADZUNA_APP_ID/ADZUNA_APP_KEY not set — skipping "
                     "(free keys: %s)", REGISTER_URL)
            return []
        now = datetime.now(timezone.utc)
        cutoff = self._cutoff(now)
        run = _Run(
            params={
                "app_id": app_id,
                "app_key": app_key,
                "what_and": "remote",
                "results_per_page": min(self.per_query, PAGE_MAX),
                # Whole days back to the cutoff, which is never past max_age_days.
                "max_days_old": max(1, math.ceil((now - cutoff) / timedelta(days=1))),
                "sort_by": "date",
            },
            cutoff=cutoff,
            calls_left=self.max_calls,
            queries_left=len(self.queries),
        )
        jobs: list[RawJob] = []
        skipped = 0
        for query in self.queries:
            new, known = self._crawl_query(run, query)
            jobs.extend(new)
            skipped += known
        log.info("adzuna: %d new jobs from %d queries (%d stored postings skipped), "
                 "%d of %d API calls used", len(jobs), len(self.queries), skipped,
                 self.max_calls - run.calls_left, self.max_calls)
        return jobs

    def _crawl_query(self, run: _Run, query: str) -> tuple[list[RawJob], int]:
        """A query's new postings, paging back to the cutoff, and how many
        stored ones it skipped."""
        allowance = run.next_allowance()
        page_size = run.params["results_per_page"]
        jobs: list[RawJob] = []
        known = repeats = rows_read = calls_made = 0
        reason = "call share used"  # unless a page below stops the query first
        while calls_made < allowance:
            calls_made += 1  # one page per call: this is page number `calls_made`
            run.calls_left -= 1
            try:
                data = self.fetcher.get_json(f"{URL}/{calls_made}",
                                             params={**run.params, "what": query})
            except Exception as exc:
                log.warning("adzuna[%s]: page %d failed: %s", query, calls_made, exc)
                reason = "request failed"
                break
            rows = (data or {}).get("results") or []
            last_page = len(rows) < page_size
            rows = rows[:self.per_query - rows_read]
            rows_read += len(rows)
            stamps = [parse_date(r.get("created")) for r in rows if isinstance(r, dict)]
            oldest = min((t for t in stamps if t), default=None)
            for item in rows:
                try:
                    job = self._parse(item, query)
                except Exception as exc:
                    log.warning("adzuna: skipping bad record: %s", exc)
                    continue
                if job is None:
                    continue
                if job.job_hash in run.seen:
                    repeats += 1
                    continue
                run.seen.add(job.job_hash)
                if self.is_known(job.job_hash):
                    known += 1
                else:
                    jobs.append(job)
            if oldest is not None and oldest < run.cutoff:
                reason = "reached cutoff"
                break
            if last_page:
                reason = "end of results"
                break
            if rows_read >= self.per_query:
                reason = "per_query reached"
                break
        log.info("adzuna[%s]: %d new, %d stored skipped%s, %d page%s (%s)",
                 query, len(jobs), known,
                 f", {repeats} repeats" if repeats else "",
                 calls_made, "" if calls_made == 1 else "s", reason)
        return jobs, known

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
