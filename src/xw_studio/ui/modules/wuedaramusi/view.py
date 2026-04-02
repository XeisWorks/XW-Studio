"""WuedaraMusi submodule placeholder."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from xw_studio.core.container import Container


class WuedaraMusiView(QWidget):
    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _ = container
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("WuedaraMusi — Rechnungen/Workflow (Migration aus Altprojekt)."))
        layout.addStretch()
