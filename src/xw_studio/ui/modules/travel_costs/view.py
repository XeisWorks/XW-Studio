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
            "Reisekosten-Modul:\n\n"
            "1) Git-Submodule: git submodule add https://github.com/XeisWorks/Reisekosten.git reisekosten\n"
            "2) Bridge: QWidget einbetten, das das Reisekosten-Qt-UI laedt.\n"
            "3) Bis dahin weiterhin eigenstaendiges Repo nutzen.\n\n"
            "Siehe README — App startet ohne Submodule."
        )
        label.setWordWrap(True)
        label.setStyleSheet("font-size: 14px; color: #888; padding: 24px;")
        layout.addWidget(label)
        layout.addStretch()
