"""Build Anthropic request bodies. The API key is never placed in these dicts."""

from __future__ import annotations

from bess_workbench.ai.prompts import EXTRACT_SYSTEM, NARRATIVE_SYSTEM, RFI_SYSTEM, SYSTEM_PROMPT

CACHE = {"type": "ephemeral"}


def _system_blocks(*texts: str) -> list[dict]:
    return [{"type": "text", "text": text, "cache_control": CACHE} for text in texts]


def build_chat_kwargs(*, model: str, rules_text: str, messages: list, tools: list, max_tokens: int = 4096) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "system": _system_blocks(SYSTEM_PROMPT, rules_text),
        "tools": tools,
        "messages": messages,
    }


def build_text_kwargs(*, model: str, system: str, user: str, max_tokens: int) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0,
        "system": _system_blocks(system),
        "messages": [{"role": "user", "content": user}],
    }


def build_extract_kwargs(*, model: str, pdf_base64: str, filename: str) -> dict:
    return {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0,
        "system": _system_blocks(EXTRACT_SYSTEM),
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "title": filename,
                        "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_base64},
                    },
                    {"type": "text", "text": "Extract the JSON object described in the system instructions."},
                ],
            }
        ],
    }


def rfi_system() -> str:
    return RFI_SYSTEM


def narrative_system() -> str:
    return NARRATIVE_SYSTEM
