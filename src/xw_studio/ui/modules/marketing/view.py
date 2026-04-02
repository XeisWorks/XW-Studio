"""Marketing — roadmap and local idea capture."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from xw_studio.services.ideas.store import IdeaEntry
from xw_studio.services.ideas.stores import MarketingIdeasStore

if TYPE_CHECKING:
    from xw_studio.core.container import Container


class MarketingView(QWidget):
    """Collect marketing ideas locally (JSON) with inline list panel."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store: MarketingIdeasStore = container.resolve(MarketingIdeasStore)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        root.addWidget(QLabel("Marketing — Ideen & Content-Planung"))

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- entry panel (left) ---
        entry_widget = QWidget()
        entry_layout = QVBoxLayout(entry_widget)
        entry_layout.setContentsMargins(0, 0, 8, 0)
        entry_layout.addWidget(QLabel("Neue Idee"))
        self._title = QPlainTextEdit()
        self._title.setPlaceholderText("Titel")
        self._title.setMaximumHeight(60)
        self._body = QPlainTextEdit()
        self._body.setPlaceholderText("Notizen, Links, Kampagnen …")
        entry_layout.addWidget(self._title)
        entry_layout.addWidget(self._body, stretch=1)
        btn_row = QHBoxLayout()
        save = QPushButton("Speichern")
        save.clicked.connect(self._on_save)
        btn_row.addWidget(save)
        btn_row.addStretch()
        entry_layout.addLayout(btn_row)
        splitter.addWidget(entry_widget)

        # --- list panel (right) ---
        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(8, 0, 0, 0)
        list_header = QHBoxLayout()
        list_header.addWidget(QLabel("Gespeicherte Ideen"))
        list_header.addStretch()
        del_btn = QPushButton("Eintrag löschen")
        del_btn.clicked.connect(self._on_delete)
        list_header.addWidget(del_btn)
        list_layout.addLayout(list_header)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_select)
        list_layout.addWidget(self._list, stretch=2)
        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setPlaceholderText("Eintrag auswählen…")
        list_layout.addWidget(self._detail, stretch=1)
        splitter.addWidget(list_widget)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter)
        self._refresh_list()

    def _on_save(self) -> None:
        title = self._title.toPlainText().strip()
        if not title:
            QMessageBox.warning(self, "Marketing", "Bitte einen Titel eingeben.")
            return
        self._store.add_idea(IdeaEntry(title=title, body=self._body.toPlainText().strip()))
        self._title.clear()
        self._body.clear()
        self._refresh_list()

    def _on_delete(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        ideas = self._store.list_ideas()
        if row >= len(ideas):
            return
        ideas.pop(row)
        self._store.replace_all(ideas)
        self._detail.clear()
        self._refresh_list()

    def _on_select(self, row: int) -> None:
        ideas = self._store.list_ideas()
        if 0 <= row < len(ideas):
            idea = ideas[row]
            self._detail.setPlainText(f"{idea.title}\n\n{idea.body}")

    def _refresh_list(self) -> None:
        self._list.clear()
        for idea in self._store.list_ideas():
            self._list.addItem(QListWidgetItem(idea.title))
