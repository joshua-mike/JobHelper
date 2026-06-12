"""Offline tests for screening auto-answers — especially knockout POLARITY, since
a wrong answer auto-rejects. Run:  python tests/test_screening.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhelper.apply.screening import desired_answer, pick_option

AUTHORIZED = {"identity": {"work_authorization_status": "Authorized to work in the US",
                           "requires_sponsorship": False, "willing_to_relocate": False}}
NEEDS_SPONSOR = {"identity": {"work_authorization_status": "Need H1B",
                             "requires_sponsorship": True, "willing_to_relocate": True}}


def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    print("== desired_answer: polarity (authorized, no sponsorship) ==")
    check(desired_answer("Are you legally authorized to work in the US?", AUTHORIZED)
          == ("work_authorization", "yes"), "authorized -> work_auth=yes")
    check(desired_answer("Will you now or in the future require visa sponsorship?", AUTHORIZED)
          == ("sponsorship", "no"), "no sponsorship needed -> sponsorship=no")
    check(desired_answer("Are you willing to relocate?", AUTHORIZED)
          == ("relocate", "no"), "relocate False -> no")

    print("== desired_answer: polarity (needs sponsorship) ==")
    check(desired_answer("Do you require sponsorship for employment?", NEEDS_SPONSOR)
          == ("sponsorship", "yes"), "needs sponsorship -> sponsorship=yes")
    # When sponsorship is needed, work-auth is ambiguous -> matched but no answer.
    rule, kind = desired_answer("Are you authorized to work?", NEEDS_SPONSOR)
    check(rule == "work_authorization" and kind is None, "needs sponsor -> work_auth left blank")
    check(desired_answer("Are you open to relocation?", NEEDS_SPONSOR)
          == ("relocate", "yes"), "relocate True -> yes")

    print("== desired_answer: EEO -> decline, age -> yes ==")
    check(desired_answer("What is your gender?", AUTHORIZED) == ("gender", "decline"), "gender decline")
    check(desired_answer("Race/Ethnicity", AUTHORIZED) == ("race", "decline"), "race decline")
    check(desired_answer("Are you a protected veteran?", AUTHORIZED) == ("veteran", "decline"), "veteran decline")
    check(desired_answer("Disability Status", AUTHORIZED) == ("disability", "decline"), "disability decline")
    check(desired_answer("Are you at least 18 years of age?", AUTHORIZED) == ("age18", "yes"), "age18 yes")

    print("== desired_answer: unknown question left alone ==")
    check(desired_answer("How did you hear about us?", AUTHORIZED) == (None, None), "unknown -> none")
    check(desired_answer("What are your salary expectations?", AUTHORIZED) == (None, None), "salary -> none (free text)")

    print("== pick_option: option matching ==")
    check(pick_option(["Select...", "Yes", "No"], "yes") == 1, "yes among placeholder")
    check(pick_option(["Select...", "Yes", "No"], "no") == 2, "no among placeholder")
    check(pick_option(["Yes, I am authorized", "No, I am not"], "yes") == 0, "verbose yes")
    check(pick_option(["Yes, I am authorized", "No, I am not"], "no") == 1, "verbose no")
    check(pick_option(["I am authorized to work", "I require sponsorship"], "yes") == 0,
          "'I am authorized' -> yes")
    check(pick_option(["Male", "Female", "Decline to self-identify"], "decline") == 2, "decline option")
    check(pick_option(["Prefer not to say", "Yes", "No"], "decline") == 0, "prefer-not -> decline")

    print("== pick_option: must NOT mismatch ==")
    check(pick_option(["None of the above", "Yes", "No"], "no") == 2, "'None...' is not 'no'")
    check(pick_option(["Yes", "No"], "decline") is None, "no decline option -> None")
    check(pick_option(["Select an option"], "yes") is None, "only placeholder -> None")

    print("\nALL SCREENING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
