"""Offline tests for the two dedupe layers: identity (job_hash, incl. the
volatile-URL sources) and content (content_hash -> status 'duplicate').
Run:  python tests/test_dedupe.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhelper import db
from jobhelper.models import RawJob
from jobhelper.util import stable_hash


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn


def _job(**kw) -> RawJob:
    base = dict(
        source="adzuna", source_job_id="1001",
        url="https://www.adzuna.com/land/ad/1001?se=tokenA&v=X",
        title="Senior Software Developer", company="Syms Strategic Group, LLC",
        description_raw="SSG is seeking a talented developer",
        description_clean="SSG is seeking a talented developer",
    )
    base.update(kw)
    return RawJob(**base)


def test_volatile_url_identity():
    print("== volatile-URL identity (Adzuna) ==")
    a = _job(volatile_url=True)
    b = _job(volatile_url=True,
             url="https://www.adzuna.com/details/1001?utm_medium=api")
    check(a.job_hash == b.job_hash,
          "same ad id -> same hash despite changed redirect URL")
    check(a.job_hash == stable_hash("adzuna", "1001"),
          "volatile_url hashes source+id, not the URL")
    c = _job()  # default: URL is the identity
    check(c.job_hash == stable_hash(c.url), "non-volatile sources still hash URL")

    conn = _mem_db()
    check(db.insert_job(conn, a) == "new", "first fetch inserts")
    check(db.insert_job(conn, b) is None,
          "re-fetch with fresh se= token is identity-ignored")


def test_content_duplicate():
    print("== content dedup ==")
    conn = _mem_db()
    check(db.insert_job(conn, _job()) == "new", "canonical row inserts as new")
    # Same ad posted per-city: fresh ad id + URL, identical content.
    dup = _job(source_job_id="1002",
               url="https://www.adzuna.com/land/ad/1002?se=tokenB",
               location="Ann Arbor, Washtenaw County")
    check(db.insert_job(conn, dup) == "duplicate", "content twin -> 'duplicate'")
    row = conn.execute(
        "SELECT * FROM jobs WHERE source_job_id='1002'").fetchone()
    canon = conn.execute(
        "SELECT id FROM jobs WHERE source_job_id='1001'").fetchone()
    check(row["status"] == "duplicate", "row parked as duplicate")
    check(row["status_reason"] == f"duplicate of job #{canon['id']}",
          "status_reason points at the canonical row")
    # Third copy still points at the canonical, not the duplicate.
    tri = _job(source_job_id="1003",
               url="https://www.adzuna.com/land/ad/1003?se=tokenC")
    check(db.insert_job(conn, tri) == "duplicate", "third copy -> 'duplicate'")
    row3 = conn.execute(
        "SELECT status_reason FROM jobs WHERE source_job_id='1003'").fetchone()
    check(row3["status_reason"] == f"duplicate of job #{canon['id']}",
          "duplicates chain to the canonical, never to each other")
    # Different content from the same company is NOT a duplicate.
    other = _job(source_job_id="2001", url="https://x.example/2001",
                 title="Full Stack Developer",
                 description_clean="A different req entirely")
    check(db.insert_job(conn, other) == "new", "different content stays new")


def test_thin_rows_never_content_match():
    print("== thin rows ==")
    check(_job(description_clean="").content_hash is None,
          "blank description -> no content identity")
    conn = _mem_db()
    a = _job(source_job_id="3001", url="https://x.example/3001",
             description_raw="", description_clean="")
    b = _job(source_job_id="3002", url="https://x.example/3002",
             description_raw="", description_clean="")
    check(db.insert_job(conn, a) == "new", "thin row inserts as new")
    check(db.insert_job(conn, b) == "new",
          "second thin row is NOT collapsed (nothing safe to compare)")


def test_window_expiry():
    print("== repost window ==")
    conn = _mem_db()
    db.insert_job(conn, _job())
    # Age the canonical past the window: an identical posting now reads as a
    # genuinely re-opened req.
    conn.execute("UPDATE jobs SET first_seen_at = date('now', ?)",
                 (f"-{db.CONTENT_DUP_WINDOW_DAYS + 5} days",))
    late = _job(source_job_id="1002",
                url="https://www.adzuna.com/land/ad/1002?se=tokenB")
    check(db.insert_job(conn, late) == "new",
          f"content match older than {db.CONTENT_DUP_WINDOW_DAYS}d is not a dup")


def test_migration_backfill():
    print("== migration backfill ==")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Pre-migration jobs table: no content_hash (and no ats_report).
    conn.execute("""CREATE TABLE jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, job_hash TEXT UNIQUE NOT NULL,
        source TEXT, source_job_id TEXT, url TEXT, title TEXT, company TEXT,
        location TEXT, remote_type TEXT, salary_min INTEGER,
        salary_max INTEGER, salary_currency TEXT, candidate_location TEXT,
        description_raw TEXT, description_clean TEXT, tags TEXT,
        date_posted TEXT, status TEXT NOT NULL DEFAULT 'new',
        status_reason TEXT, first_seen_at TEXT, created_at TEXT,
        updated_at TEXT)""")
    conn.execute(
        "INSERT INTO jobs (job_hash, title, company, description_clean, status,"
        " first_seen_at) VALUES ('h1','Dev','Acme','Great job','tailored',"
        " datetime('now'))")
    conn.execute(
        "INSERT INTO jobs (job_hash, title, company, description_clean, status,"
        " first_seen_at) VALUES ('h2','Dev','Acme','','new', datetime('now'))")
    db.init_db(conn)
    rows = {r["job_hash"]: r for r in conn.execute("SELECT * FROM jobs")}
    check(rows["h1"]["content_hash"] == stable_hash("Acme", "Dev", "Great job"),
          "existing row backfilled")
    check(rows["h1"]["status"] == "tailored", "backfill leaves statuses alone")
    check(rows["h2"]["content_hash"] is None, "thin row stays NULL")
    # New content twins of a backfilled row are caught immediately.
    twin = RawJob(source="adzuna", source_job_id="9", url="https://x.example/9",
                  title="Dev", company="Acme", description_clean="Great job")
    check(db.insert_job(conn, twin) == "duplicate",
          "post-migration insert dedupes against backfilled history")


if __name__ == "__main__":
    test_volatile_url_identity()
    test_content_duplicate()
    test_thin_rows_never_content_match()
    test_window_expiry()
    test_migration_backfill()
    print("ALL PASS")
