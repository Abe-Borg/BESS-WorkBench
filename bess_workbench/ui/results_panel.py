"""Right-hand check list for the screen that is open."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from bess_workbench.ui.theme import STATUS_COLORS


class ResultsPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.heading = QLabel("Results")
        self.heading.setObjectName("screenTitle")
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        layout.addWidget(self.heading)
        layout.addWidget(self.summary)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.holder = QWidget()
        self.cards = QVBoxLayout(self.holder)
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.addStretch(1)
        self.scroll.setWidget(self.holder)
        layout.addWidget(self.scroll, 1)

    def show_checks(self, screen_id: str, analysis, title: str) -> None:
        self.heading.setText(title)
        while self.cards.count():
            item = self.cards.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.scroll.verticalScrollBar().setValue(0)
        if analysis is None or screen_id == "settings":
            note = QLabel("Settings do not change a calc. The rules engine remains the source of pass/fail.")
            note.setWordWrap(True)
            self.cards.addWidget(note)
            self.cards.addStretch(1)
            self.summary.setText("")
            return
        checks = [item for item in analysis.checks if item.screen == screen_id]
        counts: dict[str, int] = {}
        for check in checks:
            counts[check.status.value] = counts.get(check.status.value, 0) + 1
        self.summary.setText(" · ".join(f"{counts.get(name, 0)} {name}" for name in ("BLOCKED", "FAIL", "WARN", "INFO", "PASS")))
        if not checks:
            empty = QLabel("No checks on this screen.")
            empty.setObjectName("muted")
            self.cards.addWidget(empty)
        for check in checks:
            self.cards.addWidget(_card(check))
        self.cards.addStretch(1)


def _card(check) -> QFrame:
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(8, 8, 8, 8)
    color = STATUS_COLORS.get(check.status.value, "#5D6D7E")
    status = QLabel(f"{check.status.value}  {check.title}")
    status.setStyleSheet(f"color: {color}; font-weight: 700; background: transparent;")
    status.setWordWrap(True)
    message = QLabel(check.message)
    message.setWordWrap(True)
    value = QLabel(f"Value: {check.value}")
    value.setWordWrap(True)
    cite = QLabel(f"{check.citation} · {check.edition}")
    cite.setObjectName("muted")
    cite.setWordWrap(True)
    tags = QLabel("Tags: " + (", ".join(check.tags) if check.tags else "—"))
    tags.setObjectName("muted")
    tags.setWordWrap(True)
    for widget in (status, message, value, cite, tags):
        layout.addWidget(widget)
    return frame
