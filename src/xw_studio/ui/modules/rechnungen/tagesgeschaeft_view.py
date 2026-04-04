"""Tagesgeschäft — tabbed Daily-Business hub (Rechnungen, Mollie, Gutscheine, …)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent, QHideEvent, QShowEvent
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
from xw_studio.services.daily_business.service import DailyBusinessService
from xw_studio.services.inventory.service import (
    InventoryService,
    ReprintExecutionReport,
    ReprintPreflight,
    StartExecutionReport,
    StartMode,
    StartPreflight,
)
from xw_studio.services.invoice_processing.service import InvoiceProcessingService
from xw_studio.ui.modules.rechnungen.reprint_dialog import ReprintPreviewDialog
from xw_studio.ui.modules.rechnungen.view import RechnungenView
from xw_studio.ui.widgets.data_table import DataTable
from xw_studio.ui.widgets.search_bar import SearchBar

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)

_QUEUE_COLUMNS = ["Ref", "Kunde", "Betrag", "Status", "Hinweis", "Mark."]


class _QueueTabView(QWidget):
    """Generic queue tab for Mollie/Gutscheine/Downloads/Refunds."""

    def __init__(self, container: Container, queue_name: str, title: str) -> None:
        super().__init__()
        self._container = container
        self._queue_name = queue_name
        self._title = title
        self._worker: BackgroundWorker | None = None
        self._rows: list[dict[str, str]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._caption = QLabel(self._title)
        self._caption.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self._caption)

        row = QHBoxLayout()
        self._search = SearchBar("Suchen…")
        self._search.search_changed.connect(self._on_search)
        self._search.set_suggestion_provider(self._queue_search_suggestions)
        row.addWidget(self._search, stretch=1)
        self._count_lbl = QLabel("0 Eintraege")
        row.addWidget(self._count_lbl)
        self._btn_refresh = QPushButton("Aktualisieren")
        self._btn_refresh.clicked.connect(lambda: self.reload())
        row.addWidget(self._btn_refresh)
        layout.addLayout(row)

        self._table = DataTable(_QUEUE_COLUMNS)
        layout.addWidget(self._table, stretch=1)
        self._detail = QLabel("Zeile waehlen fuer Details …")
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet("color: #9e9e9e; padding: 6px 2px;")
        layout.addWidget(self._detail)

        sel = self._table.selectionModel()
        if sel is not None:
            sel.selectionChanged.connect(self._on_selection_changed)

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(2000)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(2000)
        super().closeEvent(event)

    def reload(self, fallback_count: int = 0) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._btn_refresh.setEnabled(False)

        def job() -> list[dict[str, str]]:
            service: DailyBusinessService = self._container.resolve(DailyBusinessService)
            return service.load_queue_rows(self._queue_name, fallback_count=fallback_count)

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_load_result)
        self._worker.signals.error.connect(self._on_load_error)
        self._worker.signals.finished.connect(lambda: self._btn_refresh.setEnabled(True))
        self._worker.start()

    def _on_load_result(self, result: object) -> None:
        rows = result if isinstance(result, list) else []
        norm_rows = [r for r in rows if isinstance(r, dict)]
        self._rows = norm_rows
        self._table.set_data(norm_rows)
        self._search.refresh_suggestions()
        self._count_lbl.setText(f"{len(norm_rows)} Eintraege")
        self._detail.setText("Zeile waehlen fuer Details …")

    def _on_load_error(self, exc: Exception) -> None:
        logger.warning("Queue '%s' load failed: %s", self._queue_name, exc)
        self._count_lbl.setText("Fehler")

    def _on_search(self, text: str) -> None:
        self._table.set_filter(text, column=0)

    def _queue_search_suggestions(self, query: str) -> list[str]:
        q = query.lower().strip()
        if len(q) < 3:
            return []
        items: list[str] = []
        for row in self._rows:
            hay = f"{row.get('Ref', '')} {row.get('Kunde', '')} {row.get('Status', '')} {row.get('Hinweis', '')}".lower()
            if q in hay:
                items.append(f"{row.get('Ref', '—')} - {row.get('Kunde', '—')}")
        return items

    def _on_selection_changed(self, _selected: object, _deselected: object) -> None:
        row = self._table.selected_row_data() or {}
        if not row:
            self._detail.setText("Zeile waehlen fuer Details …")
            return
        self._detail.setText(
            f"Ref: {row.get('Ref', '—')}\n"
            f"Kunde: {row.get('Kunde', '—')}\n"
            f"Betrag: {row.get('Betrag', '—')}\n"
            f"Status: {row.get('Status', '—')}\n"
            f"Hinweis: {row.get('Hinweis', '—')}"
        )


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
            f"Entwürfe zur Abarbeitung: {self._preflight.open_invoice_count}",
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
        self._start_exec_worker: BackgroundWorker | None = None
        self._reprint_worker: BackgroundWorker | None = None
        self._reprint_exec_worker: BackgroundWorker | None = None
        self._badge_timer = QTimer(self)
        self._badge_timer.setInterval(60000)
        self._badge_timer.timeout.connect(self._refresh_badges)
        self._build_ui()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._refresh_badges()
        self._badge_timer.start()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self._badge_timer.stop()
        self._wait_for_workers()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._badge_timer.stop()
        self._wait_for_workers()
        super().closeEvent(event)

    def _wait_for_workers(self) -> None:
        for worker in (self._badge_worker, self._start_worker, self._start_exec_worker, 
                       self._reprint_worker, self._reprint_exec_worker):
            if worker is not None and worker.isRunning():
                worker.wait(3000)

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

        btn_reprints = QPushButton("🖨  Nachdrucke")
        btn_reprints.setToolTip("Lagerbestand auffüllen: Nachdrucke nur Lagerfüllung (kein Invoice-Konsum)")
        btn_reprints.setFixedHeight(34)
        btn_reprints.setFixedWidth(140)
        btn_reprints.setStyleSheet(
            "QPushButton { background-color: #388e3c; color: white; border-radius: 6px;"
            " font-weight: bold; font-size: 13px; }"
            " QPushButton:hover { background-color: #2e7d32; }"
            " QPushButton:pressed { background-color: #1b5e20; }"
        )
        btn_reprints.clicked.connect(self._on_reprints_clicked)
        bar_lay.addWidget(btn_reprints)

        main_layout.addWidget(action_bar)

        # — Tab widget —
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        self._rechnungen_view = RechnungenView(self._container)
        self._mollie_view = _QueueTabView(self._container, "mollie", "Mollie Authorized")
        self._gutscheine_view = _QueueTabView(self._container, "gutscheine", "Gutscheine")
        self._downloads_view = _QueueTabView(self._container, "downloads", "Download-Links")
        self._refunds_view = _QueueTabView(self._container, "refunds", "Rueckerstattungen")

        self._tabs.addTab(self._rechnungen_view, "📋  Rechnungen")
        self._tabs.addTab(self._mollie_view, "💳  Mollie")
        self._tabs.addTab(self._gutscheine_view, "🎁  Gutscheine")
        self._tabs.addTab(self._downloads_view, "📥  Downloads")
        self._tabs.addTab(self._refunds_view, "↩  Refunds")

        main_layout.addWidget(self._tabs, stretch=1)

    def _refresh_badges(self) -> None:
        if self._badge_worker is not None and self._badge_worker.isRunning():
            return

        def job() -> dict[str, int]:
            invoice_service: InvoiceProcessingService = self._container.resolve(InvoiceProcessingService)
            open_count = invoice_service.count_invoices(status=100)
            service: DailyBusinessService = self._container.resolve(DailyBusinessService)
            return service.load_counts(open_invoice_count=open_count)

        self._badge_worker = BackgroundWorker(job)
        self._badge_worker.signals.result.connect(self._on_badges_result)
        self._badge_worker.signals.error.connect(self._on_badges_error)
        self._badge_worker.start()

    def _on_badges_result(self, result: object) -> None:
        counts = result if isinstance(result, dict) else {}
        open_count = max(0, int(counts.get("rechnungen", 0)))
        mollie_count = max(0, int(counts.get("mollie", 0)))
        gutscheine_count = max(0, int(counts.get("gutscheine", 0)))
        downloads_count = max(0, int(counts.get("downloads", 0)))
        refunds_count = max(0, int(counts.get("refunds", 0)))

        prefix = "✳ " if open_count else ""
        self._tabs.setTabText(0, f"{prefix}📋  Rechnungen ({open_count})")
        self._tabs.setTabText(1, f"{'🔴 ' if mollie_count else ''}💳  Mollie ({mollie_count})")
        self._tabs.setTabText(2, f"{'🔴 ' if gutscheine_count else ''}🎁  Gutscheine ({gutscheine_count})")
        self._tabs.setTabText(3, f"{'🔴 ' if downloads_count else ''}📥  Downloads ({downloads_count})")
        self._tabs.setTabText(4, f"{'🔴 ' if refunds_count else ''}↩  Refunds ({refunds_count})")
        self._mollie_view.reload(mollie_count)
        self._gutscheine_view.reload(gutscheine_count)
        self._downloads_view.reload(downloads_count)
        self._refunds_view.reload(refunds_count)
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
            open_count = invoice_service.count_invoices(status=100)
            return inventory_service.build_start_preflight(open_count)

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

        mode = StartMode.INVOICES_ONLY
        if dlg.full_mode:
            mode = StartMode.INVOICES_AND_PRINT

        if mode == StartMode.INVOICES_AND_PRINT and result.missing_position_data:
            QMessageBox.information(
                self,
                "Hinweis",
                "Für den Druckplan fehlen noch Positionsdaten. "
                "Der START läuft daher im Modus 'Nur Rechnungen'.",
            )
            mode = StartMode.INVOICES_ONLY

        logger.info("Tagesgeschäft START: mode=%s", mode.value)

        if self._start_exec_worker is not None and self._start_exec_worker.isRunning():
            return

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("START wird ausgefuehrt…", 2500)

        def job() -> StartExecutionReport:
            inventory_service: InventoryService = self._container.resolve(InventoryService)
            return inventory_service.execute_start_workflow(result, mode)

        self._start_exec_worker = BackgroundWorker(job)
        self._start_exec_worker.signals.result.connect(self._on_start_executed)
        self._start_exec_worker.signals.error.connect(self._on_start_preflight_error)
        self._start_exec_worker.start()

    def _on_start_executed(self, result: object) -> None:
        if not isinstance(result, StartExecutionReport):
            return

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit(
            f"START ausgefuehrt: {result.open_invoice_count} Entwürfe "
            f"({result.mode.value}), Druckjobs: {len(result.printed_skus)}",
            5000,
        )

        QMessageBox.information(
            self,
            "START abgeschlossen",
            (
                f"Modus: {result.mode.value}\n"
                f"Entwürfe zur Abarbeitung: {result.open_invoice_count}\n"
                f"Druckjobs: {len(result.printed_skus)}\n"
                f"Betroffene SKU: {', '.join(result.printed_skus) if result.printed_skus else 'keine'}"
            ),
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

    def _on_reprints_clicked(self) -> None:
        """Trigger reprint preflight job for stock-up workflow."""
        if self._reprint_worker is not None and self._reprint_worker.isRunning():
            return

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("Nachdrucke Pre-Flight wird erstellt…", 2500)

        def job() -> ReprintPreflight:
            service: DailyBusinessService = self._container.resolve(DailyBusinessService)
            requirements = service.load_requirements()
            inventory_service: InventoryService = self._container.resolve(InventoryService)
            return inventory_service.build_reprint_preflight(requirements)

        self._reprint_worker = BackgroundWorker(job)
        self._reprint_worker.signals.result.connect(self._on_reprint_preflight_ready)
        self._reprint_worker.signals.error.connect(self._on_reprint_error)
        self._reprint_worker.start()

    def _on_reprint_preflight_ready(self, result: object) -> None:
        """Show reprint preview dialog after preflight job completes."""
        if not isinstance(result, ReprintPreflight):
            return

        dlg = ReprintPreviewDialog(result, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        if self._reprint_exec_worker is not None and self._reprint_exec_worker.isRunning():
            return

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("Nachdrucke werden ausgefuehrt…", 2500)

        def job() -> object:
            inventory_service: InventoryService = self._container.resolve(InventoryService)
            return inventory_service.execute_reprint_workflow(result)

        self._reprint_exec_worker = BackgroundWorker(job)
        self._reprint_exec_worker.signals.result.connect(self._on_reprint_executed)
        self._reprint_exec_worker.signals.error.connect(self._on_reprint_error)
        self._reprint_exec_worker.start()

    def _on_reprint_executed(self, result: object) -> None:
        """Show reprint execution summary and refresh UI."""
        if not isinstance(result, ReprintExecutionReport):
            return

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit(
            f"Nachdrucke ausgefuehrt: {result.decisions_count} Positionen geprüft, "
            f"{len(result.printed_skus)} SKUs zum Druck gegeben",
            5000,
        )

        QMessageBox.information(
            self,
            "Nachdrucke abgeschlossen",
            (
                f"Positionen geprüft: {result.decisions_count}\n"
                f"Druckjobs: {len(result.printed_skus)}\n"
                f"SKU: {', '.join(result.printed_skus) if result.printed_skus else 'keine'}\n"
                f"Bestand aktualisiert: {result.stock_updated}"
            ),
        )

        self._refresh_badges()

    def _on_reprint_error(self, exc: Exception) -> None:
        """Handle reprint workflow errors."""
        logger.error("Reprint workflow failed: %s", exc)
        QMessageBox.warning(
            self,
            "Fehler",
            f"Nachdrucke-Workflow konnte nicht ausgefuehrt werden:\n\n{exc}",
        )
