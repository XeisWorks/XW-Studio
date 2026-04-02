"""Notensatz — local idea capture for etudes / digitization roadmap."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xw_studio.services.ideas.store import IdeaEntry
from xw_studio.services.ideas.stores import NotationIdeasStore

if TYPE_CHECKING:
    from xw_studio.core.container import Container


class NotationView(QWidget):
    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store: NotationIdeasStore = container.resolve(NotationIdeasStore)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(QLabel("Notensatz — Ideen & Projekte"))
        self._title = QLineEdit()
        self._title.setPlaceholderText("Projekt / Etuede")
        self._body = QPlainTextEdit()
        self._body.setPlaceholderText("Skizzen, Quellen-PDFs, Zieltonarten …")
        layout.addWidget(self._title)
        layout.addWidget(self._body, stretch=1)
        row = QHBoxLayout()
        save = QPushButton("Speichern")
        show = QPushButton("Liste anzeigen")
        row.addWidget(save)
        row.addWidget(show)
        row.addStretch()
        layout.addLayout(row)
        save.clicked.connect(self._on_save)
        show.clicked.connect(self._on_list)

    def _on_save(self) -> None:
        title = self._title.text().strip()
        if not title:
            QMessageBox.warning(self, "Notensatz", "Bitte einen Titel eingeben.")
            return
        self._store.add_idea(IdeaEntry(title=title, body=self._body.toPlainText().strip()))
        QMessageBox.information(self, "Notensatz", "Idee gespeichert.")
        self._title.clear()
        self._body.clear()

    def _on_list(self) -> None:
        ideas = self._store.list_ideas()
        if not ideas:
            QMessageBox.information(self, "Notensatz", "Noch keine Eintraege.")
            return
        text = "\n\n".join(f"• {i.title}\n{i.body}" for i in ideas[-20:])
        QMessageBox.information(self, "Notensatz (letzte 20)", text)
