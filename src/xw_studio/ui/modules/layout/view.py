"""Layout module — tool roadmap cards."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from xw_studio.services.layout import LayoutToolsService
from xw_studio.ui.widgets.card import Card

if TYPE_CHECKING:
    from xw_studio.core.container import Container


class LayoutView(QWidget):
    """PDF layout tools (hooks into LayoutToolsService)."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _ = container
        svc = LayoutToolsService()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(QLabel("Layout-Werkzeuge — Panels werden schrittweise befuellt."))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setSpacing(16)

        for i, (title, subtitle) in enumerate(svc.describe_tools()):
            card = Card(title, subtitle, accent_color="#26c6da")
            row, col = divmod(i, 2)
            grid.addWidget(card, row, col)

        scroll.setWidget(inner)
        outer.addWidget(scroll, stretch=1)
