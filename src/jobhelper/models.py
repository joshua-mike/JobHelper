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
    volatile_url: bool = False           # URL carries per-request tracking tokens

    @property
    def job_hash(self) -> str:
        # Prefer the canonical apply URL as identity; fall back to source+id —
        # also when the source's URLs embed per-request tokens (e.g. Adzuna's
        # se= signature), which would hash the same ad differently every fetch.
        if self.url and not self.volatile_url:
            return stable_hash(self.url)
        return stable_hash(self.source, self.source_job_id)

    @property
    def content_hash(self) -> str | None:
        # Content identity for cross-posting dedup: the same ad posted once per
        # city, or reposted under a fresh aggregator ad id, hashes identically.
        # None when the row is too thin to compare safely (blank fields would
        # collide unrelated jobs).
        if (self.company.strip() and self.title.strip()
                and self.description_clean.strip()):
            return stable_hash(self.company, self.title, self.description_clean)
        return None
