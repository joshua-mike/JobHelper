"""Roster harvester (ITEM-5): turn aggregator copies into direct origin sources.

Aggregator jobs (Remotive/Arbeitnow/RemoteOK/Adzuna) are delayed copies of
postings that live on an employer's ATS. When a company's copies keep clearing
the criteria, its board belongs in sources.yaml so the pipeline reads the
origin directly. This module:

  1. gathers EVIDENCE from the jobs DB — aggregator jobs from the last 30 days
     that survived the hard filter, grouped by company; a company qualifies
     with >=2 such jobs or any LLM score >= min_score;
  2. extracts board candidates via three signals, tagged in `via`:
       "url"      — ATS URL patterns in the stored job url/description
       "redirect" — best-effort resolution of the aggregator's redirect link
       "guess"    — slugs derived from the company name (can collide with a
                    different company's board, so provenance is surfaced)
  3. live-verifies every candidate through source_verify before suggesting;
  4. persists to source_suggestions (UNIQUE kind+token — dismissed suggestions
     stay dismissed across rescans).

Accepting a suggestion merges it into sources.yaml through the
comment-preserving settings store; the human stays in the loop.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

from .sources.base import USER_AGENT
from .util import get_logger, now_iso, parse_date
from .web import settings_store, source_verify

log = get_logger()

AGGREGATOR_SOURCES = ("remotive", "arbeitnow", "remoteok", "adzuna")
# Path segments that match the board-token position but aren't tokens.
_SKIP_TOKENS = {"embed", "job_board", "jobs", "job", "en-us", "wday", "api"}

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("greenhouse", re.compile(r"(?:job-)?boards\.greenhouse\.io/([A-Za-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([A-Za-z0-9_-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_-]+)", re.I)),
    ("smartrecruiters",
     re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I)),
]
_WORKDAY = re.compile(
    r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?"
    r"([A-Za-z0-9_-]+)", re.I)


# ---- candidate extraction ------------------------------------------------------
def extract_candidates(text: str, company: str) -> list[dict[str, Any]]:
    """All ATS board references found in a blob of url/description text."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    if not text:
        return out
    for kind, pat in _PATTERNS:
        for m in pat.finditer(text):
            token = m.group(1)
            key = (kind, token.lower())
            if token.lower() in _SKIP_TOKENS or key in seen:
                continue
            seen.add(key)
            out.append({"kind": kind, "token": token, "company": company})
    for m in _WORKDAY.finditer(text):
        tenant, dc, site = m.group(1).lower(), m.group(2).lower(), m.group(3)
        if site.lower() in _SKIP_TOKENS:
            continue
        token = f"{tenant}/{dc}/{site}"
        key = ("workday", token.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"kind": "workday", "token": token, "company": company,
                    "entry": {"tenant": tenant, "dc": dc, "site": site,
                              "company": company}})
    return out


def slug_guesses(company: str) -> list[str]:
    """Likely board tokens for a company name (joined + hyphenated forms)."""
    base = (company or "").lower().strip()
    base = re.sub(r"\s*\((.*?)\)\s*", " ", base)                 # drop "(...)"
    base = re.sub(r"[,.]|\s+(inc|llc|ltd|corp|corporation|company|co|gmbh)\.?$",
                  "", base).strip()
    joined = re.sub(r"[^a-z0-9]+", "", base)
    hyphen = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    out = [s for s in (joined, hyphen) if s]
    return list(dict.fromkeys(out))[:2]


def resolve_url(url: str, timeout: float = 8.0) -> str | None:
    """Follow an aggregator redirect chain to its landing URL. Best-effort."""
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout,
                          headers={"User-Agent": USER_AGENT}) as client:
            resp = client.head(url)
            if resp.status_code >= 400:  # some hosts reject HEAD
                resp = client.get(url)
            return str(resp.url)
    except Exception:
        return None


# ---- evidence ------------------------------------------------------------------
def known_tokens(sources_cfg: dict[str, Any] | None) -> set[tuple[str, str]]:
    """Everything already in the roster, plus company names covered by Workday."""
    ats = (sources_cfg or {}).get("ats") or {}
    known: set[tuple[str, str]] = set()
    for kind in ("greenhouse", "lever", "ashby", "smartrecruiters"):
        for t in ats.get(kind) or []:
            known.add((kind, str(t).lower()))
    for e in ats.get("workday") or []:
        if isinstance(e, dict):
            known.add(("workday",
                       f"{e.get('tenant', '')}/{e.get('dc', '')}/{e.get('site', '')}".lower()))
            if e.get("company"):
                known.add(("company", str(e["company"]).lower()))
    return known


def gather_evidence(conn: sqlite3.Connection, criteria: dict[str, Any],
                    days: int = 30) -> list[dict[str, Any]]:
    """Aggregator jobs that survived the hard filter, grouped per company."""
    min_score = int(criteria.get("min_score", 70) or 0)
    qmarks = ",".join("?" * len(AGGREGATOR_SOURCES))
    rows = conn.execute(
        f"SELECT company, url, description_raw, llm_score, status, first_seen_at "
        f"FROM jobs WHERE source IN ({qmarks})", AGGREGATOR_SOURCES).fetchall()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    groups: dict[str, dict[str, Any]] = {}
    for r in rows:
        # Unassessed, rejected, and content-dup rows carry no signal — for
        # duplicates, the canonical row already counts the posting once.
        if (r["status"] or "") in ("new", "filtered_out", "error", "duplicate"):
            continue
        seen_at = parse_date(r["first_seen_at"])
        if seen_at is not None and seen_at < cutoff:
            continue
        company = (r["company"] or "").strip()
        if not company:
            continue
        g = groups.setdefault(company.lower(), {
            "company": company, "count": 0, "best": 0, "texts": [], "urls": []})
        g["count"] += 1
        g["best"] = max(g["best"], r["llm_score"] or 0)
        g["texts"].append(f"{r['url'] or ''}\n{r['description_raw'] or ''}")
        if r["url"]:
            g["urls"].append(r["url"])
    return [g for g in groups.values()
            if g["count"] >= 2 or (g["best"] and g["best"] >= min_score)]


# ---- scan ----------------------------------------------------------------------
def _default_verify(kind: str, token: str | None = None,
                    entry: dict[str, Any] | None = None) -> dict[str, Any]:
    return source_verify.verify(kind, token=token, entry=entry)


def scan(conn: sqlite3.Connection, sources_cfg: dict[str, Any],
         criteria: dict[str, Any], *, max_verify: int = 12, max_resolve: int = 10,
         verify_fn: Callable[..., dict[str, Any]] | None = None,
         resolve_fn: Callable[[str], str | None] | None = None) -> list[dict[str, Any]]:
    """One harvester pass. Returns the suggestion rows created this scan."""
    verify_fn = verify_fn or _default_verify
    resolve_fn = resolve_fn or resolve_url
    known = known_tokens(sources_cfg)
    tried: set[tuple[str, str]] = {
        (r["kind"], r["token"].lower())
        for r in conn.execute("SELECT kind, token FROM source_suggestions")}
    evidence = gather_evidence(conn, criteria)
    log.info("harvest: %d companies with evidence", len(evidence))

    created: list[dict[str, Any]] = []
    verifies = resolves = 0
    for g in sorted(evidence, key=lambda g: (g["best"], g["count"]), reverse=True):
        if ("company", g["company"].lower()) in known:
            continue
        cands: list[dict[str, Any]] = []
        via: dict[tuple[str, str], str] = {}
        for text in g["texts"]:
            for c in extract_candidates(text, g["company"]):
                cands.append(c)
                via.setdefault((c["kind"], c["token"].lower()), "url")
        if not cands:
            for url in g["urls"][:2]:
                if resolves >= max_resolve:
                    break
                resolves += 1
                final = resolve_fn(url)
                for c in extract_candidates(final or "", g["company"]):
                    cands.append(c)
                    via.setdefault((c["kind"], c["token"].lower()), "redirect")
                if cands:
                    break
        if not cands:
            for guess in slug_guesses(g["company"]):
                for kind in ("greenhouse", "lever", "ashby"):
                    cands.append({"kind": kind, "token": guess,
                                  "company": g["company"]})
                    via.setdefault((kind, guess.lower()), "guess")

        for c in cands:
            key = (c["kind"], c["token"].lower())
            if key in known or key in tried:
                continue
            if verifies >= max_verify:
                break
            verifies += 1
            tried.add(key)  # one live attempt per token per scan history
            result = verify_fn(
                c["kind"],
                token=None if c["kind"] == "workday" else c["token"],
                entry=c.get("entry"))
            if not result.get("ok"):
                continue
            row = _insert_suggestion(conn, c, via.get(key, "url"), g, result)
            if row:
                created.append(row)
    conn.commit()
    log.info("harvest: %d new suggestions (%d verifies, %d resolves)",
             len(created), verifies, resolves)
    return created


def _insert_suggestion(conn: sqlite3.Connection, cand: dict[str, Any], via: str,
                       group: dict[str, Any], verify_result: dict[str, Any]
                       ) -> dict[str, Any] | None:
    ts = now_iso()
    cur = conn.execute(
        """INSERT OR IGNORE INTO source_suggestions
           (kind, token, entry, company, evidence_count, best_score, live_count,
            sample, via, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,'suggested',?,?)""",
        (cand["kind"], cand["token"],
         json.dumps(cand["entry"]) if cand.get("entry") else None,
         cand.get("company"), group["count"], group["best"] or None,
         verify_result.get("count"), json.dumps(verify_result.get("sample") or []),
         via, ts, ts))
    if cur.rowcount == 0:
        return None
    return get_suggestion(conn, cur.lastrowid)


# ---- suggestion store ------------------------------------------------------------
def _row_to_dict(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    d["entry"] = json.loads(d["entry"]) if d.get("entry") else None
    d["sample"] = json.loads(d["sample"]) if d.get("sample") else []
    return d


def list_suggestions(conn: sqlite3.Connection,
                     include_all: bool = False) -> list[dict[str, Any]]:
    where = "" if include_all else " WHERE status='suggested'"
    rows = conn.execute(
        f"SELECT * FROM source_suggestions{where} "
        f"ORDER BY best_score DESC, evidence_count DESC, id").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_suggestion(conn: sqlite3.Connection, sid: int) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM source_suggestions WHERE id=?",
                     (sid,)).fetchone()
    return _row_to_dict(r) if r else None


def set_status(conn: sqlite3.Connection, sid: int, status: str) -> None:
    conn.execute("UPDATE source_suggestions SET status=?, updated_at=? WHERE id=?",
                 (status, now_iso(), sid))
    conn.commit()


def merge_accept(kind: str, token: str,
                 entry: dict[str, Any] | None = None) -> tuple[Any, bool]:
    """Merge an accepted suggestion into sources.yaml (comment-preserving)."""
    data = settings_store.load_data("sources") or {}
    ats = data.get("ats") or {}
    if kind == "workday":
        rows = [e for e in (ats.get("workday") or []) if isinstance(e, dict)]
        triple = (entry or {}).get("tenant"), (entry or {}).get("dc"), \
            (entry or {}).get("site")
        if entry and not any(
                (e.get("tenant"), e.get("dc"), e.get("site")) == triple
                for e in rows):
            rows.append(entry)
        payload: dict[str, Any] = {"ats": {"workday": rows}}
    else:
        items = [str(t) for t in (ats.get(kind) or [])]
        if token not in items:
            items.append(token)
        payload = {"ats": {kind: items}}
    return settings_store.save("sources", payload)
