"""Chat loop. Read-only tools run immediately. Edits wait for an approver."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from bess_workbench.ai.client import AIError, StreamDone, TextDelta, ToolCall
from bess_workbench.ai.pricing import Usage
from bess_workbench.ai.redact import scrub
from bess_workbench.ai.request import build_chat_kwargs
from bess_workbench.ai.tools import MUTATING, Proposal, apply_tool, preview_change, run_readonly, TOOL_SPECS
from bess_workbench.controller import ProjectController

log = logging.getLogger("bess_workbench.ai.assistant")


@dataclass
class ErrorEvent:
    message: str


@dataclass
class ProposalEvent:
    proposal: Proposal


@dataclass
class AppliedEvent:
    approved: bool
    detail: str


def compose_user_message(user_text: str, controller: ProjectController) -> str:
    checks = [item.model_dump(mode="json") for item in controller.analysis.checks]
    return (
        "CURRENT PROJECT JSON:\n"
        + controller.project.model_dump_json(indent=2)
        + "\n\nCURRENT CHECK RESULTS:\n"
        + json.dumps(checks, indent=2)
        + "\n\nUSER QUESTION:\n"
        + user_text
    )


class Assistant:
    def __init__(self, client, controller: ProjectController, rules_text: str) -> None:
        self.client = client
        self.controller = controller
        self.rules_text = rules_text
        self.messages: list[dict] = []
        self.usage = Usage()

    def send(self, user_text: str, approver):
        self.messages.append({"role": "user", "content": compose_user_message(user_text, self.controller)})
        yield from self._drive(approver)

    def _drive(self, approver):
        for _round in range(6):
            kwargs = build_chat_kwargs(
                model=getattr(self.client, "model", ""),
                rules_text=self.rules_text,
                messages=self.messages,
                tools=TOOL_SPECS,
            )
            text_parts: list[str] = []
            tool_calls: list[ToolCall] = []
            stop = ""
            try:
                for event in self.client.complete_stream(kwargs):
                    if isinstance(event, TextDelta):
                        text_parts.append(event.text)
                        yield event
                    elif isinstance(event, ToolCall):
                        tool_calls.append(event)
                    elif isinstance(event, StreamDone):
                        self.usage = self.usage.add(event.usage)
                        stop = event.stop_reason
                        yield event
            except AIError as exc:
                log.info("ai request failed")
                yield ErrorEvent(scrub(str(exc)))
                return
            content: list[dict] = []
            if text_parts:
                content.append({"type": "text", "text": "".join(text_parts)})
            for call in tool_calls:
                content.append({"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments})
            if content:
                self.messages.append({"role": "assistant", "content": content})
            if not tool_calls or stop == "end_turn" and not tool_calls:
                return
            if not tool_calls:
                return
            results: list[dict] = []
            proposals = [call for call in tool_calls if call.name in MUTATING]
            for call in tool_calls:
                if call.name in MUTATING:
                    continue
                try:
                    payload = run_readonly(
                        call.name,
                        call.arguments,
                        self.controller.project,
                        self.controller.analysis,
                        self.controller.rules,
                    )
                except Exception as exc:
                    payload = "Tool error: " + scrub(str(exc))
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": payload})
            if proposals:
                preview = "\n\n".join(preview_change(self.controller.project, call.name, call.arguments) for call in proposals)
                proposal = Proposal(calls=proposals, preview=preview)
                yield ProposalEvent(proposal)
                approved = bool(approver(proposal))
                details = []
                for call in proposals:
                    if not approved:
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": call.id,
                                "content": "User rejected this change. Do not apply it.",
                            }
                        )
                        continue
                    try:
                        updated, message = apply_tool(self.controller.project, call.name, call.arguments)
                        self.controller.project = updated
                        self.controller.recompute()
                        details.append(message)
                        results.append({"type": "tool_result", "tool_use_id": call.id, "content": "User approved. " + message})
                    except Exception as exc:
                        message = "Validation rejected the change: " + scrub(str(exc))
                        details.append(message)
                        results.append({"type": "tool_result", "tool_use_id": call.id, "content": message})
                yield AppliedEvent(approved=approved, detail="; ".join(details))
            self.messages.append({"role": "user", "content": results})
            if not proposals and not any(call.name not in MUTATING for call in tool_calls):
                return
        yield ErrorEvent("Stopped after too many tool rounds.")
