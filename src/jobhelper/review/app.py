"""FastAPI app for reviewing daily proposals on localhost.

Pending proposals (status proposed/tailored/approved) show as cards with the
tailored resume, cover letter, score breakdown, and screening answers. Buttons
flip status: Approve -> approved, Mark Applied -> applied (timestamped),
Skip -> skipped. Applied/Skipped have a Reset to undo a misclick.

This NEVER submits anything — it only tracks your own manual applications.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, Form
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .. import db
from ..util import ROOT, get_logger, now_iso

log = get_logger()

TEMPLATES = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES))
app = FastAPI(title="JobHelper Review")

PENDING = ("proposed", "tailored", "approved")


def _loads(v, default):
    if not v:
        return default
    try:
        return json.loads(v) if isinstance(v, str) else v
    except (json.JSONDecodeError, TypeError):
        return default


def _enrich(job: dict) -> dict:
    from ..apply.fillers import detect_ats
    job["musthaves_met"] = _loads(job.get("llm_musthaves_met"), [])
    job["missing"] = _loads(job.get("llm_missing"), [])
    job["notes"] = _loads(job.get("change_log"), [])
    job["screening"] = _loads(job.get("screening_answers"), {})
    job["display_score"] = (job.get("llm_score") if job.get("llm_score") is not None
                            else round((job.get("embed_score") or 0) * 100))
    job["has_resume"] = bool(job.get("tailored_resume_path")
                             and Path(job["tailored_resume_path"]).exists())
    job["ats"] = detect_ats(job.get("url", ""))
    # Assisted apply only helps on real hosted ATS forms, not aggregator listings.
    job["can_assist"] = job["ats"] in ("greenhouse", "lever", "ashby")
    return job


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    conn = db.connect()
    db.init_db(conn)
    qmarks = ",".join("?" * len(PENDING))
    pending = [_enrich(dict(r)) for r in conn.execute(
        f"SELECT * FROM jobs WHERE status IN ({qmarks}) "
        f"ORDER BY (llm_score IS NULL), llm_score DESC, embed_score DESC", PENDING)]
    applied = [_enrich(dict(r)) for r in conn.execute(
        "SELECT * FROM jobs WHERE status='applied' ORDER BY applied_at DESC LIMIT 50")]
    skipped = [_enrich(dict(r)) for r in conn.execute(
        "SELECT * FROM jobs WHERE status='skipped' ORDER BY updated_at DESC LIMIT 50")]
    stats = {row["status"]: row["n"] for row in conn.execute(
        "SELECT status, COUNT(*) n FROM jobs GROUP BY status")}
    conn.close()
    return templates.TemplateResponse(request, "review.html", {
        "pending": pending, "applied": applied,
        "skipped": skipped, "stats": stats,
    })


@app.post("/action/{job_id}")
def action(job_id: int, action: str = Form(...)):
    from ..applog import record_application, remove_application
    conn = db.connect()
    if action == "applied":
        stamp = now_iso()
        db.update_job(conn, job_id, status="applied", applied_at=stamp)
        row = db.get_job(conn, job_id)
        if row:
            record_application(dict(row), "review-page")
    elif action == "approve":
        db.update_job(conn, job_id, status="approved", approved_at=now_iso())
    elif action == "skip":
        db.update_job(conn, job_id, status="skipped")
    elif action == "reset":
        db.update_job(conn, job_id, status="tailored")
        remove_application(job_id)  # keep the log in sync on undo
    conn.commit()
    conn.close()
    return RedirectResponse("/", status_code=303)


@app.get("/applications.csv")
def applications_csv():
    from ..applog import LOG_CSV
    if not LOG_CSV.exists():
        return HTMLResponse("No applications logged yet.", status_code=404)
    return FileResponse(str(LOG_CSV), media_type="text/csv",
                        filename="applications_log.csv")


@app.post("/apply/{job_id}")
def assisted_apply_launch(job_id: int):
    """Launch the assisted-apply browser for this job in its own console window.

    Runs apply.py as a separate process so it gets an interactive terminal (to
    confirm 'applied' after you submit) and its own headed browser. It fills the
    form and stops — you review and click Submit yourself.
    """
    py = sys.executable
    script = str(ROOT / "apply.py")
    kwargs: dict = {"cwd": str(ROOT)}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    try:
        subprocess.Popen([py, script, str(job_id)], **kwargs)
    except Exception as exc:
        log.error("failed to launch assisted apply: %s", exc)
    return RedirectResponse("/", status_code=303)


@app.get("/resume/{job_id}")
def resume(job_id: int):
    conn = db.connect()
    row = db.get_job(conn, job_id)
    conn.close()
    if not row or not row["tailored_resume_path"]:
        return HTMLResponse("No resume for this job.", status_code=404)
    path = Path(row["tailored_resume_path"])
    if not path.exists():
        return HTMLResponse("Resume file missing.", status_code=404)
    return FileResponse(
        str(path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=path.name,
    )
