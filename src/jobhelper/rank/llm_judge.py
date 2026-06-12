"""Precise fit scoring with Claude (optional). Only the shortlist reaches this."""
from __future__ import annotations

import json
from typing import Any

from ..config import profile_comparison_text, years_of_experience
from ..llm import LLM

JUDGE_INSTRUCTIONS = (
    "You are a precise, skeptical job-fit screener. Given a candidate profile and "
    "a job posting, score how well the candidate fits THIS role from 0-100. "
    "Reward genuine overlap in required hard skills, seniority, and domain; "
    "penalize missing must-haves, wrong seniority, and location/visa mismatches. "
    "Be honest and calibrated: 80+ means a strong, apply-worthy match; 50-65 is "
    "marginal; below 40 is a poor fit. Return ONLY the structured result."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fit_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "musthaves_met": {"type": "array", "items": {"type": "string"},
                          "description": "Key requirements the candidate clearly meets."},
        "missing": {"type": "array", "items": {"type": "string"},
                    "description": "Important requirements the candidate lacks."},
        "rationale": {"type": "string",
                      "description": "One or two sentences explaining the score."},
    },
    "required": ["fit_score", "musthaves_met", "missing", "rationale"],
}


def _context(profile: dict, criteria: dict) -> str:
    must = {
        "target_titles": criteria.get("title_include_any", []),
        "required_keywords": criteria.get("keywords_any", []),
        "salary_floor": criteria.get("salary_floor", 0),
        "remote_required": criteria.get("remote_required", True),
    }
    return (
        f"CANDIDATE PROFILE\n"
        f"Years of experience: {years_of_experience(profile)}\n"
        f"Summary: {profile.get('summary', '')}\n\n"
        f"Skills & history:\n{profile_comparison_text(profile)}\n\n"
        f"WHAT THE CANDIDATE IS LOOKING FOR (must-haves):\n"
        f"{json.dumps(must, indent=2)}"
    )


class Judge:
    def __init__(self, llm: LLM, model: str, profile: dict, criteria: dict) -> None:
        self.llm = llm
        self.model = model
        self.system = LLM.cached_system(JUDGE_INSTRUCTIONS, _context(profile, criteria))

    @property
    def available(self) -> bool:
        return self.llm.available

    def score(self, job: dict) -> dict | None:
        user = (
            f"JOB POSTING\n"
            f"Title: {job.get('title', '')}\n"
            f"Company: {job.get('company', '')}\n"
            f"Location: {job.get('location', '')}\n\n"
            f"Description:\n{(job.get('description_clean') or '')[:6000]}"
        )
        return self.llm.structured(
            self.system, user, schema=SCHEMA, tool_name="job_fit",
            model=self.model, max_tokens=600,
        )
