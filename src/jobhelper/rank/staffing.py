"""Direct-hire screen: park staffing-agency and fixed-term contract postings (ITEM-26).

Staffing postings arrive almost only through the open-market aggregators —
overwhelmingly Adzuna. The curated per-company boards in sources.yaml are the
employer's own ATS, so they are trusted: text rules never run on them, and only
an explicit `staffing_companies` entry can park one of their jobs.

No source exposes an employer-type field (Adzuna's `contract_type` is filled on
~5% of ads), so detection is a weighted heuristic over the posting text and the
company name. Measured 2026-09-22 on a held-out, hand-labelled sample of 100
Adzuna companies: ~98-99% precision, ~71% recall per job / ~79% per company.
Recall is lifted by:
  - a known-agency list (national agencies whose permanent-placement ads read
    exactly like direct postings),
  - "sticky" company memory: a company flagged on most of its postings is
    flagged on the rest, and
  - the Claude judge's `employer_type` verdict when an API key is set.

The weak spot is federal contractors, who share the vocabulary ("Client:
Department of Veterans Affairs", "Job ID:"), which is why the gate PARKS jobs in
a reversible 'staffing' status rather than filtering them, and why
`direct_employers_allow` (fed by the review page's "Not staffing" button)
always wins.
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from typing import Any, Iterable

from .. import db

# Sources whose company field is whoever posted the ad. Everything else is a
# curated employer board.
OPEN_MARKET_SOURCES = frozenset({"adzuna", "remotive", "remoteok", "arbeitnow"})

PARKED = "staffing"
THRESHOLD = 2          # evidence weight needed to flag a posting
STICKY_MIN_JOBS = 2    # sticky needs this many directly-flagged postings...
STICKY_MIN_SHARE = 0.5  # ...making up at least this share of the company's ads

# Judge verdicts that park a job (see llm_judge.SCHEMA["employer_type"]).
JUDGE_PARK = {"staffing": "judge: staffing agency",
              "contract": "judge: contract role"}

_FEDERAL = (r"(the\s+)?(u\.?\s?s\.?\s|united states|department|dept\.?|army|navy|"
            r"air force|space force|marine|dod\b|dhs\b|va\b|nasa|federal|defense|"
            r"veterans)")

# (label, triggers, pattern, weight), matched against LOWERCASED text. Strong
# (2) markers alone flag a posting; weak (1) ones need a second signal. "Direct
# hire" means permanent, so fixed-term contract markers count as strong even at
# a real employer. A regex only runs when one of its literal triggers is
# present: Python's re is slow on long descriptions, and the sticky pass scans
# thousands.
_TEXT_SIGNALS: list[tuple[str, tuple[str, ...], re.Pattern, int]] = [
    (label, triggers, re.compile(p, re.M), w) for label, triggers, p, w in [
        ("W2/C2C terms", ("w2", "w-2", "c2c", "corp"),
         r"\b(only\s+)?w-?2\b(?!\s*(gu|forms?|reporting|processing))|\bc2c\b|"
         r"\bcorp[- ]?to[- ]?corp\b|\bself[- ]incorp", 2),
        ("1099 contractor", ("1099",),
         r"\b1099\b(?!\s*(compliance|forms?|reporting|processing|-?(misc|nec|k)\b|\())", 2),
        ("contract-to-hire", ("to-hire", "to hire", "to-perm", "to perm", "c2h"),
         r"contract[- ]to[- ](hire|perm)|\bc2h\b", 2),
        ("placement with a client", ("client",),
         r"\b(our|my) (direct |premier |valued )?client\b(?!['’]?s)|"
         r"\bon behalf of (our|a|one of our) clients?\b|"
         r"\bone of (our|its) (direct )?clients\b|\bend[- ]client\b|\bdirect client\b|"
         r"\bhiring for (one of )?our clients?\b|\bthe client is (seeking|looking)\b|"
         r"^[ \t]*client (is|has) ", 2),
        ("'Client:' field", ("client",), rf"\bclient\s*:\s*(?!{_FEDERAL})\w", 2),
        # Federal contractors name their agency customer the same way — weak only.
        ("'Client:' federal agency", ("client",), rf"\bclient\s*:\s*{_FEDERAL}", 1),
        ("recruiter outreach", ("hi", "hello", "greetings", "resume", "talent acq"),
         r"^[ \t]*(hi|hello)\b[ ,!]|\bgreetings from\b|"
         r"\bshare (your|the) (updated|latest) resume\b|"
         r"\btalent acquisition specialist at\b", 2),
        ("visa/tax terms", ("visa", "usc", "gc", "tax terms"),
         r"\bvisa( status)?\s*:|\b(usc|gc)\s*(/|only)|\bgc[- ]?ead\b|\b(open|any) visa\b|"
         r"\bvisa independent\b|\btax terms\b", 2),
        ("self-described staffing firm", ("staffing", "recruit", "talent firm"),
         r"\bstaffing (firm|agency|company|partner)\b|\brecruit(ing|ment) (firm|agency)\b|"
         r"\btalent firm\b", 2),
        ("fixed-term contract", ("duration", "contract", "temp"),
         r"\bduration\s*[:\-–]|\b\d+\s*[-–]?\s*(\d+\s*)?(months?|mos)\b.{0,15}"
         r"\b(contract|extension|extendable)\b|\blong[- ]term (contract|project)\b|"
         r"\bcontract (role|position|opportunity|assignment|engagement|length)\b|"
         r"\b(job|position|employment) type\s*:\s*contract\b|\btemp\s*-", 2),
        ("hourly rate", ("rate", "hr", "hour", "/h"),
         r"(pay )?rate\s*:\s*\$?\d|\$\s?\d+(\.\d+)?\s*(-|–|to)?\s*\$?\d*\s*(/|per|p/)\s*"
         r"(hr|hour|h)\b|\bper hr\b", 1),
        ("job-order id", ("job id", "job code", "job #"), r"\bjob (id|code|#)\s*[:#]", 1),
    ]]
# Title-only: "Contract .NET Developer", "... - Remote - Contract", "(Contractor)".
_TITLE_CONTRACT = re.compile(
    r"^\s*contract(or)?\b|[-–(|/,:]\s*contract(or)?\s*($|\)|[-–|/,])")
# CACI & co. name a DoD framework "Comply-to-Connect (C2C)".
_C2C_FRAMEWORK = re.compile(r"comply[- ]to[- ]connect\s*\(c2c\)")

_NAME_SIGNALS: list[tuple[str, re.Pattern, int]] = [
    ("staffing company name",
     re.compile(r"staffing|recruit|\btalent\b|\brpo\b|personnel|placement", re.I), 2),
    ("IT-consultancy company name",
     re.compile(r"(?i:consult|infotech|infotek|infosys|informatics|soft ?tech|tek\b|"
                r"workforce)|\bIT\b"), 1),
]

# Normalized names (see normalize_company); a company matches when its name
# equals an entry or starts with it plus a word ("randstad digital"). National
# agencies and talent marketplaces, plus the highest-volume body shops seen in
# the data. Big IT-services firms (Cognizant, NTT DATA, Hexaware…) are
# deliberately absent: they hire their own FTEs, so only posting text flags them.
KNOWN_STAFFING = frozenset("""
teksystems|allegis group|aerotek|kforce|robert half|randstad|insight global|apex systems
motion recruitment|akkodis|modis|adecco|manpowergroup|manpower|experis|hays|kelly services
cybercoders|collabera|mindlance|cynet systems|genesis10|system one|eliassen group
inspyr solutions|pinnacle technical resources|beacon hill|judge group|the judge group
harvey nash|jobot|vaco|addison group|russell tobin|yoh|artech|infojini|diverse lynx
compunnel|net2source|bcforward|bc forward|tandym|tandym tech|the planet group
request technology|rezult group|calance|comrise|mitchell martin|the squires group
the timberline group|tsr consulting services|talent software services
integrated resources|rangam consultants|vdart|next step systems|sunrise systems
the computer merchant|butler america aerospace|iris software|u s tech solutions|ascendion
synergisticit|bright vision technologies|apetan consulting|techgene solutions
pull skill technologies|tech observer|sysmind|stellent it|primus global services
intone networks|javen technologies|isite technologies|georgia it|widenet consulting
charter global|consultnet technology services and solutions
lemon io|turing enterprises|toptal|braintrust|a team|mercor|andela|gun io
""".replace("\n", "|").strip("|").split("|"))

_LEGAL_SUFFIXES = frozenset(
    "inc incorporated llc ltd limited corp corporation co company lp llp pllc plc".split())


def normalize_company(name: str | None) -> str:
    """Case/punctuation-insensitive company key, legal suffixes dropped:
    'Insight Global, Inc.' -> 'insight global'."""
    toks = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).split()
    while toks and toks[-1] in _LEGAL_SUFFIXES:
        toks.pop()
    return " ".join(toks)


def _known(key: str) -> bool:
    words = key.split()
    return any(" ".join(words[:n]) in KNOWN_STAFFING for n in range(1, len(words) + 1))


def evidence(job: dict[str, Any]) -> list[str]:
    """Why an open-market posting looks third-party/contract (empty = looks direct).

    Pure and allow-list-blind: the building block for both the per-job verdict
    and the sticky company memory. Ignores sticky memory itself.
    """
    company = job.get("company") or ""
    if _known(normalize_company(company)):
        return ["known staffing firm"]
    verdict = JUDGE_PARK.get((job.get("employer_type") or "").lower())
    title = (job.get("title") or "").lower()
    text = f"{title}\n{(job.get('description_clean') or '').lower()}"
    if "c2c" in text:
        text = _C2C_FRAMEWORK.sub(" ", text)
    hits = [(label, w) for label, triggers, pat, w in _TEXT_SIGNALS
            if any(t in text for t in triggers) and pat.search(text)]
    if _TITLE_CONTRACT.search(title):
        hits.append(("contract in title", 2))
    hits += [(label, w) for label, pat, w in _NAME_SIGNALS if pat.search(company)]
    reasons = [verdict] if verdict else []
    if sum(w for _, w in hits) >= THRESHOLD:
        reasons += [label for label, _ in hits]
    return reasons


def sticky_companies(rows: Iterable[dict[str, Any]],
                     only: set[str] | None = None) -> frozenset[str]:
    """Normalized names of companies flagged on most of their open-market ads.

    A body shop rarely spells out W2/C2C on every ad; once most of its ads
    do, the rest are parked too. The share guard keeps a direct employer with
    one contract-to-hire role from dragging all its other postings along.
    `only` limits the scan to these normalized names (the gate passes the
    pool's companies — scoring all history each run is needlessly slow).
    """
    total: dict[str, int] = defaultdict(int)
    flagged: dict[str, int] = defaultdict(int)
    for row in rows:
        if row.get("source") not in OPEN_MARKET_SOURCES:
            continue
        key = normalize_company(row.get("company"))
        if not key or (only is not None and key not in only):
            continue
        total[key] += 1
        if evidence(row):
            flagged[key] += 1
    return frozenset(k for k, n in flagged.items()
                     if n >= STICKY_MIN_JOBS and n / total[k] >= STICKY_MIN_SHARE)


class StaffingScreen:
    """Per-run verdicts: allow list > deny list > (open-market only) evidence > sticky."""

    def __init__(self, criteria: dict[str, Any],
                 sticky: frozenset[str] = frozenset()) -> None:
        self.allow = {normalize_company(c)
                      for c in (criteria.get("direct_employers_allow") or []) if c}
        self.deny = {normalize_company(c)
                     for c in (criteria.get("staffing_companies") or []) if c}
        self.sticky = sticky

    def reason(self, job: dict[str, Any]) -> str | None:
        """Park reason ('staffing: …'), or None to keep the job."""
        key = normalize_company(job.get("company"))
        if key and key in self.allow:
            return None
        if key and key in self.deny:
            return "staffing: listed in staffing_companies"
        if job.get("source") not in OPEN_MARKET_SOURCES:
            return None  # curated employer boards are trusted
        found = evidence(job)
        if found:
            return "staffing: " + "; ".join(dict.fromkeys(found))
        if key and key in self.sticky:
            return "staffing: company flagged on most of its other postings"
        return None


def _restored_status(row: sqlite3.Row) -> str:
    return "scored" if row["llm_score"] is not None else "ranked"


def apply_gate(conn: sqlite3.Connection, criteria: dict[str, Any]) -> tuple[int, int]:
    """Reconcile the pool with the direct_hire_only switch; returns (parked, restored).

    Runs every pipeline pass, so flipping the switch takes effect on the next
    run in both directions. ON: pool jobs (ranked/scored) that look third-party
    move to 'staffing'; parked jobs that no longer do (allow-listed since, or
    the rules changed) come back. OFF: every parked job returns to the pool.
    Jobs already in front of the user (proposed and later) are never touched.
    Caller need not commit.
    """
    parked = restored = 0
    if not criteria.get("direct_hire_only"):
        for row in db.jobs_by_status(conn, PARKED):
            db.update_job(conn, row["id"], status=_restored_status(row),
                          status_reason=None)
            restored += 1
        conn.commit()
        return parked, restored

    pool = db.jobs_by_status(conn, "ranked", "scored", PARKED)
    pool_keys = {normalize_company(r["company"]) for r in pool
                 if r["source"] in OPEN_MARKET_SOURCES}
    qmarks = ",".join("?" * len(OPEN_MARKET_SOURCES))
    history = conn.execute(
        "SELECT source, company, title, description_clean, employer_type FROM jobs "
        f"WHERE status != 'duplicate' AND source IN ({qmarks})",
        tuple(OPEN_MARKET_SOURCES))
    screen = StaffingScreen(
        criteria, sticky_companies((dict(r) for r in history), only=pool_keys))
    for row in pool:
        reason = screen.reason(dict(row))
        if reason and row["status"] != PARKED:
            db.update_job(conn, row["id"], status=PARKED, status_reason=reason)
            parked += 1
        elif not reason and row["status"] == PARKED:
            db.update_job(conn, row["id"], status=_restored_status(row),
                          status_reason=None)
            restored += 1
    conn.commit()
    return parked, restored


def restore_company(conn: sqlite3.Connection, company: str) -> int:
    """Return every parked job of `company` (normalized match) to the pool.

    The review page's "Not staffing" action; pairs with adding the company to
    direct_employers_allow so the next gate pass doesn't re-park it. Caller
    commits.
    """
    key = normalize_company(company)
    n = 0
    for row in db.jobs_by_status(conn, PARKED):
        if normalize_company(row["company"]) == key:
            db.update_job(conn, row["id"], status=_restored_status(row),
                          status_reason=None)
            n += 1
    return n
