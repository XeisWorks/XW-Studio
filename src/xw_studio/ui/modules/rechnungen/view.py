"""Rechnungen module — invoice list from sevDesk."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import QLabel, QMessageBox, QVBoxLayout, QWidget

from xw_studio.core.signals import AppSignals
from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.invoice_processing.service import InvoiceProcessingService
from xw_studio.ui.widgets.data_table import DataTable
from xw_studio.ui.widgets.progress_overlay import ProgressOverlay
from xw_studio.ui.widgets.search_bar import SearchBar
from xw_studio.ui.widgets.toolbar import Toolbar

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)

_TABLE_COLUMNS = [
    "Rechnungsnr.",
    "Datum",
    "Status",
    "Brutto EUR",
    "Kunde",
    "ID",
]


class RechnungenView(QWidget):
    """Load and display sevDesk invoices (non-blocking)."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._worker: BackgroundWorker | None = None
        self._did_initial_load = False
        self._print_allowed = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._hint = QLabel()
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        toolbar = Toolbar()
        refresh = toolbar.add_button(
            "refresh",
            "Aktualisieren",
            tooltip="Rechnungen von sevDesk laden",
        )
        refresh.clicked.connect(self._load_invoices)
        self._btn_print = toolbar.add_button(
            "print",
            "PDF drucken…",
            tooltip="PDF-Datei mit dem konfigurierten Drucker drucken",
        )
        self._btn_print.clicked.connect(self._on_print_clicked)
        self._btn_print.setEnabled(False)
        toolbar.add_stretch()
        layout.addWidget(toolbar)

        self._search = SearchBar("Suchen…")
        layout.addWidget(self._search)

        self._table = DataTable(_TABLE_COLUMNS)
        layout.addWidget(self._table, stretch=1)

        self._overlay = ProgressOverlay(self)
        self._overlay.hide()

        self._search.search_changed.connect(self._on_search)

        self._update_token_hint()

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.printer_status_changed.connect(self._on_printer_status)

    def _update_token_hint(self) -> None:
        token = (self._container.config.sevdesk.api_token or "").strip()
        if not token:
            self._hint.setText(
                "Kein sevDesk-API-Token gesetzt. Bitte SEVDESK_API_TOKEN in der "
                "Umgebung oder in .env eintragen."
            )
            self._hint.setStyleSheet("color: #ffa726; padding: 8px;")
            self._hint.show()
        else:
            self._hint.hide()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._did_initial_load:
            self._did_initial_load = True
            if (self._container.config.sevdesk.api_token or "").strip():
                self._load_invoices()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._overlay.isVisible():
            self._overlay.setGeometry(self.rect())

    def _on_search(self, text: str) -> None:
        self._table.set_filter(text, column=0)

    def _on_printer_status(self, printing_allowed: bool) -> None:
        self._print_allowed = printing_allowed
        self._btn_print.setEnabled(printing_allowed)

    def _load_invoices(self) -> None:
        if not (self._container.config.sevdesk.api_token or "").strip():
            return

        service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
        self._overlay.show_with_message("Rechnungen werden geladen…")
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

        def job() -> list[dict[str, str]]:
            return service.load_invoice_table_rows()

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_loaded)
        self._worker.signals.error.connect(self._on_load_error)
        self._worker.signals.finished.connect(self._on_load_finished)
        self._worker.start()

    def _on_loaded(self, rows: object) -> None:
        if not isinstance(rows, list):
            logger.warning("Unexpected invoice load result type: %s", type(rows))
            return
        typed: list[dict[str, Any]] = [r for r in rows if isinstance(r, dict)]
        self._table.set_data(typed)
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit(f"{len(typed)} Rechnungen geladen", 4000)

    def _on_load_error(self, exc: Exception) -> None:
        logger.error("Invoice load failed: %s", exc)
        QMessageBox.warning(
            self,
            "Fehler",
            f"Rechnungen konnten nicht geladen werden:\n\n{exc}",
        )

    def _on_load_finished(self) -> None:
        self._overlay.hide()

    def _on_print_clicked(self) -> None:
        if not self._print_allowed:
            return
        from xw_studio.ui.modules.rechnungen.print_dialog import run_invoice_pdf_print

        run_invoice_pdf_print(self, self._container)
