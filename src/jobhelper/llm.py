"""Thin wrapper over the Anthropic SDK.

Everything here is optional: if the SDK isn't installed or ANTHROPIC_API_KEY is
unset, `LLM.available` is False and callers fall back to non-AI behavior. The
static profile is sent as a cache_control system block so repeated daily calls
are cheap.

Structured results use `output_config.format` (JSON schema), not a forced
`tool_choice` — the 5.5 models reject forced tool use with a 400. Thinking is
always on for those models and thinking tokens count against `max_tokens`, so
the default ceiling is generous; `effort` is the cost lever. Every call's token
usage is logged and accumulated in `LLM.usage` for per-run comparison.
"""
from __future__ import annotations

import copy
import json
import os
from collections import defaultdict
from typing import Any

from .util import get_logger

log = get_logger()

try:
    import anthropic  # type: ignore
    _SDK = True
except ImportError:
    _SDK = False

# Non-streaming ceiling: room for thinking + answer while staying under SDK
# HTTP timeouts. Unused headroom isn't billed.
DEFAULT_MAX_TOKENS = 16000

# Keywords structured outputs don't accept; dropped before sending.
_UNSUPPORTED_SCHEMA_KEYS = {"minimum", "maximum", "exclusiveMinimum",
                            "exclusiveMaximum", "multipleOf", "minLength",
                            "maxLength", "minItems", "maxItems"}

# USD per million tokens: (input, output, cache read, cache write). Cache
# writes use the 5-minute TTL rate (1.25x input). Used only for the dashboard's
# estimated run cost; unknown models show tokens without a cost.
MODEL_PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-opus-5": (5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-8": (5.00, 25.00, 0.50, 6.25),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-sonnet-5": (2.00, 10.00, 0.20, 2.50),
    "claude-sonnet-4-6": (3.00, 15.00, 0.30, 3.75),
    "claude-haiku-4-5": (1.00, 5.00, 0.10, 1.25),
}


def estimate_cost(model: str, usage: dict[str, int]) -> float | None:
    """Estimated USD for one model's accumulated usage; None if unpriced."""
    prices = MODEL_PRICES.get(model)
    if prices is None:
        return None
    p_in, p_out, p_read, p_write = prices
    return (usage.get("input_tokens", 0) * p_in
            + usage.get("output_tokens", 0) * p_out
            + usage.get("cache_read_input_tokens", 0) * p_read
            + usage.get("cache_creation_input_tokens", 0) * p_write) / 1_000_000


_USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
                 "cache_creation_input_tokens")


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Copy `schema` into the shape structured outputs requires: every object
    gets `additionalProperties: false`, unsupported constraints are removed."""
    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {k: walk(v) for k, v in node.items()
                   if k not in _UNSUPPORTED_SCHEMA_KEYS}
            if out.get("type") == "object":
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node
    return walk(copy.deepcopy(schema))


class LLM:
    def __init__(self) -> None:
        self._client = None
        # model -> {calls, input_tokens, output_tokens, cache_*}
        self.usage: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
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

    def _record(self, msg: Any, model: str, label: str) -> None:
        u = msg.usage
        counts = {f: getattr(u, f, 0) or 0 for f in _USAGE_FIELDS}
        totals = self.usage[model]
        totals["calls"] += 1
        for f, n in counts.items():
            totals[f] += n
        log.info("llm %s (%s): in=%d out=%d cache_read=%d cache_write=%d stop=%s",
                 label, model, counts["input_tokens"], counts["output_tokens"],
                 counts["cache_read_input_tokens"],
                 counts["cache_creation_input_tokens"], msg.stop_reason)

    def log_usage_summary(self) -> None:
        for model, t in self.usage.items():
            log.info("llm usage %s: calls=%d in=%d out=%d cache_read=%d "
                     "cache_write=%d", model, t["calls"], t["input_tokens"],
                     t["output_tokens"], t["cache_read_input_tokens"],
                     t["cache_creation_input_tokens"])

    @staticmethod
    def _output_config(effort: str | None, fmt: dict | None = None) -> dict:
        cfg: dict[str, Any] = {}
        if effort:
            cfg["effort"] = effort
        if fmt:
            cfg["format"] = fmt
        return cfg

    def structured(self, system: list[dict] | str, user: str, *, schema: dict,
                   tool_name: str, model: str,
                   max_tokens: int = DEFAULT_MAX_TOKENS,
                   effort: str | None = None) -> dict | None:
        """Structured JSON result via output_config.format. `tool_name` labels
        the call in logs."""
        if not self.available:
            return None
        try:
            fmt = {"type": "json_schema", "schema": strict_schema(schema)}
            msg = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                output_config=self._output_config(effort, fmt),
                messages=[{"role": "user", "content": user}],
            )
            self._record(msg, model, tool_name)
            if msg.stop_reason in ("max_tokens", "refusal"):
                log.warning("LLM.structured %s stopped early (%s): %s",
                            tool_name, model, msg.stop_reason)
                return None
            text = next((b.text for b in msg.content if b.type == "text"), None)
            if text is not None:
                return json.loads(text)
        except Exception as exc:
            log.warning("LLM.structured failed (%s): %s", model, exc)
        return None

    def text(self, system: list[dict] | str, user: str, *, model: str,
             max_tokens: int = DEFAULT_MAX_TOKENS,
             effort: str | None = None, label: str = "text") -> str | None:
        if not self.available:
            return None
        try:
            kwargs: dict[str, Any] = {}
            cfg = self._output_config(effort)
            if cfg:
                kwargs["output_config"] = cfg
            msg = self._client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}], **kwargs,
            )
            self._record(msg, model, label)
            if msg.stop_reason in ("max_tokens", "refusal"):
                log.warning("LLM.text %s stopped early (%s): %s",
                            label, model, msg.stop_reason)
                return None
            return "".join(b.text for b in msg.content if b.type == "text").strip()
        except Exception as exc:
            log.warning("LLM.text failed (%s): %s", model, exc)
        return None
