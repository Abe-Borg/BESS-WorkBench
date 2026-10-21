import os

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from bess_workbench.controller import ProjectController
from bess_workbench.paths import sample_file
from bess_workbench.reports import export_all
from bess_workbench.ruleset import load_rules
from bess_workbench.sample_data import build_new_project, build_sample_project
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


def test_open_sample_is_an_unsaved_copy(qapp, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(autosave=False, settings=settings)
    window.open_sample()
    assert window.controller.project.meta.synthetic
    assert window.path is None
    assert str(sample_file()) not in list(settings.value("recent", []) or [])
    window.close()


def test_added_rooms_get_unique_ids_after_a_delete(qapp, tmp_path):
    rules = load_rules()
    controller = ProjectController(build_new_project(rules), rules)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(controller=controller, autosave=False, settings=settings)
    rooms = window.screens[1]
    rooms._add_room()
    rooms._add_room()
    rooms.rooms.setCurrentCell(1, 0)
    rooms._remove_room()
    rooms._add_room()
    ids = [room.id for room in window.controller.project.rooms]
    assert ids == ["ROOM-1", "ROOM-3", "ROOM-4"]
    sensor_ids = [sensor.id for sensor in window.controller.project.gas.sensors]
    assert len(sensor_ids) == len(set(sensor_ids))
    window.close()
