"""Auto-updating CSV log of jobs you've applied to.

Whenever a job is marked 'applied' (from the review page or assisted apply), a row
is upserted here — keyed by job_id so it stays in sync (undo removes it). The DB is
the source of truth; this CSV is the portable, spreadsheet-friendly record.
"""
from __future__ import annotations

import csv
from typing import Any

from .util import DATA_DIR, get_logger, now_iso

log = get_logger()
LOG_CSV = DATA_DIR / "applications_log.csv"

FIELDS = [
    "applied_at", "company", "title", "location", "remote_type", "ats",
    "url", "llm_score", "applied_via", "resume_path", "cover_letter_used",
    "job_id",
]


def _read() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if LOG_CSV.exists():
        with LOG_CSV.open("r", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                rows[r.get("job_id", "")] = r
    return rows


def _write(rows: dict[str, dict]) -> None:
    LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows.values(), key=lambda x: x.get("applied_at", ""), reverse=True)
    with LOG_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in ordered:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def record_application(job: dict[str, Any], applied_via: str) -> None:
    """Upsert one row for an applied job."""
    from .apply.fillers import detect_ats  # local import avoids import cycle
    rows = _read()
    jid = str(job.get("id", ""))
    rows[jid] = {
        "applied_at": job.get("applied_at") or now_iso(),
        "company": job.get("company", ""),
        "title": job.get("title", ""),
        "location": job.get("location") or job.get("candidate_location", ""),
        "remote_type": job.get("remote_type", ""),
        "ats": detect_ats(job.get("url", "")),
        "url": job.get("url", ""),
        "llm_score": job.get("llm_score") if job.get("llm_score") is not None else "",
        "applied_via": applied_via,
        "resume_path": job.get("tailored_resume_path", ""),
        "cover_letter_used": "yes" if job.get("cover_letter_text") else "no",
        "job_id": jid,
    }
    _write(rows)
    log.info("logged application: %s @ %s", job.get("title", ""), job.get("company", ""))


def remove_application(job_id: Any) -> None:
    """Drop a row when an 'applied' job is undone, keeping the log in sync."""
    rows = _read()
    if str(job_id) in rows:
        del rows[str(job_id)]
        _write(rows)
