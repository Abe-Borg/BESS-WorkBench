"""Capture every screen offscreen and export the sample reports.

Run from the repo root:

    QT_QPA_PLATFORM=offscreen python scripts/capture_screenshots.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_OPENGL", "software")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from bess_workbench.ai.intake import extraction_from_text
from bess_workbench.controller import ProjectController, load_project
from bess_workbench.paths import sample_file
from bess_workbench.reports import export_all
from bess_workbench.ruleset import load_rules
from bess_workbench.ui.dialogs import IntakeDialog
from bess_workbench.ui.main_window import MainWindow


def main() -> None:
    app = QApplication([])
    rules = load_rules()
    controller = ProjectController(load_project(sample_file()), rules)
    shots = ROOT / "docs" / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    settings = QSettings(str(ROOT / ".screenshot-settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(controller=controller, autosave=False, settings=settings)
    window.resize(1440, 900)
    window.show()
    app.processEvents()
    names = [
        "01-project",
        "02-rooms",
        "03-thresholds",
        "04-explosion",
        "05-gas-detection",
        "06-cause-effect",
        "07-sprinklers",
        "08-battery",
        "09-rfi",
        "10-reports",
        "11-settings",
    ]
    for index, name in enumerate(names):
        window.nav.setCurrentRow(index)
        app.processEvents()
        image = window.grab()
        target = shots / f"{name}.png"
        image.save(str(target))
        print(target, image.width(), image.height())

    window.apply_theme(True)
    window.nav.setCurrentRow(0)
    app.processEvents()
    dark = shots / "13-project-dark.png"
    window.grab().save(str(dark))
    print(dark)
    window.apply_theme(False)

    dialog = IntakeDialog(window)
    dialog.show_extraction(
        extraction_from_text(
            """
            {
              "gases": [{"name": "H2", "mass_g": 12.5, "lfl_vol_pct": 4.0, "page": 14}],
              "kwh_entries": [{"room_hint": "UPS-1", "kwh": 150, "page": 3}],
              "monitoring_only": true,
              "add_alternate": true,
              "sensors": [{"gas": "DMC", "room_hint": "UPS-1", "mount": "low", "page": 9}]
            }
            """,
            "synthetic-9540a.pdf",
        )
    )
    dialog.resize(900, 560)
    dialog.show()
    app.processEvents()
    intake = shots / "12-document-intake.png"
    dialog.grab().save(str(intake))
    print(intake)
    dialog.close()

    export_dir = ROOT / "docs" / "sample-exports"
    paths = export_all(window.controller.project, window.controller.analysis, export_dir)
    for path in paths.values():
        print(path, path.stat().st_size)
    window.close()
    settings_file = ROOT / ".screenshot-settings.ini"
    if settings_file.exists():
        settings_file.unlink()


if __name__ == "__main__":
    main()
