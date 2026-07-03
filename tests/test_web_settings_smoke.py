"""In-process smoke test for the settings API (no network, no LLM spend).

Exercises GET/PUT for all three configs against temp copies, validation
errors, the fresh-clone profile bootstrap, source verify with a stubbed
adapter, and resume import with a stubbed LLM. Run:
    python tests/test_web_settings_smoke.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from jobhelper.models import RawJob  # noqa: E402
from jobhelper.web import settings_api, settings_store, source_verify  # noqa: E402
from jobhelper.web.app import app  # noqa: E402

REAL_CONFIG = Path(__file__).resolve().parents[1] / "config"


def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


class StubSource:
    cap = 50

    def __init__(self, jobs):
        self._jobs = jobs

    def fetch(self):
        return self._jobs


class StubLLM:
    available = False
    extraction: dict | None = None

    def __init__(self) -> None:
        pass

    def structured(self, *a, **k):
        return self.extraction


EXTRACTION = {
    "identity": {"full_name": "Res Ume", "email": "res@ume.dev", "phone": "",
                 "city_state": "Remote (US)"},
    "summary": "Engineer who ships.",
    "work_history": [{
        "company": "ShipCo", "title": "Engineer",
        "start_date": "2020-01", "end_date": "Present",
        "achievements": [{"text": "Shipped the thing, 40% faster.",
                          "skills_used": ["Python"]}],
    }],
    "education": [{"institution": "State U", "degree": "B.S."}],
    "skills": {"hard_skills": [{"name": "Python"}], "soft_skills": ["grit"]},
}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="jobhelper-settings-api-"))
    cfg_dir = tmp / "config"
    cfg_dir.mkdir()
    for f in ("sources.yaml", "criteria.yaml", "profile.example.yaml"):
        shutil.copy2(REAL_CONFIG / f, cfg_dir / f)
    settings_store.CONFIG_DIR = cfg_dir
    settings_store.BACKUP_DIR = tmp / "backups"

    real_llm, real_build = settings_api.LLM, source_verify._build
    settings_api.LLM = StubLLM
    try:
        with TestClient(app) as client:
            print("== status ==")
            r = client.get("/api/settings")
            check(r.status_code == 200, "GET /api/settings -> 200")
            body = r.json()
            for key in ("anthropic_available", "run_active", "profile_exists"):
                check(key in body, f"status has '{key}'")
            check(body["profile_exists"] is False, "no profile yet")

            print("== GET configs ==")
            r = client.get("/api/settings/criteria")
            check(r.status_code == 200 and r.json()["exists"], "criteria loads")
            check(r.json()["data"]["daily_target"] == 6, "criteria data correct")
            r = client.get("/api/settings/sources")
            check(r.status_code == 200 and
                  "greenhouse" in r.json()["data"]["ats"], "sources loads")
            r = client.get("/api/settings/profile")
            check(r.status_code == 200, "profile GET works on fresh clone")
            check(r.json()["exists"] is False, "profile marked missing")
            check(r.json()["seeded_from_example"], "seeded from example")
            check(r.json()["data"]["identity"]["full_name"] == "Jane Doe",
                  "example data returned")

            print("== PUT criteria ==")
            r = client.put("/api/settings/criteria", json={"daily_target": 8})
            check(r.status_code == 200, "PUT criteria -> 200")
            check(r.json()["changed"] and not r.json()["applies_next_run"],
                  "changed, applies now (idle)")
            check(r.json()["backup"], "backup path returned")
            check(client.get("/api/settings/criteria").json()["data"]
                  ["daily_target"] == 8, "GET reflects saved value")
            text = (cfg_dir / "criteria.yaml").read_text(encoding="utf-8")
            check("CEILING" in text, "comments survived the API save")
            r = client.put("/api/settings/criteria", json={"daily_target": 8})
            check(r.status_code == 200 and not r.json()["changed"],
                  "no-op PUT reports changed=false")

            print("== validation ==")
            r = client.put("/api/settings/criteria", json={"scoring": "vibes"})
            check(r.status_code == 422, "bad criteria -> 422")
            r = client.put("/api/settings/profile", json={
                "work_history": [{"title": "no company"}]})
            check(r.status_code == 422, "bad profile -> 422")
            detail = r.json()["detail"]
            check(isinstance(detail, list) and detail
                  and "msg" in detail[0], "422 detail is structured")

            print("== profile bootstrap PUT ==")
            r = client.put("/api/settings/profile",
                           json={"identity": {"full_name": "Smoke Test"}})
            check(r.status_code == 200 and r.json()["changed"],
                  "fresh profile PUT writes")
            check((cfg_dir / "profile.yaml").exists(), "profile.yaml created")
            body = client.get("/api/settings/profile").json()
            check(body["exists"] and
                  body["data"]["identity"]["full_name"] == "Smoke Test",
                  "profile now loads with merged identity")
            check(body["data"]["qa_bank"], "example sections seeded in")
            check(client.get("/api/settings").json()["profile_exists"],
                  "status flips profile_exists")

            print("== source verify (stubbed adapter) ==")
            jobs = [RawJob(source="greenhouse", source_job_id="1",
                           url="https://x/1", title="Senior .NET Engineer",
                           company="PerfectServe"),
                    RawJob(source="greenhouse", source_job_id="2",
                           url="https://x/2", title="Platform Engineer",
                           company="PerfectServe")]
            source_verify._build = lambda *a, **k: StubSource(jobs)
            r = client.post("/api/settings/sources/verify",
                            json={"kind": "greenhouse", "token": "perfectserve"})
            check(r.status_code == 200 and r.json()["ok"], "verify ok")
            check(r.json()["count"] == 2 and
                  r.json()["company"] == "PerfectServe", "count+company")
            check("Senior .NET Engineer" in r.json()["sample"], "sample titles")
            source_verify._build = lambda *a, **k: StubSource([])
            r = client.post("/api/settings/sources/verify",
                            json={"kind": "lever", "token": "ghost"})
            check(r.status_code == 200 and not r.json()["ok"],
                  "0 jobs -> ok=false with hint")
            r = client.post("/api/settings/sources/verify",
                            json={"kind": "greenhouse"})
            check(r.status_code == 422, "missing token -> 422")
            r = client.post("/api/settings/sources/verify",
                            json={"kind": "workday", "entry": {"tenant": "x"}})
            check(r.status_code == 422, "incomplete workday entry -> 422")

            print("== resume import ==")
            StubLLM.available = False
            r = client.post("/api/settings/profile/import-resume",
                            files={"file": ("r.txt", b"text", "text/plain")})
            check(r.status_code == 409, "no key -> 409 with guidance")
            StubLLM.available = True
            StubLLM.extraction = EXTRACTION
            r = client.post("/api/settings/profile/import-resume",
                            files={"file": ("resume.pdf", b"%PDF", "application/pdf")})
            check(r.status_code == 400, ".pdf -> 400 (unsupported)")
            r = client.post("/api/settings/profile/import-resume",
                            files={"file": ("resume.txt",
                                            b"Res Ume, Engineer at ShipCo",
                                            "text/plain")})
            check(r.status_code == 200, "import -> 200")
            body = r.json()
            prop = body["proposed"]
            check(prop["identity"]["full_name"] == "Res Ume",
                  "contact imported from resume")
            check(prop["work_history"][0]["company"] == "ShipCo",
                  "work history replaced")
            check(prop["work_history"][0]["achievements"][0]["verified"] is False,
                  "imported achievements start unverified")
            check(prop["compensation"]["desired_salary_min"] is not None,
                  "compensation preserved from existing profile")
            check(prop["qa_bank"], "qa_bank preserved")
            check(prop["identity"].get("requires_sponsorship") is not None,
                  "sponsorship fields kept")
            actions = {s["section"]: s["action"] for s in body["sections"]}
            check(actions["work_history"] == "imported", "notes: imported")
            check(actions["compensation"] == "preserved", "notes: preserved")
            StubLLM.extraction = None
            r = client.post("/api/settings/profile/import-resume",
                            files={"file": ("r.txt", b"text", "text/plain")})
            check(r.status_code == 502, "LLM failure -> 502")
    finally:
        settings_api.LLM = real_llm
        source_verify._build = real_build
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nALL SETTINGS API SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
