"""Locate the rules file and the shipped sample from source or a frozen build."""

from __future__ import annotations

import os
import sys
from pathlib import Path

RULES_NAME = Path("rules") / "ifc2024_nfpa855_2023.json"
SAMPLE_NAME = "Sample - 4 Room UPS BESS.bessproj"


def _candidates(relative: Path) -> list[Path]:
    found: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            found.append(Path(meipass) / relative)
        found.append(Path(sys.executable).resolve().parent / relative)
    found.append(Path.cwd() / relative)
    here = Path(__file__).resolve()
    for parent in here.parents:
        found.append(parent / relative)
    return found


def resolve_data_file(relative: Path) -> Path:
    for candidate in _candidates(relative):
        if candidate.is_file():
            return candidate
    return _candidates(relative)[0]


def rules_file() -> Path:
    override = os.environ.get("BESS_RULES_FILE", "").strip()
    if override:
        return Path(override)
    return resolve_data_file(RULES_NAME)


def sample_file() -> Path:
    return resolve_data_file(Path("samples") / SAMPLE_NAME)
