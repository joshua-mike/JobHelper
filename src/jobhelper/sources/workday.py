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
large, so the crawl is scoped by search terms and bounded per term.

The detail call is the expensive part, so the cap bounds NEW postings only:
a posting already stored is recognized from its list entry (its job_hash is
predictable from externalPath) and skipped before the detail fetch. The cap is
then shared out across tenants so the first few in sources.yaml can't use all
of it (ITEM-37: they did, every run, and the later tenants were never crawled).

Tenants are crawled concurrently: each sits on its own host, so the Fetcher's
per-host delay still spaces every tenant's requests, and the crawl takes as
long as the slowest tenant rather than the sum of them all."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from ..models import RawJob
from ..util import get_logger, html_to_text
from .base import JobSource, fair_shares

log = get_logger()
PAGE = 20           # CXS list page size
TENANT_WORKERS = 8  # tenants crawled at once
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


def _valid(t: dict) -> bool:
    return bool(t.get("tenant") and t.get("dc") and t.get("site"))


class WorkdaySource(JobSource):
    name = "workday"

    def __init__(self, fetcher, cap: int, tenants: list[dict],
                 searches: list[str] | None = None, per_search: int = 25,
                 is_known: Callable[[str], bool] | None = None) -> None:
        super().__init__(fetcher, cap, is_known)
        self.tenants = tenants
        self.searches = searches or [""]
        self.per_search = per_search

    def _job_hash(self, base: str, site: str, ext: str) -> str:
        """The job_hash this posting will get, known before its detail call.

        RawJob hashes the URL, and a posting's externalUrl is {base}/{site}{ext}
        (true for all 8,386 stored rows as of 2026-10-09). A tenant whose
        externalUrl differs just misses here and is detail-fetched as before.
        """
        return RawJob(source=self.name, source_job_id=ext, title="", company="",
                      url=f"{base}/{site}{ext}").job_hash

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
        """Crawl every tenant, each with a fair share of the cap.

        Lists first (cheap, no detail calls), then the cap is split max-min
        fairly over each tenant's NEW postings, then only those are detail-
        fetched. Postings already stored don't count, so a share is spent only
        on new ones."""
        if not self.tenants:
            return []
        workers = min(TENANT_WORKERS, len(self.tenants))
        with ThreadPoolExecutor(max_workers=workers,
                                thread_name_prefix="workday") as pool:
            listed = list(pool.map(self._list_tenant, self.tenants))
            shares = fair_shares([len(new) for new, _ in listed], self.cap)
            crawled = list(pool.map(self._fetch_details, self.tenants,
                                    [new for new, _ in listed], shares))
        jobs: list[RawJob] = []
        for t, (new, known), share, got in zip(self.tenants, listed, shares, crawled):
            if not _valid(t):
                continue
            cxs = f"{t['tenant']}/{t['site']}"
            if share < len(new):
                log.info("workday[%s]: %d new (share reached, %d more next run), "
                         "%d stored skipped", cxs, len(got), len(new) - share, known)
            else:
                log.info("workday[%s]: %d new, %d stored skipped", cxs, len(got), known)
            jobs.extend(got)
        log.info("%s: %d new jobs from %d boards (%d stored postings skipped)",
                 self.name, len(jobs), len(self.tenants),
                 sum(known for _, known in listed))
        return jobs

    def _list_tenant(self, t: dict) -> tuple[list[dict], int]:
        """One tenant's NEW list entries (no detail calls), and how many stored
        postings it skipped."""
        if not _valid(t):
            log.warning("workday: skipping malformed tenant config %r", t)
            return [], 0
        base = _host(t["tenant"], t["dc"])
        site = t["site"]
        new: list[dict] = []
        known = 0
        seen: set[str] = set()
        for term in self.searches:
            for post in self._search(base, f"{t['tenant']}/{site}", term):
                ext = post.get("externalPath") or ""
                if not ext or ext in seen:
                    continue
                seen.add(ext)
                if self.is_known(self._job_hash(base, site, ext)):
                    known += 1
                else:
                    new.append(post)
        return new, known

    def _fetch_details(self, t: dict, posts: list[dict], share: int) -> list[RawJob]:
        """Detail-fetch the first `share` of one tenant's new list entries."""
        if not posts or share <= 0:
            return []
        tenant, site = t["tenant"], t["site"]
        company = t.get("company") or str(tenant).replace("-", " ").title()
        base = _host(tenant, t["dc"])
        cxs = f"{tenant}/{site}"
        jobs: list[RawJob] = []
        for post in posts[:share]:
            ext = post["externalPath"]
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
        return jobs
