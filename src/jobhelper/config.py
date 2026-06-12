"""Load .env and the YAML config files (profile, criteria, sources)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .util import CONFIG_DIR, get_logger

log = get_logger()


def load_env(root_env: Path | None = None) -> None:
    """Minimal .env loader (no external dep). Does not overwrite real env vars."""
    env_path = root_env or (CONFIG_DIR.parent / ".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"Missing config file: {path}. "
            f"(Did you copy profile.example.yaml -> profile.yaml?)"
        )
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_profile() -> dict[str, Any]:
    path = CONFIG_DIR / "profile.yaml"
    if not path.exists():
        raise FileNotFoundError(
            "config/profile.yaml not found. Copy config/profile.example.yaml to "
            "config/profile.yaml and fill in your real details."
        )
    return _load_yaml("profile.yaml")


def load_criteria() -> dict[str, Any]:
    return _load_yaml("criteria.yaml")


def load_sources() -> dict[str, Any]:
    return _load_yaml("sources.yaml")


# ---- Profile-derived helpers -------------------------------------------------
def profile_comparison_text(profile: dict[str, Any]) -> str:
    """Flatten the profile into one text blob for lexical/semantic scoring."""
    parts: list[str] = []
    parts.append(profile.get("summary", ""))
    skills = profile.get("skills", {}) or {}
    for hs in skills.get("hard_skills", []) or []:
        parts.append(hs.get("name", "") if isinstance(hs, dict) else str(hs))
    parts.extend(skills.get("soft_skills", []) or [])
    for job in profile.get("work_history", []) or []:
        parts.append(job.get("title", ""))
        parts.append(job.get("summary", ""))
        for ach in job.get("achievements", []) or []:
            parts.append(ach.get("text", "") if isinstance(ach, dict) else str(ach))
    return "\n".join(p for p in parts if p)


def years_of_experience(profile: dict[str, Any]) -> float:
    """Sum of work_history durations in years (rough; counts overlaps once-ish)."""
    from datetime import date

    total_months = 0
    for job in profile.get("work_history", []) or []:
        start = _parse_ym(job.get("start_date"))
        end_raw = job.get("end_date")
        end = date.today() if (not end_raw or str(end_raw).lower() == "present") \
            else _parse_ym(end_raw)
        if start and end and end >= start:
            total_months += (end.year - start.year) * 12 + (end.month - start.month)
    return round(total_months / 12.0, 1)


def _parse_ym(value) -> "object | None":
    from datetime import date
    if not value:
        return None
    s = str(value).strip()
    try:
        parts = s.split("-")
        return date(int(parts[0]), int(parts[1]) if len(parts) > 1 else 1, 1)
    except (ValueError, IndexError):
        return None


def has_anthropic() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
