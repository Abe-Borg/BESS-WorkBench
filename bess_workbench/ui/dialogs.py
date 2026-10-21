"""About, edit confirmation, and PDF intake."""

from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bess_workbench import __version__
from bess_workbench.ai.intake import ReviewField, flatten_for_review
from bess_workbench.ui.widgets import DISCLAIMER, muted


class AboutDialog(QDialog):
    def __init__(self, ruleset_label: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About BESS WorkBench")
        self.resize(480, 320)
        layout = QVBoxLayout(self)
        title = QLabel(f"BESS WorkBench {__version__}")
        title.setObjectName("screenTitle")
        layout.addWidget(title)
        body = QLabel(
            "Design aid for lithium-ion BESS / ESS (UPS battery) rooms in US hyperscale data centers.\n\n"
            f"{DISCLAIMER}\n\n"
            f"Ruleset: {ruleset_label}\n\n"
            "The rules engine is the only source of pass/fail numbers. "
            "AI drafts and extractions do not override a calculation.\n\n"
            "Sprinklers: wet, dry, and double-interlock preaction only. "
            "Clean agent, foam, water mist, and single-interlock are out of scope. United States only."
        )
        body.setWordWrap(True)
        layout.addWidget(body)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class ConfirmDialog(QDialog):
    def __init__(self, preview: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Approve change")
        self.resize(560, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(muted("Nothing is written until you approve. The rules engine recomputes after an approved edit."))
        box = QPlainTextEdit(preview)
        box.setReadOnly(True)
        layout.addWidget(box)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Approve")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Reject")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class IntakeDialog(QDialog):
    """Drop a PDF, review extracted fields, and accept the ones to keep."""

    def __init__(self, host, parent=None) -> None:
        super().__init__(parent)
        self.host = host
        self.setWindowTitle("Document intake")
        self.resize(760, 520)
        self.path: Path | None = None
        self.extraction = None
        self._checks: list[QCheckBox] = []
        layout = QVBoxLayout(self)
        self.drop = QLabel("Drop a PDF here, or browse.\nUL 9540A report, vendor controls drawings, or a specification.")
        self.drop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop.setMinimumHeight(90)
        self.drop.setObjectName("panel")
        self.drop.setAcceptDrops(True)
        self.drop.dragEnterEvent = self._drag_enter
        self.drop.dropEvent = self._drop
        layout.addWidget(self.drop)
        row = QHBoxLayout()
        browse = QPushButton("Browse")
        browse.setObjectName("secondary")
        browse.clicked.connect(self._browse)
        self.extract_button = QPushButton("Extract with AI")
        self.extract_button.clicked.connect(self._extract)
        row.addWidget(browse)
        row.addWidget(self.extract_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.status = muted("")
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Accept", "Field", "Value", "Page"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        accept = QPushButton("Accept selected")
        accept.clicked.connect(self._accept_selected)
        close = QPushButton("Close")
        close.setObjectName("secondary")
        close.clicked.connect(self.reject)
        buttons.addWidget(accept)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._refresh_enabled()

    def _refresh_enabled(self) -> None:
        present = self.host.ai_available()
        self.extract_button.setEnabled(present and self.path is not None)
        if not present:
            self.status.setText("AI is off — no API key. You can still review fields if a preview is loaded. The rules engine is unchanged.")

    def _drag_enter(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def _drop(self, event) -> None:
        urls = event.mimeData().urls()
        if urls:
            self.set_path(urls[0].toLocalFile())

    def _browse(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF (*.pdf)")
        if name:
            self.set_path(name)

    def set_path(self, path: str) -> None:
        self.path = Path(path)
        self.drop.setText(self.path.name)
        self._refresh_enabled()

    def show_extraction(self, extraction) -> None:
        self.extraction = extraction
        rows = flatten_for_review(extraction)
        self._checks = []
        self.table.setRowCount(len(rows))
        for index, field in enumerate(rows):
            box = QCheckBox()
            box.setChecked(True)
            self._checks.append(box)
            holder = QWidget()
            lay = QHBoxLayout(holder)
            lay.setContentsMargins(4, 0, 0, 0)
            lay.addWidget(box)
            self.table.setCellWidget(index, 0, holder)
            self.table.setItem(index, 1, QTableWidgetItem(field.label))
            self.table.setItem(index, 2, QTableWidgetItem(field.value))
            self.table.setItem(index, 3, QTableWidgetItem("" if field.page is None else str(field.page)))
            self.table.item(index, 1).setData(Qt.ItemDataRole.UserRole, field.key)
        self.table.resizeColumnsToContents()
        self.status.setText(f"{len(rows)} field(s) ready to review. Accepted values are tagged with the document and page.")

    def _extract(self) -> None:
        if self.path is None or not self.host.ai_available():
            return
        self.extract_button.setEnabled(False)
        self.status.setText("Sending the PDF…")
        try:
            from bess_workbench.ai.intake import extraction_from_text
            from bess_workbench.ai.request import build_extract_kwargs

            payload = base64.standard_b64encode(self.path.read_bytes()).decode("ascii")
            client = self.host.make_client()
            kwargs = build_extract_kwargs(model=client.model, pdf_base64=payload, filename=self.path.name)
            text, usage = client.complete_text(kwargs)
            extraction = extraction_from_text(text, self.path.name)
            self.show_extraction(extraction)
            self.host.note_usage(usage)
        except Exception as exc:
            from bess_workbench.ai.redact import scrub

            self.status.setText("Extraction failed: " + scrub(str(exc)))
        finally:
            self._refresh_enabled()

    def _accept_selected(self) -> None:
        if self.extraction is None:
            self.status.setText("Nothing to accept yet.")
            return
        keys = []
        for index, box in enumerate(self._checks):
            if box.isChecked():
                item = self.table.item(index, 1)
                keys.append(item.data(Qt.ItemDataRole.UserRole))
        if not keys:
            self.status.setText("Select at least one field.")
            return
        from bess_workbench.ai.intake import apply_accepted

        document = self.path.name if self.path else self.extraction.document_name
        self.host.controller.project = apply_accepted(self.host.controller.project, self.extraction, keys, document)
        self.host.controller.recompute()
        self.host.refresh_all()
        self.status.setText(f"Accepted {len(keys)} field(s). They are tagged with {document}.")
