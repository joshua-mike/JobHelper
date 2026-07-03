"""FastAPI app for reviewing daily proposals on localhost.

Pending proposals (status proposed/tailored/approved) show as cards with the
tailored resume, cover letter, score breakdown, and screening answers. Buttons
flip status: Approve -> approved, Mark Applied -> applied (timestamped),
Skip -> skipped. Applied/Skipped have a Reset to undo a misclick.

This NEVER submits anything — it only tracks your own manual applications.

The enrichment/action logic lives in review/actions.py, shared with the
dashboard API (web/app.py) so both UIs behave identically.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .. import db
from .actions import PENDING, apply_action, enrich, launch_assisted_apply

TEMPLATES = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES))
app = FastAPI(title="JobHelper Review")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    conn = db.connect()
    db.init_db(conn)
    qmarks = ",".join("?" * len(PENDING))
    pending = [enrich(dict(r)) for r in conn.execute(
        f"SELECT * FROM jobs WHERE status IN ({qmarks}) "
        f"ORDER BY (llm_score IS NULL), llm_score DESC, embed_score DESC", PENDING)]
    applied = [enrich(dict(r)) for r in conn.execute(
        "SELECT * FROM jobs WHERE status='applied' ORDER BY applied_at DESC LIMIT 50")]
    skipped = [enrich(dict(r)) for r in conn.execute(
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
    conn = db.connect()
    try:
        apply_action(conn, job_id, action, via="review-page")
        conn.commit()
    except ValueError:
        pass  # unknown action from a stray form post — ignore, as before
    finally:
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
    launch_assisted_apply(job_id)
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
