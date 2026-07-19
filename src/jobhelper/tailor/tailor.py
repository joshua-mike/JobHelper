"""Build a tailored (or passthrough) resume, cover letter, and screening answers.

Anti-hallucination design: company names, job titles, and dates are ALWAYS copied
verbatim from the profile. The LLM is only allowed to (a) reword/select bullets
from each job's own achievements, (b) write a summary, and (c) order skills that
already exist in the profile. Anything it invents is filtered out on assembly.
"""
from __future__ import annotations

import calendar
from typing import Any

from ..config import years_of_experience
from ..llm import LLM
from .keywords import term_pattern

# Longest allowed skills-line alias ("Amazon Web Services (AWS)" is 26 chars;
# anything much longer is the model padding, not mirroring).
DISPLAY_AS_MAX = 60

# ---- Date formatting ---------------------------------------------------------
def fmt_month(ym: Any) -> str:
    if not ym:
        return ""
    s = str(ym).strip()
    if s.lower() == "present":
        return "Present"
    try:
        parts = s.split("-")
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        return f"{calendar.month_name[month]} {year}"
    except (ValueError, IndexError):
        return s


# ---- Passthrough (no-LLM) resume from the profile ----------------------------
def passthrough_resume(profile: dict) -> dict:
    ident = profile.get("identity", {}) or {}
    skills_cfg = profile.get("skills", {}) or {}
    hard: list[str] = []
    groups: list[dict] = []  # [{"label": str|None, "skills": [names]}], profile order
    by_label: dict = {}
    for s in (skills_cfg.get("hard_skills") or []):
        if isinstance(s, dict):
            name, label = s.get("name"), (s.get("group") or None)
        else:
            name, label = str(s), None
        if not name:
            continue
        hard.append(name)
        if label not in by_label:
            by_label[label] = {"label": label, "skills": []}
            groups.append(by_label[label])
        by_label[label]["skills"].append(name)

    experience = []
    for job in profile.get("work_history", []) or []:
        bullets = [a.get("text") if isinstance(a, dict) else str(a)
                   for a in (job.get("achievements") or [])]
        experience.append({
            "company": job.get("company", ""),
            "title": job.get("title", ""),
            "location": job.get("location", ""),
            "start": fmt_month(job.get("start_date")),
            "end": fmt_month(job.get("end_date") or "Present"),
            "bullets": [b for b in bullets if b],
        })

    education = [{
        "institution": e.get("institution", ""),
        "degree": e.get("degree", ""),
        "field": e.get("field", ""),
        "grad": fmt_month(e.get("grad_date")),
    } for e in (profile.get("education") or [])]

    links = [v for v in (ident.get("linkedin_url"), ident.get("portfolio_url")) if v]
    content = {
        "name": ident.get("full_name", ""),
        "email": ident.get("email", ""),
        "phone": ident.get("phone", ""),
        "location": ident.get("city_state", ""),
        "links": links,
        "summary": profile.get("summary", ""),
        "skills": hard,
        "experience": experience,
        "education": education,
        "certifications": [c.get("name") if isinstance(c, dict) else str(c)
                           for c in (skills_cfg.get("certifications") or [])],
    }
    # Optional credentials line (clearance + certs) rendered directly under the
    # contact line — literal recruiter search tokens belong at the top (ITEM-13).
    if ident.get("credentials_line"):
        content["credentials"] = str(ident["credentials_line"]).strip()
    # Grouped skills only when at least one skill declares a group; otherwise the
    # renderer keeps the flat comma line.
    if any(g["label"] for g in groups):
        content["skill_groups"] = groups
    return content


# ---- LLM-tailored resume -----------------------------------------------------
TAILOR_INSTRUCTIONS = (
    "You tailor a resume to a specific job. You may ONLY use facts present in the "
    "candidate profile. Do NOT invent employers, titles, dates, metrics, or skills. "
    "For each job you receive numbered achievements; produce reworded/selected "
    "bullets drawn ONLY from that job's achievements. Write a 2-3 sentence summary "
    "aligned to the role. Order the candidate's existing skills by relevance to "
    "the posting. List concrete change notes.\n"
    "Keyword strategy (when a keyword table is provided): mirror the posting's "
    "EXACT wording wherever it is truthful for this candidate. Use acronym and "
    "expansion once each. Aim for 2-3 placements of each REQUIRED term: the "
    "summary, one evidence bullet, and the skills line — never more. NEVER place "
    "a keyword the profile has no evidence for; instead list JD-required terms "
    "the candidate genuinely lacks in missing_required (flag, don't fabricate). "
    "Make 60-80% of bullets follow: action verb + task containing the keyword + "
    "quantified outcome, using ONLY numbers already present in the achievements.\n"
    "Skills line: each entry may set display_as to mirror the JD — the acronym/"
    "expansion pair or the JD's exact phrasing ONLY (e.g. 'Amazon Web Services "
    "(AWS)' for 'AWS'). Never add versions, certifications, or proficiency levels.\n"
    "Embedding strategy (modern screeners score the natural language in context, "
    "not just keyword hits): write every bullet as a complete outcome sentence "
    "that names the skill in working context ('built REST APIs in ASP.NET Web "
    "API against Oracle'), never a keyword fragment or list. Achievements marked "
    "[DISTINCTIVE] are the candidate's memorable, verifiable specifics — keep at "
    "least one in the output essentially intact (light rewording only); they are "
    "what survives an AI summarizer. Use each quantified metric at most once "
    "across the whole resume — choose its strongest placement and drop repeats. "
    "The summary must state the target function in the posting's own vocabulary "
    "where the candidate's real work supports it; if the posting is ML/AI-"
    "adjacent, bridge the pivot by citing the candidate's in-progress ML "
    "certification from the profile. Avoid generic AI-resume phrasing "
    "('results-driven', 'proven track record', 'dynamic') — specific and "
    "verifiable beats polished and generic."
)

TAILOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "skills_order": {
            "type": "array",
            "description": "Subset/reorder of the candidate's EXISTING skills.",
            "items": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string",
                              "description": "A skill exactly as it appears in the profile."},
                    "display_as": {"type": "string",
                                   "description": "Optional JD-mirroring rendering; must contain the skill itself."},
                },
                "required": ["skill"],
            },
        },
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["index", "bullets"],
            },
        },
        "change_notes": {"type": "array", "items": {"type": "string"}},
        "missing_required": {
            "type": "array", "items": {"type": "string"},
            "description": "JD-required terms the candidate genuinely lacks.",
        },
    },
    "required": ["summary", "skills_order", "jobs", "change_notes",
                 "missing_required"],
}


def _keyword_block(keywords: list[dict]) -> str:
    rows = []
    for kw in sorted(keywords, key=lambda k: not k.get("required")):
        req = "REQUIRED" if kw.get("required") else "preferred"
        variants = ", ".join(kw.get("variants") or [])
        var = f" (variants: {variants})" if variants else ""
        rows.append(f"- [{req}] {kw.get('term', '')} [{kw.get('category', '')}]{var}")
    return ("KEYWORD TABLE FROM THE JOB DESCRIPTION (required first):\n"
            + "\n".join(rows))


def tailor_resume(llm: LLM, model: str, profile: dict, job: dict,
                  keywords: list[dict] | None = None,
                  ) -> tuple[dict, list[str], list[str]]:
    """Returns (content, change_notes, missing_required)."""
    base = passthrough_resume(profile)
    if not llm.available:
        return base, ["Tailoring skipped (no ANTHROPIC_API_KEY) — using full "
                      "profile resume."], []

    wh = profile.get("work_history", []) or []
    job_blocks = []
    for i, j in enumerate(wh):
        lines = []
        for a in (j.get("achievements") or []):
            if isinstance(a, dict):
                t, distinct = a.get("text"), bool(a.get("distinctive"))
            else:
                t, distinct = str(a), False
            if t:
                tag = "[DISTINCTIVE] " if distinct else ""
                lines.append(f"    - {tag}{t}")
        listed = "\n".join(lines)
        job_blocks.append(f"[index {i}] {j.get('title','')} @ {j.get('company','')}\n{listed}")
    profile_skills = base["skills"]

    # The keyword table is the distilled JD (checker's view); the raw excerpt
    # stays capped at 5k as before.
    keyword_part = f"{_keyword_block(keywords)}\n\n" if keywords else ""
    user = (
        f"JOB POSTING\nTitle: {job.get('title','')}\nCompany: {job.get('company','')}\n\n"
        f"{(job.get('description_clean') or '')[:5000]}\n\n"
        f"{keyword_part}"
        f"CANDIDATE SUMMARY: {profile.get('summary','')}\n\n"
        f"CANDIDATE SKILLS (use only these): {', '.join(profile_skills)}\n\n"
        f"CANDIDATE JOBS AND THEIR ACHIEVEMENTS (reword/select only from each):\n"
        + "\n\n".join(job_blocks)
    )
    result = llm.structured(
        TAILOR_INSTRUCTIONS, user, schema=TAILOR_SCHEMA,
        tool_name="tailored_resume", model=model, max_tokens=1800,
    )
    if not result:
        return base, ["Tailoring failed — using full profile resume."], []

    # --- Assemble, enforcing truthfulness ---
    content = dict(base)
    if result.get("summary"):
        content["summary"] = result["summary"].strip()

    # Skills: keep only ones that actually exist in the profile. display_as may
    # mirror the JD's wording but must contain the skill as a token (boundary-
    # aware, so 'Amazon Web Services (AWS)' passes for 'AWS' while 'JavaScript'
    # fails for 'Java'); invalid aliases silently fall back to the plain name.
    valid = {s.lower(): s for s in profile_skills}
    ordered: list[str] = []
    used: set[str] = set()
    alias_notes: list[str] = []
    shown_by_canon: dict[str, str] = {}   # canon.lower() -> rendered name
    for entry in result.get("skills_order", []):
        if isinstance(entry, dict):
            skill = str(entry.get("skill") or "").strip()
            display = str(entry.get("display_as") or "").strip()
        else:
            skill, display = str(entry).strip(), ""
        canon = valid.get(skill.lower())
        if not canon or canon.lower() in used:
            continue
        used.add(canon.lower())
        shown = canon
        if display and display.lower() != canon.lower():
            if len(display) <= DISPLAY_AS_MAX and term_pattern(canon).search(display):
                shown = display
                alias_notes.append(f"displayed '{canon}' as '{display}'")
        shown_by_canon[canon.lower()] = shown
        ordered.append(shown)
    # Append any profile skills the model dropped, so nothing real is lost.
    for s in profile_skills:
        if s.lower() not in used:
            shown_by_canon[s.lower()] = s
            ordered.append(s)
    content["skills"] = ordered

    # Rebuild skill groups (ITEM-13): group membership and group order come from
    # the profile; order WITHIN each group follows the tailored relevance order.
    if base.get("skill_groups"):
        pos = {shown.lower(): i for i, shown in enumerate(ordered)}

        def _rank(canon: str) -> int:
            shown = shown_by_canon.get(canon.lower(), canon)
            return pos.get(shown.lower(), len(ordered))

        content["skill_groups"] = [
            {"label": g.get("label"),
             "skills": [shown_by_canon.get(c.lower(), c)
                        for c in sorted(g.get("skills") or [], key=_rank)]}
            for g in base["skill_groups"]
        ]

    # Bullets: company/title/dates stay fixed; only bullets come from the model.
    by_index = {jb.get("index"): jb.get("bullets", []) for jb in result.get("jobs", [])}
    new_exp = []
    for i, exp in enumerate(base["experience"]):
        e = dict(exp)
        model_bullets = [b.strip() for b in (by_index.get(i) or []) if b and b.strip()]
        if model_bullets:
            e["bullets"] = model_bullets
        new_exp.append(e)
    content["experience"] = new_exp

    notes = list(result.get("change_notes", [])) + alias_notes
    missing_required = [s for s in (str(m).strip() for m in
                                    result.get("missing_required") or []) if s]
    return content, notes, missing_required


def distinctive_achievements(profile: dict) -> list[str]:
    """Texts of achievements flagged distinctive (FR-5.2) — the verifier checks
    that at least one survives tailoring essentially intact."""
    out: list[str] = []
    for job in profile.get("work_history", []) or []:
        for a in job.get("achievements") or []:
            if isinstance(a, dict) and a.get("distinctive") and a.get("text"):
                out.append(str(a["text"]))
    return out


# ---- Cover letter (LLM only) -------------------------------------------------
COVER_INSTRUCTIONS = (
    "Write a concise, specific cover letter (~3 short paragraphs). Ground it in 1-2 "
    "REAL achievements from the profile and a genuine, specific reason this role/"
    "company fits. No invented facts. Avoid AI clichés ('delve', 'I am writing to "
    "express'). Natural, varied sentences in the candidate's voice. Plain text only."
)


def cover_letter(llm: LLM, model: str, profile: dict, job: dict) -> str | None:
    if not llm.available:
        return None
    user = (
        f"Candidate: {profile.get('identity',{}).get('full_name','')}\n"
        f"Summary: {profile.get('summary','')}\n"
        f"Role: {job.get('title','')} at {job.get('company','')}\n\n"
        f"Job description:\n{(job.get('description_clean') or '')[:3500]}"
    )
    return llm.text(COVER_INSTRUCTIONS, user, model=model, max_tokens=600)


# ---- Screening / knockout answers (no LLM needed) ----------------------------
def screening_answers(profile: dict) -> dict[str, Any]:
    ident = profile.get("identity", {}) or {}
    comp = profile.get("compensation", {}) or {}
    eeo = profile.get("eeo", {}) or {}
    yrs = years_of_experience(profile)
    return {
        "years_of_experience": yrs,
        "work_authorization": ident.get("work_authorization_status", ""),
        "requires_sponsorship": ident.get("requires_sponsorship", None),
        "willing_to_relocate": ident.get("willing_to_relocate", None),
        "earliest_start_date": ident.get("earliest_start_date", ""),
        "notice_period": ident.get("notice_period", ""),
        "desired_salary": (
            f"{comp.get('desired_salary_min','')}-{comp.get('desired_salary_max','')} "
            f"{comp.get('currency','')}".strip()
        ),
        "salary_negotiable": comp.get("salary_negotiable", None),
        "eeo": eeo,
    }
