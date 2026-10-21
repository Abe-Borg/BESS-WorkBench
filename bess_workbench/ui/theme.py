"""Light and dark styles for the workbench."""

from __future__ import annotations

LIGHT = """
* { font-family: "Segoe UI", "Ubuntu", "Noto Sans", sans-serif; font-size: 13px; color: #1C2833; }
QMainWindow, QDialog, QWidget { background: #F4F6F8; }
QScrollArea, QStackedWidget { background: transparent; border: none; }
QFrame#panel, QTextEdit, QPlainTextEdit, QTableWidget, QListWidget, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {
  background: #FFFFFF;
  border: 1px solid #D5DCE3;
  border-radius: 6px;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit { padding: 4px 6px; min-height: 22px; }
QTextEdit, QPlainTextEdit { padding: 6px; }
QPushButton {
  background: #1F4E79;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 6px 12px;
}
QPushButton:hover { background: #163A5C; }
QPushButton:disabled { background: #C5CED6; color: #F4F6F8; }
QPushButton#secondary { background: #E8EEF4; color: #1F4E79; }
QPushButton#secondary:hover { background: #D5DCE3; }
QFrame#banner { background: #FFF8E6; border: 1px solid #F5D48A; border-radius: 8px; }
QLabel#bannerText { color: #7A4E00; font-weight: 600; background: transparent; }
QLabel#muted { color: #5D6D7E; }
QLabel#screenTitle { font-size: 18px; font-weight: 650; color: #1F4E79; }
QListWidget#nav { background: #FFFFFF; border: 1px solid #D5DCE3; border-radius: 8px; padding: 6px; }
QListWidget#nav::item { border-radius: 6px; padding: 4px; }
QListWidget#nav::item:selected { background: #E5F0FA; color: #1F4E79; }
QHeaderView::section { background: #1F4E79; color: white; border: none; padding: 6px; font-weight: 600; }
QTableWidget { gridline-color: #E6EBF0; selection-background-color: #E5F0FA; selection-color: #1C2833; }
QGroupBox { border: 1px solid #D5DCE3; border-radius: 8px; margin-top: 12px; padding: 8px; background: #FFFFFF; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #1F4E79; }
QStatusBar { background: #FFFFFF; color: #5D6D7E; }
QMenuBar { background: #FFFFFF; }
QMenu { background: #FFFFFF; border: 1px solid #D5DCE3; }
QSplitter::handle { background: #E6EBF0; }
"""

DARK = """
* { font-family: "Segoe UI", "Ubuntu", "Noto Sans", sans-serif; font-size: 13px; color: #E8EEF4; }
QMainWindow, QDialog, QWidget { background: #1B1F24; }
QScrollArea, QStackedWidget { background: transparent; border: none; }
QFrame#panel, QTextEdit, QPlainTextEdit, QTableWidget, QListWidget, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {
  background: #242A31;
  border: 1px solid #3A4450;
  border-radius: 6px;
  color: #E8EEF4;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit { padding: 4px 6px; min-height: 22px; }
QTextEdit, QPlainTextEdit { padding: 6px; }
QPushButton { background: #2F6FA8; color: white; border: none; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background: #3C82C3; }
QPushButton:disabled { background: #3A4450; color: #8B98A5; }
QPushButton#secondary { background: #2C3540; color: #D6E4F0; }
QFrame#banner { background: #3A3324; border: 1px solid #8A7040; border-radius: 8px; }
QLabel#bannerText { color: #F5D48A; font-weight: 600; background: transparent; }
QLabel#muted { color: #A9B6C2; }
QLabel#screenTitle { font-size: 18px; font-weight: 650; color: #9CC7EE; }
QListWidget#nav { background: #242A31; border: 1px solid #3A4450; border-radius: 8px; padding: 6px; }
QListWidget#nav::item:selected { background: #2C3E50; }
QHeaderView::section { background: #1F4E79; color: white; border: none; padding: 6px; }
QTableWidget { gridline-color: #3A4450; selection-background-color: #2C3E50; selection-color: #E8EEF4; background: #242A31; }
QGroupBox { border: 1px solid #3A4450; border-radius: 8px; margin-top: 12px; padding: 8px; background: #242A31; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #9CC7EE; }
QStatusBar, QMenuBar, QMenu { background: #242A31; color: #E8EEF4; }
QSplitter::handle { background: #2C3540; }
"""

STATUS_COLORS = {
    "PASS": "#1E7F4F",
    "FAIL": "#B42318",
    "WARN": "#B54708",
    "BLOCKED": "#7A271A",
    "INFO": "#175CD3",
}


def stylesheet(dark: bool) -> str:
    return DARK if dark else LIGHT
