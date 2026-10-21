"""Side chat. Edits stop for a confirm dialog before they touch the project."""

from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from bess_workbench.ai.assistant import AppliedEvent, Assistant, ErrorEvent
from bess_workbench.ai.client import StreamDone, TextDelta
from bess_workbench.ai.pricing import format_usage
from bess_workbench.ai.redact import scrub
from bess_workbench.paths import rules_file
from bess_workbench.ui.dialogs import ConfirmDialog


class _ChatThread(QThread):
    delta = Signal(str)
    failed = Signal(str)
    usage = Signal(object)
    finished_ok = Signal()

    def __init__(self, assistant: Assistant, text: str) -> None:
        super().__init__()
        self.assistant = assistant
        self.text = text
        self._gate = threading.Event()
        self._approved = False

    def decide(self, approved: bool) -> None:
        self._approved = approved
        self._gate.set()

    def run(self) -> None:
        def approver(proposal):
            self._gate.clear()
            self.proposal_box(proposal)
            self._gate.wait(timeout=600)
            return self._approved

        try:
            for event in self.assistant.send(self.text, approver):
                if isinstance(event, TextDelta):
                    self.delta.emit(event.text)
                elif isinstance(event, ErrorEvent):
                    self.failed.emit(event.message)
                elif isinstance(event, StreamDone):
                    self.usage.emit(self.assistant.usage)
                elif isinstance(event, AppliedEvent) and event.approved:
                    self.delta.emit("\n[Applied] " + event.detail + "\n")
        except Exception as exc:
            self.failed.emit(scrub(str(exc)))
        self.finished_ok.emit()

    def proposal_box(self, proposal) -> None:
        """Overridden on the instance from the UI thread via a queued signal."""
        self._pending = proposal


class AIPanel(QWidget):
    ask_approval = Signal(object)

    def __init__(self, host) -> None:
        super().__init__()
        self.host = host
        self.assistant: Assistant | None = None
        self.thread: _ChatThread | None = None
        self._buffer = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("AI assistant")
        title.setObjectName("screenTitle")
        layout.addWidget(title)
        self.state = QLabel("")
        self.state.setWordWrap(True)
        self.state.setObjectName("muted")
        layout.addWidget(self.state)
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        layout.addWidget(self.transcript, 1)
        row = QHBoxLayout()
        self.input = QTextEdit()
        self.input.setFixedHeight(64)
        self.input.setPlaceholderText("Ask about this project. Cite rule ids. Edits need approval.")
        self.send = QPushButton("Send")
        self.send.clicked.connect(self._send)
        row.addWidget(self.input, 1)
        row.addWidget(self.send)
        layout.addLayout(row)
        self.usage = QLabel("Tokens —")
        self.usage.setObjectName("muted")
        layout.addWidget(self.usage)
        self.ask_approval.connect(self._confirm)
        self.refresh_state()

    def refresh_state(self) -> None:
        if self.host.ai_available():
            self.state.setText("AI is on. Answers use the project and the rules file. A proposed edit waits for approval and never overrides a calc by itself.")
            self.input.setEnabled(True)
            self.send.setEnabled(True)
        else:
            self.state.setText("AI is off — no API key. Add one in Settings. Checks, reports, and the sample still work offline.")
            self.input.setEnabled(False)
            self.send.setEnabled(False)
            if not self.transcript.toPlainText():
                self.transcript.setPlainText("AI features are disabled.")

    def _send(self) -> None:
        text = self.input.toPlainText().strip()
        if not text or not self.host.ai_available():
            return
        client = self.host.make_client()
        if client is None:
            self.refresh_state()
            return
        rules_text = rules_file().read_text(encoding="utf-8")
        self.assistant = Assistant(client, self.host.controller, rules_text)
        self.transcript.append(f"\nYou: {text}\n")
        self.transcript.append("Assistant: ")
        self._buffer = ""
        self.input.clear()
        self.send.setEnabled(False)
        self.thread = _ChatThread(self.assistant, text)
        original = self.thread.proposal_box

        def emit_proposal(proposal):
            original(proposal)
            self.ask_approval.emit(proposal)

        self.thread.proposal_box = emit_proposal
        self.thread.delta.connect(self._on_delta)
        self.thread.failed.connect(self._on_fail)
        self.thread.usage.connect(self._on_usage)
        self.thread.finished_ok.connect(self._on_done)
        self.thread.start()

    def _on_delta(self, text: str) -> None:
        self._buffer += text
        cursor = self.transcript.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self.transcript.setTextCursor(cursor)

    def _on_fail(self, message: str) -> None:
        self.transcript.append("\n" + message + "\n")

    def _on_usage(self, usage) -> None:
        model = getattr(self.assistant.client, "model", "") if self.assistant else ""
        self.usage.setText(format_usage(model, usage) + " (estimate)")

    def _on_done(self) -> None:
        self.send.setEnabled(self.host.ai_available())
        self.host.refresh_all()

    def _confirm(self, proposal) -> None:
        dialog = ConfirmDialog(proposal.preview, self)
        approved = dialog.exec() == ConfirmDialog.DialogCode.Accepted
        if self.thread is not None:
            self.thread.decide(approved)
