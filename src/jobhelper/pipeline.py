"""The daily pipeline: source -> dedupe -> filter -> score -> select -> tailor -> digest.

Each stage is gated on the status state machine and safe to re-run. Per-job errors
are isolated (the row is marked 'error' and the batch continues).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from . import db
from .config import (has_anthropic, load_criteria, load_env, load_profile,
                     load_sources, profile_comparison_text)
from .digest import render_digest
from .llm import LLM
from .rank import Judge, Scorer, passes
from .sources import build_sources
from .tailor import (build_ats_report, build_resume, cover_letter,
                     distinctive_achievements, extract_docx_text,
                     extract_keywords, screening_answers, select_variant,
                     structural_failures, tailor_resume)
from .util import RESUME_DIR, get_logger

log = get_logger()


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

    # ---- 1. SOURCE + 2. DEDUPE ----
    duplicates = 0  # content-dups parked at ingest (run_log has no column)
    for source in build_sources(sources_cfg, use_cache=use_cache):
        try:
            jobs = source.fetch()
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

    # ---- 4. SCORE (embeddings/lexical recall, then optional LLM judge) ----
    scorer = Scorer(profile_comparison_text(profile),
                    prefer=criteria.get("scoring", "auto"))
    pool = db.jobs_by_status(conn, "ranked", "scored")
    for row in pool:
        if row["embed_score"] is None:
            s = scorer.score(row["description_clean"] or row["title"] or "")
            db.update_job(conn, row["id"], embed_score=s)
    conn.commit()

    llm = LLM()
    judge = Judge(llm, criteria.get("judge_model", "claude-sonnet-4-6"),
                  profile, criteria) if has_anthropic() else None
    llm_on = bool(judge and judge.available)

    if llm_on:
        shortlist_n = int(criteria.get("llm_shortlist", 15))
        pool = db.jobs_by_status(conn, "ranked", "scored")
        shortlist = sorted(
            [r for r in pool if r["llm_score"] is None],
            key=lambda r: r["embed_score"] or 0, reverse=True,
        )[:shortlist_n]
        for row in shortlist:
            try:
                res = judge.score(dict(row))
            except Exception as exc:
                log.warning("judge failed for %s: %s", row["id"], exc)
                res = None
            if res:
                counts["scored"] += 1
                db.update_job(
                    conn, row["id"], status="scored",
                    llm_score=int(res.get("fit_score", 0)),
                    llm_musthaves_met=res.get("musthaves_met", []),
                    llm_missing=res.get("missing", []),
                    llm_rationale=res.get("rationale", ""),
                )
        conn.commit()

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
    tailor_model = criteria.get("tailor_model", "claude-opus-4-8")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    name_slug = _safe((profile.get("identity", {}) or {}).get("full_name", "Resume"))
    for row in proposals:
        job = dict(row)
        try:
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
            resume_path = RESUME_DIR / today / str(row["id"]) / fname
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
            db.update_job(conn, row["id"], **fields)
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

    db.finish_run(conn, run_id, **counts)
    conn.close()

    log.info("DONE. Digest: %s", digest_path)
    return {"run_id": run_id, "digest": str(digest_path), "llm_on": llm_on,
            "scorer_mode": scorer.mode, "duplicates": duplicates, **counts}
