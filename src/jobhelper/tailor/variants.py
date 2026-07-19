"""Role-family variant presets (ITEM-15).

A variant is an EMPHASIS, not a content fork: it steers the summary angle and
the skills-group ordering, choosing among facts that already exist in the
profile. Selection is pure code (no LLM) so it works keyless and is
deterministic: a variant wins when at least MIN_SIGNAL_HITS of its distinct
signal terms appear (boundary-aware) in the job's title + description.
Evaluation order is the order variants appear in the profile, so the config
controls precedence; the variant marked `default: true` is the fallback.
"""
from __future__ import annotations

from .keywords import term_pattern

# Code constant by design (no new config knobs): one stray signal word must
# not flip the emphasis — "government clients" alone is not a cleared role.
MIN_SIGNAL_HITS = 2


def select_variant(profile: dict, job: dict,
                   ) -> tuple[str | None, dict | None, list[str]]:
    """Pick the variant for a job: (name, config, matched_signals).

    (None, None, []) when the profile defines no variants. Falls back to the
    variant marked `default: true` (matched_signals empty) when no signal
    threshold is met.
    """
    variants = profile.get("variants") or {}
    if not isinstance(variants, dict) or not variants:
        return None, None, []

    text = f"{job.get('title') or ''}\n{job.get('description_clean') or ''}"
    default_name, default_cfg = None, None
    for name, cfg in variants.items():
        if not isinstance(cfg, dict):
            continue
        if cfg.get("default") and default_name is None:
            default_name, default_cfg = name, cfg
        matched = []
        for sig in cfg.get("signals") or []:
            sig = str(sig).strip()
            if sig and term_pattern(sig).search(text):
                matched.append(sig)
        if len(matched) >= MIN_SIGNAL_HITS:
            return name, cfg, matched
    return default_name, default_cfg, []


def apply_group_order(content: dict, order: list[str] | None) -> None:
    """Reorder content['skill_groups'] in place: listed labels first (in the
    given order), everything else keeps its profile order afterwards."""
    groups = content.get("skill_groups")
    if not groups or not order:
        return
    rank = {label: i for i, label in enumerate(order)}
    content["skill_groups"] = sorted(
        groups, key=lambda g: (rank.get(g.get("label"), len(order)),))
