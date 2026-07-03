"""In-process smoke test for the dashboard app (no network, no LLM spend).

Exercises: every /api/* metrics endpoint against the real DB, the run
lifecycle with a stubbed child process (idle -> running -> idle, 409 on
double-start, log capture), SSE replay, and the SPA fallback. Run:
    python tests/test_web_smoke.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from jobhelper.web import runner  # noqa: E402
from jobhelper.web.app import app  # noqa: E402


def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


STUB = ("import time\n"
        "print('alpha')\n"
        "time.sleep(1.0)\n"
        "print('beta')\n"
        "print('gamma')\n")


def main() -> int:
    with TestClient(app) as client:
        print("== metrics endpoints ==")
        r = client.get("/api/summary")
        check(r.status_code == 200, "GET /api/summary -> 200")
        body = r.json()
        for key in ("last_run", "proposed_today", "pending_review",
                    "applied_total", "applied_7d", "total_jobs", "new_7d"):
            check(key in body, f"summary has '{key}'")

        r = client.get("/api/funnel")
        check(r.status_code == 200, "GET /api/funnel -> 200")
        check(any(e["status"] == "proposed" for e in r.json()),
              "funnel includes 'proposed' bucket")

        r = client.get("/api/timeline?days=14")
        check(r.status_code == 200, "GET /api/timeline -> 200")
        pts = r.json()
        check(len(pts) == 14, f"timeline returns one point per day (got {len(pts)})")
        check(all(k in pts[0] for k in ("date", "new", "proposed", "applied")),
              "timeline point shape")

        r = client.get("/api/sources")
        check(r.status_code == 200, "GET /api/sources -> 200")

        r = client.get("/api/runs?limit=5")
        check(r.status_code == 200, "GET /api/runs -> 200")

        r = client.get("/api/jobs/recent")
        check(r.status_code == 200, "GET /api/jobs/recent -> 200")

        print("== run lifecycle (stubbed child process) ==")
        original = runner.MANAGER.command
        runner.MANAGER.command = (  # type: ignore[method-assign]
            lambda use_cache: [sys.executable, "-u", "-c", STUB])
        try:
            check(client.get("/api/run/status").json()["state"] == "idle",
                  "runner starts idle")
            r = client.post("/api/run", json={"use_cache": True})
            check(r.status_code == 202, f"POST /api/run -> 202 (got {r.status_code})")
            check(r.json()["state"] == "running", "status flips to running")
            r2 = client.post("/api/run", json={"use_cache": False})
            check(r2.status_code == 409, "second POST while running -> 409")

            deadline = time.time() + 15
            status = client.get("/api/run/status").json()
            while time.time() < deadline and status["state"] != "idle":
                time.sleep(0.2)
                status = client.get("/api/run/status").json()
            check(status["state"] == "idle", "run finishes -> idle")
            check(status["exit_code"] == 0, f"exit code 0 (got {status['exit_code']})")
            check(status["line_count"] == 3,
                  f"3 lines captured (got {status['line_count']})")
            check(status["use_cache"] is True, "use_cache flag reflected in status")
            log_path = Path(status["log_path"])
            check(log_path.exists(), "log file written to data/logs/")
            check("beta" in log_path.read_text(encoding="utf-8"),
                  "log file contains output")

            print("== SSE replay ==")
            lines: list[str] = []
            done = False
            with client.stream("GET", "/api/run/logs?after=0") as resp:
                check(resp.status_code == 200, "GET /api/run/logs -> 200")
                check("text/event-stream" in resp.headers["content-type"],
                      "SSE content type")
                for raw in resp.iter_lines():
                    if raw.startswith("event: done"):
                        done = True
                    elif raw.startswith("data: ") and not done:
                        lines.append(json.loads(raw[len("data: "):]))
                    if done and raw == "":
                        break
            check(lines == ["alpha", "beta", "gamma"],
                  f"replayed all lines in order (got {lines})")
            check(done, "done event received")
        finally:
            runner.MANAGER.command = original  # type: ignore[method-assign]

        print("== SPA fallback ==")
        r = client.get("/")
        check(r.status_code in (200, 503),
              f"GET / serves index or friendly 503 (got {r.status_code})")
        r = client.get("/api/summary")
        check(r.status_code == 200, "/api/* still wins over SPA catch-all")

    print("\nALL DASHBOARD SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
