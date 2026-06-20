"""Amazon Jobs public search API (keyless).
GET https://www.amazon.jobs/en/search.json?base_query=...&result_limit=100&offset=0

One employer, one keyless endpoint. The search response is rich — description and
qualifications are INLINE, so no per-job detail call is needed. Config items under
`ats.amazon` are SEARCH QUERIES (not slugs); the crawl is bounded per query."""
from __future__ import annotations

from datetime import datetime

from ..models import RawJob
from ..util import get_logger, html_to_text
from .base import JobSource

log = get_logger()
SEARCH = "https://www.amazon.jobs/en/search.json"
BOARD = "https://www.amazon.jobs"
PAGE = 100          # result_limit honors up to 100
_HEADERS = {"Accept": "application/json"}


def _iso_date(s) -> str | None:
    """Amazon posts dates as 'June 19, 2026'; normalize to ISO for freshness checks."""
    if not s:
        return None
    try:
        return datetime.strptime(str(s).strip(), "%B %d, %Y").date().isoformat()
    except ValueError:
        return str(s)


def _remote_type(*loc_fields: str) -> str:
    blob = " ".join(str(x or "") for x in loc_fields).lower()
    return "remote" if ("virtual" in blob or "remote" in blob) else "unknown"


class AmazonSource(JobSource):
    name = "amazon"

    def __init__(self, fetcher, cap: int, queries: list[str], per_query: int = 40) -> None:
        super().__init__(fetcher, cap)
        self.queries = queries
        self.per_query = per_query

    def _search(self, query: str) -> list[dict]:
        out: list[dict] = []
        offset = 0
        while len(out) < self.per_query:
            try:
                data = self.fetcher.get_json(SEARCH, params={
                    "base_query": query, "result_limit": PAGE, "offset": offset,
                    "sort": "recent",
                }, headers=_HEADERS)
            except Exception as exc:
                log.warning("amazon[%s]: search failed at offset=%d: %s", query, offset, exc)
                break
            batch = (data or {}).get("jobs") or []
            if not batch:
                break
            out.extend(batch)
            offset += PAGE
            if offset >= int((data or {}).get("hits") or 0):
                break
        return out[: self.per_query]

    def fetch(self) -> list[RawJob]:
        jobs: list[RawJob] = []
        seen: set[str] = set()
        for query in self.queries:
            for j in self._search(query):
                jid = str(j.get("id_icims") or j.get("id") or "")
                if not jid or jid in seen:
                    continue
                seen.add(jid)
                try:
                    loc = j.get("normalized_location") or j.get("location") or ""
                    path = j.get("job_path") or ""
                    desc_html = "\n".join(p for p in (
                        j.get("description"), j.get("basic_qualifications"),
                        j.get("preferred_qualifications")) if p)
                    jobs.append(RawJob(
                        source=self.name,
                        source_job_id=jid,
                        url=f"{BOARD}{path}" if path else j.get("url_next_step", ""),
                        title=j.get("title", ""),
                        company="Amazon",
                        location=loc,
                        candidate_location=loc,
                        remote_type=_remote_type(loc, j.get("city"), j.get("location")),
                        description_raw=desc_html,
                        description_clean=html_to_text(desc_html),
                        date_posted=_iso_date(j.get("posted_date")),
                        tags=[t for t in (j.get("job_category"),) if t],
                        extra={"query": query, "id_icims": jid},
                    ))
                except Exception as exc:
                    log.warning("amazon: bad record %s: %s", jid, exc)
                if len(jobs) >= self.cap:
                    log.info("amazon: hit cap %d", self.cap)
                    return jobs
        log.info("amazon: %d jobs from %d queries", len(jobs), len(self.queries))
        return jobs
