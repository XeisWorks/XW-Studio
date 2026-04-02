"""Produkte / Inventar module."""
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
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.inventory import InventoryService, ProductRow

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)

_HEADERS = ["SKU", "Name", "Kategorie", "Bestand", "Preis EUR", "Wix-ID", "sevDesk-ID"]


class ProductsView(QWidget):
    """Inventory product catalogue with search and stock overview."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._all_rows: list[ProductRow] = []
        self._worker: BackgroundWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # --- header bar ---
        bar = QHBoxLayout()
        self._status_lbl = QLabel("Produkte werden geladen…")
        self._status_lbl.setObjectName("productsStatusLabel")
        bar.addWidget(self._status_lbl)
        bar.addStretch()
        self._refresh_btn = QPushButton("Aktualisieren")
        self._refresh_btn.clicked.connect(self._load)
        bar.addWidget(self._refresh_btn)
        root.addLayout(bar)

        # --- search ---
        self._search = QLineEdit()
        self._search.setPlaceholderText("Produkte filtern (SKU, Name, Kategorie)…")
        self._search.textChanged.connect(self._apply_filter)
        root.addWidget(self._search)

        # --- table ---
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._table)

        # --- info footer ---
        self._footer = QLabel(
            "Hinweis: Produktdaten aus der Datenbank (JSON-Key: inventory.products). "
            "Wix/sevDesk-Abgleich folgt in P1.2."
        )
        self._footer.setWordWrap(True)
        self._footer.setObjectName("infoLabel")
        root.addWidget(self._footer)

        self._load()

    # ------------------------------------------------------------------

    def _load(self) -> None:
        svc: InventoryService = self._container.resolve(InventoryService)
        self._refresh_btn.setEnabled(False)
        self._status_lbl.setText("Laden…")

        def job() -> list[ProductRow]:
            return svc.list_products()

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_loaded)
        self._worker.signals.error.connect(self._on_error)
        self._worker.start()

    def _on_loaded(self, rows: object) -> None:
        self._refresh_btn.setEnabled(True)
        if not isinstance(rows, list):
            return
        self._all_rows = rows  # type: ignore[assignment]
        if not self._all_rows:
            self._status_lbl.setText(
                "Keine Produkte in DB — Daten über Einstellungen > inventory.products JSON eintragen."
            )
        else:
            self._status_lbl.setText(f"{len(self._all_rows)} Produkte geladen")
        self._populate(self._all_rows)

    def _on_error(self, exc: BaseException) -> None:
        self._refresh_btn.setEnabled(True)
        self._status_lbl.setText(f"Fehler: {exc}")
        logger.exception("ProductsView load failed: %s", exc)
        QMessageBox.warning(self, "Produkte", str(exc))

    # ------------------------------------------------------------------

    def _populate(self, rows: list[ProductRow]) -> None:
        tbl = self._table
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

    def _apply_filter(self, text: str) -> None:
        needle = text.lower()
        filtered = [
            p for p in self._all_rows
            if needle in p.sku.lower()
            or needle in p.name.lower()
            or needle in p.category.lower()
        ]
        self._populate(filtered)

