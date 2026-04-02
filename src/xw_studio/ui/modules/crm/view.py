"""CRM module — mock contacts and duplicate scan."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.crm import ContactRecord, CrmService

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)


def _mock_contacts() -> list[ContactRecord]:
    return [
        ContactRecord(id="1", name="Musik Verlag Nord", email="kontakt@mv-nord.test"),
        ContactRecord(id="2", name="Verlags Nord GmbH", email="kontakt@mv-nord.test"),
        ContactRecord(id="3", name="Klavierschule Sued", email="info@klavier-sued.test"),
    ]


class CrmView(QWidget):
    """Customer maintenance shell with duplicate detection demo."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._worker: BackgroundWorker | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(
            QLabel(
                "CRM: Kontaktdaten aus sevDesk werden hier zusammengefuehrt. "
                "Aktuell Demo-Daten fuer Duplikat-Score."
            )
        )
        self._result = QLabel("")
        self._result.setWordWrap(True)
        layout.addWidget(self._result)
        btn = QPushButton("Duplikate suchen (Demo)")
        btn.clicked.connect(self._run_scan)
        layout.addWidget(btn)
        layout.addStretch()

    def _run_scan(self) -> None:
        crm: CrmService = self._container.resolve(CrmService)

        def job() -> str:
            dups = crm.find_duplicates_in_memory(_mock_contacts())
            if not dups:
                return "Keine Treffer ueber dem Schwellwert."
            lines = [f"Score {d.score}: {d.a.name!r} <> {d.b.name!r}" for d in dups[:10]]
            return "\n".join(lines)

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_result)
        self._worker.signals.error.connect(lambda e: QMessageBox.warning(self, "CRM", str(e)))
        self._worker.start()

    def _on_result(self, text: object) -> None:
        if isinstance(text, str):
            self._result.setText(text)
