"""Tagesgeschäft — tabbed Daily-Business hub (Rechnungen, Mollie, Gutscheine, …)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.signals import AppSignals
from xw_studio.core.types import ModuleKey
from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.inventory.service import InventoryService, StartPreflight
from xw_studio.services.invoice_processing.service import InvoiceProcessingService
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

    def __init__(self, preflight: StartPreflight, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preflight = preflight
        self.setWindowTitle("Tagesgeschäft starten")
        self.setMinimumWidth(640)
        self.setMinimumHeight(520)
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

        gb_preview = QGroupBox("Pre-Flight (Bestand vs. Bedarf)")
        preview_layout = QVBoxLayout(gb_preview)
        self._preview_text = QPlainTextEdit()
        self._preview_text.setReadOnly(True)
        self._preview_text.setMinimumHeight(260)
        self._preview_text.setPlainText(self._format_preflight())
        preview_layout.addWidget(self._preview_text)
        layout.addWidget(gb_preview)

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

    def _format_preflight(self) -> str:
        lines: list[str] = [
            f"Offene Rechnungen: {self._preflight.open_invoice_count}",
            "",
        ]
        if self._preflight.missing_position_data:
            lines.extend(
                [
                    "Noch keine Artikel-Positionsdaten für den Druckplan vorhanden.",
                    "Lege für die nächste Ausbaustufe die Queue als JSON in der DB an:",
                    "Key: daily_business.pending_requirements",
                    "Beispiel: {\"XW-4-001\": 7, \"XW-6-003\": 2}",
                ]
            )
            return "\n".join(lines)

        if not self._preflight.decisions:
            lines.append("Keine Druckjobs für den aktuellen Queue-Stand.")
            return "\n".join(lines)

        lines.append("SKU | Bedarf | Lager | Fehlmenge | Druck inkl. Puffer | Aktion")
        lines.append("-" * 72)
        for decision in self._preflight.decisions:
            action = "DRUCK" if decision.will_print else "OK"
            lines.append(
                f"{decision.sku} | {decision.required_qty} | {decision.on_hand_qty} | "
                f"{decision.missing_qty} | {decision.final_print_qty} | {action}"
            )
        return "\n".join(lines)


class TagesgeschaeftView(QWidget):
    """Tabbed Daily-Business hub — Rechnungen tab is fully functional."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._badge_worker: BackgroundWorker | None = None
        self._start_worker: BackgroundWorker | None = None
        self._build_ui()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._refresh_badges()

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

    def _refresh_badges(self) -> None:
        if self._badge_worker is not None and self._badge_worker.isRunning():
            return

        def job() -> int:
            invoice_service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            open_invoices = invoice_service.load_invoice_summaries(status=200, limit=100, offset=0)
            return len(open_invoices)

        self._badge_worker = BackgroundWorker(job)
        self._badge_worker.signals.result.connect(self._on_badges_result)
        self._badge_worker.signals.error.connect(self._on_badges_error)
        self._badge_worker.start()

    def _on_badges_result(self, result: object) -> None:
        open_count = max(0, int(result) if isinstance(result, int) else 0)
        self._tabs.setTabText(0, f"📋  Rechnungen ({open_count})")
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.badge_updated.emit(ModuleKey.RECHNUNGEN.value, open_count)

    def _on_badges_error(self, exc: Exception) -> None:
        logger.warning("Badge refresh failed: %s", exc)

    def _on_start_clicked(self) -> None:
        if self._start_worker is not None and self._start_worker.isRunning():
            return

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("Pre-Flight wird erstellt…", 2500)

        def job() -> StartPreflight:
            invoice_service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            inventory_service: InventoryService = self._container.resolve(InventoryService)
            open_invoices = invoice_service.load_invoice_summaries(status=200, limit=100, offset=0)
            return inventory_service.build_start_preflight(len(open_invoices))

        self._start_worker = BackgroundWorker(job)
        self._start_worker.signals.result.connect(self._on_start_preflight_ready)
        self._start_worker.signals.error.connect(self._on_start_preflight_error)
        self._start_worker.start()

    def _on_start_preflight_ready(self, result: object) -> None:
        if not isinstance(result, StartPreflight):
            return
        dlg = _StartDialog(result, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        mode = "full" if dlg.full_mode else "invoices"
        if mode == "full" and result.missing_position_data:
            QMessageBox.information(
                self,
                "Hinweis",
                "Für den Druckplan fehlen noch Positionsdaten. "
                "Der START läuft daher im Modus 'Nur Rechnungen'.",
            )
            mode = "invoices"

        logger.info("Tagesgeschäft START: mode=%s", mode)

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit(
            f"START ausgeführt: {result.open_invoice_count} offene Rechnungen ({mode})",
            5000,
        )

        self._tabs.setCurrentIndex(0)
        self._rechnungen_view._reload_first_page()  # noqa: SLF001
        self._refresh_badges()

    def _on_start_preflight_error(self, exc: Exception) -> None:
        logger.error("Preflight failed: %s", exc)
        QMessageBox.warning(
            self,
            "Fehler",
            f"Pre-Flight konnte nicht erstellt werden:\n\n{exc}",
        )
