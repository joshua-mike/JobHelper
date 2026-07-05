"""Pydantic validation for the three config YAMLs (Settings UI save path).

Full key parity with the files. Every field is optional and extra keys are
allowed everywhere: validation is a shape/sanity gate, not a whitelist —
unknown keys the user hand-added must survive a UI save (the store merges
only what the client sent and never deletes). Values are intentionally NOT
normalized (no lowercasing/de-duping): board slugs are case-sensitive.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_YM_RE = re.compile(r"^\d{4}(-(?P<m>\d{2}))?(-\d{2})?$")


def _check_ym(value: Any, *, label: str) -> Any:
    """Accept '', 'Present', YYYY, YYYY-MM, YYYY-MM-DD (month 01-12)."""
    if value is None:
        return value
    s = str(value).strip()
    if s == "" or s.lower() == "present":
        return value
    m = _YM_RE.match(s)
    if not m or (m.group("m") and not 1 <= int(m.group("m")) <= 12):
        raise ValueError(
            f"{label} must be YYYY-MM (or YYYY / 'Present'), got {value!r}")
    return value


class _Permissive(BaseModel):
    model_config = ConfigDict(extra="allow")


# ---- profile.yaml ---------------------------------------------------------------
class Identity(_Permissive):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    city_state: str | None = None
    linkedin_url: str | None = None
    portfolio_url: str | None = None
    work_authorization_status: str | None = None
    requires_sponsorship: bool | None = None
    willing_to_relocate: bool | None = None
    earliest_start_date: str | None = None
    notice_period: str | None = None


class Compensation(_Permissive):
    desired_salary_min: int | None = Field(None, ge=0)
    desired_salary_max: int | None = Field(None, ge=0)
    currency: str | None = None
    salary_negotiable: bool | None = None

    @model_validator(mode="after")
    def _min_le_max(self):
        lo, hi = self.desired_salary_min, self.desired_salary_max
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("desired_salary_min is greater than desired_salary_max")
        return self


class Achievement(_Permissive):
    text: str = Field(min_length=1)
    skills_used: list[str] | None = None
    verified: bool | None = None


class WorkEntry(_Permissive):
    company: str = Field(min_length=1)
    title: str = Field(min_length=1)
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    employment_type: str | None = None
    summary: str | None = None
    achievements: list[Achievement | str] | None = None

    @field_validator("start_date", "end_date")
    @classmethod
    def _dates(cls, v, info):
        return _check_ym(v, label=info.field_name)


class EducationEntry(_Permissive):
    institution: str = Field(min_length=1)
    degree: str | None = None
    field: str | None = None
    grad_date: str | None = None
    gpa: float | str | None = None

    @field_validator("grad_date")
    @classmethod
    def _dates(cls, v, info):
        return _check_ym(v, label=info.field_name)


class HardSkill(_Permissive):
    name: str = Field(min_length=1)
    years: float | None = Field(None, ge=0)
    proficiency: str | None = None


class Certification(_Permissive):
    name: str = Field(min_length=1)
    issuer: str | None = None
    date: str | None = None
    expiry: str | int | None = None


class Skills(_Permissive):
    hard_skills: list[HardSkill | str] | None = None
    soft_skills: list[str] | None = None
    certifications: list[Certification | str] | None = None
    languages: list[str] | None = None


class Eeo(_Permissive):
    race_ethnicity: str | None = None
    gender: str | None = None
    veteran_status: str | None = None
    disability_status: str | None = None


class ProfileConfig(_Permissive):
    identity: Identity | None = None
    compensation: Compensation | None = None
    summary: str | None = None
    work_history: list[WorkEntry] | None = None
    education: list[EducationEntry] | None = None
    skills: Skills | None = None
    eeo: Eeo | None = None
    qa_bank: dict[str, str] | None = None


# ---- criteria.yaml --------------------------------------------------------------
class CriteriaConfig(_Permissive):
    daily_target: int | None = Field(None, ge=1, le=100)
    max_per_company: int | None = Field(None, ge=1, le=100)
    scoring: Literal["auto", "semantic", "lexical"] | None = None
    llm_shortlist: int | None = Field(None, ge=1, le=200)
    min_score: int | None = Field(None, ge=0, le=100)
    title_include_any: list[str] | None = None
    title_exclude_any: list[str] | None = None
    keywords_any: list[str] | None = None
    keywords_exclude: list[str] | None = None
    remote_required: bool | None = None
    onsite_ok_companies: list[str] | None = None
    allowed_location_tokens: list[str] | None = None
    salary_floor: int | None = Field(None, ge=0)
    exclude_companies: list[str] | None = None
    max_age_days: int | None = Field(None, ge=1, le=365)
    judge_model: str | None = Field(None, min_length=1)
    tailor_model: str | None = Field(None, min_length=1)


# ---- sources.yaml ---------------------------------------------------------------
class WorkdayEntry(_Permissive):
    tenant: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    dc: str = Field(min_length=1, pattern=r"^[A-Za-z0-9]+$")
    site: str = Field(min_length=1)
    company: str = Field(min_length=1)


def _prune_blank(items: list[str] | None) -> list[str] | None:
    """Drop whitespace-only rows (an empty add-row in the UI isn't an error)."""
    if items is None:
        return None
    return [s for s in items if s and s.strip()]


class AtsConfig(_Permissive):
    greenhouse: list[str] | None = None
    lever: list[str] | None = None
    ashby: list[str] | None = None
    smartrecruiters: list[str] | None = None
    microsoft: list[str] | None = None  # search queries, not slugs
    amazon: list[str] | None = None     # search queries, not slugs
    usajobs: list[str] | None = None    # search queries, not slugs (keyed source)
    adzuna: list[str] | None = None     # search queries, not slugs (keyed source)
    workday: list[WorkdayEntry] | None = None

    _prune = field_validator(
        "greenhouse", "lever", "ashby", "smartrecruiters", "microsoft", "amazon",
        "usajobs", "adzuna"
    )(_prune_blank)


class SourcesConfig(_Permissive):
    aggregators: dict[str, bool] | None = None
    ats: AtsConfig | None = None
    request_delay_seconds: float | None = Field(None, ge=0, le=60)
    per_source_cap: int | None = Field(None, ge=1, le=10000)
    microsoft_per_query: int | None = Field(None, ge=1, le=500)
    amazon_per_query: int | None = Field(None, ge=1, le=500)
    usajobs_per_query: int | None = Field(None, ge=1, le=500)
    adzuna_per_query: int | None = Field(None, ge=1, le=50)
    workday_searches: list[str] | None = None
    workday_per_search: int | None = Field(None, ge=1, le=500)

    _prune = field_validator("workday_searches")(_prune_blank)
