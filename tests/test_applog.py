"""Offline tests for the applications log (upsert/remove). Uses a temp CSV path.
Run:  python tests/test_applog.py
"""
from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhelper import applog


def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _rows():
    with applog.LOG_CSV.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    tmp = Path(tempfile.mkdtemp()) / "applications_log.csv"
    applog.LOG_CSV = tmp  # redirect writes to a temp file

    job1 = {"id": 1, "company": "Acme", "title": "Backend Engineer",
            "location": "Remote", "remote_type": "remote",
            "url": "https://job-boards.greenhouse.io/acme/jobs/1",
            "llm_score": 82, "tailored_resume_path": "data/r1.docx",
            "cover_letter_text": "Dear team", "applied_at": "2026-06-08T10:00:00+00:00"}
    job2 = {"id": 2, "company": "Globex", "title": "Platform Engineer",
            "url": "https://jobs.lever.co/globex/abc", "llm_score": 71,
            "applied_at": "2026-06-08T11:00:00+00:00"}

    print("== record + read back ==")
    applog.record_application(job1, "review-page")
    rows = _rows()
    check(len(rows) == 1, "one row after first record")
    r = rows[0]
    check(r["company"] == "Acme" and r["title"] == "Backend Engineer", "company/title logged")
    check(r["ats"] == "greenhouse", "ATS derived from url")
    check(r["applied_via"] == "review-page", "applied_via logged")
    check(r["cover_letter_used"] == "yes", "cover-letter flag")
    check(r["applied_at"] == "2026-06-08T10:00:00+00:00", "applied_at preserved")

    print("== upsert (same job_id does not duplicate) ==")
    job1b = dict(job1, llm_score=90)
    applog.record_application(job1b, "assisted-apply (greenhouse)")
    rows = _rows()
    check(len(rows) == 1, "still one row after re-record")
    check(rows[0]["llm_score"] == "90", "row updated in place")
    check(rows[0]["applied_via"] == "assisted-apply (greenhouse)", "applied_via updated")

    print("== second job appends ==")
    applog.record_application(job2, "review-page")
    rows = _rows()
    check(len(rows) == 2, "two rows for two jobs")
    # Sorted by applied_at desc -> job2 (11:00) first
    check(rows[0]["company"] == "Globex", "newest application sorts first")

    print("== remove (undo) ==")
    applog.remove_application(1)
    rows = _rows()
    check(len(rows) == 1 and rows[0]["company"] == "Globex", "job 1 removed on undo")
    applog.remove_application(999)  # no-op, must not error
    check(len(_rows()) == 1, "removing missing id is a no-op")

    print("\nALL APPLOG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
