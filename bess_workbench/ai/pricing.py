"""Display-only token cost estimates. These are not an invoice."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )


# USD per million tokens. Confirm on Anthropic's pricing page. The UI labels every figure as an estimate.
_SONNET = {"in": 3.0, "out": 15.0, "cache_read": 0.30, "cache_write": 3.75}
_HAIKU = {"in": 1.0, "out": 5.0, "cache_read": 0.10, "cache_write": 1.25}
_OPUS = {"in": 15.0, "out": 75.0, "cache_read": 1.50, "cache_write": 18.75}


def price_for(model: str) -> dict[str, float]:
    name = (model or "").lower()
    if "haiku" in name:
        return _HAIKU
    if "opus" in name:
        return _OPUS
    return _SONNET


def estimate_cost(model: str, usage: Usage) -> float:
    price = price_for(model)
    return (
        usage.input_tokens * price["in"]
        + usage.output_tokens * price["out"]
        + usage.cache_read_tokens * price["cache_read"]
        + usage.cache_write_tokens * price["cache_write"]
    ) / 1_000_000


def format_usage(model: str, usage: Usage) -> str:
    cost = estimate_cost(model, usage)
    return (
        f"Tokens in {usage.input_tokens:,} · out {usage.output_tokens:,} · "
        f"cache read {usage.cache_read_tokens:,} · cache write {usage.cache_write_tokens:,} · "
        f"est. ${cost:.4f}"
    )
