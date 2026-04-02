"""XW-Copilot panel for Outlook add-in integration and text blocks."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xw_studio.services.xw_copilot.dry_run import XWCopilotDryRunService
from xw_studio.services.xw_copilot.ingress import XWCopilotIngress
from xw_studio.services.xw_copilot.service import XWCopilotConfig, XWCopilotService

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)


class XWCopilotView(QWidget):
    """Manage Outlook add-in settings and reusable copilot blocks."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._service: XWCopilotService = container.resolve(XWCopilotService)
        self._dry_run_service: XWCopilotDryRunService = container.resolve(XWCopilotDryRunService)
        self._ingress: XWCopilotIngress = container.resolve(XWCopilotIngress)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        tabs = QTabWidget()
        tabs.addTab(self._build_settings_tab(), "Einstellungen")
        tabs.addTab(self._build_templates_tab(), "Bausteine")
        tabs.addTab(self._build_dry_run_tab(), "Dry-Run")
        tabs.addTab(self._build_history_tab(), "Verlauf")
        tabs.addTab(self._build_notes_tab(), "Integration")
        root.addWidget(tabs)

        self._load_config_into_form()
        self._load_templates_into_editor()

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        group = QGroupBox("Outlook Add-in Konfiguration")
        form = QFormLayout(group)

        self._enabled = QCheckBox("XW-Copilot aktiv")
        form.addRow("Status:", self._enabled)

        self._mode = QComboBox()
        self._mode.addItems(["dry_run", "live"])
        form.addRow("Modus:", self._mode)

        self._tenant_id = QLineEdit()
        self._tenant_id.setPlaceholderText("Azure Tenant ID")
        form.addRow("Tenant ID:", self._tenant_id)

        self._client_id = QLineEdit()
        self._client_id.setPlaceholderText("App Client ID")
        form.addRow("Client ID:", self._client_id)

        self._mailbox = QLineEdit()
        self._mailbox.setPlaceholderText("z. B. info@xeisworks.at")
        form.addRow("Mailbox:", self._mailbox)

        self._webhook = QLineEdit()
        self._webhook.setPlaceholderText("Webhook URL (optional)")
        form.addRow("Webhook:", self._webhook)

        self._project = QLineEdit()
        self._project.setPlaceholderText("Standardprojekt / Board")
        form.addRow("Default Projekt:", self._project)

        self._settings_status = QLabel("—")
        form.addRow("Config Status:", self._settings_status)

        btn_row = QHBoxLayout()
        load_btn = QPushButton("Laden")
        load_btn.clicked.connect(self._load_config_into_form)
        btn_row.addWidget(load_btn)
        save_btn = QPushButton("Speichern")
        save_btn.clicked.connect(self._save_config_from_form)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        form.addRow("", btn_row)

        lay.addWidget(group)

        # Ingress controls
        ingress_group = QGroupBox("Lokaler HTTP-Ingress (optional)")
        ingress_form = QFormLayout(ingress_group)

        self._ingress_port = QSpinBox()
        self._ingress_port.setRange(1024, 65535)
        self._ingress_port.setValue(8765)
        ingress_form.addRow("Port:", self._ingress_port)

        self._ingress_secret = QLineEdit()
        self._ingress_secret.setPlaceholderText("HMAC-Secret (leer = keine Signaturpruefung)")
        self._ingress_secret.setEchoMode(QLineEdit.EchoMode.Password)
        ingress_form.addRow("HMAC-Secret:", self._ingress_secret)

        self._ingress_status = QLabel("Gestoppt")
        ingress_form.addRow("Status:", self._ingress_status)

        ingress_btn_row = QHBoxLayout()
        self._ingress_start_btn = QPushButton("Starten")
        self._ingress_start_btn.clicked.connect(self._start_ingress)
        ingress_btn_row.addWidget(self._ingress_start_btn)
        self._ingress_stop_btn = QPushButton("Stoppen")
        self._ingress_stop_btn.clicked.connect(self._stop_ingress)
        self._ingress_stop_btn.setEnabled(False)
        ingress_btn_row.addWidget(self._ingress_stop_btn)
        ingress_btn_row.addStretch()
        ingress_form.addRow("", ingress_btn_row)

        lay.addWidget(ingress_group)
        lay.addStretch()
        return page

    def _build_templates_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("Prompt-/Mail-Bausteine als JSON-Liste (name/kind/content)."))

        self._templates_editor = QPlainTextEdit()
        self._templates_editor.setPlaceholderText(
            '[{"name": "Antwort - Rechnung", "kind": "mail", "content": "Vielen Dank ..."}]'
        )
        lay.addWidget(self._templates_editor, stretch=1)

        row = QHBoxLayout()
        load_btn = QPushButton("Bausteine laden")
        load_btn.clicked.connect(self._load_templates_into_editor)
        row.addWidget(load_btn)
        save_btn = QPushButton("Bausteine speichern")
        save_btn.clicked.connect(self._save_templates_from_editor)
        row.addWidget(save_btn)
        row.addStretch()
        lay.addLayout(row)

        self._templates_status = QLabel("—")
        lay.addWidget(self._templates_status)
        return page

    def _build_notes_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(
            "XW-Copilot Integrationshinweise:\n\n"
            "1) Outlook Add-in spricht per Webhook/API mit XW-Studio.\n"
            "2) Modus dry_run: nur Vorschau/Logging, keine Live-Aktionen.\n"
            "3) Modus live: Aktionen gegen produktive Endpunkte aktiv.\n"
            "4) Bausteine werden zentral in DB gehalten (mehrere PCs).\n"
            "5) Tokens weiterhin ueber Settings/SecretService pflegen."
        )
        lay.addWidget(txt)
        return page

    def _build_dry_run_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        lay.addWidget(
            QLabel(
                "Dry-Run Contract Test: Request JSON einfuegen, validieren und Vorschauantwort erzeugen."
            )
        )

        self._dry_run_request = QPlainTextEdit()
        self._dry_run_request.setPlaceholderText("Request JSON")
        self._dry_run_request.setPlainText(
            json.dumps(
                {
                    "tenant": "xeisworks",
                    "mailbox": "info@xeisworks.at",
                    "action": "crm.lookup_contact",
                    "payload_version": "1.0",
                    "payload": {"query": "Musterkunde"},
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        lay.addWidget(self._dry_run_request, stretch=1)

        row = QHBoxLayout()
        execute_btn = QPushButton("Dry-Run ausfuehren")
        execute_btn.clicked.connect(self._execute_dry_run)
        row.addWidget(execute_btn)
        reset_btn = QPushButton("Beispiel laden")
        reset_btn.clicked.connect(self._reset_dry_run_sample)
        row.addWidget(reset_btn)
        row.addStretch()
        lay.addLayout(row)

        self._dry_run_status = QLabel("—")
        lay.addWidget(self._dry_run_status)

        self._dry_run_response = QPlainTextEdit()
        self._dry_run_response.setReadOnly(True)
        self._dry_run_response.setPlaceholderText("Response JSON")
        lay.addWidget(self._dry_run_response, stretch=1)

        return page

    def _load_config_into_form(self) -> None:
        cfg = self._service.load_config()
        self._enabled.setChecked(cfg.enabled)
        mode_idx = self._mode.findText(cfg.mode)
        self._mode.setCurrentIndex(mode_idx if mode_idx >= 0 else 0)
        self._tenant_id.setText(cfg.outlook_tenant_id)
        self._client_id.setText(cfg.outlook_client_id)
        self._mailbox.setText(cfg.mailbox_address)
        self._webhook.setText(cfg.webhook_url)
        self._project.setText(cfg.default_project)
        self._settings_status.setText("Konfiguration geladen")

    def _save_config_from_form(self) -> None:
        if not self._service.has_storage():
            QMessageBox.warning(self, "XW-Copilot", "Kein DB-Storage verfuegbar (DATABASE_URL fehlt).")
            return
        cfg = XWCopilotConfig(
            enabled=self._enabled.isChecked(),
            mode=self._mode.currentText(),
            outlook_tenant_id=self._tenant_id.text().strip(),
            outlook_client_id=self._client_id.text().strip(),
            mailbox_address=self._mailbox.text().strip(),
            webhook_url=self._webhook.text().strip(),
            default_project=self._project.text().strip(),
        )
        self._service.save_config(cfg)
        self._settings_status.setText("Konfiguration gespeichert")
        QMessageBox.information(self, "XW-Copilot", "Einstellungen gespeichert.")

    def _load_templates_into_editor(self) -> None:
        rows = self._service.load_templates()
        self._templates_editor.setPlainText(json.dumps(rows, ensure_ascii=False, indent=2))
        self._templates_status.setText(f"{len(rows)} Bausteine geladen")

    def _save_templates_from_editor(self) -> None:
        if not self._service.has_storage():
            QMessageBox.warning(self, "XW-Copilot", "Kein DB-Storage verfuegbar (DATABASE_URL fehlt).")
            return
        raw = self._templates_editor.toPlainText().strip() or "[]"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            QMessageBox.warning(self, "XW-Copilot", f"Ungueltiges JSON: {exc}")
            return
        if not isinstance(data, list):
            QMessageBox.warning(self, "XW-Copilot", "Erwartet wird ein JSON-Array aus Objekten.")
            return
        self._service.save_templates([row for row in data if isinstance(row, dict)])
        self._templates_status.setText(f"{len(data)} Bausteine gespeichert")
        QMessageBox.information(self, "XW-Copilot", "Bausteine gespeichert.")

    def _execute_dry_run(self) -> None:
        raw = self._dry_run_request.toPlainText().strip()
        if not raw:
            QMessageBox.warning(self, "XW-Copilot", "Bitte ein Request JSON eingeben.")
            return
        result = self._dry_run_service.simulate_raw_request(raw)
        self._dry_run_response.setPlainText(
            json.dumps(result.model_dump(), ensure_ascii=False, indent=2)
        )
        if result.accepted:
            self._dry_run_status.setText(
                f"OK: action={result.action}, mode={result.mode}, correlation_id={result.correlation_id}"
            )
            return
        self._dry_run_status.setText(
            f"Fehler: action={result.action}, correlation_id={result.correlation_id}"
        )

    def _reset_dry_run_sample(self) -> None:
        self._dry_run_request.setPlainText(
            json.dumps(
                {
                    "tenant": "xeisworks",
                    "mailbox": "info@xeisworks.at",
                    "action": "crm.lookup_contact",
                    "payload_version": "1.0",
                    "payload": {"query": "Musterkunde"},
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        self._dry_run_status.setText("Beispiel-Request geladen")

    # ------------------------------------------------------------------
    # Verlauf tab
    # ------------------------------------------------------------------

    def _build_history_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        cols = ["Zeit", "Action", "Modus", "OK?", "Correlation-ID"]
        self._history_table = QTableWidget(0, len(cols))
        self._history_table.setHorizontalHeaderLabels(cols)
        self._history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._history_table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self._history_table, stretch=1)

        row = QHBoxLayout()
        reload_btn = QPushButton("Verlauf laden")
        reload_btn.clicked.connect(self._reload_history)
        row.addWidget(reload_btn)
        clear_btn = QPushButton("Verlauf loeschen")
        clear_btn.clicked.connect(self._clear_history)
        row.addWidget(clear_btn)
        row.addStretch()
        lay.addLayout(row)

        self._history_status = QLabel("—")
        lay.addWidget(self._history_status)
        return page

    def _reload_history(self) -> None:
        entries = self._service.load_audit_entries()
        self._history_table.setRowCount(0)
        for e in entries:
            r = self._history_table.rowCount()
            self._history_table.insertRow(r)
            self._history_table.setItem(r, 0, QTableWidgetItem(e.timestamp))
            self._history_table.setItem(r, 1, QTableWidgetItem(e.action))
            self._history_table.setItem(r, 2, QTableWidgetItem(e.mode))
            self._history_table.setItem(r, 3, QTableWidgetItem("Ja" if e.accepted else "Nein"))
            self._history_table.setItem(r, 4, QTableWidgetItem(e.correlation_id))
        self._history_status.setText(f"{len(entries)} Eintraege geladen")

    def _clear_history(self) -> None:
        if not self._service.has_storage():
            QMessageBox.warning(self, "XW-Copilot", "Kein DB-Storage verfuegbar.")
            return
        self._service.clear_audit_log()
        self._history_table.setRowCount(0)
        self._history_status.setText("Verlauf geloescht")

    # ------------------------------------------------------------------
    # Ingress controls
    # ------------------------------------------------------------------

    def _start_ingress(self) -> None:
        port = self._ingress_port.value()
        secret = self._ingress_secret.text().strip()
        self._ingress.update_secret(secret)
        try:
            self._ingress.start(port=port)
        except OSError as exc:
            QMessageBox.warning(self, "Ingress", f"Port {port} nicht verfuegbar: {exc}")
            return
        self._ingress_status.setText(f"Laeuft auf 127.0.0.1:{port}")
        self._ingress_start_btn.setEnabled(False)
        self._ingress_stop_btn.setEnabled(True)

    def _stop_ingress(self) -> None:
        self._ingress.stop()
        self._ingress_status.setText("Gestoppt")
        self._ingress_start_btn.setEnabled(True)
        self._ingress_stop_btn.setEnabled(False)
