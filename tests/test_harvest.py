"""Offline tests for the roster harvester (ITEM-5): URL extractors, slug
guesses, evidence gating, scan orchestration, and the sources.yaml accept-merge.
No network — verification and redirect resolution are injected fakes.
Run:  python tests/test_harvest.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhelper import db, harvest
from jobhelper.models import RawJob
from jobhelper.web import settings_store


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def test_extract_candidates():
    print("== extract_candidates ==")
    text = (
        "Apply at https://boards.greenhouse.io/acmecorp/jobs/123 or "
        "https://job-boards.greenhouse.io/embed/job_board?for=other "
        "see https://jobs.lever.co/Acme-Labs/uuid and "
        "https://jobs.ashbyhq.com/acme?utm=x plus "
        "https://careers.smartrecruiters.com/AcmeGroup/456-dev and "
        "https://acme.wd5.myworkdayjobs.com/en-US/AcmeCareers/job/Remote/Dev_R1 "
        "https://beta.wd1.myworkdayjobs.com/External"
    )
    cands = harvest.extract_candidates(text, "Acme")
    by = {(c["kind"], c["token"]) for c in cands}
    check(("greenhouse", "acmecorp") in by, "greenhouse boards. token")
    check(("lever", "Acme-Labs") in by, "lever token keeps case")
    check(("ashby", "acme") in by, "ashby token")
    check(("smartrecruiters", "AcmeGroup") in by, "smartrecruiters careers. token")
    check(("workday", "acme/wd5/AcmeCareers") in by, "workday with locale segment")
    check(("workday", "beta/wd1/External") in by, "workday without locale")
    check(not any(t == "embed" for _, t in by), "embed path segment skipped")
    wd = next(c for c in cands if c["kind"] == "workday" and c["token"].startswith("acme/"))
    check(wd["entry"] == {"tenant": "acme", "dc": "wd5", "site": "AcmeCareers",
                          "company": "Acme"}, "workday entry dict built")


def test_slug_guesses():
    print("== slug_guesses ==")
    check(harvest.slug_guesses("BHG Financial, Inc.") == ["bhgfinancial", "bhg-financial"],
          "suffix stripped, joined + hyphenated")
    check(harvest.slug_guesses("Cortex") == ["cortex"], "single-word: one guess")
    check(harvest.slug_guesses("Openly (Insurance) LLC") == ["openly"],
          "parenthetical + suffix dropped")


def _mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn


_JOB_N = 0


def _add_job(conn, company, url="", desc="", status="ranked", llm=None,
             source="remotive", title="Software Engineer"):
    global _JOB_N
    _JOB_N += 1
    raw = RawJob(source=source, source_job_id=f"{company}-{_JOB_N}",
                 url=url or f"https://remotive.com/{company}/{_JOB_N}",
                 title=title, company=company, description_raw=desc,
                 description_clean=desc, tags=[])
    assert db.insert_job(conn, raw)
    jid = conn.execute("SELECT id FROM jobs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    fields = {"status": status}
    if llm is not None:
        fields["llm_score"] = llm
    db.update_job(conn, jid, **fields)
    conn.commit()


def test_scan():
    print("== scan orchestration ==")
    conn = _mem_db()
    # Evidence: 2 passing jobs w/ lever URL in the description -> via "url"
    _add_job(conn, "Acme Robotics", desc="apply: https://jobs.lever.co/acme-robotics/1")
    _add_job(conn, "Acme Robotics", desc="see https://jobs.lever.co/acme-robotics/2")
    # Only 1 passing job, no score -> no evidence
    _add_job(conn, "SoloCo")
    # 1 job but llm_score >= min_score; origin found via redirect resolution
    _add_job(conn, "HighScore", url="https://remotive.com/hs/1", status="scored", llm=88)
    # 2 passing jobs, no URLs anywhere -> slug guess path
    _add_job(conn, "GuessCo")
    _add_job(conn, "GuessCo")
    # Known company via existing roster -> excluded entirely
    _add_job(conn, "Visa", desc="https://jobs.smartrecruiters.com/Visa/1")
    _add_job(conn, "Visa", desc="https://jobs.smartrecruiters.com/Visa/2")
    # Filtered-out jobs never count as evidence
    _add_job(conn, "Rejected Inc", status="filtered_out",
             desc="https://jobs.lever.co/rejected/1")
    _add_job(conn, "Rejected Inc", status="filtered_out",
             desc="https://jobs.lever.co/rejected/2")
    # Content-dup rows never count as evidence (the canonical row already does)
    _add_job(conn, "Dupe Inc", status="duplicate",
             desc="https://jobs.lever.co/dupeinc/1")
    _add_job(conn, "Dupe Inc", status="duplicate",
             desc="https://jobs.lever.co/dupeinc/2")
    # Workday URL evidence -> entry candidate
    _add_job(conn, "WD Co", desc="https://wdco.wd5.myworkdayjobs.com/en-US/WDCareers/job/x")
    _add_job(conn, "WD Co", desc="https://wdco.wd5.myworkdayjobs.com/en-US/WDCareers/job/y")
    # A previously dismissed suggestion must stay dismissed across rescans
    _add_job(conn, "OldCo", desc="https://jobs.lever.co/oldco/1")
    _add_job(conn, "OldCo", desc="https://jobs.lever.co/oldco/2")
    conn.execute(
        "INSERT INTO source_suggestions (kind, token, status, created_at, updated_at)"
        " VALUES ('lever','oldco','dismissed','t','t')")
    conn.commit()

    sources_cfg = {"ats": {
        "smartrecruiters": ["Visa"],
        "workday": [{"tenant": "caci", "dc": "wd1", "site": "External",
                     "company": "CACI"}],
    }}
    criteria = {"min_score": 70}

    verify_calls = []

    def fake_verify(kind, token=None, entry=None):
        verify_calls.append((kind, token, entry))
        ok_keys = {("lever", "acme-robotics"), ("greenhouse", "highscore"),
                   ("greenhouse", "guessco"),
                   ("workday", "wdco/wd5/WDCareers")}
        key = (kind, f"{entry['tenant']}/{entry['dc']}/{entry['site']}"
               if kind == "workday" else (token or ""))
        ok = key in ok_keys
        return {"ok": ok, "count": 7 if ok else 0,
                "sample": ["Job A", "Job B"] if ok else [], "company": None,
                "message": ""}

    def fake_resolve(url):
        if "remotive.com/hs" in url:
            return "https://boards.greenhouse.io/highscore/jobs/9"
        return None

    created = harvest.scan(conn, sources_cfg, criteria,
                           verify_fn=fake_verify, resolve_fn=fake_resolve)
    got = {(s["kind"], s["token"]): s for s in created}

    check(("lever", "acme-robotics") in got, "URL-pattern suggestion created")
    check(got[("lever", "acme-robotics")]["via"] == "url", "via=url")
    check(("greenhouse", "highscore") in got, "redirect-resolved suggestion created")
    check(got[("greenhouse", "highscore")]["via"] == "redirect", "via=redirect")
    check(got[("greenhouse", "highscore")]["best_score"] == 88, "best_score carried")
    check(("greenhouse", "guessco") in got, "slug-guess suggestion created")
    check(got[("greenhouse", "guessco")]["via"] == "guess", "via=guess")
    check(("workday", "wdco/wd5/WDCareers") in got, "workday suggestion created")
    check(got[("workday", "wdco/wd5/WDCareers")]["entry"]["site"] == "WDCareers",
          "workday entry preserved")
    check(not any(k == "smartrecruiters" and t == "Visa" for k, t in got),
          "known roster token not re-suggested")
    check(not any(c[0] == "smartrecruiters" and c[1] == "Visa" for c in verify_calls),
          "known roster token never even verified")
    check(("lever", "oldco") not in got, "dismissed suggestion not resurrected")
    row = conn.execute("SELECT status FROM source_suggestions WHERE token='oldco'").fetchone()
    check(row["status"] == "dismissed", "dismissed row untouched")
    check(not any("rejected" in (t or "") for _, t, _e in verify_calls),
          "filtered_out jobs contributed no evidence")
    check(not any("dupeinc" in (t or "") for _, t, _e in verify_calls),
          "duplicate jobs contributed no evidence")
    check(got[("lever", "acme-robotics")]["live_count"] == 7, "live_count from verify")
    check(got[("lever", "acme-robotics")]["sample"] == ["Job A", "Job B"],
          "sample titles stored")

    # list/get/set_status round-trip
    listed = harvest.list_suggestions(conn)
    check(all(s["status"] == "suggested" for s in listed), "default list = suggested only")
    sid = listed[0]["id"]
    harvest.set_status(conn, sid, "accepted")
    check(harvest.get_suggestion(conn, sid)["status"] == "accepted", "set_status works")
    check(all(s["id"] != sid for s in harvest.list_suggestions(conn)),
          "accepted row leaves default list")
    conn.close()


def test_merge_accept():
    print("== merge_accept (sources.yaml round-trip) ==")
    yaml_text = (
        "# top comment survives\n"
        "ats:\n"
        "  lever:\n"
        "    - \"bhg-inc\"                    # BHG Financial\n"
        "  workday:\n"
        "    - { tenant: \"caci\", dc: \"wd1\", site: \"External\", company: \"CACI\" }\n"
    )
    old_cfg, old_backup = settings_store.CONFIG_DIR, settings_store.BACKUP_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            settings_store.CONFIG_DIR = tmp_path
            settings_store.BACKUP_DIR = tmp_path / "backups"
            (tmp_path / "sources.yaml").write_text(yaml_text, encoding="utf-8")

            harvest.merge_accept("lever", "acme-robotics")
            text = (tmp_path / "sources.yaml").read_text(encoding="utf-8")
            check("acme-robotics" in text, "lever token appended")
            check("# BHG Financial" in text, "existing inline comment preserved")
            check("# top comment survives" in text, "top comment preserved")

            harvest.merge_accept("workday", "wdco/wd5/WDCareers",
                                 {"tenant": "wdco", "dc": "wd5",
                                  "site": "WDCareers", "company": "WD Co"})
            data = settings_store.load_data("sources")
            wd = data["ats"]["workday"]
            check(any(e.get("tenant") == "wdco" for e in wd), "workday entry appended")
            check(any(e.get("tenant") == "caci" for e in wd), "existing entry kept")

            # accepting the same token again is a no-op
            _, changed = harvest.merge_accept("lever", "acme-robotics")
            check(changed is False, "duplicate accept is a no-op")
    finally:
        settings_store.CONFIG_DIR, settings_store.BACKUP_DIR = old_cfg, old_backup


if __name__ == "__main__":
    test_extract_candidates()
    test_slug_guesses()
    test_scan()
    test_merge_accept()
    print("ALL PASS")
