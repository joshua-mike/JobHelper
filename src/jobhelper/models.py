"""Normalized job record shared across sources and the DB."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .util import stable_hash


@dataclass
class RawJob:
    """A job after a source adapter has normalized it (pre-DB)."""
    source: str
    source_job_id: str
    url: str
    title: str
    company: str
    location: str = ""
    remote_type: str = "unknown"        # remote | hybrid | onsite | unknown
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    description_raw: str = ""
    description_clean: str = ""
    date_posted: str | None = None       # ISO string if known
    candidate_location: str = ""         # advertised location restriction, if any
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def job_hash(self) -> str:
        # Prefer the canonical apply URL as identity; fall back to source+id.
        if self.url:
            return stable_hash(self.url)
        return stable_hash(self.source, self.source_job_id)
