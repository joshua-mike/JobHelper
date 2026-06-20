"""Microsoft Careers — Eightfold 'pcsx' Job Board API (keyless reads).

Microsoft moved its careers site to Eightfold AI (~Nov 2025). The OLD
gcsservices.careers.microsoft.com endpoint is dead (its TLS cert doesn't cover
the host), so this uses the live keyless JSON API at apply.careers.microsoft.com.
Search returns "lite" records with NO description, so for each kept job we call
position_details to get the full description + the authoritative work-site/remote
field (efcustomTextWorkSite); the lite record's workLocationOption is unreliable.

Config items under `ats.microsoft` are SEARCH QUERIES, not company slugs. The
crawl is intentionally bounded (top `per_query` per term, throttled + capped) to
stay low-volume — enumerating the whole board is "impermissible scraping" under
the Microsoft Services Agreement.
"""
from __future__ import annotations

from ..models import RawJob
from ..util import get_logger, html_to_text
from .base import JobSource

log = get_logger()
SEARCH = "https://apply.careers.microsoft.com/api/pcsx/search"
DETAIL = "https://apply.careers.microsoft.com/api/pcsx/position_details"
BOARD = "https://apply.careers.microsoft.com"
DOMAIN = "microsoft.com"
PAGE = 10           # the pcsx API hard-caps num at 10 regardless of what you ask
_HEADERS = {"Accept": "application/json"}


def _remote_type(worksite) -> str:
    """Map Eightfold efcustomTextWorkSite -> remote|hybrid|onsite|unknown.

    Examples: '0 days / week in-office – remote' -> remote; '3 days / week
    in-office' -> hybrid; 'fully on-site' / '5 days...' -> onsite.
    """
    s = " ".join(str(w) for w in worksite).lower() if isinstance(worksite, list) \
        else str(worksite or "").lower()
    if not s:
        return "unknown"
    if "remote" in s or "0 day" in s:
        return "remote"
    if "fully on-site" in s or "5 day" in s:
        return "onsite"
    if "in-office" in s or "day" in s:
        return "hybrid"
    return "unknown"


class MicrosoftSource(JobSource):
    name = "microsoft"

    def __init__(self, fetcher, cap: int, queries: list[str], per_query: int = 40) -> None:
        super().__init__(fetcher, cap)
        self.queries = queries
        self.per_query = per_query

    def _search(self, query: str) -> list[dict]:
        """Page search (num capped at 10) up to per_query results, newest-relevant first."""
        out: list[dict] = []
        start = 0
        while len(out) < self.per_query:
            try:
                data = self.fetcher.get_json(SEARCH, params={
                    "domain": DOMAIN, "query": query, "start": start,
                    "num": PAGE, "sort_by": "relevance",
                }, headers=_HEADERS)
            except Exception as exc:
                log.warning("microsoft[%s]: search failed at start=%d: %s", query, start, exc)
                break
            body = (data or {}).get("data") or {}
            positions = body.get("positions") or []
            if not positions:
                break
            out.extend(positions)
            start += PAGE
            if start >= int(body.get("count") or 0):
                break
        return out[: self.per_query]

    def fetch(self) -> list[RawJob]:
        jobs: list[RawJob] = []
        seen: set[str] = set()
        for query in self.queries:
            for lite in self._search(query):
                pid = str(lite.get("id", ""))
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                try:
                    detail = self.fetcher.get_json(
                        DETAIL, params={"domain": DOMAIN, "position_id": pid},
                        headers=_HEADERS)
                    d = (detail or {}).get("data") or {}
                except Exception as exc:
                    log.warning("microsoft: detail failed for %s: %s", pid, exc)
                    d = {}
                try:
                    locs = lite.get("standardizedLocations") or lite.get("locations") or []
                    loc = "; ".join(locs) if isinstance(locs, list) else str(locs or "")
                    pos_url = lite.get("positionUrl") or f"/careers/job/{pid}"
                    desc_html = d.get("jobDescription") or ""
                    jobs.append(RawJob(
                        source=self.name,
                        source_job_id=str(lite.get("displayJobId") or pid),
                        url=f"{BOARD}{pos_url}",
                        title=lite.get("name", ""),
                        company="Microsoft",
                        location=loc,
                        candidate_location=loc,
                        remote_type=_remote_type(d.get("efcustomTextWorkSite")),
                        description_raw=desc_html,
                        description_clean=html_to_text(desc_html),
                        date_posted=lite.get("postedTs"),
                        tags=[t for t in (lite.get("department"),) if t],
                        extra={"query": query, "position_id": pid,
                               "work_site": d.get("efcustomTextWorkSite")},
                    ))
                except Exception as exc:
                    log.warning("microsoft: bad record %s: %s", pid, exc)
                if len(jobs) >= self.cap:
                    log.info("microsoft: hit cap %d", self.cap)
                    return jobs
        log.info("microsoft: %d jobs from %d queries", len(jobs), len(self.queries))
        return jobs
