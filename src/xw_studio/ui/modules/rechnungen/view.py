"""Rechnungen module — invoice list from sevDesk."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QStyledItemDelegate,
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
from xw_studio.services.products.print_decision import PieceBlock, PrintDecisionEngine
from xw_studio.services.secrets.service import SecretService
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary
from xw_studio.services.sevdesk.part_client import PartClient
from xw_studio.services.wix.client import WixOrdersClient
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
    "Brutto",
    "Kunde",
    "Land",
    "Hinweise",
    "ID",
]

_PAGE_SIZE = 50


class _HintsIconDelegate(QStyledItemDelegate):
    """Paint invoice hint icons in a compact row-friendly style."""

    _ICON_FILES = {
        "print": "print.png",
        "printondemand": "printondemand.png",
        "alternateshippingaddress": "alternateshippingaddress.png",
        "country": "country.png",
        "plc": "plc.png",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cache: dict[str, QPixmap] = {}
        self._icons_dir = Path(__file__).resolve().parents[5] / "icons"

    def _icon_for_key(self, key: str) -> QPixmap | None:
        if key in self._cache:
            pix = self._cache[key]
            return pix if not pix.isNull() else None
        file_name = self._ICON_FILES.get(key)
        if not file_name:
            self._cache[key] = QPixmap()
            return None
        pix = QPixmap(str(self._icons_dir / file_name))
        self._cache[key] = pix
        return pix if not pix.isNull() else None

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        row_data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row_data, dict):
            super().paint(painter, option, index)
            return
        icon_keys = row_data.get("__icons__Hinweise")
        if not isinstance(icon_keys, list) or not icon_keys:
            super().paint(painter, option, index)
            return

        painter.save()
        size = min(18, max(14, option.rect.height() - 6))
        gap = 6
        total_width = len(icon_keys) * size + max(0, len(icon_keys) - 1) * gap
        x = option.rect.x() + max(4, (option.rect.width() - total_width) // 2)
        y = option.rect.y() + max(2, (option.rect.height() - size) // 2)

        for key in icon_keys:
            pix = self._icon_for_key(str(key))
            if pix is None:
                x += size + gap
                continue
            target = option.rect.adjusted(0, 0, 0, 0)
            target.setX(x)
            target.setY(y)
            target.setWidth(size)
            target.setHeight(size)
            painter.drawPixmap(target, pix)
            x += size + gap
        painter.restore()

    def sizeHint(self, option, index):  # type: ignore[override]
        base = super().sizeHint(option, index)
        if base.height() < 22:
            base.setHeight(22)
        return base


class RechnungenView(QWidget):
    """Load and display sevDesk invoices (non-blocking)."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._worker: BackgroundWorker | None = None
        self._stuecke_worker: BackgroundWorker | None = None
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
            ("Entwurf", 100),
            ("Offen", 200),
            ("Teilweise bezahlt", 300),
            ("Bezahlt", 1000),
        ]:
            self._status_combo.addItem(label, code)
        self._status_combo.setCurrentIndex(0)
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
        self._search.set_suggestion_provider(self._invoice_search_suggestions)
        layout.addWidget(self._search)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._table = DataTable(_TABLE_COLUMNS)
        self._hints_delegate = _HintsIconDelegate(self._table)
        hint_col = _TABLE_COLUMNS.index("Hinweise")
        self._table.setItemDelegateForColumn(hint_col, self._hints_delegate)
        self._table.clicked.connect(self._on_table_clicked)
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
        self._dl_order_ref = QLabel("—")
        form_con.addRow("Name:", self._dl_contact)
        form_con.addRow("Land:", self._dl_country)
        form_con.addRow("ID:", self._dl_id)
        form_con.addRow("Order-Ref:", self._dl_order_ref)
        detail_main.addWidget(gb_contact)

        self._gb_note = QGroupBox("Käufernotiz")
        note_layout = QVBoxLayout(self._gb_note)
        self._dl_note = QLabel()
        self._dl_note.setWordWrap(True)
        note_layout.addWidget(self._dl_note)
        self._gb_note.hide()
        detail_main.addWidget(self._gb_note)

        self._gb_stuecke = QGroupBox("Stücke")
        self._stuecke_layout = QVBoxLayout(self._gb_stuecke)
        self._stuecke_layout.setSpacing(4)
        self._stuecke_hint = QLabel("—")
        self._stuecke_hint.setWordWrap(True)
        self._stuecke_layout.addWidget(self._stuecke_hint)
        self._gb_stuecke.hide()
        detail_main.addWidget(self._gb_stuecke)
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
        if not self._has_sevdesk_token():
            return
        self._reload_first_page()

    def _update_token_hint(self) -> None:
        token = self._current_sevdesk_token()
        if not token:
            self._hint.setText(
                "Kein sevDesk-API-Token gesetzt. Bitte Token in Settings (DB) "
                "oder in .env eintragen."
            )
            self._hint.setStyleSheet("color: #ffa726; padding: 8px;")
            self._hint.show()
        else:
            self._hint.setText(
                "Hinweis: ✳ markiert Entwürfe zur Abarbeitung, ✎/⌂/⚠ zeigen Notiz, Lieferabweichung und heikles Land."
            )
            self._hint.setStyleSheet("color: #b45309; padding: 6px;")
            self._hint.show()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._did_initial_load:
            self._did_initial_load = True
            if self._has_sevdesk_token():
                self._reload_first_page()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._overlay.isVisible():
            self._overlay.setGeometry(self.rect())

    def _on_search(self, text: str) -> None:
        self._table.set_filter(text, column=-1)

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
        if not self._has_sevdesk_token():
            return
        self._append_mode = True
        self._start_load()

    def _start_load(self) -> None:
        if not self._has_sevdesk_token():
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

    def _current_sevdesk_token(self) -> str:
        service: SecretService = self._container.resolve(SecretService)
        return service.get_secret("SEVDESK_API_TOKEN").strip()

    def _has_sevdesk_token(self) -> bool:
        return bool(self._current_sevdesk_token())

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

        self._search.refresh_suggestions()

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

    def _invoice_search_suggestions(self, query: str) -> list[str]:
        q = query.lower().strip()
        if len(q) < 3:
            return []
        items: list[str] = []
        for row in self._summaries:
            hay = (
                f"{row.invoice_number} {row.contact_name} {row.order_reference} "
                f"{row.address_country_code} {row.buyer_note}"
            ).lower()
            if q in hay:
                nr = row.invoice_number or "—"
                customer = row.contact_name or "—"
                items.append(f"{nr} - {customer}")
        return items

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

    def _on_table_clicked(self, index: Any) -> None:
        hint_col = _TABLE_COLUMNS.index("Hinweise")
        if int(index.column()) != hint_col:
            return
        source_index = self._table.model().mapToSource(index)
        row = int(source_index.row())
        if row < 0 or row >= len(self._summaries):
            return
        summary = self._summaries[row]
        if not summary.has_plc_label_candidate():
            return
        from xw_studio.ui.modules.rechnungen.print_dialog import run_plc_label_pdf_print

        run_plc_label_pdf_print(
            self,
            self._container,
            invoice_number=summary.invoice_number,
        )

    def _refresh_detail_for_selection(self) -> None:
        row = self._table.selected_source_row()
        if row is None or row < 0 or row >= len(self._summaries):
            self._reset_detail()
            return
        s = self._summaries[row]
        self._dl_number.setText(s.invoice_number or "")
        self._dl_date.setText(s.formatted_date)
        self._dl_status.setText(s.status_label())
        self._dl_brutto.setText(s.formatted_brutto)
        self._dl_contact.setText(s.contact_name or "")
        self._dl_country.setText(s.address_country_code or "")
        self._dl_id.setText(s.id)
        if s.buyer_note.strip():
            self._dl_note.setText(s.buyer_note)
            self._gb_note.show()
        else:
            self._dl_note.setText("")
            self._gb_note.hide()
        self._dl_order_ref.setText(s.order_reference or "")
        if s.order_reference:
            self._load_stuecke(s.order_reference)
        else:
            self._reset_stuecke()

    def _reset_detail(self) -> None:
        for lbl in (
            self._dl_number, self._dl_date, self._dl_status, self._dl_brutto,
            self._dl_contact, self._dl_country, self._dl_id,
        ):
            lbl.setText("—")
        self._dl_note.setText("")
        self._gb_note.hide()
        self._dl_order_ref.setText("—")
        self._reset_stuecke()

    def _reset_stuecke(self) -> None:
        self._stuecke_hint.setText("—")
        # Remove dynamic item widgets (keep only the hint label)
        while self._stuecke_layout.count() > 1:
            item = self._stuecke_layout.takeAt(1)
            if item and item.widget():
                item.widget().deleteLater()
        self._gb_stuecke.hide()

    def _load_stuecke(self, order_reference: str) -> None:
        self._reset_stuecke()
        self._stuecke_hint.setText("Wird geladen…")
        self._gb_stuecke.show()

        service: SecretService = self._container.resolve(SecretService)
        wix_client = WixOrdersClient(secret_service=service)

        if not wix_client.has_credentials():
            self._stuecke_hint.setText("Kein Wix-API-Key konfiguriert.")
            return

        ref = order_reference

        def job() -> list[PieceBlock]:
            wix_items = wix_client.fetch_order_line_items(ref)
            engine: PrintDecisionEngine = self._container.resolve(PrintDecisionEngine)
            return engine.get_piece_blocks(wix_items, invoice_ref=ref)

        self._stuecke_worker = BackgroundWorker(job)
        self._stuecke_worker.signals.result.connect(self._on_stuecke_loaded)
        self._stuecke_worker.signals.error.connect(self._on_stuecke_error)
        self._stuecke_worker.start()

    def _on_stuecke_loaded(self, items: object) -> None:
        self._stuecke_hint.hide()
        if not isinstance(items, list) or not items:
            self._stuecke_hint.setText("Keine Positionen gefunden.")
            self._stuecke_hint.show()
            return
        for item in items:
            if not isinstance(item, PieceBlock):
                continue
            # Header line: "×2  [XW-001]  Produktname ★"
            unreleased_marker = " \u2605" if item.is_unreleased else ""
            line = f"\u00d7{item.qty_needed}  [{item.sku}]  {item.name}{unreleased_marker}"
            lbl = QLabel(line)
            lbl.setWordWrap(True)
            self._stuecke_layout.addWidget(lbl)
            # Stock status line
            stock_lbl = QLabel(f"  {item.stock_label}")
            stock_lbl.setWordWrap(True)
            # Colour: red for print-needed, orange for low, green for OK, grey for digital
            if item.product is None:
                color = "#9e9e9e"
            elif item.product.is_digital:
                color = "#64748b"
            elif item.needs_print:
                color = "#ef4444"
            elif item.stock_status is not None and item.stock_status.needs_reprint:
                color = "#f59e0b"
            else:
                color = "#16a34a"
            stock_lbl.setStyleSheet(f"color: {color}; font-size: 11px; padding-left: 8px;")
            self._stuecke_layout.addWidget(stock_lbl)
            if item.note:
                note_lbl = QLabel(f"  ↳ {item.note}")
                note_lbl.setWordWrap(True)
                note_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
                self._stuecke_layout.addWidget(note_lbl)

    def _on_stuecke_error(self, exc: Exception) -> None:
        logger.warning("Stücke fetch failed: %s", exc)
        self._stuecke_hint.setText(f"Fehler: {exc}")
        self._stuecke_hint.show()
