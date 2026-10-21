"""Load the versioned rules file. Numbers in that file drive the engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from bess_workbench.paths import rules_file


class Parameter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: Any
    citation: str = ""
    edition: str = ""
    summary: str = ""
    tags: list[str] = []
    unit: str = ""


class RuleDef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    screen: str
    title: str
    summary: str
    citation: str
    edition: str
    tags: list[str] = []
    lead: str = ""
    lead_note: str = ""


class Ruleset(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ruleset_id: str
    version: str
    title: str
    changelog: list[str] = []
    editions: dict[str, str]
    scope: dict[str, Any]
    parameters: dict[str, Parameter]
    rules: list[RuleDef]

    def rule(self, rule_id: str) -> RuleDef:
        for item in self.rules:
            if item.id == rule_id:
                return item
        raise KeyError(f"Rules file has no rule id {rule_id}")

    def param(self, key: str) -> Any:
        try:
            return self.parameters[key].value
        except KeyError as exc:
            raise KeyError(f"Rules file has no parameter {key}") from exc


def load_rules(path: Path | None = None) -> Ruleset:
    source = Path(path) if path else rules_file()
    data = json.loads(source.read_text(encoding="utf-8"))
    return Ruleset.model_validate(data)
