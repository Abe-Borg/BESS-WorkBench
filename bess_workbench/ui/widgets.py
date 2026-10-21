"""Shared widgets."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bess_workbench.ui.theme import STATUS_COLORS

DISCLAIMER = "Design aid. Verify values against adopted codes and AHJ."


class Banner(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("banner")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        self.text = QLabel(DISCLAIMER)
        self.text.setObjectName("bannerText")
        self.extra = QLabel("")
        self.extra.setObjectName("bannerText")
        layout.addWidget(self.text)
        layout.addStretch(1)
        layout.addWidget(self.extra)

    def set_extra(self, text: str) -> None:
        self.extra.setText(text)


class Screen(QScrollArea):
    screen_id = ""

    def __init__(self, host) -> None:
        super().__init__()
        self.host = host
        self.loading = False
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(16, 16, 16, 16)
        self.body_layout.setSpacing(10)
        self.setWidget(self.body)

    def add_title(self, text: str) -> None:
        label = QLabel(text)
        label.setObjectName("screenTitle")
        self.body_layout.addWidget(label)

    def project(self):
        return self.host.controller.project

    def touch(self) -> None:
        if self.loading:
            return
        self.host.touch()

    def load(self) -> None:
        return

    def show_analysis(self, analysis) -> None:
        return


def spin(minimum: float, maximum: float, decimals: int = 2, step: float = 1) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    return box


def ispin(minimum: int, maximum: int) -> QSpinBox:
    box = QSpinBox()
    box.setRange(minimum, maximum)
    return box


def muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def fill_table(table, rows: list[list[str]]) -> None:
    table.blockSignals(True)
    table.setRowCount(len(rows))
    for row_index, values in enumerate(rows):
        for col_index, value in enumerate(values):
            from PySide6.QtWidgets import QTableWidgetItem

            item = QTableWidgetItem("" if value is None else str(value))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_index, col_index, item)
    table.blockSignals(False)


def panel(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    if title:
        label = QLabel(title)
        label.setObjectName("screenTitle")
        layout.addWidget(label)
    return frame, layout
