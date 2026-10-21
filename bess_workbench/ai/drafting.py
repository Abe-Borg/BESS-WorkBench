"""One-click RFI wording and the basis-of-design narrative. Both are drafts."""

from __future__ import annotations

import json

from bess_workbench.ai.request import build_text_kwargs, narrative_system, rfi_system
from bess_workbench.controller import ProjectController
from bess_workbench.models import RFI, display_rfi_id


def _rfi_user(item: RFI, controller: ProjectController) -> str:
    check = next((entry for entry in controller.analysis.checks if entry.rule_id == item.rule_id), None)
    citation = ""
    tags = ""
    if check is not None:
        citation = f"{check.citation} ({check.edition})"
        tags = ", ".join(check.tags)
    return (
        f"RFI {display_rfi_id(item)}\n"
        f"Title: {item.title}\n"
        f"Current text: {item.text}\n"
        f"Rule: {item.rule_id}\n"
        f"Citation: {citation}\n"
        f"Tags: {tags}\n"
        "Rewrite the current text as the RFI body. Keep the same ask."
    )


def draft_rfi_text(client, controller: ProjectController, item: RFI) -> tuple[str, object]:
    kwargs = build_text_kwargs(model=client.model, system=rfi_system(), user=_rfi_user(item, controller), max_tokens=700)
    return client.complete_text(kwargs)


def draft_narrative(client, controller: ProjectController) -> tuple[str, object]:
    checks = [
        {"id": item.id, "status": item.status.value, "value": item.value, "citation": item.citation, "tags": item.tags, "message": item.message}
        for item in controller.analysis.checks
        if item.status.value != "PASS"
    ]
    user = (
        "PROJECT:\n"
        + controller.project.model_dump_json(indent=2)
        + "\n\nNON-PASS CHECKS:\n"
        + json.dumps(checks, indent=2)
        + "\n\nWrite the narrative."
    )
    kwargs = build_text_kwargs(model=client.model, system=narrative_system(), user=user, max_tokens=1400)
    return client.complete_text(kwargs)
