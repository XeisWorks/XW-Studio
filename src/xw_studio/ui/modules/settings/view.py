"""App-wide settings — DB status, secrets overview, printer config."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.signals import AppSignals
from xw_studio.core.worker import BackgroundWorker
from xw_studio.repositories.settings_kv import SettingKvRepository
from xw_studio.services.clickup.client import ClickUpClient, ClickUpTask
from xw_studio.services.secrets.service import SecretService

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)

_OK_STYLE = "color: #4caf50; font-weight: bold;"
_WARN_STYLE = "color: #ffa726; font-weight: bold;"
_ERR_STYLE = "color: #ef5350; font-weight: bold;"
_INV_STOCK_KEY = "inventory.stock_levels"
_PENDING_REQ_KEY = "daily_business.pending_requirements"
_PENDING_COUNTS_KEY = "daily_business.pending_counts"
_QUEUE_MOLLIE_KEY = "daily_business.queue.mollie"
_QUEUE_GUTSCHEINE_KEY = "daily_business.queue.gutscheine"
_QUEUE_DOWNLOADS_KEY = "daily_business.queue.downloads"
_QUEUE_REFUNDS_KEY = "daily_business.queue.refunds"
_SENSITIVE_COUNTRIES_KEY = "rechnungen.sensitive_country_codes"
_CLICKUP_LIST_ID_KEY = "clickup.default_list_id"
_EXTRA_SECRET_KEYS: tuple[str, ...] = (
    "MOLLIE_ACCESS_TOKEN",
    "STRIPE_SECRET_KEY",
    "OPENAI_API_KEY",
    "CLICKUP_API_TOKEN",
    "GOOGLE_MAPS_API_KEY",
    "MS_GRAPH_CLIENT_ID",
    "MS_GRAPH_TENANT_ID",
    "FON_TEILNEHMER_ID",
    "FON_BENUTZER_ID",
    "FON_PIN",
)


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
        self._clickup_worker: BackgroundWorker | None = None
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
        secret_service: SecretService = self._container.resolve(SecretService)
        sevdesk_ok = bool(secret_service.get_secret("SEVDESK_API_TOKEN"))
        wix_ok = bool(secret_service.get_secret("WIX_API_KEY"))
        clickup_ok = bool(secret_service.get_secret("CLICKUP_API_TOKEN"))
        fernet_ok = bool((cfg.fernet_master_key or "").strip())
        form_sec.addRow("SEVDESK_API_TOKEN:", _pill("gesetzt ✓", sevdesk_ok) if sevdesk_ok else _pill("fehlt ✗", False))
        form_sec.addRow("WIX_API_KEY:", _pill("gesetzt ✓", wix_ok) if wix_ok else _pill("fehlt ✗", False))
        form_sec.addRow("CLICKUP_API_TOKEN:", _pill("gesetzt ✓", clickup_ok) if clickup_ok else _pill("fehlt ✗", False))
        form_sec.addRow("FERNET_MASTER_KEY:", _pill("gesetzt ✓", fernet_ok) if fernet_ok else _pill("fehlt ✗", False))
        main.addWidget(gb_secrets)

        gb_secret_edit = QGroupBox("Token-Verwaltung (DB verschluesselt)")
        sec_edit = QFormLayout(gb_secret_edit)
        self._inp_sevdesk = QLineEdit(secret_service.get_secret("SEVDESK_API_TOKEN"))
        self._inp_sevdesk.setEchoMode(QLineEdit.EchoMode.Password)
        self._inp_wix = QLineEdit(secret_service.get_secret("WIX_API_KEY"))
        self._inp_wix.setEchoMode(QLineEdit.EchoMode.Password)
        self._inp_wix_site = QLineEdit(secret_service.get_secret("WIX_SITE_ID"))
        self._inp_wix_account = QLineEdit(secret_service.get_secret("WIX_ACCOUNT_ID"))
        sec_edit.addRow("sevDesk Token:", self._inp_sevdesk)
        sec_edit.addRow("Wix API Key:", self._inp_wix)
        sec_edit.addRow("Wix Site ID:", self._inp_wix_site)
        sec_edit.addRow("Wix Account ID:", self._inp_wix_account)
        self._extra_tokens_json = QPlainTextEdit()
        extra_tokens_obj = {
            key: secret_service.get_secret(key)
            for key in _EXTRA_SECRET_KEYS
            if secret_service.get_secret(key)
        }
        self._extra_tokens_json.setPlaceholderText(
            '{"MOLLIE_ACCESS_TOKEN": "...", "STRIPE_SECRET_KEY": "..."}'
        )
        self._extra_tokens_json.setPlainText(json.dumps(extra_tokens_obj, ensure_ascii=False, indent=2))
        self._extra_tokens_json.setMinimumHeight(120)
        sec_edit.addRow("Weitere Tokens (JSON):", self._extra_tokens_json)
        self._secret_status = QLabel("—")
        self._secret_status.setStyleSheet("color: #9e9e9e;")
        sec_edit.addRow("Status:", self._secret_status)
        btn_save_tokens = QPushButton("Tokens sicher speichern")
        btn_save_tokens.clicked.connect(self._save_tokens)
        sec_edit.addRow("", btn_save_tokens)
        main.addWidget(gb_secret_edit)

        gb_clickup = QGroupBox("ClickUp Schnellanlage")
        clickup_form = QFormLayout(gb_clickup)
        self._clickup_list_id = QLineEdit(self._get_setting_value(_CLICKUP_LIST_ID_KEY))
        self._clickup_list_id.setPlaceholderText("ClickUp Listen-ID")
        self._clickup_title = QLineEdit()
        self._clickup_title.setPlaceholderText("Kurzbeschreibung der Aufgabe")
        self._clickup_description = QPlainTextEdit()
        self._clickup_description.setPlaceholderText("Details, Kontext, naechste Schritte")
        self._clickup_description.setMinimumHeight(90)
        clickup_form.addRow("Listen-ID:", self._clickup_list_id)
        clickup_form.addRow("Titel:", self._clickup_title)
        clickup_form.addRow("Beschreibung:", self._clickup_description)
        self._clickup_status = QLabel("—")
        self._clickup_status.setStyleSheet("color: #9e9e9e;")
        clickup_form.addRow("Status:", self._clickup_status)
        self._clickup_create_btn = QPushButton("Task in ClickUp erstellen")
        self._clickup_create_btn.clicked.connect(self._create_clickup_task)
        clickup_form.addRow("", self._clickup_create_btn)
        main.addWidget(gb_clickup)

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

        # --- START-Queue / Inventar JSON ---
        gb_queue = QGroupBox("START-Preflight Daten (JSON)")
        queue_layout = QVBoxLayout(gb_queue)
        queue_layout.addWidget(
            QLabel(
                "Definiert die Druckentscheidung im START-Dialog. "
                "Format: JSON-Objekt mit SKU als Key und Menge als Zahl."
            )
        )
        queue_layout.addWidget(QLabel(f"{_INV_STOCK_KEY}:"))
        self._stock_json = QPlainTextEdit()
        self._stock_json.setPlaceholderText('{"XW-4-001": 5, "XW-6-003": 1}')
        self._stock_json.setMinimumHeight(90)
        queue_layout.addWidget(self._stock_json)
        queue_layout.addWidget(QLabel(f"{_PENDING_REQ_KEY}:"))
        self._pending_json = QPlainTextEdit()
        self._pending_json.setPlaceholderText('{"XW-4-001": 7, "XW-6-003": 2}')
        self._pending_json.setMinimumHeight(90)
        queue_layout.addWidget(self._pending_json)
        queue_layout.addWidget(QLabel(f"{_PENDING_COUNTS_KEY}:"))
        self._pending_counts_json = QPlainTextEdit()
        self._pending_counts_json.setPlaceholderText(
            '{"mollie": 3, "gutscheine": 1, "downloads": 2, "refunds": 0}'
        )
        self._pending_counts_json.setMinimumHeight(80)
        queue_layout.addWidget(self._pending_counts_json)
        queue_layout.addWidget(QLabel(f"{_QUEUE_MOLLIE_KEY}:"))
        self._queue_mollie_json = QPlainTextEdit()
        self._queue_mollie_json.setPlaceholderText(
            '[{"ref": "MOL-1001", "customer": "Max Mustermann", "amount": "19.90", "status": "Authorized", "note": "wartet auf Rechnung"}]'
        )
        self._queue_mollie_json.setMinimumHeight(90)
        queue_layout.addWidget(self._queue_mollie_json)
        queue_layout.addWidget(QLabel(f"{_QUEUE_GUTSCHEINE_KEY}:"))
        self._queue_gutscheine_json = QPlainTextEdit()
        self._queue_gutscheine_json.setPlaceholderText('[{"ref": "GUT-23", "customer": "Erika Muster", "status": "Offen"}]')
        self._queue_gutscheine_json.setMinimumHeight(80)
        queue_layout.addWidget(self._queue_gutscheine_json)
        queue_layout.addWidget(QLabel(f"{_QUEUE_DOWNLOADS_KEY}:"))
        self._queue_downloads_json = QPlainTextEdit()
        self._queue_downloads_json.setPlaceholderText('[{"ref": "DL-1", "customer": "Demo", "status": "Bereit"}]')
        self._queue_downloads_json.setMinimumHeight(80)
        queue_layout.addWidget(self._queue_downloads_json)
        queue_layout.addWidget(QLabel(f"{_QUEUE_REFUNDS_KEY}:"))
        self._queue_refunds_json = QPlainTextEdit()
        self._queue_refunds_json.setPlaceholderText('[{"ref": "RF-77", "customer": "Demo", "amount": "-9.90", "status": "Offen"}]')
        self._queue_refunds_json.setMinimumHeight(80)
        queue_layout.addWidget(self._queue_refunds_json)
        queue_layout.addWidget(QLabel(f"{_SENSITIVE_COUNTRIES_KEY}:"))
        self._sensitive_countries_json = QPlainTextEdit()
        self._sensitive_countries_json.setPlaceholderText('["RU", "IR", "SY"]')
        self._sensitive_countries_json.setMinimumHeight(70)
        queue_layout.addWidget(self._sensitive_countries_json)
        self._queue_status = QLabel("—")
        self._queue_status.setStyleSheet("color: #9e9e9e;")
        queue_layout.addWidget(self._queue_status)
        save_queue = QPushButton("Queue speichern")
        save_queue.clicked.connect(self._save_queue_settings)
        save_queue.setEnabled(self._has_settings_repo())
        queue_layout.addWidget(save_queue)
        main.addWidget(gb_queue)

        self._load_queue_settings()

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

    def _has_settings_repo(self) -> bool:
        try:
            self._container.resolve(SettingKvRepository)
            return True
        except KeyError:
            return False

    def _get_setting_value(self, key: str) -> str:
        if not self._has_settings_repo():
            return ""
        repo: SettingKvRepository = self._container.resolve(SettingKvRepository)
        return repo.get_value_json(key) or ""

    def _set_setting_value(self, key: str, value: str) -> None:
        if not self._has_settings_repo():
            return
        repo: SettingKvRepository = self._container.resolve(SettingKvRepository)
        repo.set_value_json(key, value)

    def _load_queue_settings(self) -> None:
        if not self._has_settings_repo():
            self._queue_status.setText("DB-Repository nicht aktiv (DATABASE_URL fehlt oder Migration fehlt).")
            self._queue_status.setStyleSheet(_WARN_STYLE)
            return
        repo: SettingKvRepository = self._container.resolve(SettingKvRepository)
        stock = repo.get_value_json(_INV_STOCK_KEY) or "{}"
        pending = repo.get_value_json(_PENDING_REQ_KEY) or "{}"
        pending_counts = repo.get_value_json(_PENDING_COUNTS_KEY) or "{}"
        queue_mollie = repo.get_value_json(_QUEUE_MOLLIE_KEY) or "[]"
        queue_gutscheine = repo.get_value_json(_QUEUE_GUTSCHEINE_KEY) or "[]"
        queue_downloads = repo.get_value_json(_QUEUE_DOWNLOADS_KEY) or "[]"
        queue_refunds = repo.get_value_json(_QUEUE_REFUNDS_KEY) or "[]"
        sensitive_countries = repo.get_value_json(_SENSITIVE_COUNTRIES_KEY) or '["AF", "BY", "IQ", "IR", "KP", "RU", "SY"]'
        self._stock_json.setPlainText(stock)
        self._pending_json.setPlainText(pending)
        self._pending_counts_json.setPlainText(pending_counts)
        self._queue_mollie_json.setPlainText(queue_mollie)
        self._queue_gutscheine_json.setPlainText(queue_gutscheine)
        self._queue_downloads_json.setPlainText(queue_downloads)
        self._queue_refunds_json.setPlainText(queue_refunds)
        self._sensitive_countries_json.setPlainText(sensitive_countries)
        self._queue_status.setText("Aktueller Stand aus DB geladen.")
        self._queue_status.setStyleSheet(_OK_STYLE)

    def _save_queue_settings(self) -> None:
        if not self._has_settings_repo():
            QMessageBox.warning(self, "Fehler", "DB-Repository nicht verfuegbar.")
            return
        stock_raw = self._stock_json.toPlainText().strip() or "{}"
        pending_raw = self._pending_json.toPlainText().strip() or "{}"
        pending_counts_raw = self._pending_counts_json.toPlainText().strip() or "{}"
        queue_mollie_raw = self._queue_mollie_json.toPlainText().strip() or "[]"
        queue_gutscheine_raw = self._queue_gutscheine_json.toPlainText().strip() or "[]"
        queue_downloads_raw = self._queue_downloads_json.toPlainText().strip() or "[]"
        queue_refunds_raw = self._queue_refunds_json.toPlainText().strip() or "[]"
        sensitive_countries_raw = self._sensitive_countries_json.toPlainText().strip() or "[]"
        try:
            stock_obj = json.loads(stock_raw)
            pending_obj = json.loads(pending_raw)
            pending_counts_obj = json.loads(pending_counts_raw)
            queue_mollie_obj = json.loads(queue_mollie_raw)
            queue_gutscheine_obj = json.loads(queue_gutscheine_raw)
            queue_downloads_obj = json.loads(queue_downloads_raw)
            queue_refunds_obj = json.loads(queue_refunds_raw)
            sensitive_countries_obj = json.loads(sensitive_countries_raw)
        except json.JSONDecodeError as exc:
            QMessageBox.warning(self, "JSON-Fehler", f"Ungueltiges JSON:\n\n{exc}")
            return
        if (
            not isinstance(stock_obj, dict)
            or not isinstance(pending_obj, dict)
            or not isinstance(pending_counts_obj, dict)
            or not isinstance(queue_mollie_obj, list)
            or not isinstance(queue_gutscheine_obj, list)
            or not isinstance(queue_downloads_obj, list)
            or not isinstance(queue_refunds_obj, list)
            or not isinstance(sensitive_countries_obj, list)
        ):
            QMessageBox.warning(
                self,
                "Formatfehler",
                "Stock/Pending/Counts muessen Objekte sein; Queue- und Sensitive-Countries-Felder muessen Listen sein.",
            )
            return

        normalized_sensitive = [
            str(code).strip().upper()
            for code in sensitive_countries_obj
            if str(code).strip()
        ]

        repo: SettingKvRepository = self._container.resolve(SettingKvRepository)
        repo.set_value_json(_INV_STOCK_KEY, json.dumps(stock_obj))
        repo.set_value_json(_PENDING_REQ_KEY, json.dumps(pending_obj))
        repo.set_value_json(_PENDING_COUNTS_KEY, json.dumps(pending_counts_obj))
        repo.set_value_json(_QUEUE_MOLLIE_KEY, json.dumps(queue_mollie_obj))
        repo.set_value_json(_QUEUE_GUTSCHEINE_KEY, json.dumps(queue_gutscheine_obj))
        repo.set_value_json(_QUEUE_DOWNLOADS_KEY, json.dumps(queue_downloads_obj))
        repo.set_value_json(_QUEUE_REFUNDS_KEY, json.dumps(queue_refunds_obj))
        repo.set_value_json(_SENSITIVE_COUNTRIES_KEY, json.dumps(normalized_sensitive))
        self._queue_status.setText("Queue-Daten gespeichert.")
        self._queue_status.setStyleSheet(_OK_STYLE)

        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("START-Preflight-Daten gespeichert", 4000)

    def _save_tokens(self) -> None:
        service: SecretService = self._container.resolve(SecretService)
        extra_raw = self._extra_tokens_json.toPlainText().strip() or "{}"
        try:
            extra_obj = json.loads(extra_raw)
        except json.JSONDecodeError as exc:
            self._secret_status.setText(f"JSON-Fehler: {exc}")
            self._secret_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "JSON-Fehler", f"Ungueltiges Token-JSON:\n\n{exc}")
            return
        if not isinstance(extra_obj, dict):
            self._secret_status.setText("Formatfehler bei weiteren Tokens")
            self._secret_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "Formatfehler", "Weitere Tokens muessen ein JSON-Objekt sein.")
            return

        try:
            service.save_secret("SEVDESK_API_TOKEN", self._inp_sevdesk.text())
            service.save_secret("WIX_API_KEY", self._inp_wix.text())
            service.save_secret("WIX_SITE_ID", self._inp_wix_site.text())
            service.save_secret("WIX_ACCOUNT_ID", self._inp_wix_account.text())
            for key in _EXTRA_SECRET_KEYS:
                value = extra_obj.get(key)
                if value is None:
                    continue
                service.save_secret(key, str(value))
        except Exception as exc:
            self._secret_status.setText(f"Fehler: {exc}")
            self._secret_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "Speichern fehlgeschlagen", str(exc))
            return

        self._secret_status.setText("Tokens verschluesselt gespeichert.")
        self._secret_status.setStyleSheet(_OK_STYLE)
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("Tokens wurden in der DB gespeichert", 4500)

    def _create_clickup_task(self) -> None:
        if self._clickup_worker is not None and self._clickup_worker.isRunning():
            return

        title = self._clickup_title.text().strip()
        list_id = self._clickup_list_id.text().strip()
        description = self._clickup_description.toPlainText().strip()
        client: ClickUpClient = self._container.resolve(ClickUpClient)

        if not client.has_credentials():
            self._clickup_status.setText("CLICKUP_API_TOKEN fehlt.")
            self._clickup_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "ClickUp", "Bitte zuerst CLICKUP_API_TOKEN speichern.")
            return
        if not list_id:
            self._clickup_status.setText("Listen-ID fehlt.")
            self._clickup_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "ClickUp", "Bitte eine ClickUp Listen-ID eintragen.")
            return
        if not title:
            self._clickup_status.setText("Titel fehlt.")
            self._clickup_status.setStyleSheet(_ERR_STYLE)
            QMessageBox.warning(self, "ClickUp", "Bitte einen Titel fuer die Aufgabe eingeben.")
            return

        self._clickup_create_btn.setEnabled(False)
        self._clickup_status.setText("Erstelle Task...")
        self._clickup_status.setStyleSheet(_WARN_STYLE)

        def job() -> ClickUpTask:
            return client.create_task(title, description=description, list_id=list_id)

        self._clickup_worker = BackgroundWorker(job)
        self._clickup_worker.signals.result.connect(self._on_clickup_created)
        self._clickup_worker.signals.error.connect(self._on_clickup_error)
        self._clickup_worker.signals.finished.connect(self._on_clickup_finished)
        self._clickup_worker.start()

    def _on_clickup_created(self, task: object) -> None:
        if not isinstance(task, ClickUpTask):
            return
        self._set_setting_value(_CLICKUP_LIST_ID_KEY, self._clickup_list_id.text().strip())
        self._clickup_status.setText(f"Task erstellt: {task.name} ({task.id})")
        self._clickup_status.setStyleSheet(_OK_STYLE)
        self._clickup_title.clear()
        self._clickup_description.clear()
        signals: AppSignals = self._container.resolve(AppSignals)
        signals.status_message.emit("ClickUp-Task erstellt", 4000)

    def _on_clickup_error(self, exc: Exception) -> None:
        logger.error("ClickUp task creation failed: %s", exc)
        self._clickup_status.setText(f"Fehler: {exc}")
        self._clickup_status.setStyleSheet(_ERR_STYLE)
        QMessageBox.warning(self, "ClickUp", str(exc))

    def _on_clickup_finished(self) -> None:
        self._clickup_create_btn.setEnabled(True)
