import os

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from bess_workbench.controller import ProjectController
from bess_workbench.reports import export_all
from bess_workbench.ruleset import load_rules
from bess_workbench.sample_data import build_sample_project
from bess_workbench.ui.main_window import NAV, MainWindow


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_every_screen_loads_sample(qapp, tmp_path):
    rules = load_rules()
    controller = ProjectController(build_sample_project(rules), rules)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(controller=controller, autosave=False, settings=settings)
    window.resize(1440, 900)
    window.show()
    qapp.processEvents()
    assert "SYNTHETIC" in window.banner.extra.text()
    assert window.banner.text.text() == "Design aid. Verify values against adopted codes and AHJ."
    seen = []
    for index, (screen_id, _title) in enumerate(NAV):
        window.nav.setCurrentRow(index)
        qapp.processEvents()
        current = window.stack.currentWidget()
        assert current.screen_id == screen_id
        seen.append(window.badges[screen_id].text())
        image = window.grab()
        assert not image.isNull()
        assert image.width() > 800
    assert seen[4] == "FAIL"
    assert seen[6] == "BLOCKED"
    assert seen[10] == "OFF"
    labels = [window.screens[6].system.itemText(i) for i in range(window.screens[6].system.count())]
    assert labels == ["Wet", "Dry", "Double-interlock preaction"]
    paths = export_all(window.controller.project, window.controller.analysis, tmp_path)
    assert paths["docx"].is_file()
    window.close()
