"""Offline test for the remote-only filter + per-company onsite exemption.
Run:  python tests/test_filters_remote.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhelper.rank.filters import passes

# Minimal criteria: remote-only, with xAI exempted. Title/keyword gates kept
# permissive so we isolate the remote/location behavior.
CRITERIA = {
    "remote_required": True,
    "onsite_ok_companies": ["xAI"],
    "allowed_location_tokens": ["USA", "United States", "US", "Remote"],
    "title_include_any": ["engineer"],
    "keywords_any": ["software engineer"],
}


def job(company, location, remote_type="unknown"):
    return {
        "title": "Software Engineer",
        "description_clean": "We need a software engineer.",
        "company": company,
        "location": location,
        "candidate_location": location,
        "remote_type": remote_type,
    }


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    print("== onsite role at a normal company is rejected ==")
    ok, reason = passes(job("Acme Corp", "Palo Alto, CA"), CRITERIA)
    check(not ok, f"rejected (reason: {reason!r})")

    print("== onsite role at an exempt company (xAI) passes ==")
    ok, reason = passes(job("xAI", "Palo Alto, CA"), CRITERIA)
    check(ok, f"xAI onsite kept (reason: {reason!r})")

    print("== exemption is case-insensitive ==")
    ok, _ = passes(job("XAI", "Memphis, TN"), CRITERIA)
    check(ok, "‘XAI’ matches ‘xAI’")

    print("== exemption is EXACT, not substring (CapitexAI != xAI) ==")
    ok, reason = passes(job("CapitexAI", "New York, NY"), CRITERIA)
    check(not ok, f"CapitexAI onsite still rejected (reason: {reason!r})")

    print("== exempt company also bypasses the location-token restriction ==")
    # "Palo Alto, CA" contains none of the allowed_location_tokens.
    ok, reason = passes(job("xAI", "Palo Alto, CA", remote_type="onsite"), CRITERIA)
    check(ok, f"xAI explicit-onsite kept past location gate (reason: {reason!r})")

    print("== exemption is scoped to US: intl onsite at xAI is rejected ==")
    for intl in ("London, UK", "Tokyo, JP", "Paris, France"):
        ok, reason = passes(job("xAI", intl, remote_type="onsite"), CRITERIA)
        check(not ok, f"xAI {intl} rejected (reason: {reason!r})")

    print("== multi-location with a US option is kept ==")
    ok, reason = passes(job("xAI", "London, UK; New York, NY", remote_type="onsite"), CRITERIA)
    check(ok, f"xAI multi-loc with US part kept (reason: {reason!r})")

    print("== a genuine remote role at a normal company still passes ==")
    ok, reason = passes(job("Acme Corp", "Remote - US", remote_type="remote"), CRITERIA)
    check(ok, f"remote role kept (reason: {reason!r})")

    print("== empty exemption list => strict remote-only for everyone ==")
    strict = dict(CRITERIA, onsite_ok_companies=[])
    ok, _ = passes(job("xAI", "Palo Alto, CA"), strict)
    check(not ok, "xAI onsite rejected when list is empty")

    print("\nALL REMOTE-FILTER CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
