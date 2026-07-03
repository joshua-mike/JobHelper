"""Read-only metric queries over jobs + run_log for the dashboard API.

Timestamps are stored UTC (util.now_iso), so day-bucketing applies SQLite's
'localtime' modifier to keep "today"/"this week" aligned with the user's clock.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .. import db

PENDING_STATUSES = ("proposed", "tailored", "approved")
# Current-state buckets shown in the pipeline funnel, in pipeline order.
FUNNEL_ORDER = ("new", "filtered_out", "ranked", "scored", "proposed",
                "tailored", "approved", "applied", "skipped", "error")
# Statuses that mean "this job made it in front of the user".
SURFACED_STATUSES = ("proposed", "tailored", "approved", "applied")


def _duration_seconds(started: str | None, finished: str | None) -> float | None:
    if not started or not finished:
        return None
    try:
        delta = datetime.fromisoformat(finished) - datetime.fromisoformat(started)
        return delta.total_seconds()
    except ValueError:
        return None


def summary() -> dict[str, Any]:
    conn = db.connect()
    try:
        def scalar(sql: str, *params: Any) -> Any:
            return conn.execute(sql, params).fetchone()[0]

        last = conn.execute(
            "SELECT * FROM run_log ORDER BY started_at DESC LIMIT 1").fetchone()
        last_run = None
        if last:
            last_run = dict(last)
            last_run["duration_seconds"] = _duration_seconds(
                last["started_at"], last["finished_at"])

        qmarks = ",".join("?" * len(PENDING_STATUSES))
        return {
            "last_run": last_run,
            "proposed_today": scalar(
                "SELECT COALESCE(SUM(proposed),0) FROM run_log "
                "WHERE date(started_at,'localtime') = date('now','localtime')"),
            "pending_review": scalar(
                f"SELECT COUNT(*) FROM jobs WHERE status IN ({qmarks})",
                *PENDING_STATUSES),
            "applied_total": scalar(
                "SELECT COUNT(*) FROM jobs WHERE applied_at IS NOT NULL"),
            "applied_7d": scalar(
                "SELECT COUNT(*) FROM jobs WHERE applied_at IS NOT NULL AND "
                "date(applied_at,'localtime') >= date('now','localtime','-6 days')"),
            "total_jobs": scalar("SELECT COUNT(*) FROM jobs"),
            "new_7d": scalar(
                "SELECT COUNT(*) FROM jobs WHERE first_seen_at IS NOT NULL AND "
                "date(first_seen_at,'localtime') >= date('now','localtime','-6 days')"),
        }
    finally:
        conn.close()


def funnel() -> list[dict[str, Any]]:
    conn = db.connect()
    try:
        counts = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) n FROM jobs GROUP BY status")}
    finally:
        conn.close()
    known = [{"status": s, "count": counts.get(s, 0)} for s in FUNNEL_ORDER]
    extra = [{"status": s, "count": n}
             for s, n in sorted(counts.items()) if s not in FUNNEL_ORDER]
    return known + extra


def timeline(days: int = 30) -> list[dict[str, Any]]:
    days = max(1, min(days, 365))
    since = f"-{days - 1} days"
    conn = db.connect()
    try:
        def by_day(sql: str) -> dict[str, int]:
            return {row[0]: row[1] for row in conn.execute(sql, (since,))}

        new = by_day(
            "SELECT date(first_seen_at,'localtime') d, COUNT(*) FROM jobs "
            "WHERE first_seen_at IS NOT NULL "
            "AND date(first_seen_at,'localtime') >= date('now','localtime',?) "
            "GROUP BY d")
        applied = by_day(
            "SELECT date(applied_at,'localtime') d, COUNT(*) FROM jobs "
            "WHERE applied_at IS NOT NULL "
            "AND date(applied_at,'localtime') >= date('now','localtime',?) "
            "GROUP BY d")
        proposed = by_day(
            "SELECT date(started_at,'localtime') d, COALESCE(SUM(proposed),0) "
            "FROM run_log WHERE started_at IS NOT NULL "
            "AND date(started_at,'localtime') >= date('now','localtime',?) "
            "GROUP BY d")
    finally:
        conn.close()

    today = date.today()  # local, matching the 'localtime' buckets above
    day_list = [(today - timedelta(days=i)).isoformat()
                for i in range(days - 1, -1, -1)]
    return [{"date": d, "new": new.get(d, 0), "proposed": proposed.get(d, 0),
             "applied": applied.get(d, 0)} for d in day_list]


def sources() -> list[dict[str, Any]]:
    qmarks = ",".join("?" * len(SURFACED_STATUSES))
    conn = db.connect()
    try:
        rows = conn.execute(
            f"""
            SELECT source,
                   COUNT(*) AS total,
                   SUM(CASE WHEN date(first_seen_at,'localtime')
                            >= date('now','localtime','-6 days')
                       THEN 1 ELSE 0 END) AS new_7d,
                   SUM(CASE WHEN status IN ({qmarks}) THEN 1 ELSE 0 END) AS surfaced,
                   ROUND(AVG(llm_score), 1) AS avg_llm_score
            FROM jobs GROUP BY source ORDER BY total DESC
            """, SURFACED_STATUSES).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def runs(limit: int = 20, runner_active: bool = False) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    conn = db.connect()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM run_log ORDER BY started_at DESC LIMIT ?", (limit,))]
    finally:
        conn.close()
    for i, row in enumerate(rows):
        row["duration_seconds"] = _duration_seconds(
            row["started_at"], row["finished_at"])
        if row["finished_at"]:
            row["run_state"] = "complete"
        elif i == 0 and runner_active:
            row["run_state"] = "running"
        else:
            # Crashed mid-run, or a Task Scheduler run in flight elsewhere.
            row["run_state"] = "incomplete"
    return rows


def recent_jobs(limit: int = 15) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    qmarks = ",".join("?" * len(SURFACED_STATUSES))
    conn = db.connect()
    try:
        rows = [dict(r) for r in conn.execute(
            f"""
            SELECT id, title, company, source, url, status, llm_score,
                   embed_score, proposed_in_run_id, applied_at, updated_at
            FROM jobs
            WHERE status IN ({qmarks})
            ORDER BY COALESCE(proposed_in_run_id,'') DESC,
                     (llm_score IS NULL), llm_score DESC, embed_score DESC
            LIMIT ?
            """, (*SURFACED_STATUSES, limit))]
    finally:
        conn.close()
    for row in rows:
        # Same display rule as the review page: LLM score, else embed as %.
        if row["llm_score"] is not None:
            row["display_score"] = row["llm_score"]
        elif row["embed_score"] is not None:
            row["display_score"] = round(row["embed_score"] * 100)
        else:
            row["display_score"] = None
        row.pop("embed_score", None)
    return rows
