"""Notensatz — local idea capture for etudes / digitization roadmap."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from xw_studio.services.ideas.store import IdeaEntry
from xw_studio.services.ideas.stores import NotationIdeasStore

if TYPE_CHECKING:
    from xw_studio.core.container import Container


class NotationView(QWidget):
    """Notensatz — inline list of saved project ideas."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store: NotationIdeasStore = container.resolve(NotationIdeasStore)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        root.addWidget(QLabel("Notensatz — Ideen & Projekte"))

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- entry panel ---
        entry_widget = QWidget()
        entry_layout = QVBoxLayout(entry_widget)
        entry_layout.setContentsMargins(0, 0, 8, 0)
        entry_layout.addWidget(QLabel("Neues Projekt"))
        self._title = QPlainTextEdit()
        self._title.setPlaceholderText("Projekt / Etuede")
        self._title.setMaximumHeight(60)
        meta_row = QHBoxLayout()
        self._channel = QComboBox()
        self._channel.addItems(["", "transposition", "digitalisierung", "satz", "review"])
        self._lane = QComboBox()
        self._lane.addItems(["backlog", "in_progress", "done"])
        self._due = QLineEdit()
        self._due.setPlaceholderText("Faelligkeit (YYYY-MM-DD)")
        meta_row.addWidget(QLabel("Typ"))
        meta_row.addWidget(self._channel)
        meta_row.addWidget(QLabel("Status"))
        meta_row.addWidget(self._lane)
        meta_row.addWidget(self._due)
        self._body = QPlainTextEdit()
        self._body.setPlaceholderText("Skizzen, Quellen-PDFs, Zieltonarten …")
        entry_layout.addWidget(self._title)
        entry_layout.addLayout(meta_row)
        entry_layout.addWidget(self._body, stretch=1)
        btn_row = QHBoxLayout()
        save = QPushButton("Speichern")
        save.clicked.connect(self._on_save)
        btn_row.addWidget(save)
        btn_row.addStretch()
        entry_layout.addLayout(btn_row)
        splitter.addWidget(entry_widget)

        # --- list panel ---
        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(8, 0, 0, 0)
        list_header = QHBoxLayout()
        list_header.addWidget(QLabel("Gespeicherte Einträge"))
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
            QMessageBox.warning(self, "Notensatz", "Bitte einen Titel eingeben.")
            return
        self._store.add_idea(
            IdeaEntry(
                title=title,
                body=self._body.toPlainText().strip(),
                lane=self._lane.currentText(),
                channel=self._channel.currentText(),
                due_date=self._due.text().strip(),
            )
        )
        self._title.clear()
        self._body.clear()
        self._due.clear()
        self._lane.setCurrentIndex(0)
        self._channel.setCurrentIndex(0)
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
            self._detail.setPlainText(
                f"{idea.title}\n"
                f"Status: {idea.lane or 'backlog'}\n"
                f"Typ: {idea.channel or '—'}\n"
                f"Faelligkeit: {idea.due_date or '—'}\n\n"
                f"{idea.body}"
            )

    def _refresh_list(self) -> None:
        self._list.clear()
        for idea in self._store.list_ideas():
            suffix = f" [{idea.lane}]" if idea.lane else ""
            self._list.addItem(QListWidgetItem(f"{idea.title}{suffix}"))
