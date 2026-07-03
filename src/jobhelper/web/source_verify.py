"""Live-check one sources.yaml entry using the real adapters, scaled down.

Reuses the actual JobSource classes (same URLs, headers, parsing) so a green
check here means the daily run will work — but with tiny caps, no cache, and
a single retry so a click stays cheap: one board request for the list-based
ATSes, a handful for the search-based ones (Microsoft/Amazon/Workday fetch
per-job details).

The adapters deliberately swallow per-board HTTP errors (a bad slug must not
kill a daily run), so a failure usually surfaces here as 0 jobs rather than
an exception — the message says so.
"""
from __future__ import annotations

from typing import Any

from ..sources.amazon import AmazonSource
from ..sources.arbeitnow import ArbeitnowSource
from ..sources.ashby import AshbySource
from ..sources.base import Fetcher, JobSource
from ..sources.greenhouse import GreenhouseSource
from ..sources.lever import LeverSource
from ..sources.microsoft import MicrosoftSource
from ..sources.remoteok import RemoteOKSource
from ..sources.remotive import RemotiveSource
from ..sources.smartrecruiters import SmartRecruitersSource
from ..sources.workday import WorkdaySource

AGGREGATOR_KINDS = ("remotive", "arbeitnow", "remoteok")
TOKEN_KINDS = ("greenhouse", "lever", "ashby", "smartrecruiters",
               "microsoft", "amazon")
ALL_KINDS = AGGREGATOR_KINDS + TOKEN_KINDS + ("workday",)

_CAP = 50          # plenty to prove a board is alive, small enough to stay quick
_QUERY_CAP = 5     # search-based sources fetch a detail page per hit — keep tiny
_SAMPLE = 3


def _build(kind: str, token: str | None, entry: dict[str, Any] | None,
           searches: list[str] | None, fetcher: Fetcher) -> JobSource:
    if kind == "remotive":
        return RemotiveSource(fetcher, _CAP)
    if kind == "arbeitnow":
        return ArbeitnowSource(fetcher, _CAP)
    if kind == "remoteok":
        return RemoteOKSource(fetcher, _CAP)
    if kind == "greenhouse":
        return GreenhouseSource(fetcher, _CAP, [token])
    if kind == "lever":
        return LeverSource(fetcher, _CAP, [token])
    if kind == "ashby":
        return AshbySource(fetcher, _CAP, [token])
    if kind == "smartrecruiters":
        return SmartRecruitersSource(fetcher, _CAP, [token])
    if kind == "microsoft":
        return MicrosoftSource(fetcher, _QUERY_CAP, [token], _QUERY_CAP)
    if kind == "amazon":
        return AmazonSource(fetcher, _QUERY_CAP, [token], _QUERY_CAP)
    if kind == "workday":
        # One search term is enough to prove the tenant/dc/site triple works.
        terms = [searches[0]] if searches else ["software engineer"]
        return WorkdaySource(fetcher, _QUERY_CAP, [entry], terms, _QUERY_CAP)
    raise ValueError(f"Unknown source kind: {kind}")


def verify(kind: str, token: str | None = None,
           entry: dict[str, Any] | None = None,
           searches: list[str] | None = None) -> dict[str, Any]:
    fetcher = Fetcher(delay=0.2, timeout=15.0, use_cache=False, max_retries=1)
    try:
        source = _build(kind, token, entry, searches, fetcher)
        jobs = source.fetch()
    except Exception as exc:
        return {"ok": False, "count": 0, "sample": [], "company": None,
                "message": f"Fetch failed: {exc}"}
    finally:
        fetcher.close()

    count = len(jobs)
    if count == 0:
        hint = ("no results for this query" if kind in ("microsoft", "amazon")
                else "check the slug (they're case-sensitive) — or the board is empty")
        return {"ok": False, "count": 0, "sample": [], "company": None,
                "message": f"0 jobs returned — {hint}."}
    capped = count >= (source.cap if kind not in ("microsoft", "amazon", "workday")
                       else _QUERY_CAP)
    return {
        "ok": True,
        "count": count,
        "sample": [j.title for j in jobs[:_SAMPLE] if j.title],
        "company": jobs[0].company or None,
        "message": f"{count}{'+' if capped else ''} job(s) live",
    }
