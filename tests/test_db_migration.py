"""Migration test for the jobs.ats_report column (ITEM-8).

There is no migration framework — SCHEMA is CREATE TABLE IF NOT EXISTS, so an
existing DB never picks up new columns from it. init_db() must add ats_report
via an idempotent ALTER TABLE guard. Runs on throwaway temp DBs only.

Run:  python tests/test_db_migration.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhelper import db  # noqa: E402

# Minimal stand-in for the pre-ITEM-8 jobs table (key point: no ats_report).
OLD_JOBS_SQL = """
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_hash TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT,
    updated_at TEXT
);
"""


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def cols(conn):
    return {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}


def test_migration():
    print("== ats_report migration ==")
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "old.db"

        # Simulate a live pre-ITEM-8 database with a row in it.
        conn = sqlite3.connect(path)
        try:
            conn.executescript(OLD_JOBS_SQL)
            conn.execute("INSERT INTO jobs (job_hash, source, title, status) "
                         "VALUES ('h1', 'remotive', 'Dev', 'proposed')")
            conn.commit()
            check("ats_report" not in cols(conn), "old DB lacks ats_report")

            db.init_db(conn)
            check("ats_report" in cols(conn), "init_db adds ats_report column")
            row = conn.execute(
                "SELECT ats_report FROM jobs WHERE job_hash='h1'").fetchone()
            check(row[0] is None, "existing row stays NULL (no backfill)")

            db.init_db(conn)  # idempotent — second run must not raise
            check("ats_report" in cols(conn), "running init_db twice is harmless")

            conn.row_factory = sqlite3.Row
            db.update_job(conn, 1,
                          ats_report={"coverage": {"required_present": 2}})
            raw = conn.execute(
                "SELECT ats_report FROM jobs WHERE id=1").fetchone()[0]
            check('"required_present": 2' in raw, "update_job writes ats_report JSON")
        finally:
            conn.close()


def test_fresh_db():
    print("== fresh DB has the column from SCHEMA ==")
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    check("ats_report" in cols(conn), "fresh init_db includes ats_report")
    conn.close()


def main() -> int:
    test_migration()
    test_fresh_db()
    print("\nALL MIGRATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
