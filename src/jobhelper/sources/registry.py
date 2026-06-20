"""Build the list of enabled JobSource adapters from config/sources.yaml."""
from __future__ import annotations

from typing import Any

from ..util import get_logger
from .arbeitnow import ArbeitnowSource
from .ashby import AshbySource
from .base import Fetcher, JobSource
from .greenhouse import GreenhouseSource
from .lever import LeverSource
from .microsoft import MicrosoftSource
from .remoteok import RemoteOKSource
from .remotive import RemotiveSource
from .smartrecruiters import SmartRecruitersSource
from .workday import WorkdaySource

log = get_logger()

_AGGREGATORS = {
    "remotive": RemotiveSource,
    "arbeitnow": ArbeitnowSource,
    "remoteok": RemoteOKSource,
}


def build_sources(sources_cfg: dict[str, Any], use_cache: bool = False) -> list[JobSource]:
    cap = int(sources_cfg.get("per_source_cap", 400))
    delay = float(sources_cfg.get("request_delay_seconds", 1.0))
    fetcher = Fetcher(delay=delay, use_cache=use_cache)

    sources: list[JobSource] = []

    agg_cfg = sources_cfg.get("aggregators", {}) or {}
    for name, cls in _AGGREGATORS.items():
        if agg_cfg.get(name):
            sources.append(cls(fetcher, cap))

    ats_cfg = sources_cfg.get("ats", {}) or {}
    if ats_cfg.get("greenhouse"):
        sources.append(GreenhouseSource(fetcher, cap, list(ats_cfg["greenhouse"])))
    if ats_cfg.get("lever"):
        sources.append(LeverSource(fetcher, cap, list(ats_cfg["lever"])))
    if ats_cfg.get("ashby"):
        sources.append(AshbySource(fetcher, cap, list(ats_cfg["ashby"])))
    if ats_cfg.get("smartrecruiters"):
        sources.append(SmartRecruitersSource(fetcher, cap, list(ats_cfg["smartrecruiters"])))
    # Microsoft careers: the list items are SEARCH QUERIES, not company slugs.
    if ats_cfg.get("microsoft"):
        per_query = int(sources_cfg.get("microsoft_per_query", 40))
        sources.append(MicrosoftSource(fetcher, cap, list(ats_cfg["microsoft"]), per_query))
    # Workday: list of per-tenant {tenant, dc, site, company} dicts; searches scope the crawl.
    if ats_cfg.get("workday"):
        searches = list(sources_cfg.get("workday_searches", []) or [])
        per_search = int(sources_cfg.get("workday_per_search", 25))
        sources.append(WorkdaySource(fetcher, cap, list(ats_cfg["workday"]),
                                      searches, per_search))

    log.info("Enabled sources: %s", ", ".join(s.name for s in sources) or "(none)")
    return sources
