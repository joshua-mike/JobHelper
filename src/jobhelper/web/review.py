"""Review data + actions for the dashboard API.

Thin query/serialization layer over review.actions (shared with the legacy
review page) so /api/review/* stays in lockstep with review.py while both
UIs exist. Query shapes and ordering mirror review/app.py's index().
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import db
from ..review.actions import PENDING, apply_action, enrich
from ..review.actions import launch_assisted_apply as launch_assist

# What the frontend sees. Raw descriptions stay out of the payload — the board
# shows the LLM rationale/chips, with a link out to the posting itself.
_FIELDS = (
    "id", "title", "company", "location", "candidate_location", "remote_type",
    "salary_min", "salary_max", "salary_currency", "url", "source", "status",
    "llm_score", "llm_rationale", "cover_letter_text", "date_posted",
    "first_seen_at", "proposed_in_run_id", "approved_at", "applied_at",
    "updated_at",
    # added by enrich():
    "display_score", "musthaves_met", "missing", "notes", "screening",
    "has_resume", "ats", "can_assist", "ats_report",
)


def _serialize(row) -> dict[str, Any]:
    job = enrich(dict(row))
    return {k: job.get(k) for k in _FIELDS}


def review_lists() -> dict[str, list[dict[str, Any]]]:
    conn = db.connect()
    try:
        qmarks = ",".join("?" * len(PENDING))
        pending = [_serialize(r) for r in conn.execute(
            f"SELECT * FROM jobs WHERE status IN ({qmarks}) "
            f"ORDER BY (llm_score IS NULL), llm_score DESC, embed_score DESC",
            PENDING)]
        applied = [_serialize(r) for r in conn.execute(
            "SELECT * FROM jobs WHERE status='applied' "
            "ORDER BY applied_at DESC LIMIT 50")]
        skipped = [_serialize(r) for r in conn.execute(
            "SELECT * FROM jobs WHERE status='skipped' "
            "ORDER BY updated_at DESC LIMIT 50")]
    finally:
        conn.close()
    return {"pending": pending, "applied": applied, "skipped": skipped}


def act(job_id: int, action: str) -> dict[str, Any] | None:
    """Apply a review action; returns the updated job, or None if no such job."""
    conn = db.connect()
    try:
        if db.get_job(conn, job_id) is None:
            return None
        apply_action(conn, job_id, action, via="dashboard")
        conn.commit()
        return _serialize(db.get_job(conn, job_id))
    finally:
        conn.close()


def resume_path(job_id: int) -> Path | None:
    conn = db.connect()
    try:
        row = db.get_job(conn, job_id)
    finally:
        conn.close()
    if not row or not row["tailored_resume_path"]:
        return None
    path = Path(row["tailored_resume_path"])
    return path if path.exists() else None


def can_assist(job_id: int) -> bool | None:
    """None if no such job; else whether assisted apply supports its ATS."""
    conn = db.connect()
    try:
        row = db.get_job(conn, job_id)
    finally:
        conn.close()
    if row is None:
        return None
    return bool(enrich(dict(row))["can_assist"])
