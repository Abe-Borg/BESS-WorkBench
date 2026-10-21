from pathlib import Path

from bess_workbench.ruleset import load_rules

ROOT = Path(__file__).resolve().parents[1]


def test_spec_lists_every_rule_and_the_disclaimer():
    spec = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    rules_doc = (ROOT / "docs" / "RULES.md").read_text(encoding="utf-8")
    assert "Design aid. Verify values against adopted codes and AHJ." in spec
    assert "Design aid. Verify values against adopted codes and AHJ." in readme
    for rule in load_rules().rules:
        assert f"`{rule.id}`" in spec
    assert "ifc2024_nfpa855_2023.json" in rules_doc
    assert "ASSUMED" in rules_doc
    assert "NEEDS PE REVIEW" in rules_doc
    assert "MIT" in (ROOT / "LICENSE").read_text(encoding="utf-8")
