"""Provisionen & Kalkulation module."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from xw_studio.services.calculation import CalculationService

if TYPE_CHECKING:
    from xw_studio.core.container import Container


class CalculationView(QWidget):
    """Royalty / cost calculation shell."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        svc = CalculationService()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(QLabel(svc.describe()))
        layout.addStretch()
