"""Offline tests for pool expiry + fresh-first judge shortlist.

The ingest freshness filter only sees jobs on the way in, so the ranked/scored
pool used to keep stale postings forever — and after a score reset they hogged
the 15-slot judge shortlist ahead of brand-new arrivals. These tests cover the
two fixes: _expire_stale (pool aging) and _shortlist_fresh_first (new arrivals
claim judge slots first). Runs on throwaway temp DBs only.

Run:  python tests/test_pool_expiry.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhelper import db  # noqa: E402
from jobhelper.pipeline import _expire_stale, _shortlist_fresh_first  # noqa: E402


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def iso_days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(
        timespec="seconds")


def insert(conn, job_hash, status, date_posted=None, first_seen_at=None,
           embed_score=None):
    conn.execute(
        "INSERT INTO jobs (job_hash, source, title, status, date_posted, "
        "first_seen_at, embed_score) VALUES (?,?,?,?,?,?,?)",
        (job_hash, "test", job_hash, status, date_posted, first_seen_at,
         embed_score))


def status_of(conn, job_hash):
    return conn.execute("SELECT status, status_reason FROM jobs WHERE "
                        "job_hash=?", (job_hash,)).fetchone()


def test_expire_stale():
    print("== _expire_stale ==")
    with tempfile.TemporaryDirectory() as td:
        conn = sqlite3.connect(Path(td) / "t.db")
        conn.row_factory = sqlite3.Row
        try:
            db.init_db(conn)
            insert(conn, "old_posted", "ranked",
                   date_posted=iso_days_ago(40), first_seen_at=iso_days_ago(40))
            insert(conn, "fresh_posted", "scored",
                   date_posted=iso_days_ago(2), first_seen_at=iso_days_ago(2))
            insert(conn, "old_seen_no_date", "scored",
                   first_seen_at=iso_days_ago(40))
            insert(conn, "fresh_seen_no_date", "ranked",
                   first_seen_at=iso_days_ago(2))
            # Old posting already stale at ingest time but re-listed with a
            # fresh date would never reach here; what must NOT expire is a job
            # the user already has in flight, however old.
            insert(conn, "old_but_proposed", "proposed",
                   date_posted=iso_days_ago(90), first_seen_at=iso_days_ago(90))
            conn.commit()

            n = _expire_stale(conn, {"max_age_days": 15})
            check(n == 2, f"expires exactly the 2 stale pool jobs (got {n})")
            check(status_of(conn, "old_posted")[0] == "expired",
                  "stale date_posted -> expired")
            check(status_of(conn, "old_seen_no_date")[0] == "expired",
                  "no date_posted falls back to first_seen_at")
            check(status_of(conn, "fresh_posted")[0] == "scored",
                  "recent scored job untouched")
            check(status_of(conn, "fresh_seen_no_date")[0] == "ranked",
                  "recent ranked job untouched")
            check(status_of(conn, "old_but_proposed")[0] == "proposed",
                  "in-flight statuses never expire")
            check("older than 15 days" in status_of(conn, "old_posted")[1],
                  "reason names the age limit")

            n2 = _expire_stale(conn, {"max_age_days": 15})
            check(n2 == 0, "idempotent: second pass expires nothing")
            n3 = _expire_stale(conn, {})
            check(n3 == 0, "no max_age_days configured -> no-op")
        finally:
            conn.close()


def test_shortlist_fresh_first():
    print("== _shortlist_fresh_first ==")
    prev = iso_days_ago(1)

    def row(jid, embed, seen_days_ago):
        return {"id": jid, "embed_score": embed,
                "first_seen_at": iso_days_ago(seen_days_ago)}

    stale_hi = row(1, 0.90, 10)
    stale_mid = row(2, 0.88, 10)
    fresh_lo = row(3, 0.80, 0.1)
    fresh_mid = row(4, 0.85, 0.1)

    sel = _shortlist_fresh_first([stale_hi, fresh_lo, stale_mid, fresh_mid],
                                 3, prev)
    ids = [r["id"] for r in sel]
    check(ids == [4, 3, 1],
          f"fresh first (embed-desc), backlog fills the rest: {ids}")

    sel2 = _shortlist_fresh_first([stale_hi, fresh_lo], 5, prev)
    check([r["id"] for r in sel2] == [3, 1], "cap larger than pool returns all")

    sel3 = _shortlist_fresh_first([stale_hi, fresh_lo, fresh_mid], 5, None)
    check([r["id"] for r in sel3] == [1, 4, 3],
          "no previous run -> pure embed order")

    noseen = {"id": 9, "embed_score": 0.99, "first_seen_at": None}
    sel4 = _shortlist_fresh_first([noseen, fresh_lo], 1, prev)
    check([r["id"] for r in sel4] == [3],
          "missing first_seen_at counts as backlog, not fresh")


def test_previous_run_started_at():
    print("== previous_run_started_at ==")
    with tempfile.TemporaryDirectory() as td:
        conn = sqlite3.connect(Path(td) / "t.db")
        conn.row_factory = sqlite3.Row
        try:
            db.init_db(conn)
            check(db.previous_run_started_at(conn, "rC") is None,
                  "no runs -> None")
            conn.execute("INSERT INTO run_log (run_id, started_at, finished_at)"
                         " VALUES ('rA', '2026-07-17T10:00:00+00:00',"
                         " '2026-07-17T10:30:00+00:00')")
            conn.execute("INSERT INTO run_log (run_id, started_at) "
                         "VALUES ('rB', '2026-07-18T10:00:00+00:00')")
            conn.execute("INSERT INTO run_log (run_id, started_at) "
                         "VALUES ('rC', '2026-07-19T10:00:00+00:00')")
            conn.commit()
            got = db.previous_run_started_at(conn, "rC")
            check(got == "2026-07-17T10:00:00+00:00",
                  f"latest COMPLETED run wins (crashed rB skipped): {got}")
        finally:
            conn.close()


def main() -> int:
    test_expire_stale()
    test_shortlist_fresh_first()
    test_previous_run_started_at()
    print("\nALL POOL-EXPIRY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
