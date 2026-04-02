"""Reisekosten module — embedded submodule (Phase 4)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from xw_studio.core.container import Container


class TravelCostsView(QWidget):
    """Placeholder until Reisekosten repo is added as git submodule + bridge QWidget."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _ = container
        layout = QVBoxLayout(self)
        label = QLabel(
            "Reisekosten-Modul: Git-Submodule unter reisekosten/ einbinden und "
            "hier als QWidget einbetten (siehe README und docs/copilot_migration_plan.md)."
        )
        label.setWordWrap(True)
        label.setStyleSheet("font-size: 14px; color: #888; padding: 24px;")
        layout.addWidget(label)
