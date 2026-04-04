"""Rechnungen module — invoice list from sevDesk."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QTimer, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QDesktopServices,
    QHideEvent,
    QMouseEvent,
    QPainter,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QStyledItemDelegate,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.signals import AppSignals
from xw_studio.core.types import ModuleKey
from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.daily_business.service import DailyBusinessService
from xw_studio.services.draft_invoice.service import DraftInvoiceService
from xw_studio.services.invoice_processing.service import InvoiceProcessingService
from xw_studio.services.products.print_decision import PieceBlock, PrintDecisionEngine
from xw_studio.services.secrets.service import SecretService
from xw_studio.services.sendungen.service import OffeneSendungenService
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary
from xw_studio.services.sevdesk.refund_client import SevDeskRefundClient
from xw_studio.services.wix.client import WixOrdersClient
from xw_studio.ui.modules.rechnungen.offene_sendungen_dialog import OffeneSendungenDialog
from xw_studio.ui.modules.rechnungen.refund_dialog import RefundDialog
from xw_studio.ui.widgets.data_table import DataTable
from xw_studio.ui.widgets.progress_overlay import ProgressOverlay
from xw_studio.ui.widgets.search_bar import SearchBar
from xw_studio.ui.widgets.toolbar import Toolbar

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)

_TABLE_COLUMNS = [
    "RE-NR",
    "Datum",
    "Status",
    "BETRAG",
    "Kunde",
    "Hinweise",
    "AKTIONEN",
    "FULFILLMENT",
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


class _ActionsDelegate(QStyledItemDelegate):
    """Paint action icons (PLC / Refund / Download-Links) in one column."""

    _ACTION_KEYS = ("plc", "refund", "download_links")
    _ICON_FILES = {
        "plc": "plc.png",
        "refund": "refund.png",
        "download_links": "download_links.png",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icons_dir = Path(__file__).resolve().parents[5] / "icons"
        self._cache: dict[str, QPixmap] = {}

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

    @staticmethod
    def _layout(width: int, height: int) -> list[tuple[str, int, int]]:
        size = min(18, max(14, height - 6))
        gap = 6
        total_width = len(_ActionsDelegate._ACTION_KEYS) * size + max(0, len(_ActionsDelegate._ACTION_KEYS) - 1) * gap
        x = max(4, (width - total_width) // 2)
        out: list[tuple[str, int, int]] = []
        for key in _ActionsDelegate._ACTION_KEYS:
            out.append((key, x, size))
            x += size + gap
        return out

    @staticmethod
    def action_at_x(local_x: float, width: int, height: int) -> str:
        for key, x, size in _ActionsDelegate._layout(width, height):
            if x <= int(local_x) <= x + size:
                return key
        return ""

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        row_data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row_data, dict):
            super().paint(painter, option, index)
            return

        plc_enabled = bool(row_data.get("__plc__enabled"))
        has_order_ref = bool(row_data.get("__has_order_ref__"))

        painter.save()
        y = option.rect.y() + max(2, (option.rect.height() - min(18, max(14, option.rect.height() - 6))) // 2)
        for key, x_local, size in self._layout(option.rect.width(), option.rect.height()):
            pix = self._icon_for_key(key)
            if pix is None:
                continue
            enabled = plc_enabled if key in ("plc", "refund") else has_order_ref
            painter.setOpacity(1.0 if enabled else 0.25)
            target = option.rect.adjusted(0, 0, 0, 0)
            target.setX(option.rect.x() + x_local)
            target.setY(y)
            target.setWidth(size)
            target.setHeight(size)
            painter.drawPixmap(target, pix)
        painter.restore()

    def sizeHint(self, option, index):  # type: ignore[override]
        base = super().sizeHint(option, index)
        if base.height() < 22:
            base.setHeight(22)
        return base


class _FulfillmentDelegate(QStyledItemDelegate):
    """Paint clickable status chips for fulfillment steps in one column."""

    _CHIPS = (
        ("label_printed", "labelprint.png"),
        ("invoice_printed", "invoice_print.png"),
        ("product_ready", "print.png"),
        ("mail_sent", "mail_sent.png"),
        ("wix_fulfilled", "wix.png"),
        ("payment_booked", "payment.png"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icons_dir = Path(__file__).resolve().parents[5] / "icons"
        self._cache: dict[str, QPixmap] = {}

    def _icon(self, file_name: str) -> QPixmap | None:
        if file_name in self._cache:
            pix = self._cache[file_name]
            return pix if not pix.isNull() else None
        pix = QPixmap(str(self._icons_dir / file_name))
        self._cache[file_name] = pix
        return pix if not pix.isNull() else None

    @classmethod
    def _layout(cls, width: int, height: int) -> list[tuple[str, str, int, int]]:
        size = min(18, max(14, height - 6))
        gap = 4
        total = len(cls._CHIPS) * size + max(0, len(cls._CHIPS) - 1) * gap
        x = max(4, (width - total) // 2)
        out: list[tuple[str, str, int, int]] = []
        for key, label in cls._CHIPS:
            out.append((key, label, x, size))
            x += size + gap
        return out

    @classmethod
    def chip_at_x(cls, local_x: float, width: int, height: int) -> str:
        for key, _file, x, size in cls._layout(width, height):
            if key == "payment_booked":
                continue
            if x <= int(local_x) <= x + size:
                return key
        return ""

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        row_data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row_data, dict):
            super().paint(painter, option, index)
            return
        payload = row_data.get("__fulfillment__")
        if not isinstance(payload, dict):
            super().paint(painter, option, index)
            return

        painter.save()
        has_run = bool(payload.get("last_run_iso"))
        for key, file_name, x_local, size in self._layout(option.rect.width(), option.rect.height()):
            state = payload.get(key)
            if key == "payment_booked" and not bool(payload.get("payment_applicable")):
                opacity = 0.2
                bg = "#e2e8f0"
            elif not has_run:
                opacity = 0.45
                bg = "#e2e8f0"
            elif bool(state):
                opacity = 1.0
                bg = "#dcfce7"
            else:
                opacity = 1.0
                bg = "#fee2e2"
            target = option.rect.adjusted(0, 0, 0, 0)
            target.setX(option.rect.x() + x_local)
            target.setY(option.rect.y() + max(2, (option.rect.height() - size) // 2))
            target.setWidth(size)
            target.setHeight(size)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(bg))
            painter.drawRoundedRect(target, 6, 6)
            pix = self._icon(file_name)
            if pix is not None:
                painter.setOpacity(opacity)
                painter.drawPixmap(target, pix)
                painter.setOpacity(1.0)
        painter.restore()

    def sizeHint(self, option, index):  # type: ignore[override]
        base = super().sizeHint(option, index)
        if base.height() < 22:
            base.setHeight(22)
        return base


class _DraftInvoiceDialog(QDialog):
    """Collect Wix order number for draft invoice creation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rechnungs-Entwurf erstellen")
        self.setMinimumWidth(560)
        self.setMinimumHeight(420)
        self._preview_ok = False

        layout = QVBoxLayout(self)
        info = QLabel(
            "Wix-Order-Nr eingeben (keine ID).\n"
            "Es wird daraus ein sevDesk-Rechnungsentwurf erzeugt."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._order_number = QLineEdit(self)
        self._order_number.setPlaceholderText("z.B. 10023")
        self._order_number.setClearButtonEnabled(True)
        layout.addWidget(self._order_number)

        self._btn_preview = QPushButton("Vorschau laden")
        self._btn_preview.setToolTip("Wix-Order laden und Positionen/Mappings prüfen")
        layout.addWidget(self._btn_preview)

        self._preview = QPlainTextEdit(self)
        self._preview.setReadOnly(True)
        self._preview.setMinimumHeight(190)
        self._preview.setPlainText("Noch keine Vorschau geladen.")
        layout.addWidget(self._preview)

        self._open_in_sevdesk = QCheckBox("Nach Erstellung in sevDesk öffnen", self)
        self._open_in_sevdesk.setChecked(True)
        layout.addWidget(self._open_in_sevdesk)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #64748b;")
        layout.addWidget(self._status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def wix_order_number(self) -> str:
        return self._order_number.text().strip()

    @property
    def open_in_sevdesk(self) -> bool:
        return self._open_in_sevdesk.isChecked()

    @property
    def preview_ok(self) -> bool:
        return self._preview_ok

    def on_preview_requested(self, callback: Any) -> None:
        self._btn_preview.clicked.connect(callback)

    def set_preview_result(self, text: str, *, ok: bool) -> None:
        self._preview.setPlainText(text)
        self._preview_ok = ok
        if ok:
            self._status.setText("Vorschau OK: Entwurf kann erstellt werden.")
            self._status.setStyleSheet("color: #15803d;")
        else:
            self._status.setText("Vorschau enthält Probleme. Entwurf wird blockiert.")
            self._status.setStyleSheet("color: #b91c1c;")

    def _accept_if_valid(self) -> None:
        value = self.wix_order_number
        if not value:
            self._status.setText("Bitte eine Wix-Order-Nr eingeben.")
            self._order_number.setFocus()
            return
        if not self._preview_ok:
            self._status.setText("Bitte zuerst eine gültige Vorschau laden.")
            self._status.setStyleSheet("color: #b91c1c;")
            return
        self.accept()


class RechnungenView(QWidget):
    """Load and display sevDesk invoices (non-blocking)."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._worker: BackgroundWorker | None = None
        self._refund_worker: BackgroundWorker | None = None
        self._draft_worker: BackgroundWorker | None = None
        self._mollie_badge_worker: BackgroundWorker | None = None
        self._stuecke_worker: BackgroundWorker | None = None
        self._wix_meta_worker: BackgroundWorker | None = None
        self._fulfillment_step_worker: BackgroundWorker | None = None
        self._did_initial_load = False
        self._print_allowed = False
        self._open_draft_after_create = False
        self._mollie_alert_count = 0
        self._sendungen_alert_count = 0
        self._search_index: list[dict[str, str]] = []
        self._mollie_timer = QTimer(self)
        self._mollie_timer.setInterval(60000)
        self._mollie_timer.timeout.connect(self._refresh_mollie_alert_count)
        self._last_plc_invoice = "—"
        self._next_offset = 0
        self._summaries: list[InvoiceSummary] = []
        self._current_piece_blocks: list[PieceBlock] = []
        self._piece_print_buttons: list[QPushButton] = []
        self._append_mode = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        toolbar = Toolbar()
        refresh = toolbar.add_button(
            "refresh",
            "Aktualisieren",
            tooltip="Erste Seite neu laden",
        )
        refresh.clicked.connect(self._reload_first_page)
        self._btn_draft = toolbar.add_button(
            "draft",
            "Rechnungs-Entwurf",
            tooltip="Neuen sevDesk-Rechnungsentwurf aus Wix-Order-Nr erstellen",
        )
        self._btn_draft.clicked.connect(self._on_create_draft_clicked)
        toolbar.add_stretch()
        self._btn_sendungen_alert = toolbar.add_button(
            "sendungen_alert",
            "✉ OFFENE SENDUNGEN",
            tooltip="Offene Versand-Mails anzeigen",
        )
        self._btn_sendungen_alert.setStyleSheet(
            "QPushButton {"
            "background-color: #b91c1c; color: white; border-radius: 6px;"
            "font-weight: bold; padding: 0 14px;"
            "}"
            "QPushButton:hover { background-color: #991b1b; }"
        )
        self._btn_sendungen_alert.clicked.connect(self._on_sendungen_alert_clicked)
        self._btn_sendungen_alert.hide()
        self._btn_mollie_alert = toolbar.add_button(
            "mollie_alert",
            "💳 MOLLIE AUTH",
            tooltip="Offene Mollie-Authorisierungen anzeigen",
        )
        self._btn_mollie_alert.setStyleSheet(
            "QPushButton {"
            "background-color: #b91c1c; color: white; border-radius: 6px;"
            "font-weight: bold; padding: 0 14px;"
            "}"
            "QPushButton:hover { background-color: #991b1b; }"
        )
        self._btn_mollie_alert.clicked.connect(self._on_mollie_alert_clicked)
        self._btn_mollie_alert.hide()
        layout.addWidget(toolbar)

        self._search = SearchBar("Suchen…", debounce_ms=220, min_chars=2, max_suggestions=12)
        self._search.set_suggestion_provider(self._invoice_search_suggestions)
        layout.addWidget(self._search)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self._table = DataTable(_TABLE_COLUMNS)
        self._table.setStyleSheet(
            "QTableView::item:selected { background-color: rgba(29, 78, 216, 0.16); color: #0f172a; }"
            "QTableView::item:selected:focus { background-color: rgba(29, 78, 216, 0.26); color: #0f172a; }"
        )
        self._hints_delegate = _HintsIconDelegate(self._table)
        self._actions_delegate = _ActionsDelegate(self._table)
        self._fulfillment_delegate = _FulfillmentDelegate(self._table)
        hint_col = _TABLE_COLUMNS.index("Hinweise")
        fulfillment_col = _TABLE_COLUMNS.index("FULFILLMENT")
        actions_col = _TABLE_COLUMNS.index("AKTIONEN")
        self._table.setItemDelegateForColumn(hint_col, self._hints_delegate)
        self._table.setItemDelegateForColumn(fulfillment_col, self._fulfillment_delegate)
        self._table.setItemDelegateForColumn(actions_col, self._actions_delegate)
        self._table.clicked.connect(self._on_table_clicked)
        self._table.viewport().installEventFilter(self)
        self._table.setSortingEnabled(False)
        self._table.horizontalHeader().setSectionsClickable(False)
        self._table.horizontalHeader().resizeSection(hint_col, 150)
        self._table.horizontalHeader().resizeSection(actions_col, 120)
        self._table.horizontalHeader().resizeSection(fulfillment_col, 170)
        self._table.setColumnHidden(_TABLE_COLUMNS.index("ID"), True)
        left_layout.addWidget(self._table, stretch=1)

        load_more_row = QHBoxLayout()
        load_more_row.addStretch()
        self._btn_more = QPushButton("Weitere laden")
        self._btn_more.setToolTip(f"Naechste bis zu {_PAGE_SIZE} Rechnungen anhaengen")
        self._btn_more.setFixedHeight(28)
        self._btn_more.setFixedWidth(136)
        self._btn_more.clicked.connect(self._load_more)
        load_more_row.addWidget(self._btn_more)
        left_layout.addLayout(load_more_row)

        splitter.addWidget(left_panel)

        # --- Structured detail panel ---
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setMinimumWidth(260)

        detail_content = QWidget()
        detail_main = QVBoxLayout(detail_content)
        detail_main.setContentsMargins(8, 8, 8, 8)
        detail_main.setSpacing(10)

        self._gb_open = QGroupBox("OFFENE RECHNUNGEN")
        form_open = QFormLayout(self._gb_open)
        self._open_total = QLabel("—")
        self._open_physical = QLabel("—")
        self._open_digital = QLabel("—")
        self._open_with_ref = QLabel("—")
        self._open_plc = QLabel("—")
        self._open_note = QLabel("—")
        form_open.addRow("Gesamt:", self._open_total)
        form_open.addRow("Davon physisch:", self._open_physical)
        form_open.addRow("Davon digital-only:", self._open_digital)
        form_open.addRow("Mit Wix-Order-Ref:", self._open_with_ref)
        form_open.addRow("Mit PLC-Hinweis:", self._open_plc)
        form_open.addRow("Mit Käufernotiz:", self._open_note)
        detail_main.addWidget(self._gb_open)

        self._gb_info = QGroupBox("INFO")
        form_info = QFormLayout(self._gb_info)
        self._dl_number = QLabel("—")
        self._dl_date = QLabel("—")
        self._dl_status = QLabel("—")
        self._dl_brutto = QLabel("—")
        self._dl_contact = QLabel("—")
        self._dl_contact.setWordWrap(True)
        self._dl_country = QLabel("—")
        self._dl_id = QLabel("—")
        self._dl_order_ref = QLabel("—")
        self._wix_order_no = QLabel("—")
        self._wix_customer = QLabel("—")
        self._wix_customer_email = QLabel("—")
        self._wix_shipping = QLabel("—")
        self._wix_shipping.setWordWrap(True)
        form_info.addRow("Rechnung:", self._dl_number)
        form_info.addRow("Datum:", self._dl_date)
        form_info.addRow("Status:", self._dl_status)
        form_info.addRow("Brutto:", self._dl_brutto)
        form_info.addRow("Kunde:", self._dl_contact)
        form_info.addRow("Land:", self._dl_country)
        form_info.addRow("ID:", self._dl_id)
        form_info.addRow("Order-Ref:", self._dl_order_ref)
        form_info.addRow("Wix-Order:", self._wix_order_no)
        form_info.addRow("Wix-Kunde:", self._wix_customer)
        form_info.addRow("Wix-E-Mail:", self._wix_customer_email)
        form_info.addRow("Lieferadresse:", self._wix_shipping)
        self._gb_info.hide()
        detail_main.addWidget(self._gb_info)

        self._gb_note = QGroupBox("Käufernotiz")
        note_layout = QVBoxLayout(self._gb_note)
        self._dl_note = QLabel()
        self._dl_note.setWordWrap(True)
        note_layout.addWidget(self._dl_note)
        self._gb_note.hide()
        detail_main.addWidget(self._gb_note)

        self._gb_actions = QGroupBox("AKTIONEN")
        actions_layout = QVBoxLayout(self._gb_actions)
        self._action_state = QLabel("Keine Rechnung ausgewählt")
        self._action_state.setWordWrap(True)
        self._action_state.setStyleSheet("color: #64748b;")
        actions_layout.addWidget(self._action_state)
        self._plc_last = QLabel("Letzter PLC-Druck: —")
        self._plc_last.setStyleSheet("color: #64748b; font-size: 11px;")
        actions_layout.addWidget(self._plc_last)

        self._btn_print = QPushButton("Rechnung drucken")
        self._btn_print.clicked.connect(self._on_print_clicked)
        self._btn_print.setEnabled(False)
        actions_layout.addWidget(self._btn_print)

        self._btn_print_label = QPushButton("Label drucken")
        self._btn_print_label.clicked.connect(self._on_print_label_clicked)
        self._btn_print_label.setEnabled(False)
        actions_layout.addWidget(self._btn_print_label)

        self._btn_print_plc = QPushButton("PLC-Label drucken")
        self._btn_print_plc.clicked.connect(self._on_print_plc_selected)
        self._btn_print_plc.setEnabled(False)
        actions_layout.addWidget(self._btn_print_plc)

        self._btn_print_music = QPushButton("Noten drucken")
        self._btn_print_music.clicked.connect(self._on_print_music_clicked)
        self._btn_print_music.setEnabled(False)
        actions_layout.addWidget(self._btn_print_music)
        self._gb_actions.hide()
        detail_main.addWidget(self._gb_actions)

        self._gb_stuecke = QGroupBox("Produkte")
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

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.printer_status_changed.connect(self._on_printer_status)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._did_initial_load:
            self._did_initial_load = True
            if self._has_sevdesk_token():
                self._reload_first_page()
        self._refresh_mollie_alert_count()
        self._mollie_timer.start()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self._mollie_timer.stop()
        self._stop_mollie_worker()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            global_pos = self.mapToGlobal(event.position().toPoint())
            local_to_table = self._table.mapFromGlobal(global_pos)
            if not self._table.rect().contains(local_to_table):
                sel = self._table.selectionModel()
                if sel is not None:
                    sel.clearSelection()
                self._refresh_detail_for_selection()
        super().mousePressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._mollie_timer.stop()
        self._stop_mollie_worker()
        super().closeEvent(event)

    def _stop_mollie_worker(self) -> None:
        if self._mollie_badge_worker is not None and self._mollie_badge_worker.isRunning():
            self._mollie_badge_worker.wait(1000)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._overlay.isVisible():
            self._overlay.setGeometry(self.rect())

    def _on_search(self, text: str) -> None:
        self._table.set_filter(text, column=-1)

    def _on_printer_status(self, printing_allowed: bool) -> None:
        self._print_allowed = printing_allowed
        for button in self._piece_print_buttons:
            button.setEnabled(printing_allowed)
        self._update_plc_controls()

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
        offset = self._next_offset if self._append_mode else 0
        append = self._append_mode

        self._overlay.show_with_message(
            "Rechnungen werden geladen…" if not append else "Weitere Rechnungen werden geladen…",
        )
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

        def job() -> tuple[list[dict[str, str]], list[InvoiceSummary], bool]:
            rows, sums = service.load_invoice_batch(
                status=None,
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
        self._rebuild_search_index()
        self._apply_table_column_layout()
        self._refresh_open_invoice_overview()

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

    def _apply_table_column_layout(self) -> None:
        header = self._table.horizontalHeader()
        for idx in range(len(_TABLE_COLUMNS)):
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)
        self._table.resizeColumnsToContents()
        for idx in range(len(_TABLE_COLUMNS)):
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.Interactive)

    def _refresh_mollie_alert_count(self) -> None:
        if self._mollie_badge_worker is not None and self._mollie_badge_worker.isRunning():
            return

        def job() -> dict[str, int]:
            service: DailyBusinessService = self._container.resolve(DailyBusinessService)
            counts = service.load_counts(open_invoice_count=0)
            sendungen_service: OffeneSendungenService = self._container.resolve(OffeneSendungenService)
            return {
                "mollie": max(0, int(counts.get("mollie", 0))),
                "sendungen": max(0, int(sendungen_service.open_count())),
            }

        self._mollie_badge_worker = BackgroundWorker(job)
        self._mollie_badge_worker.signals.result.connect(self._on_mollie_badge_result)
        self._mollie_badge_worker.start()

    def _on_mollie_badge_result(self, result: object) -> None:
        if isinstance(result, dict):
            mollie = max(0, int(result.get("mollie") or 0))
            sendungen = max(0, int(result.get("sendungen") or 0))
        else:
            mollie = max(0, int(result)) if isinstance(result, int) else 0
            sendungen = 0
        self.update_mollie_alert_count(mollie)
        self.update_sendungen_alert_count(sendungen)

    def update_mollie_alert_count(self, count: int) -> None:
        self._mollie_alert_count = max(0, int(count))
        if self._mollie_alert_count > 0:
            self._btn_mollie_alert.setText(f"💳 MOLLIE AUTH ({self._mollie_alert_count})")
            self._btn_mollie_alert.show()
            return
        self._btn_mollie_alert.hide()

    def update_sendungen_alert_count(self, count: int) -> None:
        self._sendungen_alert_count = max(0, int(count))
        if self._sendungen_alert_count > 0:
            self._btn_sendungen_alert.setText(f"✉ OFFENE SENDUNGEN ({self._sendungen_alert_count})")
            self._btn_sendungen_alert.show()
            return
        self._btn_sendungen_alert.hide()

    def _on_mollie_alert_clicked(self) -> None:
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.navigate_to_module.emit(ModuleKey.MOLLIE.value)

    def _on_sendungen_alert_clicked(self) -> None:
        dlg = OffeneSendungenDialog(self._container, self)
        dlg.exec()
        self.update_sendungen_alert_count(dlg.open_count())

    def _selected_summary(self) -> InvoiceSummary | None:
        row = self._table.selected_source_row()
        if row is None or row < 0 or row >= len(self._summaries):
            return None
        return self._summaries[row]

    def _require_selected_invoice(self) -> InvoiceSummary | None:
        summary = self._selected_summary()
        if summary is not None:
            return summary
        QMessageBox.information(
            self,
            "Aktion",
            "Bitte zuerst eine Rechnung in der Liste auswählen.",
        )
        return None

    def _invoice_search_suggestions(self, query: str) -> list[str]:
        q = query.lower().strip()
        if len(q) < 2:
            return []
        exact: list[str] = []
        starts: list[str] = []
        contains: list[str] = []
        for row in self._search_index:
            inv = row.get("inv", "")
            customer = row.get("customer", "")
            order_nr = row.get("order", "")
            label = row.get("label", "")

            if inv == q or customer == q or order_nr == q:
                exact.append(label)
                continue
            if inv.startswith(q) or customer.startswith(q) or order_nr.startswith(q):
                starts.append(label)
                continue
            if q in inv or q in customer or q in order_nr:
                contains.append(label)

        out: list[str] = []
        for bucket in (exact, starts, contains):
            for item in bucket:
                if item not in out:
                    out.append(item)
                if len(out) >= 12:
                    return out
        return out

    def _rebuild_search_index(self) -> None:
        self._search_index = []
        for summary in self._summaries:
            inv = str(summary.invoice_number or "").strip().lower()
            customer = str(summary.contact_name or "").strip().lower()
            order_ref = str(summary.order_reference or "").strip().lower()
            numeric_order = "".join(ch for ch in order_ref if ch.isdigit())
            order_search = numeric_order if numeric_order else order_ref
            label = f"{summary.invoice_number or '—'} - {summary.contact_name or '—'}"
            self._search_index.append(
                {
                    "inv": inv,
                    "customer": customer,
                    "order": order_search,
                    "label": label,
                }
            )

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

    def _refresh_open_invoice_overview(self) -> None:
        open_rows = [s for s in self._summaries if s.status_code == 100]
        total = len(open_rows)
        with_ref = sum(1 for s in open_rows if s.order_reference.strip())
        plc = sum(1 for s in open_rows if s.has_plc_label_candidate())
        with_note = sum(1 for s in open_rows if s.buyer_note.strip())

        # Approximation aligned with legacy analysis intent: invoices with Wix order refs
        # are considered physical candidates, remainder digital-only.
        physical = with_ref
        digital = max(0, total - physical)

        self._open_total.setText(str(total))
        self._open_physical.setText(str(physical))
        self._open_digital.setText(str(digital))
        self._open_with_ref.setText(str(with_ref))
        self._open_plc.setText(str(plc))
        self._open_note.setText(str(with_note))

    def _on_print_clicked(self) -> None:
        if not self._print_allowed:
            return
        if self._require_selected_invoice() is None:
            return
        from xw_studio.ui.modules.rechnungen.print_dialog import run_invoice_pdf_print

        run_invoice_pdf_print(self, self._container)

    def _on_print_label_clicked(self) -> None:
        if not self._print_allowed:
            return
        if self._require_selected_invoice() is None:
            return
        from xw_studio.ui.modules.rechnungen.print_dialog import run_label_pdf_print

        run_label_pdf_print(self, self._container)

    def _on_print_plc_selected(self) -> None:
        if not self._print_allowed:
            return
        summary = self._require_selected_invoice()
        if summary is None:
            return
        self._run_plc_print(summary)

    def _run_plc_print(self, summary: InvoiceSummary) -> None:
        if not self._print_allowed:
            return
        from xw_studio.ui.modules.rechnungen.print_dialog import run_plc_label_pdf_print

        run_plc_label_pdf_print(
            self,
            self._container,
            invoice_number=summary.invoice_number,
        )
        self._last_plc_invoice = summary.invoice_number or summary.id
        self._plc_last.setText(f"Letzter PLC-Druck: {self._last_plc_invoice}")

    def _on_print_music_clicked(self) -> None:
        if not self._print_allowed:
            return
        if self._require_selected_invoice() is None:
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
        row = int(index.row()) if hasattr(index, "row") else -1
        if row < 0:
            return
        self._table.selectRow(row)

    def eventFilter(self, watched: Any, event: QEvent) -> bool:  # type: ignore[override]
        if watched is self._table.viewport() and event.type() == QEvent.Type.MouseButtonRelease:
            if isinstance(event, QMouseEvent):
                index = self._table.indexAt(event.position().toPoint())
                if index.isValid():
                    self._table.selectRow(int(index.row()))
                    fulfillment_col = _TABLE_COLUMNS.index("FULFILLMENT")
                    actions_col = _TABLE_COLUMNS.index("AKTIONEN")
                    if int(index.column()) == fulfillment_col:
                        rect = self._table.visualRect(index)
                        chip = self._fulfillment_delegate.chip_at_x(
                            local_x=event.position().x() - rect.x(),
                            width=rect.width(),
                            height=rect.height(),
                        )
                        if chip:
                            source_index = self._table.model().mapToSource(index)
                            row = int(source_index.row())
                            if 0 <= row < len(self._summaries):
                                row_payload = self._table.selected_row_data() or {}
                                flags = row_payload.get("__fulfillment__")
                                self._run_fulfillment_chip_action(self._summaries[row], chip, flags)
                    if int(index.column()) == actions_col:
                        rect = self._table.visualRect(index)
                        action = self._actions_delegate.action_at_x(
                            local_x=event.position().x() - rect.x(),
                            width=rect.width(),
                            height=rect.height(),
                        )
                        if action:
                            source_index = self._table.model().mapToSource(index)
                            row = int(source_index.row())
                            if 0 <= row < len(self._summaries):
                                self._run_row_action(self._summaries[row], action)
        return super().eventFilter(watched, event)

    def _run_fulfillment_chip_action(
        self,
        summary: InvoiceSummary,
        chip: str,
        flags: object,
    ) -> None:
        if chip == "payment_booked":
            QMessageBox.information(self, "Payment", "Payment-Flow ist aktuell noch deaktiviert.")
            return
        if self._fulfillment_step_worker is not None and self._fulfillment_step_worker.isRunning():
            return

        labels = {
            "label_printed": "Label",
            "invoice_printed": "Rechnung",
            "product_ready": "Produkt",
            "mail_sent": "Mail",
            "wix_fulfilled": "Wix",
        }
        self._overlay.show_with_message(f"Retry {labels.get(chip, chip)} läuft…")
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

        invoice_id = summary.id

        def job() -> dict[str, object]:
            service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            updated = service.retry_fulfillment_step(invoice_id, chip)
            payload = updated.as_row_payload() if hasattr(updated, "as_row_payload") else {}
            return {
                "invoice": summary.invoice_number or summary.id,
                "chip": chip,
                "flags": payload,
            }

        self._fulfillment_step_worker = BackgroundWorker(job)
        self._fulfillment_step_worker.signals.result.connect(self._on_fulfillment_step_result)
        self._fulfillment_step_worker.signals.error.connect(self._on_fulfillment_step_error)
        self._fulfillment_step_worker.signals.finished.connect(self._on_fulfillment_step_finished)
        self._fulfillment_step_worker.start()

    def _on_fulfillment_step_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        invoice = str(data.get("invoice") or "—")
        chip = str(data.get("chip") or "")
        QMessageBox.information(
            self,
            "Fulfillment aktualisiert",
            f"Rechnung {invoice}: Schritt '{chip}' wurde erneut ausgeführt.",
        )
        self._reload_first_page()

    def _on_fulfillment_step_error(self, exc: Exception) -> None:
        QMessageBox.warning(
            self,
            "Fulfillment-Fehler",
            f"Schritt konnte nicht ausgeführt werden:\n\n{exc}",
        )

    def _on_fulfillment_step_finished(self) -> None:
        self._overlay.hide()

    def _run_row_action(self, summary: InvoiceSummary, action: str) -> None:
        if action == "plc":
            self._run_plc_print(summary)
            return
        if action == "download_links":
            self._open_wix_download_links(summary)
            return
        if action == "refund":
            self._open_refund_dialog(summary)

    def _open_wix_download_links(self, summary: InvoiceSummary) -> None:
        if not summary.order_reference.strip():
            QMessageBox.information(
                self,
                "Download-Links",
                "Diese Rechnung hat keine Wix-Order-Referenz.",
            )
            return
        wix_orders: WixOrdersClient = self._container.resolve(WixOrdersClient)
        url = wix_orders.resolve_order_dashboard_url(summary.order_reference)
        if not url:
            QMessageBox.warning(
                self,
                "Download-Links",
                "Wix-Order konnte nicht aufgelöst werden.",
            )
            return
        QDesktopServices.openUrl(QUrl(url))

    def _open_refund_dialog(self, summary: InvoiceSummary) -> None:
        dlg = RefundDialog(summary, self)
        if dlg.exec() != 1:
            return

        send_mail = dlg.send_customer_mail
        self._overlay.show_with_message("Rückerstattung wird ausgeführt…")
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

        def job() -> dict[str, Any]:
            sevdesk_refund: SevDeskRefundClient = self._container.resolve(SevDeskRefundClient)
            wix_orders: WixOrdersClient = self._container.resolve(WixOrdersClient)

            cancel_payload = sevdesk_refund.cancel_invoice(summary.id)
            wix_payload: dict[str, Any] = {}
            wix_ok = False
            if summary.order_reference.strip():
                wix_payload = wix_orders.refund_full_order(
                    summary.order_reference,
                    send_customer_email=send_mail,
                    customer_reason=f"Storno {summary.invoice_number or summary.id}",
                )
                wix_ok = bool(wix_payload)
            return {
                "invoice": summary.invoice_number or summary.id,
                "cancel": cancel_payload,
                "wix": wix_payload,
                "wix_ok": wix_ok,
                "had_order_ref": bool(summary.order_reference.strip()),
            }

        self._refund_worker = BackgroundWorker(job)
        self._refund_worker.signals.result.connect(self._on_refund_result)
        self._refund_worker.signals.error.connect(self._on_refund_error)
        self._refund_worker.signals.finished.connect(self._on_refund_finished)
        self._refund_worker.start()

    def _on_refund_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        invoice = str(data.get("invoice") or "—")
        had_order_ref = bool(data.get("had_order_ref"))
        wix_ok = bool(data.get("wix_ok"))

        if not had_order_ref:
            QMessageBox.information(
                self,
                "Rückerstattung durchgeführt",
                f"Rechnung {invoice}: sevDesk-Stornorechnung wurde erstellt.\n"
                "Keine Wix-Order-Referenz vorhanden, daher kein Zahlungsrefund in Wix.",
            )
            self._reload_first_page()
            return

        if wix_ok:
            QMessageBox.information(
                self,
                "Rückerstattung durchgeführt",
                f"Rechnung {invoice}: sevDesk-Storno + Wix-Zahlungsrefund erfolgreich.",
            )
        else:
            QMessageBox.warning(
                self,
                "Teilweise abgeschlossen",
                f"Rechnung {invoice}: sevDesk-Storno erstellt, aber Wix-Zahlungsrefund konnte nicht bestätigt werden.",
            )
        self._reload_first_page()

    def _on_refund_error(self, exc: Exception) -> None:
        QMessageBox.warning(
            self,
            "Rückerstattung fehlgeschlagen",
            f"Die Rückerstattung konnte nicht ausgeführt werden:\n\n{exc}",
        )

    def _on_refund_finished(self) -> None:
        self._overlay.hide()

    def _refresh_detail_for_selection(self) -> None:
        row = self._table.selected_source_row()
        if row is None or row < 0 or row >= len(self._summaries):
            self._reset_detail()
            return
        self._gb_open.hide()
        self._gb_info.show()
        s = self._summaries[row]
        self._dl_number.setText(s.invoice_number or "")
        self._dl_date.setText(s.formatted_date)
        self._dl_status.setText(s.status_label())
        self._dl_brutto.setText(s.formatted_brutto)
        self._dl_contact.setText(s.contact_name or "")
        self._dl_country.setText(s.display_country or "")
        self._dl_id.setText(s.id)
        if s.buyer_note.strip():
            self._dl_note.setText(s.buyer_note)
            self._gb_note.show()
        else:
            self._dl_note.setText("")
            self._gb_note.hide()
        self._dl_order_ref.setText(s.order_reference or "")
        self._reset_wix_meta("Lade Wix-Daten…")
        self._action_state.setText("Aktionen für die ausgewählte Rechnung verfügbar.")
        self._gb_actions.show()
        self._update_plc_controls()
        if s.order_reference:
            self._load_wix_meta(s.order_reference)
            self._load_stuecke(s.order_reference)
        else:
            self._reset_wix_meta("Keine Wix-Order-Referenz")
            self._reset_stuecke()

    def _reset_detail(self) -> None:
        self._gb_open.show()
        self._gb_info.hide()
        for lbl in (
            self._dl_number, self._dl_date, self._dl_status, self._dl_brutto,
            self._dl_contact, self._dl_country, self._dl_id,
        ):
            lbl.setText("—")
        self._dl_note.setText("")
        self._gb_note.hide()
        self._dl_order_ref.setText("—")
        self._reset_wix_meta("—")
        self._action_state.setText("Keine Rechnung ausgewählt")
        self._gb_actions.hide()
        self._update_plc_controls()
        self._reset_stuecke()

    def _reset_wix_meta(self, text: str) -> None:
        self._wix_order_no.setText(text)
        self._wix_customer.setText("—")
        self._wix_customer_email.setText("—")
        self._wix_shipping.setText("—")

    def _load_wix_meta(self, order_reference: str) -> None:
        if self._wix_meta_worker is not None and self._wix_meta_worker.isRunning():
            return
        ref = order_reference.strip()
        if not ref:
            self._reset_wix_meta("Keine Wix-Order-Referenz")
            return

        def job() -> dict[str, str]:
            service: SecretService = self._container.resolve(SecretService)
            wix = WixOrdersClient(secret_service=service)
            if not wix.has_credentials():
                return {"status": "Kein Wix-API-Key konfiguriert."}
            return wix.resolve_order_summary(ref)

        self._wix_meta_worker = BackgroundWorker(job)
        self._wix_meta_worker.signals.result.connect(self._on_wix_meta_loaded)
        self._wix_meta_worker.signals.error.connect(self._on_wix_meta_error)
        self._wix_meta_worker.start()

    def _on_wix_meta_loaded(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        if not data:
            self._reset_wix_meta("Wix-Order nicht gefunden")
            return
        if data.get("status"):
            self._reset_wix_meta(str(data.get("status")))
            return
        self._wix_order_no.setText(data.get("wix_order_number") or data.get("wix_order_id") or "—")
        self._wix_customer.setText(data.get("wix_customer_name") or "—")
        self._wix_customer_email.setText(data.get("wix_customer_email") or "—")
        shipping = (data.get("wix_shipping_address") or "").strip()
        if not shipping:
            city = data.get("wix_shipping_city") or ""
            country = data.get("wix_shipping_country") or ""
            shipping = " / ".join(part for part in (city, country) if part)
        self._wix_shipping.setText(shipping or "—")

    def _on_wix_meta_error(self, exc: Exception) -> None:
        self._reset_wix_meta(f"Wix-Fehler: {exc}")

    def _update_plc_controls(self) -> None:
        enabled = self._print_allowed and (self._selected_summary() is not None)
        self._btn_print.setEnabled(enabled)
        self._btn_print_label.setEnabled(enabled)
        self._btn_print_plc.setEnabled(enabled)
        self._btn_print_music.setEnabled(enabled)

    def _on_create_draft_clicked(self) -> None:
        if self._draft_worker is not None and self._draft_worker.isRunning():
            return
        dlg = _DraftInvoiceDialog(self)
        dlg.on_preview_requested(lambda: self._run_draft_preview(dlg))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        order_number = dlg.wix_order_number
        self._open_draft_after_create = dlg.open_in_sevdesk
        self._overlay.show_with_message("Rechnungsentwurf wird erstellt…")
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

        def job() -> dict[str, str]:
            service: DraftInvoiceService = self._container.resolve(DraftInvoiceService)
            return service.create_draft_from_wix_order_number(order_number)

        self._draft_worker = BackgroundWorker(job)
        self._draft_worker.signals.result.connect(self._on_create_draft_result)
        self._draft_worker.signals.error.connect(self._on_create_draft_error)
        self._draft_worker.signals.finished.connect(self._on_create_draft_finished)
        self._draft_worker.start()

    def _on_create_draft_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        invoice_id = str(data.get("invoice_id") or "").strip()
        invoice_number = str(data.get("invoice_number") or "").strip()
        wix_order_number = str(data.get("wix_order_number") or "").strip()
        positions = str(data.get("positions") or "0")
        QMessageBox.information(
            self,
            "Rechnungs-Entwurf erstellt",
            (
                f"Wix-Order-Nr: {wix_order_number}\n"
                f"Rechnung: {invoice_number}\n"
                f"sevDesk-ID: {invoice_id}\n"
                f"Positionen: {positions}"
            ),
        )
        if self._open_draft_after_create and invoice_id:
            base = str(self._container.config.sevdesk.base_url or "https://my.sevdesk.de/api/v1").strip().rstrip("/")
            if base.endswith("/api/v1"):
                base = base[:-7]
            url = f"{base}/#/invoices/{invoice_id}"
            QDesktopServices.openUrl(QUrl(url))
        self._reload_first_page()

    def _on_create_draft_error(self, exc: Exception) -> None:
        QMessageBox.warning(
            self,
            "Rechnungs-Entwurf fehlgeschlagen",
            f"Der Entwurf konnte nicht erstellt werden:\n\n{exc}",
        )

    def _on_create_draft_finished(self) -> None:
        self._overlay.hide()

    def _run_draft_preview(self, dlg: _DraftInvoiceDialog) -> None:
        reference = dlg.wix_order_number
        if not reference:
            dlg.set_preview_result("Bitte zuerst eine Wix-Order-Nr eingeben.", ok=False)
            return
        try:
            service: DraftInvoiceService = self._container.resolve(DraftInvoiceService)
            preview = service.preview_wix_order_number(reference)
        except Exception as exc:
            dlg.set_preview_result(f"Vorschau fehlgeschlagen:\n{exc}", ok=False)
            return

        lines: list[str] = []
        lines.append(f"Wix-Order: {preview.get('wix_order_number', '—')}")
        lines.append(f"Kunde: {preview.get('customer', '—')}")
        lines.append(f"E-Mail: {preview.get('email', '—')}")
        lines.append("")
        lines.append("Positionen:")
        items = preview.get("items") if isinstance(preview.get("items"), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('qty', '1')}x [{item.get('sku', '—')}] {item.get('name', '—')} -> {item.get('status', '—')}"
            )

        missing = preview.get("missing_skus") if isinstance(preview.get("missing_skus"), list) else []
        if missing:
            lines.append("")
            lines.append("Fehlende/ungültige SKU-Mappings:")
            for sku in missing:
                lines.append(f"- {sku}")

        can_create = bool(preview.get("can_create"))
        dlg.set_preview_result("\n".join(lines), ok=can_create)

    def _reset_stuecke(self) -> None:
        self._current_piece_blocks = []
        self._piece_print_buttons = []
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
        self._current_piece_blocks = [item for item in items if isinstance(item, PieceBlock)]
        for item in self._current_piece_blocks:
            # Header line: "×2  [XW-001]  Produktname ★"
            unreleased_marker = " \u2605" if item.is_unreleased else ""
            line = f"\u00d7{item.qty_needed}  [{item.sku}]  {item.name}{unreleased_marker}"
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            lbl = QLabel(line)
            lbl.setWordWrap(True)
            row_layout.addWidget(lbl, stretch=1)

            if item.is_unreleased:
                print_btn = QPushButton("Drucken")
                print_btn.setFixedHeight(24)
                print_btn.setEnabled(self._print_allowed)
                print_btn.clicked.connect(lambda _checked=False, block=item: self._on_product_print_clicked(block))
                row_layout.addWidget(print_btn)
                self._piece_print_buttons.append(print_btn)

            self._stuecke_layout.addWidget(row_widget)
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

    def _on_product_print_clicked(self, block: PieceBlock) -> None:
        if not self._print_allowed:
            return
        from xw_studio.ui.modules.rechnungen.print_dialog import run_piece_pdf_print

        if run_piece_pdf_print(self, self._container, piece=block):
            try:
                engine: PrintDecisionEngine = self._container.resolve(PrintDecisionEngine)
                row = self._table.selected_source_row()
                invoice_ref = ""
                if row is not None and 0 <= row < len(self._summaries):
                    invoice_ref = self._summaries[row].invoice_number or self._summaries[row].id
                qty = max(1, int(block.print_qty or block.qty_needed or 1))
                engine.record_print_and_update_sevdesk(block, qty, invoice_ref=invoice_ref)
            except Exception as exc:
                logger.warning("Stock update after product print failed: %s", exc)

    def _on_stuecke_error(self, exc: Exception) -> None:
        logger.warning("Stücke fetch failed: %s", exc)
        self._stuecke_hint.setText(f"Fehler: {exc}")
        self._stuecke_hint.show()
