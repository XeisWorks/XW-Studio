"""Produkte / Inventar module — Inventar + Wix-Abgleich."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
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
from xw_studio.services.sevdesk.part_client import PartClient, SevdeskPart
from xw_studio.services.wix.client import WixProduct, WixProductsClient

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)

_INV_HEADERS = ["SKU", "Name", "Kategorie", "Bestand", "Preis EUR", "Wix-ID", "sevDesk-ID"]
_WIX_HEADERS = ["SKU", "Name", "Preis", "Sichtbar", "Bestand", "Wix-ID", "Status"]
_SYNC_HEADERS = [
    "SKU",
    "Lokal Bestand",
    "Wix Bestand",
    "sevDesk Bestand",
    "Lokal Preis",
    "Wix Preis",
    "sevDesk Preis",
    "Status",
]


@dataclass(frozen=True)
class _SyncRow:
    sku: str
    local_stock: int
    wix_stock: int | None
    sevdesk_stock: int | None
    local_price: str
    wix_price: str
    sevdesk_price: str
    status: str


class ProductsView(QWidget):
    """Inventory + Wix sync — tabbed product module."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._all_rows: list[ProductRow] = []
        self._wix_rows: list[WixProduct] = []
        self._sevdesk_rows: list[SevdeskPart] = []
        self._sync_rows: list[_SyncRow] = []
        self._inv_worker: BackgroundWorker | None = None
        self._wix_worker: BackgroundWorker | None = None
        self._sevdesk_worker: BackgroundWorker | None = None
        self._save_worker: BackgroundWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        tabs = QTabWidget()
        tabs.addTab(self._build_inventory_tab(), "Inventar (DB)")
        tabs.addTab(self._build_wix_tab(), "Wix-Abgleich")
        tabs.addTab(self._build_sync_tab(), "Sync-Konflikte")
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

    # ==================================================================
    # Sync tab (local / Wix / sevDesk)
    # ==================================================================

    def _build_sync_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        bar = QHBoxLayout()
        self._sync_status_lbl = QLabel("Noch kein Sync-Vergleich geladen.")
        bar.addWidget(self._sync_status_lbl)
        bar.addStretch()
        self._sync_load_btn = QPushButton("Alle Quellen laden")
        self._sync_load_btn.clicked.connect(self._load_sync_sources)
        bar.addWidget(self._sync_load_btn)
        self._sync_apply_btn = QPushButton("Wix -> Lokal uebernehmen")
        self._sync_apply_btn.clicked.connect(self._apply_wix_to_local)
        self._sync_apply_btn.setEnabled(False)
        bar.addWidget(self._sync_apply_btn)
        lay.addLayout(bar)

        self._sync_table = QTableWidget(0, len(_SYNC_HEADERS))
        self._sync_table.setHorizontalHeaderLabels(_SYNC_HEADERS)
        self._sync_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._sync_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._sync_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        lay.addWidget(self._sync_table, stretch=1)

        tip = QLabel(
            "Konflikte zeigen Unterschiede zwischen lokalem Inventar, Wix und sevDesk. "
            "Aktuell wird ein sicherer Wix->Lokal Abgleich unterstuetzt."
        )
        tip.setWordWrap(True)
        tip.setObjectName("infoLabel")
        lay.addWidget(tip)

        plans_group = QGroupBox("Druckplaene (JSON)")
        plans_lay = QVBoxLayout(plans_group)
        self._plans_editor = QPlainTextEdit()
        self._plans_editor.setPlaceholderText(
            '[{"sku": "XW-4-001", "min_qty": 1, "target_qty": 3, "pdf": "plans/xw-4-001.pdf"}]'
        )
        self._plans_editor.setMinimumHeight(130)
        plans_lay.addWidget(self._plans_editor)
        plans_btns = QHBoxLayout()
        load_plans_btn = QPushButton("Druckplaene laden")
        load_plans_btn.clicked.connect(self._load_print_plans)
        plans_btns.addWidget(load_plans_btn)
        save_plans_btn = QPushButton("Druckplaene speichern")
        save_plans_btn.clicked.connect(self._save_print_plans)
        plans_btns.addWidget(save_plans_btn)
        plans_btns.addStretch()
        plans_lay.addLayout(plans_btns)
        lay.addWidget(plans_group)
        return page

    def _load_sync_sources(self) -> None:
        self._sync_load_btn.setEnabled(False)
        self._sync_apply_btn.setEnabled(False)
        self._sync_status_lbl.setText("Lade lokale Produkte, Wix und sevDesk...")

        def job() -> tuple[list[ProductRow], list[WixProduct], list[SevdeskPart]]:
            inv: InventoryService = self._container.resolve(InventoryService)
            wix_client: WixProductsClient = self._container.resolve(WixProductsClient)
            part_client: PartClient = self._container.resolve(PartClient)

            local = inv.list_products()
            wix = wix_client.list_products()
            sevdesk: list[SevdeskPart] = []
            try:
                sevdesk = part_client.list_parts()
            except Exception as exc:  # noqa: BLE001
                logger.warning("sevDesk products not available for sync: %s", exc)
            return (local, wix, sevdesk)

        self._sevdesk_worker = BackgroundWorker(job)
        self._sevdesk_worker.signals.result.connect(self._on_sync_sources_loaded)
        self._sevdesk_worker.signals.error.connect(self._on_sync_sources_error)
        self._sevdesk_worker.start()

    def _on_sync_sources_loaded(self, payload: object) -> None:
        self._sync_load_btn.setEnabled(True)
        if not isinstance(payload, tuple) or len(payload) != 3:
            return
        local_rows, wix_rows, sevdesk_rows = payload
        if not isinstance(local_rows, list) or not isinstance(wix_rows, list) or not isinstance(sevdesk_rows, list):
            return
        self._all_rows = [r for r in local_rows if isinstance(r, ProductRow)]
        self._wix_rows = [r for r in wix_rows if isinstance(r, WixProduct)]
        self._sevdesk_rows = [r for r in sevdesk_rows if isinstance(r, SevdeskPart)]

        self._populate_inv(self._all_rows)
        self._populate_wix(self._wix_rows)
        self._compute_overlap()

        self._sync_rows = self._build_sync_rows()
        self._populate_sync_table(self._sync_rows)
        conflicts = sum(1 for row in self._sync_rows if row.status != "ok")
        self._sync_status_lbl.setText(
            f"Sync-Vergleich geladen: {len(self._sync_rows)} SKU, Konflikte: {conflicts}"
        )
        self._sync_apply_btn.setEnabled(bool(self._wix_rows))

    def _on_sync_sources_error(self, exc: BaseException) -> None:
        self._sync_load_btn.setEnabled(True)
        self._sync_apply_btn.setEnabled(False)
        self._sync_status_lbl.setText(f"Fehler: {exc}")
        logger.exception("Sync source load failed: %s", exc)

    def _build_sync_rows(self) -> list[_SyncRow]:
        local_by_sku = {row.sku: row for row in self._all_rows if row.sku}
        wix_by_sku = {row.sku: row for row in self._wix_rows if row.sku}
        sevdesk_by_sku = {row.sku: row for row in self._sevdesk_rows if row.sku}
        all_skus = sorted(set(local_by_sku) | set(wix_by_sku) | set(sevdesk_by_sku))

        rows: list[_SyncRow] = []
        for sku in all_skus:
            local = local_by_sku.get(sku)
            wix = wix_by_sku.get(sku)
            sevdesk = sevdesk_by_sku.get(sku)

            local_stock = local.on_hand if local is not None else 0
            wix_stock = wix.inventory_quantity if wix is not None else None
            sevdesk_stock = sevdesk.stock_qty if sevdesk is not None else None

            local_price = local.price_eur if local is not None else ""
            wix_price = wix.price if wix is not None else ""
            sevdesk_price = sevdesk.price_eur if sevdesk is not None else ""

            status_parts: list[str] = []
            if local is None:
                status_parts.append("nur extern")
            if wix is None:
                status_parts.append("nicht in wix")
            if sevdesk is None:
                status_parts.append("nicht in sevdesk")
            if wix is not None and local is not None and wix_stock != local_stock:
                status_parts.append("bestand diff wix")
            if sevdesk is not None and local is not None and sevdesk_stock != local_stock:
                status_parts.append("bestand diff sevdesk")
            if wix is not None and local is not None and (wix_price or "") != (local_price or ""):
                status_parts.append("preis diff wix")
            if sevdesk is not None and local is not None and (sevdesk_price or "") != (local_price or ""):
                status_parts.append("preis diff sevdesk")

            rows.append(
                _SyncRow(
                    sku=sku,
                    local_stock=local_stock,
                    wix_stock=wix_stock,
                    sevdesk_stock=sevdesk_stock,
                    local_price=local_price,
                    wix_price=wix_price,
                    sevdesk_price=sevdesk_price,
                    status="; ".join(status_parts) if status_parts else "ok",
                )
            )
        return rows

    def _populate_sync_table(self, rows: list[_SyncRow]) -> None:
        tbl = self._sync_table
        tbl.setRowCount(0)
        for row in rows:
            r = tbl.rowCount()
            tbl.insertRow(r)
            tbl.setItem(r, 0, QTableWidgetItem(row.sku))
            tbl.setItem(r, 1, QTableWidgetItem(str(row.local_stock)))
            tbl.setItem(r, 2, QTableWidgetItem("" if row.wix_stock is None else str(row.wix_stock)))
            tbl.setItem(r, 3, QTableWidgetItem("" if row.sevdesk_stock is None else str(row.sevdesk_stock)))
            tbl.setItem(r, 4, QTableWidgetItem(row.local_price))
            tbl.setItem(r, 5, QTableWidgetItem(row.wix_price))
            tbl.setItem(r, 6, QTableWidgetItem(row.sevdesk_price))
            status_item = QTableWidgetItem(row.status)
            if row.status == "ok":
                status_item.setForeground(Qt.GlobalColor.green)
            else:
                status_item.setForeground(Qt.GlobalColor.yellow)
            tbl.setItem(r, 7, status_item)
        for col in (1, 2, 3):
            tbl.resizeColumnToContents(col)

    def _apply_wix_to_local(self) -> None:
        if not self._wix_rows:
            QMessageBox.information(self, "Produkte", "Bitte zuerst Wix-Daten laden.")
            return
        inv: InventoryService = self._container.resolve(InventoryService)

        local_by_sku = {row.sku: row for row in self._all_rows if row.sku}
        merged = dict(local_by_sku)
        changed = 0
        for wix in self._wix_rows:
            if not wix.sku:
                continue
            current = merged.get(wix.sku)
            if current is None:
                merged[wix.sku] = ProductRow(
                    sku=wix.sku,
                    name=wix.name,
                    category="",
                    on_hand=max(0, int(wix.inventory_quantity)),
                    price_eur=wix.price,
                    wix_id=wix.id,
                    sevdesk_id="",
                )
                changed += 1
                continue
            updated = ProductRow(
                sku=current.sku,
                name=current.name or wix.name,
                category=current.category,
                on_hand=max(0, int(wix.inventory_quantity)),
                price_eur=wix.price or current.price_eur,
                wix_id=wix.id or current.wix_id,
                sevdesk_id=current.sevdesk_id,
            )
            if updated != current:
                merged[wix.sku] = updated
                changed += 1

        if changed == 0:
            QMessageBox.information(self, "Produkte", "Keine Aenderungen aus Wix zu uebernehmen.")
            return

        to_save = sorted(merged.values(), key=lambda row: row.sku)
        self._sync_apply_btn.setEnabled(False)
        self._sync_status_lbl.setText("Speichere Wix->Lokal Abgleich...")

        def job() -> int:
            inv.save_products(to_save)
            return changed

        self._save_worker = BackgroundWorker(job)
        self._save_worker.signals.result.connect(self._on_apply_done)
        self._save_worker.signals.error.connect(self._on_apply_error)
        self._save_worker.start()

    def _on_apply_done(self, changed: object) -> None:
        self._sync_apply_btn.setEnabled(True)
        count = int(changed) if isinstance(changed, int) else 0
        self._sync_status_lbl.setText(f"Wix->Lokal gespeichert: {count} Produkte aktualisiert")
        QMessageBox.information(self, "Produkte", f"{count} Produkte wurden lokal aktualisiert.")
        self._load_inventory()

    def _on_apply_error(self, exc: BaseException) -> None:
        self._sync_apply_btn.setEnabled(True)
        self._sync_status_lbl.setText(f"Fehler: {exc}")
        QMessageBox.warning(self, "Produkte", str(exc))

    def _load_print_plans(self) -> None:
        inv: InventoryService = self._container.resolve(InventoryService)
        plans = inv.load_print_plans()
        self._plans_editor.setPlainText(json.dumps(plans, ensure_ascii=False, indent=2))

    def _save_print_plans(self) -> None:
        inv: InventoryService = self._container.resolve(InventoryService)
        raw = self._plans_editor.toPlainText().strip() or "[]"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            QMessageBox.warning(self, "Druckplaene", f"Ungueltiges JSON: {exc}")
            return
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            QMessageBox.warning(self, "Druckplaene", "Erwartet wird ein JSON-Array aus Objekten.")
            return
        inv.save_print_plans(data)
        QMessageBox.information(self, "Druckplaene", f"{len(data)} Druckplan-Eintraege gespeichert.")
