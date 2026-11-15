"""The daily pipeline: source -> dedupe -> filter -> direct-hire gate -> score ->
select -> tailor -> digest.

Each stage is gated on the status state machine and safe to re-run. Per-job errors
are isolated (the row is marked 'error' and the batch continues).
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import db
from .config import (has_anthropic, load_criteria, load_env, load_profile,
                     load_sources, profile_comparison_text)
from .digest import render_digest
from .llm import LLM
from .rank import Judge, Scorer, passes, staffing
from .sources import build_sources
from .tailor import (build_ats_report, build_resume, cover_letter,
                     distinctive_achievements, extract_docx_text,
                     extract_keywords, screening_answers, select_variant,
                     structural_failures, tailor_resume)
from .util import RESUME_DIR, age_days, get_logger, parse_date

log = get_logger()

# Network waits dominate a run, so sources are fetched, and Claude calls made,
# a few at a time. The Fetcher still spaces requests per host.
FETCH_WORKERS = 8
LLM_WORKERS = 4


def _safe(text: str, n: int = 48) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_")[:n] or "job"


def _select_diverse(cands: list, target: int, max_per_company: int) -> list:
    """Pick up to `target` proposals, at most `max_per_company` from any one company.

    Candidates must already be sorted best-first. Pass 1 enforces the per-company
    cap to spread across employers; if that leaves us short of `target` (too few
    distinct companies), pass 2 fills the remainder with the next-best regardless
    of the cap, so we still surface a full day's worth.
    """
    def company(r):
        return (r["company"] or "").strip().lower()

    chosen, counts = [], {}
    for r in cands:                                   # pass 1: respect the cap
        if len(chosen) >= target:
            break
        c = company(r)
        if counts.get(c, 0) < max(1, max_per_company):
            chosen.append(r)
            counts[c] = counts.get(c, 0) + 1
    if len(chosen) < target:                          # pass 2: fill the gap
        picked = {r["id"] for r in chosen}
        for r in cands:
            if len(chosen) >= target:
                break
            if r["id"] not in picked:
                chosen.append(r)
    return chosen


def _expire_stale(conn, criteria: dict) -> int:
    """Expire pool jobs older than max_age_days (posted date, else first seen).

    The ingest freshness filter only sees jobs on the way in; without this the
    ranked/scored pool keeps stale postings forever, and they compete with new
    arrivals for judge-shortlist slots long after the listings are dead.
    """
    max_age = criteria.get("max_age_days")
    if not max_age:
        return 0
    expired = 0
    for row in db.jobs_by_status(conn, "ranked", "scored"):
        posted = parse_date(row["date_posted"]) or parse_date(row["first_seen_at"])
        age = age_days(posted)
        if age is not None and age > float(max_age):
            db.update_job(conn, row["id"], status="expired",
                          status_reason=f"expired: older than {max_age} days")
            expired += 1
    conn.commit()
    return expired


def _shortlist_fresh_first(unjudged: list, n: int,
                           prev_run_started: str | None) -> list:
    """Order unjudged jobs for the LLM judge: this cycle's arrivals first.

    Embed rank alone lets a large unjudged backlog starve brand-new postings
    out of the shortlist for days. Jobs first seen since the previous completed
    run claim slots first (best embed first); the backlog fills what's left.
    """
    def embed(r):
        return r["embed_score"] or 0

    fresh, backlog = [], []
    for r in unjudged:
        is_fresh = (prev_run_started is None
                    or (r["first_seen_at"] or "") >= prev_run_started)
        (fresh if is_fresh else backlog).append(r)
    fresh.sort(key=embed, reverse=True)
    backlog.sort(key=embed, reverse=True)
    return (fresh + backlog)[:n]


def _judge_all(judge: Judge, shortlist: list) -> list[dict | None]:
    """Judge every shortlisted job; results line up with `shortlist`, None where
    a call failed.

    The first job is judged alone so its call writes the shared profile to the
    prompt cache; the rest then run concurrently and read it. Started together,
    every call would miss the cache and pay to write it."""
    def score(row) -> dict | None:
        try:
            return judge.score(dict(row))
        except Exception as exc:
            log.warning("judge failed for %s: %s", row["id"], exc)
            return None

    if not shortlist:
        return []
    first = score(shortlist[0])
    with ThreadPoolExecutor(max_workers=LLM_WORKERS,
                            thread_name_prefix="judge") as pool:
        return [first, *pool.map(score, shortlist[1:])]


def run(use_cache: bool = False) -> dict:
    load_env()
    profile = load_profile()
    criteria = load_criteria()
    sources_cfg = load_sources()

    conn = db.connect()
    db.init_db(conn)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    db.start_run(conn, run_id)
    counts = {"sourced": 0, "new_jobs": 0, "filtered": 0, "scored": 0,
              "proposed": 0, "errors": 0}

    # The previous COMPLETED run's start (this run is recorded but unfinished, so
    # excluded): Adzuna pages back to it (ITEM-40); the judge shortlist treats
    # jobs first seen after it as fresh.
    prev_run_started = db.previous_run_started_at(conn, run_id)

    # ---- 1. SOURCE + 2. DEDUPE ----
    duplicates = 0  # content-dups parked at ingest (run_log has no column)
    # Sources fetch on worker threads, which can't use this connection, so the
    # stored-posting check reads a snapshot of the hashes taken before any fetch.
    known_hashes = db.all_job_hashes(conn)
    sources = build_sources(sources_cfg, use_cache=use_cache,
                            is_known=known_hashes.__contains__,
                            last_run_started=prev_run_started,
                            max_age_days=criteria.get("max_age_days"))
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS,
                            thread_name_prefix="fetch") as pool:
        fetches = [pool.submit(source.fetch) for source in sources]
        # Insert in sources.yaml order, not completion order: which copy of a
        # cross-posted job is kept (the rest park as 'duplicate') must not
        # depend on which site answered first.
        for source, fetch in zip(sources, fetches):
            try:
                jobs = fetch.result()
            except Exception as exc:
                log.error("source %s failed: %s", source.name, exc)
                counts["errors"] += 1
                continue
            for raw in jobs:
                counts["sourced"] += 1
                try:
                    inserted = db.insert_job(conn, raw)
                    if inserted == "duplicate":
                        duplicates += 1
                    elif inserted:
                        counts["new_jobs"] += 1
                except Exception as exc:
                    log.warning("insert failed: %s", exc)
            conn.commit()
    log.info("sourced=%d new=%d duplicate=%d",
             counts["sourced"], counts["new_jobs"], duplicates)

    # ---- 3. HARD FILTER ----
    for row in db.jobs_by_status(conn, "new"):
        ok, reason = passes(dict(row), criteria)
        if ok:
            db.update_job(conn, row["id"], status="ranked")
        else:
            counts["filtered"] += 1
            db.update_job(conn, row["id"], status="filtered_out", status_reason=reason)
    conn.commit()
    log.info("filtered_out=%d", counts["filtered"])

    # ---- 3.2 DIRECT-HIRE GATE: park (or, switched off, restore) staffing jobs --
    # Before embedding, so parked jobs cost no embed time or judge slots.
    parked, restored = staffing.apply_gate(conn, criteria)
    if parked or restored:
        log.info("direct-hire gate: parked=%d restored=%d (direct_hire_only=%s)",
                 parked, restored, bool(criteria.get("direct_hire_only")))

    # ---- 3.5 EXPIRE stale pool jobs ----
    expired = _expire_stale(conn, criteria)
    if expired:
        log.info("expired=%d (pool jobs older than %s days)",
                 expired, criteria.get("max_age_days"))

    # ---- 4. SCORE (embeddings/lexical recall, then optional LLM judge) ----
    scorer = Scorer(profile_comparison_text(profile),
                    prefer=criteria.get("scoring", "auto"))
    unscored = [r for r in db.jobs_by_status(conn, "ranked", "scored")
                if r["embed_score"] is None]
    scores = scorer.score_many(
        [r["description_clean"] or r["title"] or "" for r in unscored])
    for row, s in zip(unscored, scores):
        db.update_job(conn, row["id"], embed_score=s)
    conn.commit()

    llm = LLM()
    judge = Judge(llm, criteria.get("judge_model", "claude-sonnet-5-5"),
                  profile, criteria) if has_anthropic() else None
    llm_on = bool(judge and judge.available)

    if llm_on:
        shortlist_n = int(criteria.get("llm_shortlist", 15))
        pool = db.jobs_by_status(conn, "ranked", "scored")
        unjudged = [r for r in pool if r["llm_score"] is None]
        shortlist = _shortlist_fresh_first(
            unjudged, shortlist_n, prev_run_started)
        for row, res in zip(shortlist, _judge_all(judge, shortlist)):
            if res:
                counts["scored"] += 1
                db.update_job(
                    conn, row["id"], status="scored",
                    llm_score=max(0, min(100, int(res.get("fit_score", 0)))),
                    llm_musthaves_met=res.get("musthaves_met", []),
                    llm_missing=res.get("missing", []),
                    llm_rationale=res.get("rationale", ""),
                    employer_type=res.get("employer_type"),
                )
        conn.commit()
        # The judge's employer_type verdict can park a job the text rules
        # missed — before selection sees it.
        if criteria.get("direct_hire_only"):
            parked, _ = staffing.apply_gate(conn, criteria)
            if parked:
                log.info("direct-hire gate: judge verdicts parked %d more",
                         parked)

    # ---- 5. SELECT today's proposals ----
    target = int(criteria.get("daily_target", 4))
    min_score = int(criteria.get("min_score", 55))
    max_per_company = int(criteria.get("max_per_company", 1))
    pool = db.jobs_by_status(conn, "ranked", "scored")
    if llm_on:
        cands = [r for r in pool if r["llm_score"] is not None
                 and r["llm_score"] >= min_score]
        cands.sort(key=lambda r: r["llm_score"], reverse=True)
    else:
        # Lexical scores are relative, not absolute — rank and take the top N.
        cands = sorted(pool, key=lambda r: r["embed_score"] or 0, reverse=True)
    proposals = _select_diverse(cands, target, max_per_company)
    for row in proposals:
        db.update_job(conn, row["id"], status="proposed", proposed_in_run_id=run_id)
    conn.commit()
    counts["proposed"] = len(proposals)
    log.info("proposed=%d (llm=%s)", len(proposals), llm_on)

    # ---- 6. TAILOR ----
    tailor_model = criteria.get("tailor_model", "claude-opus-5-5")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    name_slug = _safe((profile.get("identity", {}) or {}).get("full_name", "Resume"))

    def tailor_one(job: dict) -> dict:
        """Tailor one proposal and return its DB fields. Runs on a worker
        thread, so it writes nothing shared: the DB update happens back in
        the loop below."""
        # Keyword table first (checker independent of writer). Returns
        # None in no-LLM mode or on a dead extraction call — which must
        # not cost the day's proposals, so we tailor without it.
        keywords = extract_keywords(llm, tailor_model, job)
        # Role-family emphasis: pure-code selection from JD signals.
        variant_name, variant_cfg, variant_signals = select_variant(
            profile, job)
        content, notes, missing_required = tailor_resume(
            llm, tailor_model, profile, job, keywords=keywords,
            variant_name=variant_name, variant=variant_cfg)

        # Job id is the folder; the filename is recruiter-facing.
        fname = f"{name_slug}_{_safe(job.get('title') or 'Role', 40)}.docx"
        resume_path = RESUME_DIR / today / str(job["id"]) / fname
        build_resume(content, resume_path)

        # Verify the artifact, not the dict. Structural problems mean the
        # resume is unusable — take the existing per-job error path.
        failures = structural_failures(resume_path, content)
        if failures:
            raise RuntimeError("resume failed verification: "
                               + "; ".join(failures))

        variant_blob = ({"name": variant_name, "signals": variant_signals}
                        if variant_name else None)
        if keywords:
            report = build_ats_report(
                keywords, extract_docx_text(resume_path), missing_required,
                distinctive_texts=distinctive_achievements(profile),
                variant=variant_blob)
        elif llm.available:
            report = {"error": "keyword extraction failed"}
        else:
            report = None  # no-LLM mode: no coverage to report

        cl = cover_letter(llm, tailor_model, profile, job)
        ans = screening_answers(profile)
        fields: dict = dict(
            status="tailored",
            tailored_resume_path=str(resume_path),
            cover_letter_text=cl or "",
            change_log=notes,
            screening_answers=ans,
        )
        if report is not None:
            fields["ats_report"] = report
        return fields

    with ThreadPoolExecutor(max_workers=LLM_WORKERS,
                            thread_name_prefix="tailor") as pool:
        tailoring = [pool.submit(tailor_one, dict(row)) for row in proposals]
        for row, done in zip(proposals, tailoring):
            try:
                db.update_job(conn, row["id"], **done.result())
            except Exception as exc:
                counts["errors"] += 1
                log.error("tailor failed for %s: %s", row["id"], exc)
                db.update_job(conn, row["id"], status="error", error_text=str(exc))
    conn.commit()

    # ---- 7. DIGEST ----
    tailored = [dict(r) for r in db.jobs_by_status(conn, "tailored")
                if r["proposed_in_run_id"] == run_id]
    if llm_on:
        tailored.sort(key=lambda j: j.get("llm_score") or 0, reverse=True)
    else:
        tailored.sort(key=lambda j: j.get("embed_score") or 0, reverse=True)
    _, digest_path = render_digest(tailored, run_id, scorer.mode, llm_on)

    db.finish_run(conn, run_id, **counts,
                  llm_usage=json.dumps(llm.usage) if llm.usage else None)
    conn.close()

    llm.log_usage_summary()
    log.info("DONE. Digest: %s", digest_path)
    return {"run_id": run_id, "digest": str(digest_path), "llm_on": llm_on,
            "scorer_mode": scorer.mode, "duplicates": duplicates, **counts}
