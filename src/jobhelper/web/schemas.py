"""Pydantic response models — the API contract mirrored by web/src/api/types.ts."""
from __future__ import annotations

from pydantic import BaseModel


class LastRun(BaseModel):
    run_id: str
    started_at: str | None = None
    finished_at: str | None = None
    sourced: int = 0
    new_jobs: int = 0
    filtered: int = 0
    scored: int = 0
    proposed: int = 0
    errors: int = 0
    notes: str | None = None
    duration_seconds: float | None = None


class Summary(BaseModel):
    last_run: LastRun | None
    proposed_today: int
    pending_review: int
    applied_total: int
    applied_7d: int
    total_jobs: int
    new_7d: int


class FunnelEntry(BaseModel):
    status: str
    count: int


class TimelinePoint(BaseModel):
    date: str
    new: int
    proposed: int
    applied: int


class SourceStats(BaseModel):
    source: str
    total: int
    new_7d: int
    surfaced: int
    avg_llm_score: float | None = None


class RunLogEntry(LastRun):
    run_state: str  # complete | incomplete | running


class RecentJob(BaseModel):
    id: int
    title: str | None
    company: str | None
    source: str
    url: str | None
    status: str
    llm_score: int | None
    display_score: int | None
    proposed_in_run_id: str | None
    applied_at: str | None
    updated_at: str | None


class RunStatus(BaseModel):
    state: str  # idle | running
    started_at: str | None
    finished_at: str | None
    exit_code: int | None
    use_cache: bool
    log_path: str | None
    line_count: int


class StartRunRequest(BaseModel):
    use_cache: bool = False
