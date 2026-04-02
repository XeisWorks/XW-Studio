"""Tagesgeschäft — tabbed Daily-Business hub (Rechnungen, Mollie, Gutscheine, …)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xw_studio.ui.modules.rechnungen.view import RechnungenView

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)


def _placeholder_tab(label: str) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    hint = QLabel(f"{label} — Implementierung folgt")
    hint.setStyleSheet("color: #9e9e9e; font-size: 15px;")
    lay.addWidget(hint)
    return w


class _StartDialog(QDialog):
    """Pre-flight dialog for the ▶ START workflow."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tagesgeschäft starten")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        intro = QLabel(
            "Wähle den gewünschten Modus für den Tagesstart.\n"
            "Die Rückmeldungen aus dem Lager und aus Mollie werden danach automatisch geladen."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        gb = QGroupBox("Modus")
        gb_lay = QVBoxLayout(gb)
        self._mode_invoices = QPushButton("📄  Nur Rechnungen")
        self._mode_invoices.setCheckable(True)
        self._mode_invoices.setChecked(True)
        self._mode_invoices.setMinimumHeight(40)
        self._mode_full = QPushButton("📄 + 🖨  Rechnungen + Druck (Noten & Labels vorbereiten)")
        self._mode_full.setCheckable(True)
        self._mode_full.setMinimumHeight(40)
        gb_lay.addWidget(self._mode_invoices)
        gb_lay.addWidget(self._mode_full)
        layout.addWidget(gb)

        # Mutual exclusion
        self._mode_invoices.toggled.connect(lambda c: self._mode_full.setChecked(not c) if c else None)
        self._mode_full.toggled.connect(lambda c: self._mode_invoices.setChecked(not c) if c else None)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def full_mode(self) -> bool:
        return bool(self._mode_full.isChecked())


class TagesgeschaeftView(QWidget):
    """Tabbed Daily-Business hub — Rechnungen tab is fully functional."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # — Top action bar —
        action_bar = QWidget()
        action_bar.setFixedHeight(44)
        bar_lay = QHBoxLayout(action_bar)
        bar_lay.setContentsMargins(12, 4, 12, 4)
        bar_lay.setSpacing(10)

        title = QLabel("Tagesgeschäft")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        bar_lay.addWidget(title)
        bar_lay.addStretch()

        btn_start = QPushButton("▶  START")
        btn_start.setToolTip("Tagesgeschäft starten: Rechnungen & Druck-Workflow")
        btn_start.setFixedHeight(34)
        btn_start.setFixedWidth(130)
        btn_start.setStyleSheet(
            "QPushButton { background-color: #1976d2; color: white; border-radius: 6px;"
            " font-weight: bold; font-size: 13px; }"
            " QPushButton:hover { background-color: #1565c0; }"
            " QPushButton:pressed { background-color: #0d47a1; }"
        )
        btn_start.clicked.connect(self._on_start_clicked)
        bar_lay.addWidget(btn_start)

        main_layout.addWidget(action_bar)

        # — Tab widget —
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        self._rechnungen_view = RechnungenView(self._container)
        self._tabs.addTab(self._rechnungen_view, "📋  Rechnungen")
        self._tabs.addTab(_placeholder_tab("Mollie 💳"), "💳  Mollie")
        self._tabs.addTab(_placeholder_tab("Gutscheine 🎁"), "🎁  Gutscheine")
        self._tabs.addTab(_placeholder_tab("Download-Links 📥"), "📥  Downloads")
        self._tabs.addTab(_placeholder_tab("Rückerstattungen ↩"), "↩  Refunds")

        main_layout.addWidget(self._tabs, stretch=1)

    def _on_start_clicked(self) -> None:
        dlg = _StartDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        mode = "full" if dlg.full_mode else "invoices"
        logger.info("Tagesgeschäft START: mode=%s", mode)
        # Navigate to Rechnungen tab and trigger reload
        self._tabs.setCurrentIndex(0)
        self._rechnungen_view._reload_first_page()  # noqa: SLF001
