"""Render the daily Markdown digest of proposed jobs."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from ..util import DIGEST_DIR


def _loads(v, default):
    if not v:
        return default
    try:
        return json.loads(v) if isinstance(v, str) else v
    except (json.JSONDecodeError, TypeError):
        return default


def _fmt_screening(ans: dict[str, Any]) -> str:
    if not ans:
        return ""
    lines = [
        f"- **Years of experience:** {ans.get('years_of_experience','')}",
        f"- **Work authorization:** {ans.get('work_authorization','')}",
        f"- **Requires sponsorship:** {ans.get('requires_sponsorship','')}",
        f"- **Willing to relocate:** {ans.get('willing_to_relocate','')}",
        f"- **Earliest start:** {ans.get('earliest_start_date','')}",
        f"- **Desired salary:** {ans.get('desired_salary','')} "
        f"(negotiable: {ans.get('salary_negotiable','')})",
    ]
    return "\n".join(lines)


def render_digest(jobs: list[dict], run_id: str, scorer_mode: str,
                  llm_on: bool) -> tuple[str, Path]:
    today = date.today().isoformat()
    out: list[str] = []
    out.append(f"# JobHelper — {today}")
    out.append("")
    out.append(f"**{len(jobs)} proposed roles**  ·  scoring: `{scorer_mode}`  ·  "
               f"AI tailoring: `{'on' if llm_on else 'off'}`  ·  run `{run_id}`")
    out.append("")
    if not llm_on:
        out.append("> ℹ️ No `ANTHROPIC_API_KEY` set — scores are lexical and resumes "
                   "are the full-profile version. Add a key to enable Claude scoring "
                   "and per-job tailoring.")
        out.append("")

    # Screening answers are identical across jobs; show once.
    if jobs:
        ans = _loads(jobs[0].get("screening_answers"), {})
        if ans:
            out.append("## Your standard answers (copy/paste into forms)")
            out.append(_fmt_screening(ans))
            out.append("")

    out.append("---")
    for i, j in enumerate(jobs, 1):
        score = j.get("llm_score")
        score = score if score is not None else round((j.get("embed_score") or 0) * 100)
        out.append("")
        out.append(f"## {i}. {j.get('title','')} — {j.get('company','')}  ·  score {score}")
        loc = j.get("location") or j.get("candidate_location") or ""
        out.append(f"*{loc}*  ·  source: `{j.get('source','')}`")
        out.append("")
        out.append(f"**Apply:** {j.get('url','')}")
        out.append("")
        if j.get("llm_rationale"):
            out.append(f"**Why it matched:** {j['llm_rationale']}")
        met = _loads(j.get("llm_musthaves_met"), [])
        missing = _loads(j.get("llm_missing"), [])
        if met:
            out.append(f"- ✅ Meets: {', '.join(met)}")
        if missing:
            out.append(f"- ⚠️ Gaps: {', '.join(missing)}")
        out.append("")
        if j.get("tailored_resume_path"):
            out.append(f"**Tailored resume:** `{j['tailored_resume_path']}`")
        notes = _loads(j.get("change_log"), [])
        if notes:
            out.append("  - " + "\n  - ".join(notes))
        out.append("")
        if j.get("cover_letter_text"):
            out.append("**Cover letter draft:**")
            out.append("")
            out.append("> " + j["cover_letter_text"].replace("\n", "\n> "))
        out.append("")
        out.append("---")

    md = "\n".join(out)
    path = DIGEST_DIR / f"digest-{today}.md"
    path.write_text(md, encoding="utf-8")
    return md, path
