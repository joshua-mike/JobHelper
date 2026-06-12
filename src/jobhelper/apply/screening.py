"""Best-effort answers to common screening dropdowns.

Maps a question's text to a desired answer derived from the master profile, and
picks the matching option from a dropdown's option list. PURE logic (no browser)
so the risky knockout-question polarity is unit-tested offline.

Design stance: only answer questions we can map confidently from explicit profile
fields; leave everything else for the human. Every auto-answer is reported so the
human verifies before submitting (a wrong knockout answer can auto-reject).
"""
from __future__ import annotations

import re
from typing import Any, Callable

YES, NO, DECLINE = "yes", "no", "decline"


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "yes", "1")


def _falsey(v: Any) -> bool:
    return str(v).strip().lower() in ("false", "no", "0")


def _work_auth(p: dict) -> str | None:
    ident = p.get("identity", {}) or {}
    if _truthy(ident.get("requires_sponsorship")):
        return None  # needs sponsorship — auth answer is ambiguous, leave to human
    status = str(ident.get("work_authorization_status", "")).lower()
    if any(k in status for k in ("authoriz", "citizen", "permanent resident",
                                 "green card", "eligible", "no sponsorship")):
        return YES
    return None


def _sponsorship(p: dict) -> str | None:
    ident = p.get("identity", {}) or {}
    v = ident.get("requires_sponsorship")
    if _truthy(v):
        return YES
    if _falsey(v) or v is False:
        return NO
    return None


def _relocate(p: dict) -> str | None:
    v = (p.get("identity", {}) or {}).get("willing_to_relocate")
    if isinstance(v, bool):
        return YES if v else NO
    if _truthy(v):
        return YES
    if _falsey(v) or v is False:
        return NO
    return None


def _yes(_p: dict) -> str:
    return YES


def _decline(_p: dict) -> str:
    return DECLINE


# Order matters: check sponsorship before work-auth-style "eligible" phrasing.
RULES: list[dict[str, Any]] = [
    {"name": "sponsorship",
     "patterns": [r"require\s+(?:visa\s+)?sponsor", r"need\s+(?:visa\s+)?sponsor",
                  r"visa\s+sponsor", r"sponsorship\s+(?:now|in the future|to)",
                  r"will you (?:now or )?.*sponsor"],
     "answer": _sponsorship},
    {"name": "work_authorization",
     "patterns": [r"authori[sz]ed to work", r"legally\s+(?:authori|eligible|entitled|able)",
                  r"eligible to work", r"right to work", r"lawfully.*work"],
     "answer": _work_auth},
    {"name": "relocate",
     "patterns": [r"willing to relocate", r"open to relocat", r"able to relocate"],
     "answer": _relocate},
    {"name": "age18",
     "patterns": [r"at least 18", r"18 years (?:of age|or older)", r"are you 18"],
     "answer": _yes},
    {"name": "gender", "patterns": [r"\bgender\b", r"what is your sex\b"], "answer": _decline},
    {"name": "race", "patterns": [r"\brace\b", r"ethnicit", r"hispanic", r"latino"],
     "answer": _decline},
    {"name": "veteran", "patterns": [r"veteran", r"military service"], "answer": _decline},
    {"name": "disability", "patterns": [r"disabilit"], "answer": _decline},
]


def desired_answer(question_text: str, profile: dict) -> tuple[str | None, str | None]:
    """Return (rule_name, answer_kind). answer_kind is None when matched-but-unsure."""
    t = (question_text or "").lower()
    for rule in RULES:
        if any(re.search(p, t) for p in rule["patterns"]):
            return rule["name"], rule["answer"](profile)
    return None, None


_PLACEHOLDERS = {"", "-", "--", "select...", "select", "please select",
                 "please select an option", "choose...", "choose"}


_KINDS: dict[str, list[Callable[[str], bool]]] = {
    YES: [
        lambda o: o == "yes",
        lambda o: o.startswith("yes,") or o.startswith("yes "),
        lambda o: o == "true",
        lambda o: o.startswith("i am") and " not " not in f" {o} ",
    ],
    NO: [
        lambda o: o == "no",
        lambda o: o.startswith("no,") or o.startswith("no "),
        lambda o: o == "false",
        lambda o: "do not" in o or "don't" in o or "i am not" in o,
    ],
    DECLINE: [
        lambda o: "decline" in o,
        lambda o: "prefer not" in o,
        lambda o: "wish not" in o or "do not wish" in o or "don't wish" in o,
        lambda o: "not to answer" in o or "not to disclose" in o,
        lambda o: "i don't want" in o,
    ],
}


def pick_option(options: list[str], kind: str) -> int | None:
    """Index of the option best matching the desired answer kind, or None.

    Note: a valid index can be 0, so predicates are checked with `is not None`
    (never truthiness) to avoid silently skipping the first option.
    """
    norm = [(o or "").strip().lower() for o in options]

    def find(pred: Callable[[str], bool]) -> int | None:
        for i, o in enumerate(norm):
            if o in _PLACEHOLDERS:
                continue
            if pred(o):
                return i
        return None

    for pred in _KINDS.get(kind, []):
        idx = find(pred)
        if idx is not None:
            return idx
    return None
