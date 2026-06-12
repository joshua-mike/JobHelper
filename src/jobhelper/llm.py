"""Thin wrapper over the Anthropic SDK.

Everything here is optional: if the SDK isn't installed or ANTHROPIC_API_KEY is
unset, `LLM.available` is False and callers fall back to non-AI behavior. The
static profile is sent as a cache_control system block so repeated daily calls
are cheap.
"""
from __future__ import annotations

import json
import os
from typing import Any

from .util import get_logger

log = get_logger()

try:
    import anthropic  # type: ignore
    _SDK = True
except ImportError:
    _SDK = False


class LLM:
    def __init__(self) -> None:
        self._client = None
        if _SDK and os.environ.get("ANTHROPIC_API_KEY"):
            try:
                self._client = anthropic.Anthropic()
            except Exception as exc:  # pragma: no cover
                log.warning("Anthropic client init failed: %s", exc)

    @property
    def available(self) -> bool:
        return self._client is not None

    @staticmethod
    def cached_system(instructions: str, cached_context: str) -> list[dict[str, Any]]:
        """System prompt with the large, static `cached_context` marked cacheable."""
        return [
            {"type": "text", "text": instructions},
            {"type": "text", "text": cached_context,
             "cache_control": {"type": "ephemeral"}},
        ]

    def structured(self, system: list[dict] | str, user: str, *, schema: dict,
                   tool_name: str, model: str, max_tokens: int = 1024) -> dict | None:
        """Force a structured JSON result via a single-tool tool_choice."""
        if not self.available:
            return None
        try:
            msg = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                tools=[{"name": tool_name,
                        "description": f"Return the {tool_name} result.",
                        "input_schema": schema}],
                tool_choice={"type": "tool", "name": tool_name},
                messages=[{"role": "user", "content": user}],
            )
            for block in msg.content:
                if block.type == "tool_use":
                    return dict(block.input)
        except Exception as exc:
            log.warning("LLM.structured failed (%s): %s", model, exc)
        return None

    def text(self, system: list[dict] | str, user: str, *, model: str,
             max_tokens: int = 1024) -> str | None:
        if not self.available:
            return None
        try:
            msg = self._client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(b.text for b in msg.content if b.type == "text").strip()
        except Exception as exc:
            log.warning("LLM.text failed (%s): %s", model, exc)
        return None
