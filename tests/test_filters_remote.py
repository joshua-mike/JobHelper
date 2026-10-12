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


def job(company, location, remote_type="unknown",
        description="We need a software engineer."):
    return {
        "title": "Software Engineer",
        "description_clean": description,
        "company": company,
        "location": location,
        "candidate_location": location,
        "remote_type": remote_type,
    }


# Pushes a sentence past the 400-character head the bare-word check reads.
FILLER = "We need a software engineer to build and run our services. " * 10


def deep(sentence):
    return FILLER + sentence + " " + FILLER


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

    print("== foreign country codes that collide with US state codes are NOT US ==")
    # 'City, Region, CC' where CC collides with a state abbr (IN India/Indiana,
    # CA Canada/California, DE Germany/Delaware). Trailing token is the country.
    ms = dict(CRITERIA, onsite_ok_companies=["Microsoft"])
    for loc in ("Bengaluru, KA, IN", "Hyderabad, TS, IN; Noida, UP, IN",
                "Toronto, ON, CA", "Berlin, BE, DE"):
        ok, reason = passes(job("Microsoft", loc, remote_type="onsite"), ms)
        check(not ok, f"{loc!r} rejected (reason: {reason!r})")
    # ...but the genuine US forms still pass.
    for loc in ("Redmond, WA, US", "Redmond, WA, US; Bengaluru, KA, IN",
                "Arlington, Virginia, USA"):
        ok, reason = passes(job("Microsoft", loc, remote_type="onsite"), ms)
        check(ok, f"{loc!r} kept (reason: {reason!r})")

    print("== a genuine remote role at a normal company still passes ==")
    ok, reason = passes(job("Acme Corp", "Remote - US", remote_type="remote"), CRITERIA)
    check(ok, f"remote role kept (reason: {reason!r})")

    print("== empty exemption list => strict remote-only for everyone ==")
    strict = dict(CRITERIA, onsite_ok_companies=[])
    ok, _ = passes(job("xAI", "Palo Alto, CA"), strict)
    check(not ok, "xAI onsite rejected when list is empty")

    print("== ITEM-46: a remote statement past char 400 confirms remote ==")
    check(len(FILLER) > 400, "filler pushes the statement past the 400-char head")
    for sentence, loc in [
            ("This role is fully remote.", "United States"),               # Skylight
            ("This is a remote, on-call role that provides flexibility.", "Reston, VA"),
            ("Job Location: Remote work is authorized.", "Reston, VA"),    # ICF
            ("Job Location: Remote (USA). Local candidates may visit.", "Reston, VA"),
            ("Work is fully remote within the United States.", "Reston, VA"),
            ("This position is fully remote within the U.S.; some travel.", "Reston, VA")]:
        ok, reason = passes(job("Acme Corp", loc, description=deep(sentence)), CRITERIA)
        check(ok, f"{sentence!r} @ {loc!r} kept (reason: {reason!r})")

    print("== ITEM-46: negated statements are still rejected ==")
    for sentence in [
            "This is NOT a remote work opportunity.",
            "This is a fully on-site position; hybrid or remote work is not available.",
            "Must be onsite 4 days a week, remote work is not an option for this role.",
            "This position requires being onsite and does not support remote or hybrid work.",
            "This is not a fully remote role."]:
        ok, reason = passes(job("Acme Corp", "Melbourne, FL", description=deep(sentence)), CRITERIA)
        check(not ok and reason == "remote not confirmed", f"{sentence!r} rejected (reason: {reason!r})")

    print("== ITEM-46: remote that isn't about this job's workplace is rejected ==")
    for sentence in [
            "Remote: If this position is listed as remote, there may be in-person days.",
            "You will apply AI to problems in remote sensing and remote monitoring.",
            "We are a remote-first company with a headquarters in Berlin.",
            "We offer on-site, hybrid, or remote work options across teams.",
            "This role is remote 2 days a week and in our office otherwise.",
            "This position is remote, hybrid with weekly team days."]:
        ok, reason = passes(job("Acme Corp", "San Diego, CA", description=deep(sentence)), CRITERIA)
        check(not ok and reason == "remote not confirmed", f"{sentence!r} rejected (reason: {reason!r})")

    print("== ITEM-46: a statement only counts for a US-located job ==")
    for loc in ("", "Heredia, Heredia, CR"):
        ok, reason = passes(job("Acme Corp", loc, description=deep("Location: Remote (Europe).")), CRITERIA)
        check(not ok, f"'Remote (Europe)' @ {loc!r} rejected (reason: {reason!r})")

    print("== ITEM-46: US 'City, ST' satisfies a US token on a confirmed-remote job ==")
    ok, reason = passes(job("Acme Corp", "Reston, VA", remote_type="remote"), CRITERIA)
    check(ok, f"remote @ 'Reston, VA' kept (reason: {reason!r})")
    ok, reason = passes(job("Acme Corp", "Washington, D.C", remote_type="remote"), CRITERIA)
    check(ok, f"remote @ 'Washington, D.C' kept (reason: {reason!r})")
    ok, reason = passes(job("Acme Corp", "New York, NY", remote_type="hybrid"), CRITERIA)
    check(not ok, f"hybrid @ 'New York, NY' still location-restricted (reason: {reason!r})")
    ok, reason = passes(job("Acme Corp", "San Diego, CA",
                            description="Ocean remote sensing for national defense."), CRITERIA)
    check(not ok, f"head-only 'remote sensing' @ 'San Diego, CA' rejected (reason: {reason!r})")
    ok, reason = passes(job("Acme Corp", "Toronto, ON", remote_type="remote"), CRITERIA)
    check(not ok, f"remote @ 'Toronto, ON' still rejected (reason: {reason!r})")
    no_us = dict(CRITERIA, allowed_location_tokens=["Anywhere"])
    ok, reason = passes(job("Acme Corp", "Reston, VA", remote_type="remote"), no_us)
    check(not ok, f"no US token configured => 'Reston, VA' rejected (reason: {reason!r})")

    print("\nALL REMOTE-FILTER CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
