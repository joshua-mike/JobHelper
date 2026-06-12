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
    hard = [s.get("name") if isinstance(s, dict) else str(s)
            for s in (skills_cfg.get("hard_skills") or [])]

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
    return {
        "name": ident.get("full_name", ""),
        "email": ident.get("email", ""),
        "phone": ident.get("phone", ""),
        "location": ident.get("city_state", ""),
        "links": links,
        "summary": profile.get("summary", ""),
        "skills": [s for s in hard if s],
        "experience": experience,
        "education": education,
        "certifications": [c.get("name") if isinstance(c, dict) else str(c)
                           for c in (skills_cfg.get("certifications") or [])],
    }


# ---- LLM-tailored resume -----------------------------------------------------
TAILOR_INSTRUCTIONS = (
    "You tailor a resume to a specific job. You may ONLY use facts present in the "
    "candidate profile. Do NOT invent employers, titles, dates, metrics, or skills. "
    "For each job you receive numbered achievements; produce reworded/selected "
    "bullets drawn ONLY from that job's achievements, mirroring the job posting's "
    "terminology where truthful (action verb + task + quantified result). Write a "
    "2-3 sentence summary aligned to the role. Order the candidate's existing skills "
    "by relevance to the posting. List concrete change notes."
)

TAILOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "skills_order": {"type": "array", "items": {"type": "string"},
                         "description": "Subset/reorder of the candidate's EXISTING skills."},
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
    },
    "required": ["summary", "skills_order", "jobs", "change_notes"],
}


def tailor_resume(llm: LLM, model: str, profile: dict, job: dict) -> tuple[dict, list[str]]:
    base = passthrough_resume(profile)
    if not llm.available:
        return base, ["Tailoring skipped (no ANTHROPIC_API_KEY) — using full profile resume."]

    wh = profile.get("work_history", []) or []
    job_blocks = []
    for i, j in enumerate(wh):
        achs = [a.get("text") if isinstance(a, dict) else str(a)
                for a in (j.get("achievements") or [])]
        listed = "\n".join(f"    - {t}" for t in achs)
        job_blocks.append(f"[index {i}] {j.get('title','')} @ {j.get('company','')}\n{listed}")
    profile_skills = base["skills"]

    user = (
        f"JOB POSTING\nTitle: {job.get('title','')}\nCompany: {job.get('company','')}\n\n"
        f"{(job.get('description_clean') or '')[:5000]}\n\n"
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
        return base, ["Tailoring failed — using full profile resume."]

    # --- Assemble, enforcing truthfulness ---
    content = dict(base)
    if result.get("summary"):
        content["summary"] = result["summary"].strip()

    # Skills: keep only ones that actually exist in the profile.
    valid = {s.lower(): s for s in profile_skills}
    ordered = [valid[s.lower()] for s in result.get("skills_order", []) if s.lower() in valid]
    # Append any profile skills the model dropped, so nothing real is lost.
    for s in profile_skills:
        if s not in ordered:
            ordered.append(s)
    content["skills"] = ordered

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

    return content, list(result.get("change_notes", []))


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
