"""Offline tests for the direct-hire gate (ITEM-26): staffing classifier + pool gate.

Phrases are taken from real postings in the DB — the positives that identify
staffing/contract ads, and the traps a naive matcher trips on (a direct
employer's "our client's businesses" boilerplate, Leidos' "Our customer, DISA",
CACI's "Comply-to-Connect (C2C)", a VA contractor's "Client: Department of
Veterans Affairs"). Runs on throwaway temp DBs only.

Run:  python tests/test_staffing.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhelper import db  # noqa: E402
from jobhelper.rank.staffing import (  # noqa: E402
    StaffingScreen, apply_gate, evidence, normalize_company, restore_company,
    sticky_companies)


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def job(company="Acme Corp", title="Senior .NET Developer", desc="",
        source="adzuna", employer_type=None):
    return {"company": company, "title": title, "description_clean": desc,
            "source": source, "employer_type": employer_type}


def test_normalize():
    print("== normalize_company ==")
    check(normalize_company("Insight Global, Inc.") == "insight global",
          "punctuation + legal suffix dropped")
    check(normalize_company("CYNET SYSTEMS") == normalize_company("Cynet Systems"),
          "case-insensitive")
    check(normalize_company("Syms Strategic Group, LLC ") == "syms strategic group",
          "trailing whitespace + LLC")
    check(normalize_company(None) == "", "None -> empty key")


POSITIVES = [
    ("known agency", job(company="TEKsystems c/o Allegis Group",
                         desc="We are seeking a Software Developer.")),
    ("known agency perm placement", job(
        company="INSPYR Solutions",
        desc="Sr. Software Engineer - Direct-Hire/FTE - Remote (US)")),
    ("W2 only", job(desc=".NET Developer - Hybrid / 70% Remote ONLY W2/USC")),
    ("our client", job(desc="Our client, which is a large Insurance Firm is urgently "
                            "looking to hire a Sr. Full Stack Developer.")),
    ("state-agency Client: field", job(
        desc="Location: Des Moines, IA Duration: 12 Months Pay Rate: $60/H W2 "
             "Client: IA-DOM-DOIT")),
    ("Duration field", job(desc="Job Title: .NET Developer Location: Remote "
                                "Duration: Long term contract")),
    ("recruiter greeting", job(desc="Hi, Hope all is well, Please find the job "
                                    "description given below.")),
    ("contract-to-hire", job(desc="Position Type: Contract-to-Hire Location: Fully Remote")),
    ("contract in title", job(title="Full Stack .Net Developer - Angular and Banking - "
                                    "Remote - Contract",
                              desc="We are seeking a skilled .NET Developer.")),
    ("title starts with Contract", job(title="Contract .NET Developer",
                                       desc="Build APIs.")),
    ("staffing company name", job(company="Spear Staffing", desc="Build APIs.")),
    ("1099 contractor", job(desc="Job Type: Independent Contract Pay Rate: $58-62/hr "
                                 "1099 / C2C")),
    ("self-described agency", job(desc="Recruiting from Scratch is a premier talent firm "
                                       "that focuses on placing the best talent.")),
]

NEGATIVES = [
    ("SitusAMC boilerplate", job(
        company="SitusAMC",
        desc="SitusAMC is where the best and most passionate people come to "
             "transform our client's businesses and their own careers.")),
    ("Leidos 'Our customer'", job(
        company="Leidos",
        desc="Our customer, Defense Information Systems Agency (DISA), needs you.")),
    ("CACI Comply-to-Connect", job(
        company="CACI", title="Senior Cyber Security Engineer - Comply-to-Connect (C2C)",
        desc="Deploy Comply-to-Connect (C2C) frameworks.")),
    ("consultancy 'our clients'", job(
        company="Praxent",
        desc="We help our clients modernize, rather than rebuild, outdated systems.")),
    ("VA contractor Client: field alone", job(
        company="Fathom Management LLC",
        desc="Client: Department of Veterans Affairs (VA) Location: 100% Remote "
             "Salary: $140,000")),
    ("consultancy name alone", job(
        company="ICF Consulting Group, Inc.",
        desc="ICF's Digital Modernization division is seeking developers.")),
    ("payroll W-2 forms", job(
        company="Experian",
        desc="Delivering files for W-2 GU, VI, PR, 1099 (M, R, NEC).")),
    ("1099 compliance", job(company="Curri",
                            desc="Own payout escalations and 1099 compliance.")),
    ("'Contracts' in title", job(title="Software Engineer - Government Contracts",
                                 desc="Build APIs.")),
    ("Technologies in name", job(company="L3Harris Technologies",
                                 desc="L3Harris has an immediate opening.")),
    ("plain direct posting", job(company="OneStream",
                                 desc="Senior Software Engineer II, full-time, remote.")),
]


def test_evidence():
    print("== evidence (positives) ==")
    for name, j in POSITIVES:
        found = evidence(j)
        check(bool(found), f"{name}: {found}")
    print("== evidence (negatives / traps) ==")
    for name, j in NEGATIVES:
        found = evidence(j)
        check(not found, f"{name}: {found or 'clean'}")


def test_screen():
    print("== StaffingScreen ==")
    base = StaffingScreen({})
    w2 = job(desc="Only W2 candidates.")
    check(base.reason(w2).startswith("staffing: W2/C2C"), "reason names the signal")
    check(base.reason(job(source="greenhouse", desc="Only W2 candidates.")) is None,
          "curated board: text rules never run")

    allow = StaffingScreen({"direct_employers_allow": ["Apex Systems, Inc."]})
    check(allow.reason(job(company="APEX SYSTEMS", desc="Only W2.")) is None,
          "allow list beats known list + text (normalized match)")

    deny = StaffingScreen({"staffing_companies": ["Acme Talent Partners"]})
    check(deny.reason(job(company="Acme Talent Partners", source="greenhouse")) ==
          "staffing: listed in staffing_companies",
          "staffing_companies parks even a curated-board job")

    check(base.reason(job(employer_type="staffing")) == "staffing: judge: staffing agency",
          "judge 'staffing' verdict parks an aggregator job")
    check(base.reason(job(employer_type="contract")) == "staffing: judge: contract role",
          "judge 'contract' verdict parks")
    check(base.reason(job(employer_type="direct")) is None, "judge 'direct' keeps")
    check(base.reason(job(employer_type="unclear")) is None, "judge 'unclear' keeps")
    check(base.reason(job(source="lever", employer_type="staffing")) is None,
          "judge verdict ignored on curated boards")


def test_sticky():
    print("== sticky_companies ==")
    flagged = job(company="Body Shop Inc", desc="W2 only")
    clean = job(company="Body Shop Inc", desc="Build APIs.")
    check("body shop" in sticky_companies([flagged, flagged, clean]),
          "2 of 3 postings flagged -> sticky")
    check("body shop" not in sticky_companies([flagged, clean]),
          "a single flagged posting is not enough")
    check("body shop" not in sticky_companies([flagged, flagged, clean, clean, clean]),
          "2 of 5 (under half) -> not sticky")
    check("body shop" not in sticky_companies(
        [dict(flagged, source="greenhouse")] * 3),
          "curated-board rows never count")
    check(sticky_companies([flagged, flagged, clean], only={"other"}) == frozenset(),
          "`only` restricts the scan")
    screen = StaffingScreen({}, sticky_companies([flagged, flagged, clean]))
    check(screen.reason(clean) == "staffing: company flagged on most of its other postings",
          "sticky parks the clean posting")


def _insert(conn, key, status, company="Acme Corp", desc="Build APIs.",
            source="adzuna", llm_score=None):
    conn.execute(
        "INSERT INTO jobs (job_hash, source, title, company, description_clean, "
        "status, llm_score) VALUES (?,?,?,?,?,?,?)",
        (key, source, "Senior .NET Developer", company, desc, status, llm_score))


def _status(conn, key):
    return tuple(conn.execute("SELECT status, status_reason FROM jobs WHERE job_hash=?",
                              (key,)).fetchone())


def test_gate():
    print("== apply_gate round trip ==")
    with tempfile.TemporaryDirectory() as td:
        conn = sqlite3.connect(Path(td) / "t.db")
        conn.row_factory = sqlite3.Row
        try:
            db.init_db(conn)
            _insert(conn, "agency_ranked", "ranked", company="Kforce Inc.")
            _insert(conn, "w2_scored", "scored", company="Fiekon",
                    desc="Only W2", llm_score=82)
            _insert(conn, "direct", "ranked", company="OneStream")
            _insert(conn, "curated_w2", "ranked", company="Rackner",
                    desc="Only W2", source="greenhouse")
            _insert(conn, "agency_proposed", "proposed", company="Apex Systems")
            # Sticky via history: two filtered-out W2 ads + one clean pool ad.
            _insert(conn, "shop_hist1", "filtered_out", company="Shop LLC", desc="W2 only")
            _insert(conn, "shop_hist2", "expired", company="Shop LLC", desc="C2C ok")
            _insert(conn, "shop_pool", "ranked", company="Shop LLC")
            # Duplicates never count as sticky evidence.
            _insert(conn, "dup1", "duplicate", company="Dup Co", desc="W2 only")
            _insert(conn, "dup2", "duplicate", company="Dup Co", desc="W2 only")
            _insert(conn, "dup_pool", "ranked", company="Dup Co")
            conn.commit()

            on = {"direct_hire_only": True}
            parked, restored = apply_gate(conn, on)
            check((parked, restored) == (3, 0), f"ON parks 3 (got {parked}, {restored})")
            check(_status(conn, "agency_ranked")[0] == "staffing", "known agency parked")
            check(_status(conn, "w2_scored") ==
                  ("staffing", "staffing: W2/C2C terms"), "scored W2 job parked w/ reason")
            check(_status(conn, "shop_pool")[0] == "staffing", "sticky from history parks")
            check(_status(conn, "direct")[0] == "ranked", "direct employer kept")
            check(_status(conn, "curated_w2")[0] == "ranked", "curated board kept")
            check(_status(conn, "agency_proposed")[0] == "proposed",
                  "in-flight job never touched")
            check(_status(conn, "dup_pool")[0] == "ranked",
                  "duplicate rows are not sticky evidence")

            check(apply_gate(conn, on) == (0, 0), "idempotent second pass")

            parked, restored = apply_gate(
                conn, {**on, "direct_employers_allow": ["fiekon"]})
            check((parked, restored) == (0, 1), "allow-listing restores on next pass")
            check(_status(conn, "w2_scored") == ("scored", None),
                  "restored to 'scored' (has llm_score), reason cleared")

            parked, restored = apply_gate(conn, {"direct_hire_only": False})
            check((parked, restored) == (0, 2), "OFF restores every parked job")
            check(_status(conn, "agency_ranked") == ("ranked", None),
                  "restored to 'ranked' (no llm_score)")
            check(apply_gate(conn, {}) == (0, 0), "missing key = off, nothing parked")

            parked, _ = apply_gate(conn, on)
            check(parked == 3, "ON again re-parks all three")
        finally:
            conn.close()


def test_restore_company_and_migration():
    print("== restore_company + employer_type migration ==")
    with tempfile.TemporaryDirectory() as td:
        conn = sqlite3.connect(Path(td) / "t.db")
        conn.row_factory = sqlite3.Row
        try:
            # A pre-ITEM-26 jobs table: no employer_type column.
            conn.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, job_hash TEXT "
                         "UNIQUE NOT NULL, source TEXT NOT NULL, title TEXT, company "
                         "TEXT, description_clean TEXT, status TEXT NOT NULL DEFAULT "
                         "'new', status_reason TEXT, llm_score INTEGER, updated_at TEXT)")
            db.init_db(conn)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
            check("employer_type" in cols, "init_db adds employer_type to an old table")
            db.init_db(conn)
            check(True, "migration is idempotent")

            _insert(conn, "a", "staffing", company="Georgia IT, Inc.")
            _insert(conn, "b", "staffing", company="GEORGIA IT", llm_score=70)
            _insert(conn, "c", "staffing", company="Other Shop")
            n = restore_company(conn, "Georgia IT")
            conn.commit()
            check(n == 2, f"restores both name variants (got {n})")
            check(_status(conn, "b")[0] == "scored", "judged job back to 'scored'")
            check(_status(conn, "c")[0] == "staffing", "other companies untouched")
        finally:
            conn.close()


if __name__ == "__main__":
    test_normalize()
    test_evidence()
    test_screen()
    test_sticky()
    test_gate()
    test_restore_company_and_migration()
    print("\nAll staffing tests passed.")
