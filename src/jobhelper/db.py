"""SQLite layer. The schema enforces idempotency (UNIQUE job_hash) and a status
state machine so daily re-runs never re-source, re-tailor, or double-propose."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable

from .models import RawJob
from .util import DB_PATH, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    job_hash            TEXT UNIQUE NOT NULL,
    source              TEXT NOT NULL,
    source_job_id       TEXT,
    url                 TEXT,
    title               TEXT,
    company             TEXT,
    location            TEXT,
    remote_type         TEXT,
    salary_min          INTEGER,
    salary_max          INTEGER,
    salary_currency     TEXT,
    candidate_location  TEXT,
    description_raw     TEXT,
    description_clean   TEXT,
    tags                TEXT,           -- JSON array
    date_posted         TEXT,
    first_seen_at       TEXT,
    embed_score         REAL,
    llm_score           INTEGER,
    llm_musthaves_met   TEXT,           -- JSON
    llm_missing         TEXT,           -- JSON
    llm_rationale       TEXT,
    tailored_resume_path TEXT,
    cover_letter_text   TEXT,
    change_log          TEXT,           -- JSON
    screening_answers   TEXT,           -- JSON
    ats_report          TEXT,           -- JSON: keyword table + coverage + warnings
    status              TEXT NOT NULL DEFAULT 'new',
    status_reason       TEXT,
    proposed_in_run_id  TEXT,
    approved_at         TEXT,
    applied_at          TEXT,
    error_text          TEXT,
    created_at          TEXT,
    updated_at          TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS source_suggestions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL,
    token           TEXT NOT NULL,
    entry           TEXT,           -- JSON: workday {tenant,dc,site,company}
    company         TEXT,
    evidence_count  INTEGER DEFAULT 0,
    best_score      INTEGER,
    live_count      INTEGER,
    sample          TEXT,           -- JSON array of live job titles
    via             TEXT DEFAULT 'url',  -- url | redirect | guess
    status          TEXT NOT NULL DEFAULT 'suggested',  -- suggested|accepted|dismissed
    created_at      TEXT,
    updated_at      TEXT,
    UNIQUE(kind, token)
);

CREATE TABLE IF NOT EXISTS run_log (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT,
    finished_at TEXT,
    sourced     INTEGER DEFAULT 0,
    new_jobs    INTEGER DEFAULT 0,
    filtered    INTEGER DEFAULT 0,
    scored      INTEGER DEFAULT 0,
    proposed    INTEGER DEFAULT 0,
    errors      INTEGER DEFAULT 0,
    notes       TEXT
);
"""

# Columns that update_job() is allowed to write.
_WRITABLE = {
    "url", "title", "company", "location", "remote_type", "salary_min",
    "salary_max", "salary_currency", "candidate_location", "description_raw",
    "description_clean", "tags", "date_posted", "embed_score", "llm_score",
    "llm_musthaves_met", "llm_missing", "llm_rationale", "tailored_resume_path",
    "cover_letter_text", "change_log", "screening_answers", "ats_report", "status",
    "status_reason", "proposed_in_run_id", "approved_at", "applied_at",
    "error_text",
}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Columns added after a DB already exists: SCHEMA is CREATE TABLE IF NOT
    # EXISTS, so editing it alone never reaches live databases.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    if "ats_report" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN ats_report TEXT")
    conn.commit()


def insert_job(conn: sqlite3.Connection, job: RawJob) -> bool:
    """INSERT OR IGNORE on job_hash. Returns True only if a NEW row was created."""
    ts = now_iso()
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO jobs (
            job_hash, source, source_job_id, url, title, company, location,
            remote_type, salary_min, salary_max, salary_currency,
            candidate_location, description_raw, description_clean, tags,
            date_posted, first_seen_at, status, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            job.job_hash, job.source, job.source_job_id, job.url, job.title,
            job.company, job.location, job.remote_type, job.salary_min,
            job.salary_max, job.salary_currency, job.candidate_location,
            job.description_raw, job.description_clean, json.dumps(job.tags),
            job.date_posted, ts, "new", ts, ts,
        ),
    )
    return cur.rowcount > 0


def update_job(conn: sqlite3.Connection, job_id: int, **fields: Any) -> None:
    cols = []
    vals = []
    for k, v in fields.items():
        if k not in _WRITABLE:
            raise KeyError(f"Refusing to write non-whitelisted column: {k}")
        cols.append(f"{k}=?")
        vals.append(json.dumps(v) if isinstance(v, (list, dict)) else v)
    cols.append("updated_at=?")
    vals.append(now_iso())
    vals.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE id=?", vals)


def jobs_by_status(conn: sqlite3.Connection, *statuses: str) -> list[sqlite3.Row]:
    qmarks = ",".join("?" * len(statuses))
    return list(conn.execute(
        f"SELECT * FROM jobs WHERE status IN ({qmarks}) ORDER BY id", statuses
    ))


def get_job(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


# ---- run_log -----------------------------------------------------------------
def start_run(conn: sqlite3.Connection, run_id: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO run_log (run_id, started_at) VALUES (?, ?)",
        (run_id, now_iso()),
    )
    conn.commit()


def finish_run(conn: sqlite3.Connection, run_id: str, **counts: Any) -> None:
    sets = ", ".join(f"{k}=?" for k in counts)
    vals = list(counts.values())
    conn.execute(
        f"UPDATE run_log SET finished_at=?, {sets} WHERE run_id=?",
        [now_iso(), *vals, run_id],
    )
    conn.commit()
