"""Build the list of enabled JobSource adapters from config/sources.yaml."""
from __future__ import annotations

from typing import Any, Callable

from ..util import get_logger
from .adzuna import HOST as ADZUNA_HOST
from .adzuna import MIN_INTERVAL as ADZUNA_MIN_INTERVAL
from .adzuna import AdzunaSource
from .amazon import AmazonSource
from .arbeitnow import ArbeitnowSource
from .ashby import AshbySource
from .base import Fetcher, JobSource
from .greenhouse import GreenhouseSource
from .lever import LeverSource
from .microsoft import MicrosoftSource
from .remoteok import RemoteOKSource
from .remotive import RemotiveSource
from .smartrecruiters import SmartRecruitersSource
from .usajobs import USAJobsSource
from .workday import WorkdaySource

log = get_logger()

_AGGREGATORS = {
    "remotive": RemotiveSource,
    "arbeitnow": ArbeitnowSource,
    "remoteok": RemoteOKSource,
}


def build_sources(sources_cfg: dict[str, Any], use_cache: bool = False,
                  is_known: Callable[[str], bool] | None = None,
                  last_run_started: str | None = None,
                  max_age_days: int | None = None) -> list[JobSource]:
    """`is_known(job_hash)` says whether a posting is already stored. The
    multi-board adapters (Greenhouse, Lever, Ashby, SmartRecruiters, Workday)
    skip stored postings before they count toward the cap, and before the
    detail call where there is one. Adzuna skips them too (it has no cap).

    `last_run_started` (the previous completed run's start) and `max_age_days`
    tell Adzuna how far back to page (ITEM-40); without them it pages back
    30 days, bounded by its call budget."""
    cap = int(sources_cfg.get("per_source_cap", 400))
    delay = float(sources_cfg.get("request_delay_seconds", 1.0))
    # Adzuna's key allows 25 hits/min, stricter than `delay` once it pages.
    fetcher = Fetcher(delay=delay, use_cache=use_cache,
                      host_delays={ADZUNA_HOST: ADZUNA_MIN_INTERVAL})

    sources: list[JobSource] = []

    agg_cfg = sources_cfg.get("aggregators", {}) or {}
    for name, cls in _AGGREGATORS.items():
        if agg_cfg.get(name):
            sources.append(cls(fetcher, cap))

    ats_cfg = sources_cfg.get("ats", {}) or {}
    if ats_cfg.get("greenhouse"):
        sources.append(GreenhouseSource(fetcher, cap, list(ats_cfg["greenhouse"]),
                                        is_known=is_known))
    if ats_cfg.get("lever"):
        sources.append(LeverSource(fetcher, cap, list(ats_cfg["lever"]),
                                   is_known=is_known))
    if ats_cfg.get("ashby"):
        sources.append(AshbySource(fetcher, cap, list(ats_cfg["ashby"]),
                                   is_known=is_known))
    if ats_cfg.get("smartrecruiters"):
        sources.append(SmartRecruitersSource(fetcher, cap, list(ats_cfg["smartrecruiters"]),
                                             is_known=is_known))
    # Microsoft careers: the list items are SEARCH QUERIES, not company slugs.
    if ats_cfg.get("microsoft"):
        per_query = int(sources_cfg.get("microsoft_per_query", 40))
        sources.append(MicrosoftSource(fetcher, cap, list(ats_cfg["microsoft"]), per_query))
    # Workday: list of per-tenant {tenant, dc, site, company} dicts; searches scope the crawl.
    if ats_cfg.get("workday"):
        searches = list(sources_cfg.get("workday_searches", []) or [])
        per_search = int(sources_cfg.get("workday_per_search", 25))
        sources.append(WorkdaySource(fetcher, cap, list(ats_cfg["workday"]),
                                      searches, per_search, is_known=is_known))
    # Amazon careers: the list items are SEARCH QUERIES, not company slugs.
    if ats_cfg.get("amazon"):
        per_query = int(sources_cfg.get("amazon_per_query", 40))
        sources.append(AmazonSource(fetcher, cap, list(ats_cfg["amazon"]), per_query))
    # USAJOBS: the list items are SEARCH QUERIES; needs USAJOBS_API_KEY in .env
    # (the adapter skips itself with a log hint when the key is missing).
    if ats_cfg.get("usajobs"):
        per_query = int(sources_cfg.get("usajobs_per_query", 50))
        sources.append(USAJobsSource(fetcher, cap, list(ats_cfg["usajobs"]), per_query))
    # Adzuna: SEARCH QUERIES; needs ADZUNA_APP_ID + ADZUNA_APP_KEY in .env
    # (skips itself with a log hint when the keys are missing). Each query pages
    # back to the previous run; per_query bounds rows read per query and
    # max_calls the API calls per run. per_source_cap doesn't apply (ITEM-40).
    if ats_cfg.get("adzuna"):
        per_query = int(sources_cfg.get("adzuna_per_query", 500))
        max_calls = int(sources_cfg.get("adzuna_max_calls", 75))
        sources.append(AdzunaSource(fetcher, queries=list(ats_cfg["adzuna"]),
                                    per_query=per_query, max_calls=max_calls,
                                    is_known=is_known,
                                    last_run_started=last_run_started,
                                    max_age_days=max_age_days))

    log.info("Enabled sources: %s", ", ".join(s.name for s in sources) or "(none)")
    return sources
