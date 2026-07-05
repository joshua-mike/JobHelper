"""Pydantic response models — the API contract mirrored by web/src/api/types.ts."""
from __future__ import annotations

from typing import Any, Literal

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


class ReviewJob(BaseModel):
    """A job as shown on the review board (fields from jobs + review enrichment)."""
    id: int
    title: str | None
    company: str | None
    location: str | None = None
    candidate_location: str | None = None
    remote_type: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    url: str | None
    source: str
    status: str
    llm_score: int | None = None
    display_score: int
    llm_rationale: str | None = None
    musthaves_met: list[Any] = []
    missing: list[Any] = []
    notes: list[Any] = []
    screening: dict[str, Any] = {}
    cover_letter_text: str | None = None
    has_resume: bool = False
    ats: str = "generic"
    can_assist: bool = False
    date_posted: str | None = None
    first_seen_at: str | None = None
    proposed_in_run_id: str | None = None
    approved_at: str | None = None
    applied_at: str | None = None
    updated_at: str | None = None


class ReviewLists(BaseModel):
    pending: list[ReviewJob]
    applied: list[ReviewJob]
    skipped: list[ReviewJob]


class ReviewActionRequest(BaseModel):
    action: Literal["applied", "approve", "skip", "reset"]


class ReviewActionResult(BaseModel):
    ok: bool
    job: ReviewJob


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


# ---- Settings (ITEM-4) -----------------------------------------------------------
ConfigName = Literal["profile", "sources", "criteria"]


class SettingsStatus(BaseModel):
    anthropic_available: bool
    run_active: bool
    profile_exists: bool


class ConfigPayload(BaseModel):
    name: ConfigName
    exists: bool
    # Fresh clone: profile GET returns the example file's data so the form has
    # a starting point, flagged so the UI can say "not saved yet".
    seeded_from_example: bool = False
    data: dict[str, Any] | None


class SaveResult(BaseModel):
    ok: bool = True
    changed: bool
    # The daily run is a child process that reads config at launch; a save
    # during a run only applies from the next run.
    applies_next_run: bool
    backup: str | None


class VerifySourceRequest(BaseModel):
    kind: Literal["remotive", "arbeitnow", "remoteok", "greenhouse", "lever",
                  "ashby", "smartrecruiters", "microsoft", "amazon", "workday",
                  "usajobs"]
    token: str | None = None                 # board slug or search query
    entry: dict[str, Any] | None = None      # workday {tenant, dc, site, company}


class VerifySourceResult(BaseModel):
    ok: bool
    count: int
    sample: list[str]
    company: str | None
    message: str


class SourceSuggestion(BaseModel):
    """A harvested board candidate awaiting review (ITEM-5)."""
    id: int
    kind: str
    token: str
    entry: dict[str, Any] | None = None      # workday {tenant, dc, site, company}
    company: str | None = None
    evidence_count: int = 0
    best_score: int | None = None
    live_count: int | None = None
    sample: list[str] = []
    via: Literal["url", "redirect", "guess"] = "url"
    status: Literal["suggested", "accepted", "dismissed"] = "suggested"
    created_at: str | None = None
    updated_at: str | None = None


class SuggestionScanResult(BaseModel):
    new: int
    suggestions: list[SourceSuggestion]


class SuggestionActionResult(BaseModel):
    ok: bool = True
    suggestion: SourceSuggestion
    applies_next_run: bool = False
    backup: str | None = None


class SectionNote(BaseModel):
    section: str
    action: Literal["imported", "preserved", "seeded"]
    detail: str


class ResumeImportResult(BaseModel):
    proposed: dict[str, Any]
    sections: list[SectionNote]
    model: str
