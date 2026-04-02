"""App-wide settings — DB status, secrets overview, printer config."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.worker import BackgroundWorker

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)

_OK_STYLE = "color: #4caf50; font-weight: bold;"
_WARN_STYLE = "color: #ffa726; font-weight: bold;"
_ERR_STYLE = "color: #ef5350; font-weight: bold;"


def _pill(text: str, ok: bool) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(_OK_STYLE if ok else _WARN_STYLE)
    return lbl


class SettingsView(QWidget):
    """Infrastructure status and configuration overview."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._db_worker: BackgroundWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        cfg = self._container.config

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        main = QVBoxLayout(content)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(14)

        # --- Datenbank ---
        gb_db = QGroupBox("Datenbank (PostgreSQL / Railway)")
        form_db = QFormLayout(gb_db)
        db_url = (cfg.database_url or "").strip()
        form_db.addRow("DATABASE_URL:", _pill("gesetzt ✓", bool(db_url)) if db_url else _pill("fehlt ✗", False))
        self._db_status_lbl = QLabel("—")
        self._db_status_lbl.setStyleSheet("color: #9e9e9e;")
        form_db.addRow("Verbindung:", self._db_status_lbl)
        btn_test = QPushButton("Verbindung testen")
        btn_test.setFixedWidth(160)
        btn_test.clicked.connect(self._test_db)
        btn_test.setEnabled(bool(db_url))
        row_btn = QHBoxLayout()
        row_btn.addWidget(btn_test)
        row_btn.addStretch()
        form_db.addRow("", row_btn)  # type: ignore[arg-type]
        main.addWidget(gb_db)

        # --- Secrets / API-Token ---
        gb_secrets = QGroupBox("API-Zugangsdaten")
        form_sec = QFormLayout(gb_secrets)
        sevdesk_ok = bool((cfg.sevdesk.api_token or "").strip())
        wix_ok = bool((cfg.wix.api_key or "").strip())
        fernet_ok = bool((cfg.fernet_master_key or "").strip())
        form_sec.addRow("SEVDESK_API_TOKEN:", _pill("gesetzt ✓", sevdesk_ok) if sevdesk_ok else _pill("fehlt ✗", False))
        form_sec.addRow("WIX_API_KEY:", _pill("gesetzt ✓", wix_ok) if wix_ok else _pill("fehlt ✗", False))
        form_sec.addRow("FERNET_MASTER_KEY:", _pill("gesetzt ✓", fernet_ok) if fernet_ok else _pill("fehlt ✗", False))
        main.addWidget(gb_secrets)

        # --- Drucker ---
        gb_printer = QGroupBox("Drucker (konfiguriert)")
        form_pr = QFormLayout(gb_printer)
        printer_names = cfg.printing.configured_printer_names or []
        form_pr.addRow("Musik-DPI:", QLabel(str(cfg.printing.music_dpi)))
        form_pr.addRow("Rechnungs-DPI:", QLabel(str(cfg.printing.invoice_dpi)))
        form_pr.addRow("Puffer-Menge:", QLabel(str(cfg.printing.buffer_quantity)))
        if printer_names:
            for i, name in enumerate(printer_names, 1):
                form_pr.addRow(f"Drucker {i}:", QLabel(name))
        else:
            form_pr.addRow("Drucker:", _pill("keine konfiguriert", False))
        main.addWidget(gb_printer)

        main.addStretch()
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _test_db(self) -> None:
        if self._db_worker is not None and self._db_worker.isRunning():
            return
        self._db_status_lbl.setText("Prüfe…")
        self._db_status_lbl.setStyleSheet("color: #9e9e9e;")
        cfg = self._container.config

        def ping() -> str:
            try:
                from sqlalchemy import text  # local import keeps startup lean
                from xw_studio.core.database import create_engine_from_config
                engine = create_engine_from_config(cfg)
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                return "ok"
            except Exception as exc:
                return str(exc)

        self._db_worker = BackgroundWorker(ping)
        self._db_worker.signals.result.connect(self._on_db_result)
        self._db_worker.signals.error.connect(self._on_db_error)
        self._db_worker.start()

    def _on_db_result(self, result: object) -> None:
        msg = str(result)
        if msg == "ok":
            self._db_status_lbl.setText("Verbunden ✓")
            self._db_status_lbl.setStyleSheet(_OK_STYLE)
        else:
            short = msg[:120] + ("…" if len(msg) > 120 else "")
            self._db_status_lbl.setText(f"Fehler: {short}")
            self._db_status_lbl.setStyleSheet(_ERR_STYLE)

    def _on_db_error(self, exc: Exception) -> None:
        logger.error("DB ping failed: %s", exc)
        self._db_status_lbl.setText(f"Fehler: {exc}")
        self._db_status_lbl.setStyleSheet(_ERR_STYLE)
