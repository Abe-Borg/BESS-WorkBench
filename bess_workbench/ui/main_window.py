"""Main window: navigation, autosave, and the persistent design-aid banner."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from bess_workbench import __version__
from bess_workbench.ai.client import AnthropicClient
from bess_workbench.ai.keystore import Keystore
from bess_workbench.ai.pricing import format_usage
from bess_workbench.ai.redact import scrub
from bess_workbench.controller import ProjectController, load_project, save_project
from bess_workbench.paths import rules_file, sample_file
from bess_workbench.ruleset import load_rules
from bess_workbench.sample_data import build_new_project
from bess_workbench.ui.ai_panel import AIPanel
from bess_workbench.ui.dialogs import AboutDialog, IntakeDialog
from bess_workbench.ui.results_panel import ResultsPanel
from bess_workbench.ui.screens import all_screens
from bess_workbench.ui.theme import STATUS_COLORS, stylesheet
from bess_workbench.ui.widgets import DISCLAIMER, Banner

NAV = [
    ("project", "Project & Code Basis"),
    ("rooms", "Rooms & ESS"),
    ("thresholds", "Thresholds & Fire Areas"),
    ("explosion", "Explosion & Exhaust"),
    ("gas", "Gas Detection"),
    ("cause_effect", "Cause & Effect"),
    ("sprinklers", "Sprinklers"),
    ("battery", "FA & Battery"),
    ("rfi", "Open Items / RFI"),
    ("reports", "Reports"),
    ("settings", "Settings"),
]
DEFAULT_MODEL = "claude-sonnet-5-5"


class MainWindow(QMainWindow):
    def __init__(self, controller: ProjectController | None = None, autosave: bool = True, settings: QSettings | None = None) -> None:
        super().__init__()
        self.setWindowTitle("BESS WorkBench")
        self.resize(1440, 900)
        self.settings = settings or QSettings("BESSWorkBench", "BESSWorkBench")
        self.keystore = Keystore()
        self.autosave_enabled = autosave
        self.path: Path | None = None
        rules = load_rules()
        self.controller = controller or ProjectController(build_new_project(rules), rules)
        self._session_usage = None

        self.banner = Banner()
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(280)
        self.badges: dict[str, QLabel] = {}
        for screen_id, title in NAV:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, screen_id)
            row = QWidget()
            row.setMinimumHeight(48)
            layout = QHBoxLayout(row)
            layout.setContentsMargins(8, 4, 8, 4)
            label = QLabel(title)
            label.setWordWrap(True)
            badge = QLabel("—")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setMinimumWidth(64)
            self.badges[screen_id] = badge
            layout.addWidget(label, 1)
            layout.addWidget(badge)
            self.nav.addItem(item)
            item.setSizeHint(row.sizeHint())
            self.nav.setItemWidget(item, row)
        self.nav.currentRowChanged.connect(self._goto)

        self.screens = all_screens(self)
        self.stack = QStackedWidget()
        for screen in self.screens:
            self.stack.addWidget(screen)
        self.results = ResultsPanel()
        self.ai_panel = AIPanel(self)
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.results)
        right.addWidget(self.ai_panel)
        right.setSizes([420, 280])
        body = QSplitter(Qt.Orientation.Horizontal)
        body.addWidget(self.nav)
        body.addWidget(self.stack)
        body.addWidget(right)
        body.setSizes([280, 720, 420])

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.addWidget(self.banner)
        outer.addWidget(body, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self._build_menu()
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._autosave)
        self.apply_theme(self.settings.value("theme", "light") == "dark")
        self.refresh_all()
        self.nav.setCurrentRow(0)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        self._action(file_menu, "New", self.new_project, QKeySequence.StandardKey.New)
        self._action(file_menu, "Open…", self.open_project, QKeySequence.StandardKey.Open)
        self._action(file_menu, "Save", self.save, QKeySequence.StandardKey.Save)
        self._action(file_menu, "Save As…", self.save_as, QKeySequence.StandardKey.SaveAs)
        file_menu.addSeparator()
        self._action(file_menu, "Open sample", self.open_sample)
        self._action(file_menu, "Document intake…", self.open_intake)
        file_menu.addSeparator()
        self.recent_menu = file_menu.addMenu("Recent")
        self._rebuild_recent()
        file_menu.addSeparator()
        self._action(file_menu, "Quit", self.close, QKeySequence.StandardKey.Quit)

        view = self.menuBar().addMenu("View")
        self._action(view, "Light theme", lambda: self.apply_theme(False))
        self._action(view, "Dark theme", lambda: self.apply_theme(True))
        tools = self.menuBar().addMenu("Tools")
        self._action(tools, "Reload rules file", self.reload_rules)
        help_menu = self.menuBar().addMenu("Help")
        self._action(help_menu, "About", self.about)

    def _action(self, menu, label, slot, shortcut=None) -> QAction:
        action = QAction(label, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def apply_theme(self, dark: bool) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet(dark))
        self.settings.setValue("theme", "dark" if dark else "light")

    def model_name(self) -> str:
        value = str(self.settings.value("model", DEFAULT_MODEL) or DEFAULT_MODEL).strip()
        return value or DEFAULT_MODEL

    def set_model(self, model: str) -> None:
        self.settings.setValue("model", model or DEFAULT_MODEL)

    def ai_available(self) -> bool:
        key, _source = self.keystore.resolve()
        return bool(key)

    def make_client(self):
        key, _source = self.keystore.resolve()
        if not key:
            return None
        return AnthropicClient(key, self.model_name())

    def note_usage(self, usage) -> None:
        if self._session_usage is None:
            self._session_usage = usage
        else:
            self._session_usage = self._session_usage.add(usage)
        self.ai_panel.usage.setText(format_usage(self.model_name(), self._session_usage) + " (estimate)")

    def status(self, text: str) -> None:
        self.statusBar().showMessage(scrub(text), 8000)

    def touch(self) -> None:
        self.controller.recompute()
        self._refresh_chrome()
        current = self._current_screen()
        if current is not None:
            current.show_analysis(self.controller.analysis)
        if self.autosave_enabled:
            self._autosave_timer.start(1200)

    def refresh_all(self) -> None:
        self._refresh_chrome()
        for screen in self.screens:
            screen.load()
            screen.show_analysis(self.controller.analysis)
        self.ai_panel.refresh_state()

    def _current_screen(self):
        row = self.nav.currentRow()
        if row < 0 or row >= len(self.screens):
            return None
        return self.screens[row]

    def _goto(self, row: int) -> None:
        if row < 0 or row >= len(self.screens):
            return
        self.stack.setCurrentIndex(row)
        screen = self.screens[row]
        screen.load()
        screen.show_analysis(self.controller.analysis)
        _screen_id, title = NAV[row]
        self.results.show_checks(screen.screen_id, self.controller.analysis, title)

    def _refresh_chrome(self) -> None:
        analysis = self.controller.analysis
        project = self.controller.project
        for screen_id, _title in NAV:
            badge = self.badges[screen_id]
            if screen_id == "settings":
                text = "ON" if self.ai_available() else "OFF"
                color = STATUS_COLORS["PASS"] if text == "ON" else "#5D6D7E"
            else:
                text = analysis.screen_status.get(screen_id, "INFO")
                color = STATUS_COLORS.get(text, "#5D6D7E")
            badge.setText(text)
            badge.setStyleSheet(f"background: {color}; color: white; border-radius: 8px; padding: 2px 6px; font-weight: 700;")
        extra = "SYNTHETIC" if project.meta.synthetic else ""
        self.banner.set_extra(extra)
        worst = "PASS"
        rank = {"PASS": 0, "INFO": 1, "WARN": 2, "FAIL": 3, "BLOCKED": 4}
        for value in analysis.screen_status.values():
            if rank.get(value, 0) > rank.get(worst, 0):
                worst = value
        self.setWindowTitle(f"BESS WorkBench — {project.meta.name} — {worst}")
        row = self.nav.currentRow()
        if row >= 0:
            self.results.show_checks(self.screens[row].screen_id, analysis, NAV[row][1])

    def new_project(self) -> None:
        self.controller = ProjectController(build_new_project(self.controller.rules), self.controller.rules)
        self.path = None
        self.refresh_all()
        self.status("New project.")

    def open_project(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Open project", "", "BESS project (*.bessproj *.json)")
        if name:
            self.load_path(Path(name))

    def open_sample(self) -> None:
        path = sample_file()
        if not path.is_file():
            QMessageBox.warning(self, "Sample", f"Sample file was not found at {path}")
            return
        # Unsaved copy: autosave must not write to the bundled file (a temp extraction in the one-file build).
        self.load_path(path, as_copy=True)

    def load_path(self, path: Path, as_copy: bool = False) -> None:
        try:
            project = load_project(path)
        except Exception as exc:
            QMessageBox.warning(self, "Open project", scrub(str(exc)))
            return
        self.controller = ProjectController(project, self.controller.rules)
        if as_copy:
            self.path = None
        else:
            self.path = path
            self._remember(path)
        self.refresh_all()
        self.status(f"Opened {path.name} as an unsaved copy. Use Save As to keep changes." if as_copy else f"Opened {path.name}")

    def save(self) -> None:
        if self.path is None:
            self.save_as()
            return
        self._write(self.path)

    def save_as(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, "Save project", "project.bessproj", "BESS project (*.bessproj)")
        if not name:
            return
        path = Path(name)
        if path.suffix.lower() != ".bessproj":
            path = path.with_suffix(".bessproj")
        self.path = path
        self._write(path)
        self._remember(path)

    def _write(self, path: Path) -> None:
        save_project(self.controller.project, path)
        self.status(f"Saved {path.name}")

    def _autosave(self) -> None:
        if not self.autosave_enabled:
            return
        try:
            if self.path is not None:
                save_project(self.controller.project, self.path)
                self.status(f"Autosaved {self.path.name}")
            else:
                target = self._recovery_path()
                save_project(self.controller.project, target)
                self.status("Autosaved a recovery copy")
        except Exception as exc:
            self.status("Autosave failed: " + scrub(str(exc)))

    def _recovery_path(self) -> Path:
        base = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation) or ".")
        base.mkdir(parents=True, exist_ok=True)
        return base / "autosave.bessproj"

    def _remember(self, path: Path) -> None:
        recent = list(self.settings.value("recent", []) or [])
        text = str(path)
        recent = [item for item in recent if item != text]
        recent.insert(0, text)
        self.settings.setValue("recent", recent[:8])
        self._rebuild_recent()

    def _rebuild_recent(self) -> None:
        self.recent_menu.clear()
        recent = list(self.settings.value("recent", []) or [])
        if not recent:
            action = self.recent_menu.addAction("None")
            action.setEnabled(False)
            return
        for item in recent:
            action = self.recent_menu.addAction(item)
            action.triggered.connect(lambda _checked=False, path=item: self.load_path(Path(path)))

    def reload_rules(self) -> None:
        rules = load_rules()
        self.controller.rules = rules
        self.controller.recompute()
        self.refresh_all()
        self.status(f"Reloaded {rules_file().name} {rules.version}")

    def open_intake(self) -> None:
        IntakeDialog(self, self).exec()

    def about(self) -> None:
        rules = self.controller.rules
        AboutDialog(f"{rules.ruleset_id} {rules.version}", self).exec()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.autosave_enabled:
            self._autosave()
        event.accept()


def run(args=None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("BESS WorkBench")
    app.setOrganizationName("BESSWorkBench")
    app.setStyle("Fusion")
    window = MainWindow(autosave=True)
    if args is not None and getattr(args, "sample", False):
        window.open_sample()
    elif args is not None and getattr(args, "project", None):
        window.load_path(Path(args.project))
    window.show()
    return app.exec()


def install_excepthook() -> None:
    def hook(exc_type, exc, tb):
        text = scrub("".join(traceback.format_exception(exc_type, exc, tb)))
        try:
            base = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation) or ".")
            base.mkdir(parents=True, exist_ok=True)
            (base / "error.log").write_text(text, encoding="utf-8")
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook
