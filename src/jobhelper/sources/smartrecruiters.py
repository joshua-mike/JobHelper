"""SmartRecruiters public Posting API (keyless).
GET https://api.smartrecruiters.com/v1/companies/{slug}/postings        (list)
GET https://api.smartrecruiters.com/v1/companies/{slug}/postings/{id}   (detail + job ad)

The list omits the description, so each posting's detail is fetched for the job-ad
sections. location.remote is an authoritative boolean. One slug per company."""
from __future__ import annotations

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


class SmartRecruitersSource(JobSource):
    name = "smartrecruiters"

    def __init__(self, fetcher, cap: int, slugs: list[str]) -> None:
        super().__init__(fetcher, cap)
        self.slugs = slugs

    def _postings(self, slug: str) -> list[dict]:
        out: list[dict] = []
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
            out.extend(content)
            offset += PAGE
            if not content or offset >= int((data or {}).get("totalFound") or 0):
                break
            if len(out) >= self.cap:
                break
        return out

    def fetch(self) -> list[RawJob]:
        jobs: list[RawJob] = []
        for slug in self.slugs:
            company = slug
            for post in self._postings(slug):
                pid = str(post.get("id", ""))
                if not pid:
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
                            or f"https://jobs.smartrecruiters.com/{slug}/{pid}",
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
                if len(jobs) >= self.cap:
                    log.info("smartrecruiters: hit cap %d", self.cap)
                    return jobs
        log.info("smartrecruiters: %d jobs from %d companies", len(jobs), len(self.slugs))
        return jobs
