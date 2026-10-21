"""Read-only tool handlers and proposed edits. Nothing here calls the network."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from bess_workbench.analysis import Analysis, Status
from bess_workbench.models import Project, RFI, display_rfi_id
from bess_workbench.ruleset import Ruleset

TOOL_SPECS = [
    {
        "name": "get_project",
        "description": "Return the current project JSON. Read-only.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "run_checks",
        "description": "Return the current rules-engine checks. Read-only. These statuses are authoritative.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_rule",
        "description": "Return one rule from the rules file, including its citation, edition, summary, and tags.",
        "input_schema": {
            "type": "object",
            "properties": {"rule_id": {"type": "string"}},
            "required": ["rule_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_open_items",
        "description": "Return open RFIs and checks that are not PASS. Read-only.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "add_rfi",
        "description": "Propose a new RFI. The user must approve it before it is added.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "text": {"type": "string"},
                "assignee": {
                    "type": "string",
                    "enum": ["Architect", "Mech", "Elec", "Controls vendor", "Owner", "AHJ"],
                },
                "due": {"type": "string"},
            },
            "required": ["title", "text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_input",
        "description": "Propose a project field change. The user must approve it. path examples: sprinklers.hose_gpm, rooms[0].area_sf, gas.alarm_pct_lfl.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "value": {}},
            "required": ["path", "value"],
            "additionalProperties": False,
        },
    },
]

MUTATING = {"add_rfi", "set_input"}
_SEGMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\[(\d+)\])?$")
_ROOTS = {
    "meta",
    "code_basis",
    "rooms",
    "ess_groups",
    "fire_areas",
    "sprinklers",
    "exhaust",
    "gas",
    "battery",
    "cause_effect",
    "ai_narrative",
    "ai_narrative_edited",
    "ai_narrative_model",
}


def _segments(path: str) -> list[tuple[str, int | None]]:
    if not path or ".." in path or path.startswith("_"):
        raise ValueError(f"Illegal path: {path}")
    parts = path.split(".")
    parsed: list[tuple[str, int | None]] = []
    for part in parts:
        match = _SEGMENT.match(part)
        if not match or match.group(1).startswith("_"):
            raise ValueError(f"Illegal path segment: {part}")
        index = int(match.group(2)) if match.group(2) is not None else None
        parsed.append((match.group(1), index))
    if parsed[0][0] not in _ROOTS:
        raise ValueError(f"Path root is not editable: {parsed[0][0]}")
    return parsed


def get_path(data: dict, path: str):
    current = data
    for name, index in _segments(path):
        if not isinstance(current, dict) or name not in current:
            raise ValueError(f"Missing field {name} in {path}")
        current = current[name]
        if index is not None:
            if not isinstance(current, list) or index >= len(current):
                raise ValueError(f"Index out of range in {path}")
            current = current[index]
    return current


def set_path(data: dict, path: str, value) -> None:
    segments = _segments(path)
    current = data
    for name, index in segments[:-1]:
        current = current[name]
        if index is not None:
            current = current[index]
    name, index = segments[-1]
    if index is None:
        if not isinstance(current, dict):
            raise ValueError(f"Cannot set {path}")
        current[name] = value
        return
    container = current[name]
    if not isinstance(container, list) or index >= len(container):
        raise ValueError(f"Index out of range in {path}")
    container[index] = value


def preview_change(project: Project, name: str, arguments: dict) -> str:
    if name == "set_input":
        path = str(arguments.get("path", ""))
        try:
            old = get_path(project.model_dump(mode="json"), path)
        except ValueError as exc:
            old = f"<unreadable: {exc}>"
        return f"set_input {path}\n- {old!r}\n+ {arguments.get('value')!r}"
    if name == "add_rfi":
        return "add_rfi\n" + json.dumps(
            {
                "title": arguments.get("title", ""),
                "text": arguments.get("text", ""),
                "assignee": arguments.get("assignee", "Owner"),
                "due": arguments.get("due", ""),
            },
            indent=2,
        )
    return name


def apply_tool(project: Project, name: str, arguments: dict) -> tuple[Project, str]:
    data = project.model_dump(mode="json")
    if name == "set_input":
        path = str(arguments["path"])
        set_path(data, path, arguments.get("value"))
        updated = Project.model_validate(data)
        return updated, f"Set {path}."
    if name == "add_rfi":
        assignee = arguments.get("assignee") or "Owner"
        number = max((item.number for item in project.rfis), default=0) + 1
        item = RFI(
            number=number,
            key=f"ai:{number}",
            source="ai",
            title=str(arguments.get("title") or "AI RFI"),
            text=str(arguments.get("text") or ""),
            assignee=assignee,
            due=str(arguments.get("due") or ""),
            status="open",
            ai_drafted=True,
        )
        updated = project.model_copy(deep=True)
        updated.rfis.append(item)
        Project.model_validate(updated.model_dump())
        return updated, f"Added {display_rfi_id(item)}."
    raise ValueError(f"Not a project edit: {name}")


def run_readonly(name: str, arguments: dict, project: Project, analysis: Analysis, rules: Ruleset) -> str:
    if name == "get_project":
        return project.model_dump_json(indent=2)
    if name == "run_checks":
        return json.dumps([item.model_dump(mode="json") for item in analysis.checks], indent=2)
    if name == "get_rule":
        rule_id = str(arguments.get("rule_id", ""))
        try:
            return rules.rule(rule_id).model_dump_json(indent=2)
        except KeyError:
            ids = ", ".join(item.id for item in rules.rules)
            return f"Unknown rule id {rule_id}. Known ids: {ids}"
    if name == "list_open_items":
        payload = {
            "open_rfis": [
                {"id": display_rfi_id(item), "title": item.title, "text": item.text, "rule_id": item.rule_id, "assignee": item.assignee}
                for item in project.rfis
                if item.status == "open"
            ],
            "non_pass_checks": [
                {"id": item.id, "status": item.status.value, "value": item.value, "citation": item.citation, "message": item.message, "tags": item.tags}
                for item in analysis.checks
                if item.status != Status.PASS
            ],
        }
        return json.dumps(payload, indent=2)
    raise ValueError(f"Unknown read-only tool: {name}")


@dataclass
class Proposal:
    calls: list
    preview: str
