"""One module for live Anthropic calls and the offline mock used by tests."""

from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass

from bess_workbench.ai.pricing import Usage
from bess_workbench.ai.redact import register_secret, scrub

log = logging.getLogger("bess_workbench.ai.client")

TRANSIENT_STATUS = {408, 409, 429, 500, 502, 503, 529}
TRANSIENT_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
    "RateLimitError",
    "OverloadedError",
    "ServiceUnavailableError",
}


class AIError(Exception):
    pass


class AITransientError(AIError):
    pass


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class StreamDone:
    usage: Usage
    stop_reason: str


def classify_error(exc: Exception) -> AIError:
    name = type(exc).__name__
    code = getattr(exc, "status_code", None)
    text = scrub(f"{name}: {exc}")
    if name in TRANSIENT_NAMES or code in TRANSIENT_STATUS:
        return AITransientError(text)
    return AIError(text)


def call_with_retries(fn, attempts: int = 3, base_delay: float = 0.5, sleep=time.sleep):
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except AITransientError as exc:
            last = exc
            if attempt == attempts - 1:
                break
            sleep(base_delay * (2**attempt))
        except AIError:
            raise
    raise AIError(scrub(str(last))) from None


def _usage_from_message(message) -> Usage:
    usage = getattr(message, "usage", None)
    if usage is None:
        return Usage()
    return Usage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        cache_write_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
    )


class AnthropicClient:
    """Live client. Construct with a key; do not log the instance."""

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise AIError("No API key.")
        register_secret(api_key)
        self._api_key = api_key
        self.model = model

    def _sdk(self):
        import anthropic

        return anthropic.Anthropic(api_key=self._api_key)

    def complete_stream(self, kwargs: dict):
        log.info("ai request model=%s max_tokens=%s", kwargs.get("model"), kwargs.get("max_tokens"))

        def open_stream():
            try:
                return self._sdk().messages.stream(**kwargs)
            except Exception as exc:
                raise classify_error(exc) from None

        manager = call_with_retries(open_stream)
        try:
            with manager as stream:
                for event in stream:
                    if getattr(event, "type", None) == "text":
                        yield TextDelta(getattr(event, "text", "") or "")
                final = stream.get_final_message()
                for block in final.content:
                    if getattr(block, "type", None) == "tool_use":
                        raw = getattr(block, "input", {}) or {}
                        arguments = dict(raw) if isinstance(raw, dict) else {}
                        yield ToolCall(id=block.id, name=block.name, arguments=arguments)
                usage = _usage_from_message(final)
                log.info(
                    "ai usage input=%s output=%s cache_read=%s cache_write=%s",
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cache_read_tokens,
                    usage.cache_write_tokens,
                )
                yield StreamDone(usage=usage, stop_reason=str(getattr(final, "stop_reason", "") or ""))
        except AIError:
            raise
        except Exception as exc:
            raise classify_error(exc) from None

    def complete_text(self, kwargs: dict) -> tuple[str, Usage]:
        parts: list[str] = []
        usage = Usage()
        for event in self.complete_stream(kwargs):
            if isinstance(event, TextDelta):
                parts.append(event.text)
            elif isinstance(event, StreamDone):
                usage = event.usage
        return "".join(parts).strip(), usage


class MockClient:
    """Scripted client. Each complete_stream call consumes one round of events."""

    def __init__(self, rounds: list | None = None, text: str = "OK") -> None:
        self.rounds = list(rounds or [])
        self.text = text
        self.calls: list[dict] = []
        self.model = "mock-claude"

    def complete_stream(self, kwargs: dict):
        self.calls.append(copy.deepcopy(kwargs))
        if self.rounds:
            events = self.rounds.pop(0)
        else:
            events = [TextDelta(self.text), StreamDone(Usage(input_tokens=10, output_tokens=2), "end_turn")]
        yield from events

    def complete_text(self, kwargs: dict) -> tuple[str, Usage]:
        parts: list[str] = []
        usage = Usage()
        for event in self.complete_stream(kwargs):
            if isinstance(event, TextDelta):
                parts.append(event.text)
            elif isinstance(event, StreamDone):
                usage = event.usage
        return "".join(parts).strip(), usage
