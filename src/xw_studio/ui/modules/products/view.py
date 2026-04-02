"""Produkte / Inventar module."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from xw_studio.services.inventory import InventoryService

if TYPE_CHECKING:
    from xw_studio.core.container import Container


class ProductsView(QWidget):
    """Inventory, sync, print plans — service hooks only in this baseline."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _ = container
        svc = InventoryService()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(QLabel(svc.describe()))
        layout.addStretch()
