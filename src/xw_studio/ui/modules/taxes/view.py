"""Steuern module — UVA, Clearing, Ausgaben with non-blocking actions."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.signals import AppSignals
from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.clearing.service import PaymentClearingService
from xw_studio.services.expenses.service import ExpenseAuditService
from xw_studio.services.finanzonline import UvaService, UvaSubmitResult

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)


class TaxesView(QWidget):
    """UVA | Clearing | Ausgaben — calls services off the UI thread."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._worker: BackgroundWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        tabs = QTabWidget()

        tabs.addTab(self._build_uva_tab(), "UVA")
        tabs.addTab(self._build_clearing_tab(), "Clearing")
        tabs.addTab(self._build_expenses_tab(), "Ausgaben")
        outer.addWidget(tabs)

    def _build_uva_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        info = QPlainTextEdit()
        uva: UvaService = self._container.resolve(UvaService)
        info.setPlainText(uva.describe_capabilities())
        info.setReadOnly(True)
        layout.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(QLabel("Jahr:"))
        year = QSpinBox()
        year.setRange(2000, 2100)
        year.setValue(2026)
        row.addWidget(year)
        row.addWidget(QLabel("Monat:"))
        month = QSpinBox()
        month.setRange(1, 12)
        month.setValue(1)
        row.addWidget(month)
        row.addStretch()
        layout.addLayout(row)

        preview = QPushButton("Preview-Payload erzeugen")
        submit = QPushButton("UVA senden (SOAP)")

        def on_preview() -> None:
            payload = uva.mock_build_payload(year.value(), month.value())
            info.appendPlainText("\n\n" + repr(payload))

        def on_submit() -> None:
            payload = uva.mock_build_payload(year.value(), month.value())

            def job() -> UvaSubmitResult:
                return uva.submit_uva(payload)

            self._worker = BackgroundWorker(job)

            def on_uva_result(res: object) -> None:
                if not isinstance(res, UvaSubmitResult) or not res.ok:
                    return
                text = res.message + (f" (Ref. {res.reference_id})" if res.reference_id else "")
                QMessageBox.information(self, "UVA", f"Erfolg: {text}")

            self._worker.signals.result.connect(on_uva_result)
            self._worker.signals.error.connect(
                lambda exc: QMessageBox.information(
                    self,
                    "UVA",
                    f"Fehler: {exc}",
                )
            )
            self._worker.signals.finished.connect(
                lambda: self._container.resolve(AppSignals).status_message.emit("UVA-Job beendet", 3000)
            )
            self._worker.start()

        preview.clicked.connect(on_preview)
        submit.clicked.connect(on_submit)
        layout.addWidget(preview)
        layout.addWidget(submit)
        return page

    def _build_clearing_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        svc: PaymentClearingService = self._container.resolve(PaymentClearingService)
        box = QGroupBox("Zahlungsclearing")
        bl = QVBoxLayout(box)
        bl.addWidget(QLabel(svc.describe()))
        status = QLabel("Offene Zuordnungen (Mock): 0")
        bl.addWidget(status)
        refresh = QPushButton("Platzhalter aktualisieren")

        def on_refresh() -> None:
            pending = svc.list_pending_mock()
            status.setText(f"Offene Zuordnungen (Mock): {len(pending)}")

        refresh.clicked.connect(on_refresh)
        bl.addWidget(refresh)
        layout.addWidget(box)
        layout.addStretch()
        return page

    def _build_expenses_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        svc: ExpenseAuditService = self._container.resolve(ExpenseAuditService)
        layout.addWidget(QLabel(svc.describe()))
        btn = QPushButton("Offene Belege (Mock)")
        btn.clicked.connect(lambda: QMessageBox.information(self, "Ausgaben", str(svc.list_open_mock())))
        layout.addWidget(btn)
        layout.addStretch()
        return page
