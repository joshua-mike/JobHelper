"""Cheap, deterministic hard filters. Run BEFORE any embeddings/LLM spend."""
from __future__ import annotations

from typing import Any

from ..util import age_days, parse_date


def _any_in(needles: list[str], haystack: str) -> bool:
    h = haystack.lower()
    return any(n.lower() in h for n in needles if n)


def passes(job: dict[str, Any], criteria: dict[str, Any]) -> tuple[bool, str]:
    """Return (passed, reason_if_rejected)."""
    title = (job.get("title") or "")
    desc = (job.get("description_clean") or "")
    company = (job.get("company") or "")
    blob = f"{title}\n{desc}"

    # Company exclusions
    for bad in criteria.get("exclude_companies", []) or []:
        if bad and bad.lower() in company.lower():
            return False, f"excluded company ({company})"

    # Title gating
    inc = criteria.get("title_include_any", []) or []
    if inc and not _any_in(inc, title):
        return False, "title lacks any include keyword"
    exc = criteria.get("title_exclude_any", []) or []
    if exc and _any_in(exc, title):
        return False, "title has an exclude keyword"

    # Keyword gating
    kany = criteria.get("keywords_any", []) or []
    if kany and not _any_in(kany, blob):
        return False, "no required keyword in title/description"
    kexc = criteria.get("keywords_exclude", []) or []
    if kexc and _any_in(kexc, desc):
        return False, "description has a dealbreaker keyword"

    # Remote requirement
    if criteria.get("remote_required"):
        rtype = (job.get("remote_type") or "unknown").lower()
        loc = (job.get("location") or "")
        if rtype == "onsite":
            return False, "onsite role"
        if rtype == "unknown" and not _any_in(["remote"], f"{title} {loc} {desc[:400]}"):
            return False, "remote not confirmed"

    # Candidate-location restriction
    tokens = criteria.get("allowed_location_tokens", []) or []
    cand = (job.get("candidate_location") or "").strip()
    if tokens and cand and not _any_in(tokens, cand):
        return False, f"location restricted to '{cand}'"

    # Salary floor (only when a salary is actually listed)
    floor = int(criteria.get("salary_floor", 0) or 0)
    smax = job.get("salary_max")
    if floor and smax and smax < floor:
        return False, f"salary max {smax} below floor {floor}"

    # Freshness
    max_age = criteria.get("max_age_days")
    if max_age:
        age = age_days(parse_date(job.get("date_posted")))
        if age is not None and age > float(max_age):
            return False, f"older than {max_age} days"

    return True, ""
