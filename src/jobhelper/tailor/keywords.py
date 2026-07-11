"""JD keyword extraction (LLM) + boundary-aware coverage matching.

The extraction call is deliberately separate from the tailor call so the
coverage report is not the writer grading its own homework. The matcher builds
per-term boundary guards from the term's edge characters because naive \\b
never matches C#, .NET, or C++ (#, +, . are non-word chars, so \\b needs a
word<->non-word transition that isn't there).
"""
from __future__ import annotations

import re
from typing import Any

from ..llm import LLM

# Code constants by design — no new config knobs for this feature.
JD_CHAR_CAP = 15_000
FREQUENCY_CAP = 4

KEYWORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "keywords": {
            "type": "array",
            "description": "Ranked most-important-first.",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string",
                             "description": "The JD's exact wording."},
                    "category": {"type": "string",
                                 "enum": ["hard_skill", "method", "title", "soft"]},
                    "required": {"type": "boolean",
                                 "description": "True if the JD treats it as required, false if preferred/nice-to-have."},
                    "variants": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Acronym/expansion pair plus 2-3 semantic variations (e.g. 'REST API' -> 'RESTful services', 'web services').",
                    },
                },
                "required": ["term", "category", "required", "variants"],
            },
        },
    },
    "required": ["keywords"],
}

EXTRACT_INSTRUCTIONS = (
    "You extract ATS-relevant keywords from a job description. Produce a ranked "
    "table (most important first): hard skills (languages, frameworks, tools, "
    "platforms, certifications), then industry/method terms, then the job title "
    "language, then soft skills only if the JD emphasizes them. Use the JD's "
    "exact wording as the term. Mark required=true only for genuinely required "
    "qualifications. For each term list variants: the acronym/expansion "
    "counterpart if one exists, plus 2-3 common semantic variations."
)


def extract_keywords(llm: LLM, model: str, job: dict) -> list[dict] | None:
    """Ranked keyword table for a job, or None (soft-fail: tailor without it)."""
    if not llm.available:
        return None
    user = (
        f"JOB POSTING\nTitle: {job.get('title', '')}\n"
        f"Company: {job.get('company', '')}\n\n"
        f"{(job.get('description_clean') or '')[:JD_CHAR_CAP]}"
    )
    result = llm.structured(
        EXTRACT_INSTRUCTIONS, user, schema=KEYWORD_SCHEMA,
        tool_name="jd_keywords", model=model, max_tokens=1200,
    )
    if not result or not isinstance(result.get("keywords"), list):
        return None
    table = []
    for kw in result["keywords"]:
        if not isinstance(kw, dict):
            continue
        term = str(kw.get("term") or "").strip()
        if not term:
            continue
        table.append({
            "term": term,
            "category": kw.get("category") or "hard_skill",
            "required": bool(kw.get("required")),
            "variants": [s for s in (str(v).strip() for v in kw.get("variants") or [])
                         if s],
        })
    return table or None


# ---- Boundary-aware matching ---------------------------------------------------
def term_pattern(term: str) -> re.Pattern:
    """Case-insensitive pattern for `term` with guards built from its edge chars.

    Left guard (?<!\\w) blocks mid-word starts (Java inside JavaScript, .NET
    inside ASP.NET). Right guard is (?!\\w) normally; terms ending in # or +
    also exclude a following #/+ so C# doesn't hit C## nor C++ hit C+++.
    """
    t = term.strip()
    right = r"(?![#+\w])" if t and t[-1] in "#+" else r"(?!\w)"
    return re.compile(r"(?<!\w)" + re.escape(t) + right, re.IGNORECASE)


def count_hits(text: str, term: str, variants: list[str] | None = None) -> int:
    """Occurrences of the term or any variant in text (frequency-cap counting)."""
    total = 0
    for t in [term, *(variants or [])]:
        t = (t or "").strip()
        if t:
            total += len(term_pattern(t).findall(text))
    return total


def coverage(text: str, table: list[dict]) -> dict:
    """Coverage report: presence of required terms + per-term hit counts."""
    hits: dict[str, int] = {}
    missing: list[str] = []
    required_total = required_present = 0
    for kw in table:
        n = count_hits(text, kw["term"], kw.get("variants"))
        hits[kw["term"]] = n
        if kw.get("required"):
            required_total += 1
            if n:
                required_present += 1
            else:
                missing.append(kw["term"])
    return {"required_present": required_present, "required_total": required_total,
            "missing": missing, "hits": hits}
