"""In-process smoke test for the review app (no running server, no network).

Exercises: page load, the apply action flipping status + timestamp, the skip
action, reset/undo, and resume download. Run:  python tests/test_review_smoke.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from jobhelper.review.app import app  # noqa: E402
from jobhelper.util import DB_PATH  # noqa: E402


def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _status(job_id: int) -> str:
    c = sqlite3.connect(DB_PATH)
    row = c.execute("SELECT status, applied_at FROM jobs WHERE id=?", (job_id,)).fetchone()
    c.close()
    return row


def main() -> int:
    if not DB_PATH.exists():
        print("No DB yet — run `python run_daily.py` first.")
        return 1
    client = TestClient(app)

    print("== page load ==")
    r = client.get("/")
    check(r.status_code == 200, f"GET / -> 200 (got {r.status_code})")
    check("JobHelper" in r.text, "page renders title")

    # Find a pending tailored job to act on.
    c = sqlite3.connect(DB_PATH)
    row = c.execute(
        "SELECT id FROM jobs WHERE status IN ('tailored','proposed','approved') "
        "ORDER BY llm_score DESC LIMIT 1").fetchone()
    c.close()
    if not row:
        print("No pending jobs to test actions against (all reviewed). Skipping actions.")
        return 0
    jid = row[0]
    print(f"== actions on job id={jid} ==")

    # Resume download
    rr = client.get(f"/resume/{jid}")
    check(rr.status_code == 200, f"GET /resume/{jid} -> 200")
    check("wordprocessingml" in rr.headers.get("content-type", ""), "resume served as .docx")

    # Mark applied
    pa = client.post(f"/action/{jid}", data={"action": "applied"}, follow_redirects=False)
    check(pa.status_code == 303, "POST applied -> 303 redirect")
    st, applied_at = _status(jid)
    check(st == "applied", "status flipped to 'applied'")
    check(bool(applied_at), "applied_at timestamp set")

    # It should now appear in the Applied section, not pending
    r2 = client.get("/")
    check("Applied (" in r2.text, "Applied section renders")

    # Undo back to tailored
    client.post(f"/action/{jid}", data={"action": "reset"}, follow_redirects=False)
    check(_status(jid)[0] == "tailored", "reset returns job to 'tailored'")

    # Skip then restore
    client.post(f"/action/{jid}", data={"action": "skip"}, follow_redirects=False)
    check(_status(jid)[0] == "skipped", "skip -> 'skipped'")
    client.post(f"/action/{jid}", data={"action": "reset"}, follow_redirects=False)
    check(_status(jid)[0] == "tailored", "restore -> 'tailored'")

    print("\nALL REVIEW SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
