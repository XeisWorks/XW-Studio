"""Produkte / Inventar module — Inventar + Wix-Abgleich."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.inventory import InventoryService, ProductRow
from xw_studio.services.wix.client import WixProduct, WixProductsClient

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)

_INV_HEADERS = ["SKU", "Name", "Kategorie", "Bestand", "Preis EUR", "Wix-ID", "sevDesk-ID"]
_WIX_HEADERS = ["SKU", "Name", "Preis", "Sichtbar", "Bestand", "Wix-ID", "Status"]


class ProductsView(QWidget):
    """Inventory + Wix sync — tabbed product module."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._all_rows: list[ProductRow] = []
        self._wix_rows: list[WixProduct] = []
        self._inv_worker: BackgroundWorker | None = None
        self._wix_worker: BackgroundWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        tabs = QTabWidget()
        tabs.addTab(self._build_inventory_tab(), "Inventar (DB)")
        tabs.addTab(self._build_wix_tab(), "Wix-Abgleich")
        root.addWidget(tabs)

        self._load_inventory()

    # ==================================================================
    # Inventar tab
    # ==================================================================

    def _build_inventory_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        bar = QHBoxLayout()
        self._inv_status_lbl = QLabel("Produkte werden geladen...")
        self._inv_status_lbl.setObjectName("productsStatusLabel")
        bar.addWidget(self._inv_status_lbl)
        bar.addStretch()
        self._inv_refresh_btn = QPushButton("Aktualisieren")
        self._inv_refresh_btn.clicked.connect(self._load_inventory)
        bar.addWidget(self._inv_refresh_btn)
        lay.addLayout(bar)

        self._inv_search = QLineEdit()
        self._inv_search.setPlaceholderText("Produkte filtern (SKU, Name, Kategorie)...")
        self._inv_search.textChanged.connect(self._apply_inv_filter)
        lay.addWidget(self._inv_search)

        self._inv_table = QTableWidget(0, len(_INV_HEADERS))
        self._inv_table.setHorizontalHeaderLabels(_INV_HEADERS)
        self._inv_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._inv_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._inv_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._inv_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._inv_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay.addWidget(self._inv_table)

        footer = QLabel("Produktdaten aus DB (JSON-Key: inventory.products). Eintragen unter Einstellungen.")
        footer.setWordWrap(True)
        footer.setObjectName("infoLabel")
        lay.addWidget(footer)
        return page

    def _load_inventory(self) -> None:
        svc: InventoryService = self._container.resolve(InventoryService)
        self._inv_refresh_btn.setEnabled(False)
        self._inv_status_lbl.setText("Laden...")

        def job() -> list[ProductRow]:
            return svc.list_products()

        self._inv_worker = BackgroundWorker(job)
        self._inv_worker.signals.result.connect(self._on_inv_loaded)
        self._inv_worker.signals.error.connect(self._on_inv_error)
        self._inv_worker.start()

    def _on_inv_loaded(self, rows: object) -> None:
        self._inv_refresh_btn.setEnabled(True)
        if not isinstance(rows, list):
            return
        self._all_rows = rows  # type: ignore[assignment]
        if not self._all_rows:
            self._inv_status_lbl.setText("Keine Produkte in DB — Einstellungen > inventory.products")
        else:
            self._inv_status_lbl.setText(f"{len(self._all_rows)} Produkte geladen")
        self._populate_inv(self._all_rows)

    def _on_inv_error(self, exc: BaseException) -> None:
        self._inv_refresh_btn.setEnabled(True)
        self._inv_status_lbl.setText(f"Fehler: {exc}")
        logger.exception("ProductsView inv load failed: %s", exc)

    def _populate_inv(self, rows: list[ProductRow]) -> None:
        tbl = self._inv_table
        tbl.setRowCount(0)
        for prod in rows:
            r = tbl.rowCount()
            tbl.insertRow(r)
            tbl.setItem(r, 0, QTableWidgetItem(prod.sku))
            tbl.setItem(r, 1, QTableWidgetItem(prod.name))
            tbl.setItem(r, 2, QTableWidgetItem(prod.category))
            stock_item = QTableWidgetItem(str(prod.on_hand))
            stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(r, 3, stock_item)
            price_item = QTableWidgetItem(prod.price_eur)
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tbl.setItem(r, 4, price_item)
            tbl.setItem(r, 5, QTableWidgetItem(prod.wix_id))
            tbl.setItem(r, 6, QTableWidgetItem(prod.sevdesk_id))
        tbl.resizeColumnToContents(0)
        for col in (3, 4, 5, 6):
            tbl.resizeColumnToContents(col)

    def _apply_inv_filter(self, text: str) -> None:
        needle = text.lower()
        filtered = [
            p for p in self._all_rows
            if needle in p.sku.lower() or needle in p.name.lower() or needle in p.category.lower()
        ]
        self._populate_inv(filtered)

    # ==================================================================
    # Wix-Abgleich tab
    # ==================================================================

    def _build_wix_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        bar = QHBoxLayout()
        self._wix_status_lbl = QLabel("Wix-Produkte noch nicht geladen.")
        bar.addWidget(self._wix_status_lbl)
        bar.addStretch()
        self._wix_load_btn = QPushButton("Wix-Produkte laden")
        self._wix_load_btn.clicked.connect(self._load_wix)
        bar.addWidget(self._wix_load_btn)
        lay.addLayout(bar)

        self._wix_search = QLineEdit()
        self._wix_search.setPlaceholderText("Filtern (SKU, Name)...")
        self._wix_search.textChanged.connect(self._apply_wix_filter)
        lay.addWidget(self._wix_search)

        self._wix_table = QTableWidget(0, len(_WIX_HEADERS))
        self._wix_table.setHorizontalHeaderLabels(_WIX_HEADERS)
        self._wix_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._wix_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._wix_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._wix_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay.addWidget(self._wix_table, stretch=2)

        # SKU-Overlap summary
        self._overlap_lbl = QLabel("")
        self._overlap_lbl.setObjectName("infoLabel")
        self._overlap_lbl.setWordWrap(True)
        lay.addWidget(self._overlap_lbl)
        return page

    def _load_wix(self) -> None:
        client: WixProductsClient = self._container.resolve(WixProductsClient)
        if not client.has_credentials():
            QMessageBox.warning(
                self,
                "Wix-Abgleich",
                "Kein WIX_API_KEY oder WIX_SITE_ID konfiguriert.\n"
                "Bitte unter Einstellungen > Token-Verwaltung eintragen.",
            )
            return
        self._wix_load_btn.setEnabled(False)
        self._wix_status_lbl.setText("Lade Wix-Produkte...")

        def job() -> list[WixProduct]:
            return client.list_products()

        self._wix_worker = BackgroundWorker(job)
        self._wix_worker.signals.result.connect(self._on_wix_loaded)
        self._wix_worker.signals.error.connect(self._on_wix_error)
        self._wix_worker.start()

    def _on_wix_loaded(self, rows: object) -> None:
        self._wix_load_btn.setEnabled(True)
        if not isinstance(rows, list):
            return
        self._wix_rows = rows  # type: ignore[assignment]
        self._wix_status_lbl.setText(f"{len(self._wix_rows)} Wix-Produkte geladen")
        self._populate_wix(self._wix_rows)
        self._compute_overlap()

    def _on_wix_error(self, exc: BaseException) -> None:
        self._wix_load_btn.setEnabled(True)
        self._wix_status_lbl.setText(f"Fehler: {exc}")
        logger.exception("Wix load failed: %s", exc)
        QMessageBox.warning(self, "Wix-Abgleich", str(exc))

    def _populate_wix(self, rows: list[WixProduct]) -> None:
        tbl = self._wix_table
        tbl.setRowCount(0)
        inv_skus = {p.sku for p in self._all_rows if p.sku}
        for prod in rows:
            r = tbl.rowCount()
            tbl.insertRow(r)
            tbl.setItem(r, 0, QTableWidgetItem(prod.sku))
            tbl.setItem(r, 1, QTableWidgetItem(prod.name))
            price_item = QTableWidgetItem(prod.price)
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tbl.setItem(r, 2, price_item)
            vis_item = QTableWidgetItem("ja" if prod.visible else "nein")
            vis_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(r, 3, vis_item)
            qty_item = QTableWidgetItem(str(prod.inventory_quantity))
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(r, 4, qty_item)
            tbl.setItem(r, 5, QTableWidgetItem(prod.id))
            # Status: matched in local DB?
            matched = prod.sku in inv_skus if prod.sku else False
            status_item = QTableWidgetItem("verknuepft" if matched else "nur Wix")
            status_item.setForeground(
                Qt.GlobalColor.green if matched else Qt.GlobalColor.yellow
            )
            tbl.setItem(r, 6, status_item)
        for col in (0, 3, 4, 6):
            tbl.resizeColumnToContents(col)

    def _apply_wix_filter(self, text: str) -> None:
        needle = text.lower()
        filtered = [
            p for p in self._wix_rows
            if needle in p.sku.lower() or needle in p.name.lower()
        ]
        self._populate_wix(filtered)

    def _compute_overlap(self) -> None:
        inv_skus = {p.sku for p in self._all_rows if p.sku}
        wix_skus = {p.sku for p in self._wix_rows if p.sku}
        matched = inv_skus & wix_skus
        only_wix = wix_skus - inv_skus
        only_inv = inv_skus - wix_skus
        self._overlap_lbl.setText(
            f"Abgleich: {len(matched)} verknuepft | "
            f"{len(only_wix)} nur in Wix | "
            f"{len(only_inv)} nur in lokalem Inventar"
        )
