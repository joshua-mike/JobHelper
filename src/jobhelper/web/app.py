"""FastAPI app for the JobHelper dashboard (metrics + run control).

Serves the JSON API under /api/* and the built React frontend from web/dist
with an SPA fallback. The review page (port 8765) is separate and unchanged.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import AsyncIterator, Iterator

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from starlette.status import HTTP_202_ACCEPTED, HTTP_409_CONFLICT

from .. import db
from ..util import ROOT
from . import metrics, schemas
from .runner import MANAGER

WEB_DIST = ROOT / "web" / "dist"


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    yield


app = FastAPI(title="JobHelper Dashboard", lifespan=_lifespan)

# Vite dev server (npm run dev) proxies /api, but also allow direct calls.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Metrics ------------------------------------------------------------------
@app.get("/api/summary", response_model=schemas.Summary)
def get_summary():
    return metrics.summary()


@app.get("/api/funnel", response_model=list[schemas.FunnelEntry])
def get_funnel():
    return metrics.funnel()


@app.get("/api/timeline", response_model=list[schemas.TimelinePoint])
def get_timeline(days: int = Query(30, ge=1, le=365)):
    return metrics.timeline(days)


@app.get("/api/sources", response_model=list[schemas.SourceStats])
def get_sources():
    return metrics.sources()


@app.get("/api/runs", response_model=list[schemas.RunLogEntry])
def get_runs(limit: int = Query(20, ge=1, le=200)):
    active = MANAGER.status()["state"] == "running"
    return metrics.runs(limit, runner_active=active)


@app.get("/api/jobs/recent", response_model=list[schemas.RecentJob])
def get_recent_jobs(limit: int = Query(15, ge=1, le=100)):
    return metrics.recent_jobs(limit)


# ---- Run control ----------------------------------------------------------------
@app.post("/api/run", response_model=schemas.RunStatus, status_code=HTTP_202_ACCEPTED)
def start_run(req: schemas.StartRunRequest):
    if not MANAGER.start(use_cache=req.use_cache):
        raise HTTPException(HTTP_409_CONFLICT, "A run is already in progress.")
    return MANAGER.status()


@app.get("/api/run/status", response_model=schemas.RunStatus)
def run_status():
    return MANAGER.status()


@app.get("/api/run/logs")
def run_logs(request: Request, after: int = 0) -> StreamingResponse:
    """SSE stream of run output: replays buffered lines past `after`, then
    follows live output; ends with a `done` event when the run finishes."""
    last_event_id = request.headers.get("last-event-id")
    if last_event_id:
        try:
            after = max(after, int(last_event_id))
        except ValueError:
            pass

    def gen() -> Iterator[str]:
        for kind, seq, text in MANAGER.stream(after=after):
            if kind == "line":
                yield f"id: {seq}\nevent: line\ndata: {json.dumps(text)}\n\n"
            elif kind == "done":
                yield f"event: done\ndata: {json.dumps(MANAGER.status())}\n\n"
            else:  # ping
                yield ": keep-alive\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


# ---- Static frontend (SPA fallback) ---------------------------------------------
# Registered last so /api/* routes above always win.
@app.get("/{path:path}", include_in_schema=False)
def spa(path: str = ""):
    dist = WEB_DIST.resolve()
    if path:
        candidate = (WEB_DIST / path).resolve()
        # Path-traversal guard: only serve files inside web/dist.
        if candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(candidate)
    index = WEB_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return PlainTextResponse(
        "Frontend not built yet. Run:  cd web && npm install && npm run build\n"
        "(API is live under /api/*, e.g. /api/summary)",
        status_code=503,
    )
