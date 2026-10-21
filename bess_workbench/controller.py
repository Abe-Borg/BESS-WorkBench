"""Project state, fire-area sync, cause-and-effect refresh, and the RFI register."""

from __future__ import annotations

from pathlib import Path

from bess_workbench.analysis import AutoRFI, Status, worst_status
from bess_workbench.calcs import build_cause_effect, fingerprint
from bess_workbench.engine import analyze, ensure_fire_areas
from bess_workbench.models import Project, RFI
from bess_workbench.ruleset import Ruleset, load_rules

CLEARED_NOTE = "Condition cleared by the rules engine."


class ProjectController:
    def __init__(self, project: Project, rules: Ruleset | None = None) -> None:
        self.project = project
        self.rules = rules or load_rules()
        self.analysis = None
        self.recompute()

    def recompute(self) -> None:
        ensure_fire_areas(self.project)
        if not self.project.cause_effect_manual:
            self.project.cause_effect = build_cause_effect(self.project)
            self.project.cause_effect_fingerprint = fingerprint(self.project)
        self.analysis = analyze(self.project, self.rules)
        sync_rfis(self.project, self.analysis.auto_rfis)
        self.analysis.screen_status["rfi"] = _rfi_badge(self.project, self.analysis.checks)


def sync_rfis(project: Project, specs: list[AutoRFI]) -> None:
    by_key = {item.key: item for item in project.rfis}
    active = {spec.key for spec in specs}
    for spec in sorted(specs, key=lambda item: item.key):
        existing = by_key.get(spec.key)
        if existing is None:
            number = max((item.number for item in project.rfis), default=0) + 1
            created = RFI(
                number=number,
                key=spec.key,
                source="auto",
                rule_id=spec.rule_id,
                title=spec.title,
                text=spec.text,
                assignee=spec.assignee,
                status="open",
                screen=spec.screen,
            )
            project.rfis.append(created)
            by_key[spec.key] = created
            continue
        if existing.source == "auto" and not existing.text_edited:
            existing.title = spec.title
            existing.text = spec.text
            existing.screen = spec.screen
            existing.rule_id = spec.rule_id
        if existing.source == "auto" and not existing.assignee_edited:
            existing.assignee = spec.assignee
        if existing.auto_closed and not existing.user_closed and existing.status == "closed":
            existing.status = "open"
            existing.auto_closed = False
            existing.text = existing.text.replace("\n\n" + CLEARED_NOTE, "").replace(CLEARED_NOTE, "").rstrip()
    for item in project.rfis:
        if item.source != "auto" or item.key in active or item.status != "open":
            continue
        item.status = "closed"
        item.auto_closed = True
        if CLEARED_NOTE not in item.text:
            item.text = item.text.rstrip() + "\n\n" + CLEARED_NOTE


def _rfi_badge(project: Project, checks) -> str:
    by_rule = {item.rule_id: item.status for item in checks}
    open_items = [item for item in project.rfis if item.status == "open"]
    if not open_items:
        return Status.PASS.value
    return worst_status([by_rule.get(item.rule_id, Status.WARN) for item in open_items]).value


def load_project(path: str | Path) -> Project:
    return Project.model_validate_json(Path(path).read_text(encoding="utf-8"))


def save_project(project: Project, path: str | Path) -> None:
    target = Path(path)
    target.write_text(project.model_dump_json(indent=2) + "\n", encoding="utf-8")
