"""Shared review logic: job enrichment + status actions + assisted-apply launch.

Used by both the legacy review page (review/app.py, port 8765) and the dashboard
API (web/app.py, port 8787) so the two UIs apply identical status transitions
and applications-log bookkeeping while both exist.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .. import db
from ..util import ROOT, get_logger, now_iso

log = get_logger()

PENDING = ("proposed", "tailored", "approved")
ACTIONS = ("applied", "approve", "skip", "reset")


def loads_json(v, default):
    if not v:
        return default
    try:
        return json.loads(v) if isinstance(v, str) else v
    except (json.JSONDecodeError, TypeError):
        return default


def enrich(job: dict) -> dict:
    from ..apply.fillers import detect_ats
    job["musthaves_met"] = loads_json(job.get("llm_musthaves_met"), [])
    job["missing"] = loads_json(job.get("llm_missing"), [])
    job["notes"] = loads_json(job.get("change_log"), [])
    job["screening"] = loads_json(job.get("screening_answers"), {})
    job["display_score"] = (job.get("llm_score") if job.get("llm_score") is not None
                            else round((job.get("embed_score") or 0) * 100))
    job["has_resume"] = bool(job.get("tailored_resume_path")
                             and Path(job["tailored_resume_path"]).exists())
    # Keyword coverage blob (ITEM-8); distinct from 'ats' (detected vendor) below.
    job["ats_report"] = loads_json(job.get("ats_report"), None)
    job["ats"] = detect_ats(job.get("url", ""))
    # Assisted apply only helps on real hosted ATS forms, not aggregator listings.
    job["can_assist"] = job["ats"] in ("greenhouse", "lever", "ashby")
    return job


def apply_action(conn, job_id: int, action: str, via: str) -> None:
    """Apply one review action. Caller commits. Raises ValueError on unknown action."""
    from ..applog import record_application, remove_application
    if action == "applied":
        db.update_job(conn, job_id, status="applied", applied_at=now_iso())
        row = db.get_job(conn, job_id)
        if row:
            record_application(dict(row), via)
    elif action == "approve":
        db.update_job(conn, job_id, status="approved", approved_at=now_iso())
    elif action == "skip":
        db.update_job(conn, job_id, status="skipped")
    elif action == "reset":
        # Clear applied_at too — metrics count applications by that column, so
        # an undone misclick must not linger as a phantom application.
        db.update_job(conn, job_id, status="tailored", applied_at=None)
        remove_application(job_id)  # keep the log in sync on undo
    else:
        raise ValueError(f"unknown review action: {action}")


def launch_assisted_apply(job_id: int) -> bool:
    """Launch apply.py for this job in its own console window.

    Runs as a separate process so it gets an interactive terminal (to confirm
    'applied' after you submit) and its own headed browser. It fills the form
    and stops — you review and click Submit yourself.
    """
    py = sys.executable
    script = str(ROOT / "apply.py")
    kwargs: dict = {"cwd": str(ROOT)}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    try:
        subprocess.Popen([py, script, str(job_id)], **kwargs)
        return True
    except Exception as exc:
        log.error("failed to launch assisted apply: %s", exc)
        return False
