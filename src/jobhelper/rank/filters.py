"""Cheap, deterministic hard filters. Run BEFORE any embeddings/LLM spend."""
from __future__ import annotations

import re
from typing import Any

from ..util import age_days, parse_date

# US states + DC, used to scope the onsite exemption to US-based roles so an
# onsite role abroad (e.g. "London, UK") isn't kept.
_US_STATE_CODES = frozenset(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
    .split()
)


def _is_us_location(loc: str) -> bool:
    """Heuristic: does this location string denote a US-based place?

    Handles both shapes seen in the data: 'City, ST' (no country) and
    'City, Region, CC' (trailing country code). Only the TRAILING token is read as
    the country, so a foreign country code that collides with a US state
    abbreviation — 'IN' India vs Indiana, 'CA' Canada vs California, 'DE' Germany
    vs Delaware — is not misread as US. Multi-location strings joined by ';' or
    '/' are split and pass if ANY part is US.
    """
    if not loc:
        return False
    if "united states" in loc.lower() or "usa" in loc.lower():
        return True
    for sub in re.split(r"[;/]", loc):
        toks = [t.strip() for t in sub.split(",") if t.strip()]
        if not toks:
            continue
        last = toks[-1].upper().replace(".", "")
        if last in ("US", "USA"):
            return True
        # 'City, ST' with no country suffix: the trailing token is a US state code.
        if len(toks) == 2 and last in _US_STATE_CODES:
            return True
    return False


def _any_in(needles: list[str], haystack: str) -> bool:
    h = haystack.lower()
    return any(n.lower() in h for n in needles if n)


# Explicit statements that THIS job is remote, searched across the whole
# description (ITEM-46). The bare-word check in passes() reads only the first
# 400 characters, and further down a bare "remote" is as often "remote sensing",
# a benefits menu ("on-site, hybrid or remote") or Booz Allen's boilerplate "If
# this position is listed as remote" as a statement about the job. Skylight puts
# "This role is fully remote" ~4,400 characters in, so every one of its roles
# was rejected. `remote(?![\w-])` keeps "remote-first company" out.
_REMOTE_STATEMENT = re.compile(
    r"\b(?:this|the) (?:role|position|job|opportunity) is (?:a )?"
    r"(?:fully |100% |completely )?remote(?![\w-])"
    r"|\bthis is a (?:fully |100% |completely )?remote(?![\w-])(?! sensing)"
    r"|\bremote work is (?:authorized|available|permitted|allowed|offered)\b"
    r"|\b(?:fully|100%|completely) remote (?:role|position|job|opportunity)\b"
    r"|\blocation\s*:\s*remote(?![\w-])"
    r"|\bremote\s*[-,(]\s*(?:us\b|usa\b|u\.s\.|united states\b)"
    r"|\bremote (?:with)?in the (?:us\b|u\.s\.|united states\b)",
    re.I)
# Within the statement's own sentence: a negation before it ("not a fully remote
# role") or a weekly office schedule after it ("remote 2 days a week") voids it.
_NEGATED = re.compile(r"(?:\bnot|\bno|\bnon|n't)\b", re.I)
_OFFICE_DAYS = re.compile(r"\bhybrid\b|\b\d+ days? (?:a|per|each) week\b", re.I)
_SENTENCE_END = re.compile(r"[.!?\n]")


def _states_remote(desc: str) -> bool:
    """Does the description explicitly say this job is remote, anywhere in it?"""
    if "remote" not in desc.lower():  # cheap gate: the regex is ~3x slower
        return False
    for m in _REMOTE_STATEMENT.finditer(desc):
        before = _SENTENCE_END.split(desc[max(0, m.start() - 60):m.start()])[-1]
        after = _SENTENCE_END.split(desc[m.end():m.end() + 60])[0]
        if not _NEGATED.search(before) and not _OFFICE_DAYS.search(after):
            return True
    return False


# allowed_location_tokens that mean "the US": with one of them configured, a US
# place the token can't substring-match ("Reston, VA") still counts as US.
_US_TOKENS = frozenset({"us", "usa", "united states"})


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

    # A company you'd relocate for is exempt from BOTH the remote requirement and
    # the candidate-location restriction — but only for US-based roles (an onsite
    # role abroad is still dropped). Exact (case-insensitive) name match, so "xAI"
    # doesn't also exempt "CapitexAI".
    loc = (job.get("location") or "")
    onsite_ok = {c.strip().lower()
                 for c in (criteria.get("onsite_ok_companies", []) or []) if c}
    company_exempt = (company.strip().lower() in onsite_ok
                      and _is_us_location(loc or job.get("candidate_location") or ""))

    # An unknown-type job counts as remote when its title or location says so, or
    # (ITEM-46) when a US-located job's description states it anywhere. The US
    # check matters: postings with no location field say "Location: Remote
    # (Europe)" just as plainly.
    rtype = (job.get("remote_type") or "unknown").lower()
    cand = (job.get("candidate_location") or "").strip()
    said_remote = rtype == "unknown" and (
        _any_in(["remote"], f"{title} {loc}")
        or (_is_us_location(loc or cand) and _states_remote(desc)))

    # Remote requirement. The bare-word read of the first 400 characters stays
    # as a weaker signal (it also accepts "ocean remote sensing").
    if criteria.get("remote_required") and not company_exempt:
        if rtype == "onsite":
            return False, "onsite role"
        if rtype == "unknown" and not said_remote and not _any_in(["remote"], desc[:400]):
            return False, "remote not confirmed"

    # Candidate-location restriction. On a confirmed-remote job a US "City, ST"
    # here is the office the adapter copied in, so it satisfies a US token; on a
    # hybrid job it's where you'd commute, so it doesn't.
    tokens = criteria.get("allowed_location_tokens", []) or []
    us_ok = ((rtype == "remote" or said_remote) and _is_us_location(cand)
             and any(t.strip().lower() in _US_TOKENS for t in tokens if t))
    if tokens and cand and not company_exempt and not us_ok and not _any_in(tokens, cand):
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
