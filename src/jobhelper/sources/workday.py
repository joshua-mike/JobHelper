"""Workday public CXS Job Board API (keyless).

Workday powers a huge share of large-employer career sites. Each tenant exposes a
keyless JSON search:
    POST https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
         body {"appliedFacets":{},"limit":20,"offset":0,"searchText":"..."}
returning {"total":N, "jobPostings":[{title, externalPath, locationsText, ...}]}.
The list omits the description, so each kept posting's detail is fetched at
    GET  https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}
(externalPath already begins with '/job/...'), giving jobDescription, externalUrl,
startDate, location.

Each tenant needs THREE slugs from its careers URL: tenant, data-center subdomain
(wd1/wd3/wd5/wd103...), and site (e.g. 'NVIDIAExternalCareerSite'). Boards are
large, so the crawl is scoped by search terms and bounded per term."""
from __future__ import annotations

from ..models import RawJob
from ..util import get_logger, html_to_text
from .base import JobSource

log = get_logger()
PAGE = 20           # CXS list page size
_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}

# Workday's own vocabulary for the detail payload's remoteType -> ours.
_REMOTE_TYPES = {"remote": "remote", "hybrid": "hybrid",
                 "onsite": "onsite", "on-site": "onsite", "on site": "onsite"}


def _host(tenant: str, dc: str) -> str:
    return f"https://{tenant}.{dc}.myworkdayjobs.com"


def _remote_type(raw: str | None, loc: str) -> str:
    """Prefer the structured remoteType field over sniffing the location string.

    Tenants that set it can phrase the location anything they like: iHerb tags its
    remote roles "Home Office, CA" and never writes "remote" in the description, so
    the location sniff alone silently dropped every one of them. Most tenants omit
    the field entirely (Leidos, ICF, GDIT, NVIDIA, Mastercard as of 2026-08), so the
    sniff stays as the fallback."""
    mapped = _REMOTE_TYPES.get((raw or "").strip().lower())
    if mapped:
        return mapped
    return "remote" if "remote" in loc.lower() else "unknown"


class WorkdaySource(JobSource):
    name = "workday"

    def __init__(self, fetcher, cap: int, tenants: list[dict],
                 searches: list[str] | None = None, per_search: int = 25) -> None:
        super().__init__(fetcher, cap)
        self.tenants = tenants
        self.searches = searches or [""]
        self.per_search = per_search

    def _search(self, base: str, cxs: str, term: str) -> list[dict]:
        """Page one search term up to per_search postings."""
        out: list[dict] = []
        offset = 0
        while len(out) < self.per_search:
            try:
                data = self.fetcher.post_json(f"{base}/wday/cxs/{cxs}/jobs", json_body={
                    "appliedFacets": {}, "limit": PAGE, "offset": offset,
                    "searchText": term,
                }, headers=_HEADERS)
            except Exception as exc:
                log.warning("workday[%s]: search %r failed at offset=%d: %s",
                            cxs, term, offset, exc)
                break
            postings = (data or {}).get("jobPostings") or []
            if not postings:
                break
            out.extend(postings)
            offset += PAGE
            if offset >= int((data or {}).get("total") or 0):
                break
        return out[: self.per_search]

    def fetch(self) -> list[RawJob]:
        jobs: list[RawJob] = []
        for t in self.tenants:
            tenant, dc, site = t.get("tenant"), t.get("dc"), t.get("site")
            if not (tenant and dc and site):
                log.warning("workday: skipping malformed tenant config %r", t)
                continue
            company = t.get("company") or str(tenant).replace("-", " ").title()
            base = _host(tenant, dc)
            cxs = f"{tenant}/{site}"
            seen: set[str] = set()
            for term in self.searches:
                for post in self._search(base, cxs, term):
                    ext = post.get("externalPath") or ""
                    if not ext or ext in seen:
                        continue
                    seen.add(ext)
                    try:
                        detail = self.fetcher.get_json(
                            f"{base}/wday/cxs/{cxs}{ext}", headers=_HEADERS)
                        info = (detail or {}).get("jobPostingInfo") or {}
                    except Exception as exc:
                        log.warning("workday[%s]: detail failed for %s: %s", cxs, ext, exc)
                        info = {}
                    try:
                        loc = post.get("locationsText") or info.get("location") or ""
                        rtype = _remote_type(info.get("remoteType"), loc)
                        # For a remote role the office label says nothing about where
                        # the candidate may live — iHerb's remote reqs read "Home
                        # Office, CA" — so the candidate-location check gets the
                        # requisition's country instead.
                        country = (info.get("country") or {}).get("descriptor") or ""
                        cand = country if (rtype == "remote" and country) else loc
                        desc_html = info.get("jobDescription") or ""
                        req = (post.get("bulletFields") or [None])[0] or info.get("jobReqId")
                        jobs.append(RawJob(
                            source=self.name,
                            source_job_id=str(req or ext),
                            url=info.get("externalUrl") or f"{base}/{site}{ext}",
                            title=post.get("title") or info.get("title") or "",
                            company=company,
                            location=loc,
                            candidate_location=cand,
                            remote_type=rtype,
                            description_raw=desc_html,
                            description_clean=html_to_text(desc_html),
                            date_posted=info.get("startDate"),
                            tags=[v for v in (info.get("timeType"),) if v],
                            extra={"tenant": tenant, "site": site, "externalPath": ext},
                        ))
                    except Exception as exc:
                        log.warning("workday[%s]: bad record %s: %s", cxs, ext, exc)
                    if len(jobs) >= self.cap:
                        log.info("workday: hit cap %d", self.cap)
                        return jobs
        log.info("workday: %d jobs from %d tenants", len(jobs), len(self.tenants))
        return jobs
