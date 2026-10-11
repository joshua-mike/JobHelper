"""Greenhouse public Job Board API (keyless).
GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
Pulls ALL of a company's published jobs; the hard filter drops non-remote ones.

NOTE: use boards-api.greenhouse.io (public, keyless). Do NOT switch this to
harvest.greenhouse.io — that's the employer Harvest API and requires a secret
key (HTTP 401 for outside applicants).

The cap counts NEW postings only and is split across boards by
JobSource._share_fetched (ITEM-39)."""
from __future__ import annotations

from typing import Callable

from ..models import RawJob
from ..util import get_logger, html_to_text
from .base import JobSource

log = get_logger()
BASE = "https://boards-api.greenhouse.io/v1/boards"

# A few companies host their Greenhouse board under an internal codename token,
# so deriving the display name from the token (token.title()) would be wrong or
# unrecognizable. Map those tokens to the real company name here.
_NAME_OVERRIDES = {
    "air": "Govini",   # Govini's board token is "air"
    "xai": "xAI",      # so the display name isn't the title-cased "Xai"
}


class GreenhouseSource(JobSource):
    name = "greenhouse"

    def __init__(self, fetcher, cap: int, tokens: list[str],
                 is_known: Callable[[str], bool] | None = None) -> None:
        super().__init__(fetcher, cap, is_known)
        self.tokens = tokens

    def fetch(self) -> list[RawJob]:
        return self._share_fetched(self.tokens, self._fetch_board)

    def _fetch_board(self, token: str) -> list[RawJob]:
        """Every posting on one board, stored or not; [] if the fetch fails."""
        url = f"{BASE}/{token}/jobs"
        try:
            data = self.fetcher.get_json(url, params={"content": "true"})
        except Exception as exc:
            log.warning("greenhouse[%s]: fetch failed: %s", token, exc)
            return []
        company = _NAME_OVERRIDES.get(token) or token.replace("-", " ").title()
        jobs: list[RawJob] = []
        for item in (data.get("jobs") or []):
            try:
                loc = (item.get("location") or {}).get("name", "") or ""
                remote = "remote" if "remote" in loc.lower() else "unknown"
                jobs.append(RawJob(
                    source=self.name,
                    source_job_id=str(item.get("id", "")),
                    url=item.get("absolute_url", ""),
                    title=item.get("title", ""),
                    company=company,
                    location=loc,
                    candidate_location=loc,
                    remote_type=remote,
                    description_raw=item.get("content", "") or "",
                    description_clean=html_to_text(item.get("content")),
                    date_posted=item.get("updated_at"),
                    tags=[token],
                    extra={"board_token": token},
                ))
            except Exception as exc:
                log.warning("greenhouse[%s]: bad record: %s", token, exc)
        return jobs
