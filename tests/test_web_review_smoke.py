"""In-process smoke test for the dashboard review API (no server, no network).

Inserts synthetic jobs (source '_uitest') into the DB, exercises the full
/api/review/* surface — lists + enrichment, every action incl. applications-log
sync, resume download, assisted-apply launch (monkeypatched) — then deletes
them. Real jobs are never touched. Run:  python tests/test_web_review_smoke.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from jobhelper import applog  # noqa: E402
from jobhelper.util import DB_PATH, now_iso  # noqa: E402
from jobhelper.web import review as webreview  # noqa: E402
from jobhelper.web.app import app  # noqa: E402


def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _insert(conn: sqlite3.Connection, **cols) -> int:
    ts = now_iso()
    base = {"job_hash": f"_uitest-{uuid.uuid4().hex}", "source": "_uitest",
            "status": "tailored", "first_seen_at": ts,
            "created_at": ts, "updated_at": ts}
    base.update(cols)
    keys = ",".join(base)
    marks = ",".join("?" * len(base))
    cur = conn.execute(f"INSERT INTO jobs ({keys}) VALUES ({marks})",
                       list(base.values()))
    return cur.lastrowid


def _db_row(job_id: int):
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    row = c.execute(
        "SELECT status, applied_at, approved_at FROM jobs WHERE id=?",
        (job_id,)).fetchone()
    c.close()
    return row


def _find(payload: dict, bucket: str, job_id: int) -> dict | None:
    return next((j for j in payload[bucket] if j["id"] == job_id), None)


def main() -> int:
    if not DB_PATH.exists():
        print("No DB yet — run `python run_daily.py` first.")
        return 1

    fd, tmp_name = tempfile.mkstemp(suffix=".docx", prefix="_uitest-")
    os.close(fd)  # keep no handle open, or Windows blocks the unlink later
    resume_file = Path(tmp_name)
    resume_file.write_bytes(b"PK\x03\x04 fake docx for smoke test")

    conn = sqlite3.connect(DB_PATH)
    jid = _insert(
        conn,
        title="Staff Python Engineer", company="Acme",
        location="Remote - US", remote_type="remote",
        url="https://boards.greenhouse.io/acme/jobs/123",
        llm_score=82, embed_score=0.71,
        llm_rationale="Strong backend match.",
        llm_musthaves_met='["Python", "SQL"]', llm_missing='["Go"]',
        change_log='["Reordered skills section"]',
        screening_answers='{"years_of_experience": 9, "requires_sponsorship": "no"}',
        cover_letter_text="Dear Acme,\nI would love to help.",
        tailored_resume_path=str(resume_file),
    )
    # No llm_score -> display_score falls back to embed*100; sorts after jid.
    jid2 = _insert(conn, title="Data Engineer", company="Beta", status="proposed",
                   url="https://remoteok.com/jobs/999", embed_score=0.634)
    conn.commit()
    conn.close()

    real_launch = webreview.launch_assist
    assist_calls: list[int] = []
    ok = False
    try:
        with TestClient(app) as client:
            print("== review lists + enrichment ==")
            r = client.get("/api/review/jobs")
            check(r.status_code == 200, f"GET /api/review/jobs -> 200 (got {r.status_code})")
            data = r.json()
            check(all(k in data for k in ("pending", "applied", "skipped")),
                  "payload has pending/applied/skipped")
            j = _find(data, "pending", jid)
            check(j is not None, "synthetic tailored job listed as pending")
            assert j is not None
            check(j["display_score"] == 82, "display_score uses llm_score")
            check(j["has_resume"] is True, "has_resume true (file exists)")
            check(j["ats"] == "greenhouse" and j["can_assist"] is True,
                  "greenhouse URL -> ats detected, can_assist")
            check(j["musthaves_met"] == ["Python", "SQL"] and j["missing"] == ["Go"],
                  "musthave/missing JSON parsed to lists")
            check(j["screening"].get("years_of_experience") == 9, "screening parsed")
            check(j["notes"] == ["Reordered skills section"], "change_log -> notes")
            j2 = _find(data, "pending", jid2)
            check(j2 is not None, "synthetic proposed job listed as pending")
            assert j2 is not None
            check(j2["display_score"] == 63, "display_score falls back to embed*100")
            ids = [x["id"] for x in data["pending"]]
            check(ids.index(jid) < ids.index(jid2), "LLM-scored job sorts first")

            print("== actions ==")
            r = client.post(f"/api/review/jobs/{jid}/action", json={"action": "approve"})
            check(r.status_code == 200, "POST approve -> 200")
            check(r.json()["job"]["status"] == "approved", "response job approved")
            row = _db_row(jid)
            check(row["status"] == "approved" and row["approved_at"],
                  "DB: approved + approved_at set")
            check(_find(client.get("/api/review/jobs").json(), "pending", jid)
                  is not None, "approved job still pending review")

            r = client.post(f"/api/review/jobs/{jid}/action", json={"action": "applied"})
            check(r.status_code == 200, "POST applied -> 200")
            row = _db_row(jid)
            check(row["status"] == "applied" and row["applied_at"],
                  "DB: applied + applied_at set")
            logged = applog._read().get(str(jid))
            check(logged is not None, "applications_log has the row")
            check(logged and logged.get("applied_via") == "dashboard",
                  "applied_via recorded as 'dashboard'")
            data = client.get("/api/review/jobs").json()
            check(_find(data, "applied", jid) is not None
                  and _find(data, "pending", jid) is None,
                  "job moved pending -> applied list")

            r = client.post(f"/api/review/jobs/{jid}/action", json={"action": "reset"})
            check(r.status_code == 200, "POST reset -> 200")
            row = _db_row(jid)
            check(row["status"] == "tailored", "reset -> status tailored")
            check(row["applied_at"] is None, "reset clears applied_at")
            check(applog._read().get(str(jid)) is None,
                  "applications_log row removed on reset")

            r = client.post(f"/api/review/jobs/{jid}/action", json={"action": "skip"})
            check(r.status_code == 200 and _db_row(jid)["status"] == "skipped",
                  "POST skip -> 'skipped'")
            check(_find(client.get("/api/review/jobs").json(), "skipped", jid)
                  is not None, "skipped job listed under skipped")
            client.post(f"/api/review/jobs/{jid}/action", json={"action": "reset"})
            check(_db_row(jid)["status"] == "tailored", "restore -> 'tailored'")

            print("== validation + errors ==")
            r = client.post(f"/api/review/jobs/{jid}/action", json={"action": "explode"})
            check(r.status_code == 422, f"unknown action -> 422 (got {r.status_code})")
            r = client.post("/api/review/jobs/987654321/action", json={"action": "skip"})
            check(r.status_code == 404, "action on missing job -> 404")

            print("== resume + csv ==")
            r = client.get(f"/api/review/jobs/{jid}/resume")
            check(r.status_code == 200, "GET resume -> 200")
            check("wordprocessingml" in r.headers.get("content-type", ""),
                  "resume served as .docx")
            check(r.content == resume_file.read_bytes(), "resume bytes match")
            r = client.get("/api/review/jobs/987654321/resume")
            check(r.status_code == 404, "resume for missing job -> 404")
            r = client.get(f"/api/review/jobs/{jid2}/resume")
            check(r.status_code == 404, "resume when none tailored -> 404")
            r = client.get("/api/review/applications.csv")
            check(r.status_code in (200, 404), "applications.csv endpoint responds")

            print("== assisted apply ==")
            webreview.launch_assist = lambda job_id: (assist_calls.append(job_id)
                                                      or True)
            r = client.post(f"/api/review/jobs/{jid}/assist")
            check(r.status_code == 202 and r.json()["launched"] is True,
                  "assist on greenhouse job -> 202 launched")
            check(assist_calls == [jid], "launcher invoked with the job id")
            r = client.post(f"/api/review/jobs/{jid2}/assist")
            check(r.status_code == 409, "assist on non-ATS job -> 409")
            r = client.post("/api/review/jobs/987654321/assist")
            check(r.status_code == 404, "assist on missing job -> 404")
        ok = True
    finally:
        webreview.launch_assist = real_launch
        applog.remove_application(jid)  # safety if a FAIL aborted mid-applied
        c = sqlite3.connect(DB_PATH)
        c.execute("DELETE FROM jobs WHERE source='_uitest'")
        c.commit()
        c.close()
        resume_file.unlink(missing_ok=True)
        print(f"  [{'PASS' if ok else 'INFO'}] synthetic rows + temp resume cleaned up")

    print("\nALL WEB REVIEW SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
