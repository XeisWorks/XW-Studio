"""Rechnungen module — invoice list from sevDesk."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.signals import AppSignals
from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.invoice_processing.service import InvoiceProcessingService
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary
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
    "Land",
    "Notiz",
    "ID",
]

_PAGE_SIZE = 50


class RechnungenView(QWidget):
    """Load and display sevDesk invoices (non-blocking)."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._worker: BackgroundWorker | None = None
        self._did_initial_load = False
        self._print_allowed = False
        self._next_offset = 0
        self._summaries: list[InvoiceSummary] = []
        self._append_mode = False
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
            tooltip="Erste Seite neu laden (aktueller Statusfilter)",
        )
        refresh.clicked.connect(self._reload_first_page)
        self._btn_print = toolbar.add_button(
            "print",
            "PDF drucken…",
            tooltip="PDF mit Rechnungs-DPI (und Seitenbereich aus dem Druckdialog)",
        )
        self._btn_print.clicked.connect(self._on_print_clicked)
        self._btn_print.setEnabled(False)
        self._btn_print_label = toolbar.add_button(
            "print_label",
            "Label drucken…",
            tooltip="PDF fuer Versandetiketten drucken (Seitenbereich aus dem Druckdialog)",
        )
        self._btn_print_label.clicked.connect(self._on_print_label_clicked)
        self._btn_print_label.setEnabled(False)
        self._btn_print_music = toolbar.add_button(
            "print_music",
            "Noten drucken…",
            tooltip="PDF mit 600 DPI fuer Noten (Seitenbereich aus dem Druckdialog)",
        )
        self._btn_print_music.clicked.connect(self._on_print_music_clicked)
        self._btn_print_music.setEnabled(False)
        toolbar.add_stretch()
        layout.addWidget(toolbar)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("Status:"))
        self._status_combo = QComboBox()
        self._status_combo.setMinimumWidth(220)
        self._status_combo.blockSignals(True)
        for label, code in [
            ("Alle", None),
            ("Offen", 200),
            ("Bezahlt", 1000),
            ("Entwurf", 100),
            ("Teilweise bezahlt", 300),
        ]:
            self._status_combo.addItem(label, code)
        self._status_combo.setCurrentIndex(1)
        self._status_combo.blockSignals(False)
        self._status_combo.currentIndexChanged.connect(self._on_status_filter_changed)
        filter_row.addWidget(self._status_combo)
        filter_row.addStretch()
        self._btn_more = QPushButton("Weitere laden")
        self._btn_more.setToolTip(f"Naechste bis zu {_PAGE_SIZE} Rechnungen anhaengen")
        self._btn_more.clicked.connect(self._load_more)
        filter_row.addWidget(self._btn_more)
        layout.addLayout(filter_row)

        self._search = SearchBar("Suchen…")
        layout.addWidget(self._search)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._table = DataTable(_TABLE_COLUMNS)
        splitter.addWidget(self._table)

        # --- Structured detail panel ---
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setMinimumWidth(260)

        detail_content = QWidget()
        detail_main = QVBoxLayout(detail_content)
        detail_main.setContentsMargins(8, 8, 8, 8)
        detail_main.setSpacing(10)

        gb_invoice = QGroupBox("Rechnung")
        form_inv = QFormLayout(gb_invoice)
        self._dl_number = QLabel("—")
        self._dl_date = QLabel("—")
        self._dl_status = QLabel("—")
        self._dl_brutto = QLabel("—")
        form_inv.addRow("Nummer:", self._dl_number)
        form_inv.addRow("Datum:", self._dl_date)
        form_inv.addRow("Status:", self._dl_status)
        form_inv.addRow("Brutto:", self._dl_brutto)
        detail_main.addWidget(gb_invoice)

        gb_contact = QGroupBox("Kunde")
        form_con = QFormLayout(gb_contact)
        self._dl_contact = QLabel("—")
        self._dl_contact.setWordWrap(True)
        self._dl_country = QLabel("—")
        self._dl_id = QLabel("—")
        form_con.addRow("Name:", self._dl_contact)
        form_con.addRow("Land:", self._dl_country)
        form_con.addRow("ID:", self._dl_id)
        detail_main.addWidget(gb_contact)

        self._gb_note = QGroupBox("Käufernotiz")
        note_layout = QVBoxLayout(self._gb_note)
        self._dl_note = QLabel()
        self._dl_note.setWordWrap(True)
        note_layout.addWidget(self._dl_note)
        self._gb_note.hide()
        detail_main.addWidget(self._gb_note)

        detail_main.addStretch()
        detail_scroll.setWidget(detail_content)

        splitter.addWidget(detail_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, stretch=1)

        self._overlay = ProgressOverlay(self)
        self._overlay.hide()

        self._search.search_changed.connect(self._on_search)
        sel = self._table.selectionModel()
        if sel is not None:
            sel.selectionChanged.connect(self._on_table_selection_changed)

        self._update_token_hint()

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.printer_status_changed.connect(self._on_printer_status)

    def _current_status(self) -> int | None:
        data = self._status_combo.currentData()
        if data is None:
            return None
        if isinstance(data, int):
            return data
        try:
            return int(data)
        except (TypeError, ValueError):
            return None

    def _on_status_filter_changed(self, _index: int) -> None:
        if not (self._container.config.sevdesk.api_token or "").strip():
            return
        self._reload_first_page()

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
                self._reload_first_page()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._overlay.isVisible():
            self._overlay.setGeometry(self.rect())

    def _on_search(self, text: str) -> None:
        self._table.set_filter(text, column=0)

    def _on_printer_status(self, printing_allowed: bool) -> None:
        self._print_allowed = printing_allowed
        self._btn_print.setEnabled(printing_allowed)
        self._btn_print_label.setEnabled(printing_allowed)
        self._btn_print_music.setEnabled(printing_allowed)

    def _reload_first_page(self) -> None:
        self._next_offset = 0
        self._append_mode = False
        self._start_load()

    def _load_more(self) -> None:
        if not (self._container.config.sevdesk.api_token or "").strip():
            return
        self._append_mode = True
        self._start_load()

    def _start_load(self) -> None:
        if not (self._container.config.sevdesk.api_token or "").strip():
            return

        service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
        status = self._current_status()
        offset = self._next_offset if self._append_mode else 0
        append = self._append_mode

        self._overlay.show_with_message(
            "Rechnungen werden geladen…" if not append else "Weitere Rechnungen werden geladen…",
        )
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

        def job() -> tuple[list[dict[str, str]], list[InvoiceSummary], bool]:
            rows, sums = service.load_invoice_batch(
                status=status,
                limit=_PAGE_SIZE,
                offset=offset,
            )
            has_more = len(sums) >= _PAGE_SIZE
            return rows, sums, has_more

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_load_result)
        self._worker.signals.error.connect(self._on_load_error)
        self._worker.signals.finished.connect(self._on_load_finished)
        self._worker.start()

    def _on_load_result(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 3:
            logger.warning("Unexpected invoice load payload: %s", type(payload))
            return
        rows_obj, sums_obj, has_more_obj = payload
        if not isinstance(rows_obj, list) or not isinstance(sums_obj, list):
            return
        rows: list[dict[str, Any]] = [r for r in rows_obj if isinstance(r, dict)]
        summaries: list[InvoiceSummary] = [s for s in sums_obj if isinstance(s, InvoiceSummary)]
        has_more = bool(has_more_obj)

        if self._append_mode:
            self._table.append_rows(rows)
            self._summaries.extend(summaries)
        else:
            self._table.set_data(rows)
            self._summaries = summaries

        self._next_offset = len(self._summaries)
        self._btn_more.setEnabled(has_more)

        signals: AppSignals = self._container.resolve(AppSignals)
        mode = "angehaengt" if self._append_mode else "geladen"
        signals.status_message.emit(
            f"{len(rows)} Rechnungen {mode} ({self._next_offset} gesamt in Liste)",
            5000,
        )
        self._append_mode = False
        self._refresh_detail_for_selection()

    def _on_load_error(self, exc: Exception) -> None:
        logger.error("Invoice load failed: %s", exc)
        QMessageBox.warning(
            self,
            "Fehler",
            f"Rechnungen konnten nicht geladen werden:\n\n{exc}",
        )
        self._append_mode = False

    def _on_load_finished(self) -> None:
        self._overlay.hide()

    def _on_print_clicked(self) -> None:
        if not self._print_allowed:
            return
        from xw_studio.ui.modules.rechnungen.print_dialog import run_invoice_pdf_print

        run_invoice_pdf_print(self, self._container)

    def _on_print_label_clicked(self) -> None:
        if not self._print_allowed:
            return
        from xw_studio.ui.modules.rechnungen.print_dialog import run_label_pdf_print

        run_label_pdf_print(self, self._container)

    def _on_print_music_clicked(self) -> None:
        if not self._print_allowed:
            return
        from xw_studio.ui.modules.rechnungen.print_dialog import run_music_pdf_print

        run_music_pdf_print(self, self._container)

    def _on_table_selection_changed(
        self,
        _selected: Any,
        _deselected: Any,
    ) -> None:
        self._refresh_detail_for_selection()

    def _refresh_detail_for_selection(self) -> None:
        row = self._table.selected_source_row()
        if row is None or row < 0 or row >= len(self._summaries):
            self._reset_detail()
            return
        s = self._summaries[row]
        self._dl_number.setText(s.invoice_number or "—")
        self._dl_date.setText(s.invoice_date or "—")
        self._dl_status.setText(s.status_label())
        self._dl_brutto.setText(str(s.sum_gross) if s.sum_gross is not None else "—")
        self._dl_contact.setText(s.contact_name or "—")
        self._dl_country.setText(s.address_country_code or "—")
        self._dl_id.setText(s.id)
        if s.buyer_note.strip():
            self._dl_note.setText(s.buyer_note)
            self._gb_note.show()
        else:
            self._dl_note.setText("")
            self._gb_note.hide()

    def _reset_detail(self) -> None:
        for lbl in (
            self._dl_number, self._dl_date, self._dl_status, self._dl_brutto,
            self._dl_contact, self._dl_country, self._dl_id,
        ):
            lbl.setText("—")
        self._dl_note.setText("")
        self._gb_note.hide()
