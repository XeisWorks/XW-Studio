"""PLC label export dialog (ported from legacy Tkinter flow)."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QLineEdit,
)

from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.plc.polling import (
    DEFAULT_PLC_IMPORT_DIR,
    DEFAULT_TEST_PLC_IMPORT_DIR,
    PlcConfig,
    ShipmentAddress,
    build_postdefaultport_lines,
    normalize_shipment_address,
    write_import_file,
)
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary
from xw_studio.services.wix.client import WixOrderItem, WixOrdersClient

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)

_EU_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
    "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
}
_EU_PRODUCT_ID = "45"
_DEFAULT_ITEM_WEIGHT_KG = 0.30


@dataclass
class _PlcDialogContext:
    order_number: str
    address_lines: list[str]
    weight_kg: float
    items: list[WixOrderItem]


class PlcLabelPrintDialog(QDialog):
    _mail_ref_counters: dict[str, int] = {}

    def __init__(
        self,
        container: Container,
        summary: InvoiceSummary,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._summary = summary
        self._load_worker: BackgroundWorker | None = None
        self._context = _PlcDialogContext(order_number="", address_lines=[], weight_kg=0.0, items=[])
        self._product_catalog = self._load_products()
        self._product_user_set = False
        self._address_edited = False
        self._weight_user_set = False

        self.setWindowTitle("PLC Label Print")
        self.setMinimumWidth(700)
        self._build_ui()
        self._load_context()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        mode_row = QHBoxLayout()
        self._mode_live = QRadioButton("LIVE")
        self._mode_test = QRadioButton("TEST")
        self._mode_live.setChecked(True)
        mode_row.addWidget(self._mode_live)
        mode_row.addWidget(self._mode_test)
        mode_row.addStretch()
        mode_wrap = QWidget()
        mode_wrap.setLayout(mode_row)
        form.addRow("Modus:", mode_wrap)

        self._product_combo = QComboBox()
        self._product_combo.currentTextChanged.connect(self._on_product_selected)
        form.addRow("Versandprodukt:", self._product_combo)

        self._weight_edit = QLineEdit()
        self._weight_edit.setPlaceholderText("z.B. 0,45")
        self._weight_edit.textChanged.connect(self._on_weight_edit)
        form.addRow("Gewicht (kg):", self._weight_edit)

        self._customs_edit = QPlainTextEdit()
        self._customs_edit.setPlaceholderText("Zollbeschreibung")
        self._customs_edit.setFixedHeight(72)
        form.addRow("Zollbeschreibung:", self._customs_edit)

        self._address_edit = QPlainTextEdit()
        self._address_edit.setPlaceholderText("Adresszeilen")
        self._address_edit.setFixedHeight(140)
        self._address_edit.textChanged.connect(self._on_address_edit)
        form.addRow("Lieferadresse:", self._address_edit)

        self._status = QLabel("Lade Analyse...")
        self._status.setStyleSheet("color: #64748b;")
        form.addRow("Status:", self._status)

        root.addLayout(form)

        buttons = QDialogButtonBox(self)
        self._send_btn = buttons.addButton("Senden an PLC", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Abbrechen", QDialogButtonBox.ButtonRole.RejectRole)
        self._send_btn.clicked.connect(self._send_to_plc)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _load_context(self) -> None:
        def job() -> _PlcDialogContext:
            order_number = self._summary.wix_order_number()
            address_lines: list[str] = []
            items: list[WixOrderItem] = []
            weight = 0.0
            ref = self._summary.order_reference.strip()
            if ref:
                wix: WixOrdersClient = self._container.resolve(WixOrdersClient)
                if wix.has_credentials():
                    meta = wix.resolve_order_summary(ref)
                    order_number = str(meta.get("wix_order_number") or order_number or "").strip()
                    shipping = str(meta.get("wix_shipping_address") or "").strip()
                    if shipping:
                        address_lines = [ln.strip() for ln in shipping.splitlines() if ln.strip()]
                    if not address_lines:
                        address_lines = wix.resolve_order_address_lines(ref)
                    items = wix.fetch_order_line_items(ref)
                    weight = sum(max(1, int(item.qty or 1)) * _DEFAULT_ITEM_WEIGHT_KG for item in items)
            return _PlcDialogContext(order_number=order_number, address_lines=address_lines, weight_kg=weight, items=items)

        self._load_worker = BackgroundWorker(job)
        self._load_worker.signals.result.connect(self._on_context_loaded)
        self._load_worker.signals.error.connect(self._on_context_error)
        self._load_worker.start()

    def _on_context_loaded(self, result: object) -> None:
        if not isinstance(result, _PlcDialogContext):
            self._status.setText("Analyse unvollständig geladen")
            return
        self._context = result
        if result.address_lines and not self._address_edited:
            self._address_edit.setPlainText("\n".join(result.address_lines))
        if result.weight_kg > 0 and not self._weight_user_set:
            self._weight_edit.setText(f"{result.weight_kg:.2f}".replace(".", ","))
        self._sync_product_options()
        self._update_customs_visibility()
        self._status.setText("Bereit")

    def _on_context_error(self, exc: Exception) -> None:
        logger.warning("PLC context load failed: %s", exc)
        self._sync_product_options()
        self._update_customs_visibility()
        self._status.setText(f"Analyse konnte nicht vollständig geladen werden: {exc}")

    def _on_product_selected(self, _value: str) -> None:
        self._product_user_set = True
        self._update_customs_visibility()

    def _on_address_edit(self) -> None:
        self._address_edited = True
        if not self._product_user_set:
            self._sync_product_options()
        self._update_customs_visibility()

    def _on_weight_edit(self, _value: str) -> None:
        self._weight_user_set = True

    def _current_mode(self) -> str:
        return "LIVE" if self._mode_live.isChecked() else "TEST"

    def _build_reference(self) -> str:
        if self._context.order_number:
            return self._context.order_number[:40]
        slug = re.sub(r"[^A-Za-z0-9]+", "", (self._summary.contact_name or ""))[:12]
        day = time.strftime("%Y%m%d")
        count = self._mail_ref_counters.get(day, 0) + 1
        self._mail_ref_counters[day] = count
        value = f"MAIL-{day}-{count:03d}-{slug}" if slug else f"MAIL-{day}-{count:03d}"
        return value[:40]

    def _current_address_lines(self) -> list[str]:
        return [ln.strip() for ln in self._address_edit.toPlainText().splitlines() if ln.strip()]

    def _parse_address(self, lines: list[str]) -> ShipmentAddress:
        country = lines[-1].strip().upper() if lines else ""
        zip_city = lines[-2] if len(lines) >= 2 else ""
        m = re.match(r"^([0-9]{3,6})\s+(.+)$", zip_city.strip())
        zip_code = m.group(1) if m else ""
        city = m.group(2) if m else zip_city.strip()
        street_line = lines[-3] if len(lines) >= 3 else ""
        house_no = ""
        street = street_line
        m2 = re.match(r"^(.*?)(\d+[A-Za-z0-9\-/]*)$", street_line.strip())
        if m2:
            street = m2.group(1).strip().rstrip(",")
            house_no = m2.group(2).strip()
        name_lines = lines[:-3] if len(lines) > 3 else lines[:1]
        name1 = name_lines[0] if name_lines else (self._summary.contact_name or "")
        name2 = name_lines[1] if len(name_lines) > 1 else ""
        return normalize_shipment_address(
            ShipmentAddress(
                name1=name1,
                name2=name2,
                street=street,
                house_no=house_no,
                zip=zip_code,
                city=city,
                country_iso2=country,
            )
        )

    def _country_group(self, iso2: str) -> str:
        code = str(iso2 or "").upper().strip()
        if code == "AT":
            return "AT"
        if code and code in _EU_COUNTRIES:
            return "EU"
        return "NON_EU"

    def _current_country(self) -> str:
        lines = self._current_address_lines()
        return lines[-1].strip().upper() if lines else ""

    def _sync_product_options(self) -> None:
        group = self._country_group(self._current_country())
        options = [item for item in self._product_catalog if group in item.get("regions", set())]
        labels = [str(item["label"]) for item in options]
        self._product_combo.blockSignals(True)
        self._product_combo.clear()
        self._product_combo.addItems(labels)
        self._product_combo.blockSignals(False)
        if labels:
            self._product_combo.setCurrentIndex(0)

    def _update_customs_visibility(self) -> None:
        needs_customs = self._country_group(self._current_country()) == "NON_EU"
        self._customs_edit.setVisible(needs_customs)

    def _find_product(self) -> dict:
        label = self._product_combo.currentText().strip()
        for item in self._product_catalog:
            if str(item.get("label") or "").strip() == label:
                return item
        return {}

    def _build_customs_articles(self) -> list[dict]:
        out: list[dict] = []
        for item in self._context.items:
            qty = max(1, int(item.qty or 1))
            out.append(
                {
                    "sku": item.sku,
                    "content": item.name,
                    "origin": "AT",
                    "hs_code": "49019900",
                    "customs_type": "GOODS",
                    "description": item.name,
                    "quantity": qty,
                    "unit": "pcs",
                    "net_weight_kg": round(qty * _DEFAULT_ITEM_WEIGHT_KG, 3),
                    "customs_value": "",
                    "currency": "EUR",
                }
            )
        return out

    def _send_to_plc(self) -> None:
        lines = self._current_address_lines()
        if not lines:
            QMessageBox.warning(self, "PLC", "Bitte Lieferadresse eingeben.")
            return

        address = self._parse_address(lines)
        if not address.name1 or not address.city:
            QMessageBox.warning(self, "PLC", "Adresse ist unvollständig.")
            return

        product = self._find_product()
        product_id = str(product.get("product_id") or "").strip()
        pakettyp = str(product.get("pakettyp") or "PC").strip() or "PC"
        if self._country_group(address.country_iso2) == "EU" and product_id != _EU_PRODUCT_ID:
            product_id = _EU_PRODUCT_ID
        if not product_id:
            QMessageBox.warning(self, "PLC", "Versandprodukt ist nicht konfiguriert.")
            return

        weight_raw = self._weight_edit.text().strip().replace(",", ".")
        if not weight_raw:
            QMessageBox.warning(self, "PLC", "Bitte Gewicht angeben.")
            return
        try:
            float(weight_raw)
        except ValueError:
            QMessageBox.warning(self, "PLC", "Gewicht ist ungueltig.")
            return

        mode = self._current_mode()
        import_dir = str(os.getenv("PLC_IMPORT_DIR" if mode == "LIVE" else "TEST_PLC_IMPORT_DIR") or "").strip()
        if not import_dir:
            import_dir = DEFAULT_PLC_IMPORT_DIR if mode == "LIVE" else DEFAULT_TEST_PLC_IMPORT_DIR

        ref = self._build_reference()
        parcels = [{"pakettyp": pakettyp, "gewicht": weight_raw, "referenz": ref}]
        metadata = {
            "shipment_id": ref,
            "ref1": ref,
            "ref2": (self._summary.invoice_number or self._summary.id),
            "customs_description": self._customs_edit.toPlainText().strip(),
            "returnsend": "0",
        }

        articles: list[dict] = []
        if self._country_group(address.country_iso2) == "NON_EU":
            articles = self._build_customs_articles()
            if not articles:
                QMessageBox.warning(self, "PLC", "Für Nicht-EU werden Wix-Positionen benötigt.")
                return

        config = PlcConfig(mode=mode, import_dir=import_dir)
        try:
            payload_lines = build_postdefaultport_lines(
                config,
                product_id=product_id,
                address=address,
                parcels=parcels,
                metadata=metadata,
                articles=articles,
            )
            path = write_import_file(payload_lines, import_dir, f"plc_{ref}")
        except Exception as exc:
            QMessageBox.critical(self, "PLC Fehler", str(exc))
            return

        self._status.setText(f"Gesendet: {path}")
        QMessageBox.information(self, "PLC", "Sendung erfolgreich an PLC übergeben.")
        self.accept()

    @staticmethod
    def _load_products() -> list[dict]:
        defaults = {
            "Paket Oesterreich": {"product_id": os.getenv("PLC_PRODUCT_ID_PAKET_OESTERREICH", "10")},
            "Premium Int. Outbound B2B": {"product_id": os.getenv("PLC_PRODUCT_ID_PREMIUM_INT_OUTBOUND_B2B", "45")},
            "Paket Plus Int. Outbound": {"product_id": os.getenv("PLC_PRODUCT_ID_PAKET_PLUS_INT_OUTBOUND", "70")},
        }
        raw = os.getenv("PLC_PRODUCTS_JSON")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    for item in parsed:
                        if not isinstance(item, dict):
                            continue
                        label = str(item.get("label") or "").strip()
                        pid = str(item.get("product_id") or "").strip()
                        pakettyp = str(item.get("pakettyp") or "").strip() or "PC"
                        if label in defaults and pid:
                            defaults[label]["product_id"] = pid
                            defaults[label]["pakettyp"] = pakettyp
            except Exception:
                pass
        return [
            {
                "label": "Paket Oesterreich",
                "product_id": defaults["Paket Oesterreich"]["product_id"],
                "pakettyp": defaults["Paket Oesterreich"].get("pakettyp", "PC"),
                "regions": {"AT"},
            },
            {
                "label": "Premium Int. Outbound B2B",
                "product_id": defaults["Premium Int. Outbound B2B"]["product_id"],
                "pakettyp": defaults["Premium Int. Outbound B2B"].get("pakettyp", "PC"),
                "regions": {"EU"},
            },
            {
                "label": "Paket Plus Int. Outbound",
                "product_id": defaults["Paket Plus Int. Outbound"]["product_id"],
                "pakettyp": defaults["Paket Plus Int. Outbound"].get("pakettyp", "PC"),
                "regions": {"EU", "NON_EU"},
            },
        ]
