"""SmartRecruiters public Posting API (keyless).
GET https://api.smartrecruiters.com/v1/companies/{slug}/postings        (list)
GET https://api.smartrecruiters.com/v1/companies/{slug}/postings/{id}   (detail + job ad)

The list omits the description, so each posting's detail is fetched for the job-ad
sections. location.remote is an authoritative boolean. One slug per company.

The detail call is the expensive part, so the cap bounds NEW postings only: a
posting already stored is recognized from its list entry (its job_hash is
predictable from id + name, or id alone if its detail call failed) and skipped
before the detail fetch. The cap is then shared out across slugs so the first
few in sources.yaml can't use all of it (ITEM-39)."""
from __future__ import annotations

import re
import unicodedata
from typing import Callable, Iterator

from ..models import RawJob
from ..util import get_logger, html_to_text
from .base import JobSource

log = get_logger()
BASE = "https://api.smartrecruiters.com/v1/companies"
PAGE = 100
_HEADERS = {"Accept": "application/json"}
_SECTIONS = ("jobDescription", "qualifications", "additionalInformation",
             "companyDescription")


def _location(loc: dict) -> str:
    parts = [loc.get("city"), loc.get("region")]
    country = loc.get("country")
    if country:
        parts.append(str(country).upper() if len(str(country)) <= 3 else country)
    return ", ".join(p for p in parts if p)


def _fallback_url(slug: str, pid: str) -> str:
    """The URL a posting is stored under when its detail call fails (no postingUrl)."""
    return f"https://jobs.smartrecruiters.com/{slug}/{pid}"


def _slugify(text: str) -> str:
    """A posting name as SmartRecruiters writes it into postingUrl: accents folded
    to ASCII, lowercased, each run of anything else one '-'. The ends are NOT
    trimmed — ".Net Engineer" gives "-net-engineer", so the URL reads "{id}--net-engineer"."""
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower())


class SmartRecruitersSource(JobSource):
    name = "smartrecruiters"

    def __init__(self, fetcher, cap: int, slugs: list[str],
                 is_known: Callable[[str], bool] | None = None) -> None:
        super().__init__(fetcher, cap, is_known)
        self.slugs = slugs

    def _job_hash(self, slug: str, pid: str, name: str | None = None) -> str:
        """The job_hash a posting is stored under, known before its detail call.

        RawJob hashes the URL, which has one of two shapes:
        - with `name`, the detail's postingUrl:
          https://jobs.smartrecruiters.com/{slug}/{id}-{_slugify(name)} (true for
          all 1,821 stored rows as of 2026-10-11). A posting whose postingUrl
          differs just misses here and is detail-fetched as before; dedupe handles it.
        - without, _fallback_url: https://jobs.smartrecruiters.com/{slug}/{id},
          stored when the detail call failed.
        """
        url = _fallback_url(slug, pid)
        if name is not None:
            url = f"{url}-{_slugify(name)}"
        return RawJob(source=self.name, source_job_id=pid, title="", company="",
                      url=url).job_hash

    def _postings(self, slug: str) -> Iterator[dict]:
        """Every listed posting, a page at a time. Lazy, so stored postings can be
        paged past and no page is requested once the slug's share is reached."""
        offset = 0
        while True:
            try:
                data = self.fetcher.get_json(
                    f"{BASE}/{slug}/postings",
                    params={"limit": PAGE, "offset": offset}, headers=_HEADERS)
            except Exception as exc:
                log.warning("smartrecruiters[%s]: list failed at offset=%d: %s",
                            slug, offset, exc)
                break
            content = (data or {}).get("content") or []
            yield from content
            offset += PAGE
            if not content or offset >= int((data or {}).get("totalFound") or 0):
                break

    def fetch(self) -> list[RawJob]:
        return self._share_cap(self.slugs, self._crawl_slug)

    def _crawl_slug(self, slug: str, share: int) -> tuple[list[RawJob], int]:
        """Up to `share` new postings from one company, and how many stored ones it skipped."""
        jobs: list[RawJob] = []
        known = 0
        seen: set[str] = set()
        for post in self._postings(slug):
            pid = str(post.get("id", ""))
            if not pid or pid in seen:
                continue
            seen.add(pid)
            if (self.is_known(self._job_hash(slug, pid, post.get("name") or ""))
                    or self.is_known(self._job_hash(slug, pid))):
                known += 1
                continue
            try:
                detail = self.fetcher.get_json(
                    f"{BASE}/{slug}/postings/{pid}", headers=_HEADERS) or {}
            except Exception as exc:
                log.warning("smartrecruiters[%s]: detail failed for %s: %s",
                            slug, pid, exc)
                detail = {}
            try:
                company = (post.get("company") or {}).get("name") or slug
                loc = post.get("location") or {}
                loc_str = _location(loc)
                is_remote = bool(loc.get("remote"))
                sections = (detail.get("jobAd") or {}).get("sections") or {}
                desc_html = "\n".join(
                    (sections.get(k) or {}).get("text") or "" for k in _SECTIONS)
                jobs.append(RawJob(
                    source=self.name,
                    source_job_id=pid,
                    url=detail.get("postingUrl") or detail.get("applyUrl")
                        or _fallback_url(slug, pid),
                    title=post.get("name", ""),
                    company=company,
                    location=loc_str,
                    candidate_location=loc_str,
                    remote_type="remote" if is_remote else (
                        "remote" if "remote" in loc_str.lower() else "unknown"),
                    description_raw=desc_html,
                    description_clean=html_to_text(desc_html),
                    date_posted=post.get("releasedDate"),
                    tags=[v for v in (
                        (post.get("department") or {}).get("label")
                        if isinstance(post.get("department"), dict) else None,
                        (post.get("typeOfEmployment") or {}).get("label")
                        if isinstance(post.get("typeOfEmployment"), dict) else None,
                    ) if v],
                    extra={"slug": slug},
                ))
            except Exception as exc:
                log.warning("smartrecruiters[%s]: bad record %s: %s", slug, pid, exc)
            if len(jobs) >= share:
                log.info("smartrecruiters[%s]: %d new (share reached), %d stored skipped",
                         slug, len(jobs), known)
                return jobs, known
        log.info("smartrecruiters[%s]: %d new, %d stored skipped", slug, len(jobs), known)
        return jobs, known
