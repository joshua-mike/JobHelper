"""Form-field matching for assisted apply.

The matching core is PURE (no Playwright) so it can be unit-tested offline. It maps
a form field's descriptors (label / aria-label / placeholder / name / id) to a
logical field key. The Playwright layer (runner.py) sweeps the page's inputs,
builds those descriptors, and fills using this mapping.

NOTHING here clicks a submit button — filling only. The human always submits.
"""
from __future__ import annotations

import re
from typing import Any

# Ordered: more specific logical fields first so "First Name" matches first_name,
# not the looser full-name "name" pattern.
FIELD_PATTERNS: list[tuple[str, list[str]]] = [
    ("first_name", [r"first[\s_]*name", r"given[\s_]*name", r"\bfname\b"]),
    ("last_name", [r"last[\s_]*name", r"family[\s_]*name", r"surname", r"\blname\b"]),
    ("full_name", [r"full[\s_]*name", r"your[\s_]*name", r"applicant[\s_]*name",
                   r"^[\s*]*name[\s*]*$", r"^name$"]),
    ("email", [r"e[-\s]?mail"]),
    ("phone", [r"phone", r"mobile", r"telephone", r"\bcell\b"]),
    ("linkedin", [r"linked[\s]?in"]),
    ("github", [r"git[\s]?hub"]),
    ("website", [r"website", r"portfolio", r"personal[\s_]*site", r"your[\s_]*site",
                 r"\bweb\b", r"\burl\b"]),
    ("location", [r"location", r"current[\s_]*city", r"\bcity\b", r"where are you",
                  r"based[\s_]*in", r"city.*state"]),
    ("cover_letter", [r"cover[\s_]*letter", r"why do you want", r"tell us about",
                      r"additional information", r"anything else"]),
]

RESUME_PATTERNS = [r"resume", r"\bcv\b", r"curriculum"]


def _matches(text: str, patterns: list[str]) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    return any(re.search(p, t) for p in patterns)


def match_field(text: str) -> str | None:
    """Map a single descriptor string to a logical field key (or None)."""
    for field, patterns in FIELD_PATTERNS:
        if _matches(text, patterns):
            return field
    return None


def match_descriptor(parts: list[str]) -> tuple[str | None, str]:
    """Given [label, aria, placeholder, name, id], return (field, matched_part).

    Tries the most human-meaningful descriptor first; a label beats a raw id.
    """
    for part in parts:
        field = match_field(part)
        if field:
            return field, part
    return None, ""


def is_resume_descriptor(parts: list[str]) -> bool:
    return any(_matches(p, RESUME_PATTERNS) for p in parts)


def detect_ats(url: str) -> str:
    u = (url or "").lower()
    if "greenhouse.io" in u:
        return "greenhouse"
    if "lever.co" in u:
        return "lever"
    if "ashbyhq.com" in u:
        return "ashby"
    if "myworkdayjobs" in u or "myworkdaysite" in u:
        return "workday"
    return "generic"


def apply_url(url: str, ats: str) -> str:
    """Best-effort URL for the application FORM (vs the description page)."""
    if not url:
        return url
    if ats == "lever":
        base = url.split("?")[0].rstrip("/")
        return base if base.endswith("/apply") else base + "/apply"
    # Greenhouse/Ashby/generic: the form is on the posting page (or one Apply click away).
    return url


def split_name(full_name: str) -> tuple[str, str]:
    parts = (full_name or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def build_apply_data(profile: dict, job: dict) -> dict[str, Any]:
    """Assemble the values the filler will type, from the master profile + job."""
    ident = profile.get("identity", {}) or {}
    first, last = split_name(ident.get("full_name", ""))
    return {
        "first_name": first,
        "last_name": last,
        "full_name": ident.get("full_name", ""),
        "email": ident.get("email", ""),
        "phone": ident.get("phone", ""),
        "location": ident.get("city_state", ""),
        "linkedin": ident.get("linkedin_url", ""),
        "github": "",
        "website": ident.get("portfolio_url", ""),
        "cover_letter": job.get("cover_letter_text") or "",
        "resume_path": job.get("tailored_resume_path") or "",
    }
