"""Steuern module — tab shell for UVA, clearing, expenses."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from xw_studio.core.container import Container


def _placeholder_tab(message: str) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    label = QLabel(message)
    label.setWordWrap(True)
    label.setStyleSheet("font-size: 14px; color: #888; padding: 24px;")
    layout.addWidget(label)
    return page


class TaxesView(QWidget):
    """UVA | Clearing | Ausgaben (content wired in Phase 2)."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _ = container
        tabs = QTabWidget()
        tabs.addTab(
            _placeholder_tab(
                "UVA / FinanzOnline – SOAP-Client und Meldungen werden hier angebunden "
                "(siehe docs/copilot_migration_plan.md)."
            ),
            "UVA",
        )
        tabs.addTab(
            _placeholder_tab(
                "Zahlungsclearing – Stripe/Mollie und Ausgleich mit Rechnungen (Phase 2)."
            ),
            "Clearing",
        )
        tabs.addTab(
            _placeholder_tab(
                "Ausgaben-Check – Ausgabenprüfung und Freigaben (Phase 2)."
            ),
            "Ausgaben",
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.addWidget(tabs)
