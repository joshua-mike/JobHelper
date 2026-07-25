"""Offline regression test for the assisted-apply confirm-applied path.

The bug this guards: runner.py used to pass submit_confirmation=... to
db.update_job(), a column that exists neither in db.SCHEMA nor db._WRITABLE.
update_job() rejects non-whitelisted columns, so answering 'y' at the "type 'y'
to mark this job applied" prompt raised KeyError BEFORE the status flip, the
applied_at stamp, and the applications-log row — the job silently stayed
pending. mark_applied() is the extracted block; this exercises it directly, so
no browser or network is involved.

Run:  python tests/test_apply_mark_applied.py
"""
from __future__ import annotations

import csv
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhelper import applog, db  # noqa: E402
from jobhelper.apply.runner import mark_applied  # noqa: E402


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


JOB = {
    "id": 1,
    "company": "Acme",
    "title": "Senior Backend Engineer",
    "location": "Remote",
    "remote_type": "remote",
    "url": "https://job-boards.greenhouse.io/acme/jobs/1",
    "llm_score": 82,
    "tailored_resume_path": "data/resumes/2026-07-25/1/Resume.docx",
    "cover_letter_text": "Dear team",
}


def _seed(conn):
    db.init_db(conn)
    conn.execute(
        "INSERT INTO jobs (id, job_hash, source, title, company, url, status, "
        "llm_score) VALUES (?,?,?,?,?,?,?,?)",
        (JOB["id"], "h1", "greenhouse", JOB["title"], JOB["company"], JOB["url"],
         "tailored", JOB["llm_score"]))
    conn.commit()


def _rows():
    with applog.LOG_CSV.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_mark_applied():
    print("== mark_applied: DB row ==")
    with tempfile.TemporaryDirectory() as td:
        applog.LOG_CSV = Path(td) / "applications_log.csv"
        conn = sqlite3.connect(Path(td) / "t.db")
        conn.row_factory = sqlite3.Row
        try:
            _seed(conn)

            # The regression itself: this used to raise KeyError on a
            # non-whitelisted column before touching anything.
            stamp = mark_applied(conn, JOB, "greenhouse")

            row = conn.execute("SELECT status, applied_at FROM jobs WHERE id=1"
                               ).fetchone()
            check(row["status"] == "applied", "status flipped to 'applied'")
            check(row["applied_at"] == stamp, "applied_at set to the returned stamp")
            check(bool(stamp), "a timestamp was returned")

            # Committed, not just pending on this connection — assisted_apply()
            # closes the connection right after and the UI reads it back.
            other = sqlite3.connect(Path(td) / "t.db")
            check(other.execute("SELECT status FROM jobs WHERE id=1").fetchone()[0]
                  == "applied", "the update is committed")
            other.close()

            print("== mark_applied: applications log ==")
            rows = _rows()
            check(len(rows) == 1, "one row appended to the log")
            r = rows[0]
            check(r["job_id"] == "1", "keyed by job_id")
            check(r["company"] == "Acme" and r["title"] == JOB["title"],
                  "company/title logged")
            check(r["applied_via"] == "assisted-apply (greenhouse)",
                  "applied_via records the assisted-apply channel + ATS")
            check(r["ats"] == "greenhouse", "ATS derived from the url")
            check(r["applied_at"] == stamp, "log timestamp matches the DB stamp")
        finally:
            conn.close()


def test_only_whitelisted_columns():
    """Guard the general rule, not just this one column: every field
    mark_applied() writes must be in db._WRITABLE, or update_job() raises."""
    print("== update_job column whitelist ==")
    check("applied_at" in db._WRITABLE and "status" in db._WRITABLE,
          "the columns mark_applied writes are whitelisted")
    check("submit_confirmation" not in db._WRITABLE,
          "submit_confirmation is still not a column (fix was to drop it)")

    with tempfile.TemporaryDirectory() as td:
        conn = sqlite3.connect(Path(td) / "t.db")
        conn.row_factory = sqlite3.Row
        try:
            _seed(conn)
            raised = False
            try:
                db.update_job(conn, 1, status="applied",
                              submit_confirmation="assisted apply (greenhouse)")
            except KeyError:
                raised = True
            check(raised, "update_job still rejects a non-whitelisted column")
        finally:
            conn.close()


def main() -> int:
    test_mark_applied()
    test_only_whitelisted_columns()
    print("\nALL ASSISTED-APPLY MARK-APPLIED CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
