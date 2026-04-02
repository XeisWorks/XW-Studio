"""Marketing — roadmap and local idea capture."""
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
from xw_studio.services.ideas.stores import MarketingIdeasStore

if TYPE_CHECKING:
    from xw_studio.core.container import Container


class MarketingView(QWidget):
    """Collect marketing ideas locally (JSON); sync via DB later."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store: MarketingIdeasStore = container.resolve(MarketingIdeasStore)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(QLabel("Marketing — Ideen & Content-Planung"))
        self._title = QLineEdit()
        self._title.setPlaceholderText("Titel")
        self._body = QPlainTextEdit()
        self._body.setPlaceholderText("Notizen, Links, Kampagnen …")
        layout.addWidget(self._title)
        layout.addWidget(self._body, stretch=1)
        row = QHBoxLayout()
        save = QPushButton("Speichern")
        reload = QPushButton("Liste anzeigen")
        row.addWidget(save)
        row.addWidget(reload)
        row.addStretch()
        layout.addLayout(row)

        save.clicked.connect(self._on_save)
        reload.clicked.connect(self._on_list)

    def _on_save(self) -> None:
        title = self._title.text().strip()
        if not title:
            QMessageBox.warning(self, "Marketing", "Bitte einen Titel eingeben.")
            return
        self._store.add_idea(IdeaEntry(title=title, body=self._body.toPlainText().strip()))
        QMessageBox.information(self, "Marketing", "Idee gespeichert.")
        self._title.clear()
        self._body.clear()

    def _on_list(self) -> None:
        ideas = self._store.list_ideas()
        if not ideas:
            QMessageBox.information(self, "Marketing", "Noch keine Ideen gespeichert.")
            return
        text = "\n\n".join(f"• {i.title}\n{i.body}" for i in ideas[-20:])
        QMessageBox.information(self, "Marketing (letzte 20)", text)
