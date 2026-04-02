"""Statistik module."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from xw_studio.services.statistics import StatisticsService

if TYPE_CHECKING:
    from xw_studio.core.container import Container


class StatisticsView(QWidget):
    """Business analytics shell."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _ = container
        svc = StatisticsService()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(QLabel(svc.describe()))
        self._summary = QLabel(json.dumps(svc.summary_mock(), ensure_ascii=False, indent=2))
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        layout.addStretch()
