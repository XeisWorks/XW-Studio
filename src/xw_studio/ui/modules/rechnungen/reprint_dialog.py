"""Reprint preview dialog — shows what will be printed vs what's in stock."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from xw_studio.services.inventory.service import ReprintPreflight

logger = logging.getLogger(__name__)


class ReprintPreviewDialog(QDialog):
    """Review and confirm reprint operations before execution.

    Shows:
    - "ZU DRUCKEN" table: SKU, aktuelle Menge, Druck-Menge, neue Menge
    - "IM BESTAND" table: SKUs die nicht gedruckt werden (Stock OK)
    """

    def __init__(self, preflight: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.preflight = preflight
        self.setWindowTitle("📋 Nachdrucke Übersicht")
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # --- Header ---
        header = QLabel("Nachdrucke: Lagerfüllung (nur Auffüllung, kein Invoice-Konsum)")
        header.setStyleSheet("font-size: 13px; font-weight: bold; color: #1976d2;")
        layout.addWidget(header)

        # --- "ZU DRUCKEN" section ---
        gb_print = QGroupBox("🖨 ZU DRUCKEN")
        gb_print_layout = QVBoxLayout(gb_print)

        table_print = QTableWidget()
        table_print.setColumnCount(4)
        table_print.setHorizontalHeaderLabels(["SKU", "Bestand jetzt", "Drucken", "Bestand nachher"])
        table_print.horizontalHeader().setStretchLastSection(True)
        table_print.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table_print.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table_print.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table_print.setMaximumHeight(200)

        to_print = [d for d in self.preflight.decisions if d.will_print]
        table_print.setRowCount(len(to_print))

        for row, decision in enumerate(to_print):
            new_stock = decision.on_hand_qty + decision.final_print_qty
            table_print.setItem(row, 0, QTableWidgetItem(decision.sku))
            table_print.setItem(row, 1, QTableWidgetItem(str(decision.on_hand_qty)))
            table_print.setItem(row, 2, QTableWidgetItem(str(decision.final_print_qty)))
            table_print.setItem(row, 3, QTableWidgetItem(str(new_stock)))
            # Highlight print rows
            for col in range(4):
                item = table_print.item(row, col)
                item.setBackground(Qt.GlobalColor.yellow)
                item.setForeground(Qt.GlobalColor.black)

        gb_print_layout.addWidget(table_print)

        summary_print = QLabel(
            f"Gesamt: {len(to_print)} Positionen werden gedruckt "
            f"({sum(d.final_print_qty for d in to_print)} Stück)"
        )
        summary_print.setStyleSheet("font-size: 11px; color: #f57c00;")
        gb_print_layout.addWidget(summary_print)
        layout.addWidget(gb_print)

        # --- "IM BESTAND" section ---
        gb_stock = QGroupBox("✓ IM BESTAND (nicht nötig)")
        gb_stock_layout = QVBoxLayout(gb_stock)

        table_stock = QTableWidget()
        table_stock.setColumnCount(2)
        table_stock.setHorizontalHeaderLabels(["SKU", "Bestand"])
        table_stock.horizontalHeader().setStretchLastSection(True)
        table_stock.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table_stock.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table_stock.setMaximumHeight(150)

        in_stock = [d for d in self.preflight.decisions if not d.will_print]
        table_stock.setRowCount(len(in_stock))

        for row, decision in enumerate(in_stock):
            table_stock.setItem(row, 0, QTableWidgetItem(decision.sku))
            table_stock.setItem(row, 1, QTableWidgetItem(str(decision.on_hand_qty)))
            # Green for in-stock items
            for col in range(2):
                item = table_stock.item(row, col)
                item.setBackground(Qt.GlobalColor.green)
                item.setForeground(Qt.GlobalColor.white)

        gb_stock_layout.addWidget(table_stock)

        summary_stock = QLabel(f"Gesamt: {len(in_stock)} Positionen im ausreichenden Bestand")
        summary_stock.setStyleSheet("font-size: 11px; color: #2e7d32;")
        gb_stock_layout.addWidget(summary_stock)
        layout.addWidget(gb_stock)

        # --- Buttons ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
