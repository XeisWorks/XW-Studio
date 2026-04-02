"""Debounced search input with clear button."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QLineEdit, QWidget


class SearchBar(QLineEdit):
    """Search input with 300ms debounce and clear button."""

    search_changed = Signal(str)

    def __init__(
        self, placeholder: str = "Suchen...", debounce_ms: int = 300,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumHeight(36)
        self.setStyleSheet("padding: 6px 12px; font-size: 14px;")

        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(lambda: self.search_changed.emit(self.text()))
        self.textChanged.connect(lambda _: self._timer.start())
