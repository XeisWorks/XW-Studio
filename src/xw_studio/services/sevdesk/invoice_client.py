"""sevDesk Invoice API client (read-focused)."""
from __future__ import annotations

import base64
import logging
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from xw_studio.services.http_client import SevdeskConnection

logger = logging.getLogger(__name__)


def _format_date_de(raw: str | None) -> str:
    """Parse ISO date string from sevDesk and return DD.MM.YYYY."""
    if not raw:
        return "—"
    try:
        dt = datetime.fromisoformat(raw)
        return dt.strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return raw


def _format_amount_de(raw: str | float | None) -> str:
    """Format a decimal amount in German style: 1.234,56 €."""
    if raw is None:
        return "—"
    try:
        val = float(raw)
        # German format: dot as thousands sep, comma as decimal sep
        formatted = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{formatted} €"
    except (ValueError, TypeError):
        return str(raw)

# Common sevDesk invoice status codes (subset; unknown -> label mapping default)
_INVOICE_STATUS_DE: dict[int, str] = {
    100: "Entwurf",
    200: "Offen",
    300: "Teilweise bezahlt",
    1000: "Bezahlt",
}

DEFAULT_SENSITIVE_COUNTRY_CODES: set[str] = {
    "AF",
    "BY",
    "IQ",
    "IR",
    "KP",
    "RU",
    "SY",
}


def _extract_country_code(value: object) -> str:
    if isinstance(value, str):
        return value.strip().upper()
    if isinstance(value, dict):
        for key in ("translationCode", "code", "countryCode", "isoCode", "value"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip().upper()
        nested = value.get("country")
        if nested is not None:
            nested_code = _extract_country_code(nested)
            if nested_code:
                return nested_code
    return ""


class InvoiceSummary(BaseModel):
    """Normalized row for UI tables."""

    model_config = ConfigDict(extra="ignore")

    id: str
    invoice_number: str = Field(default="", alias="invoiceNumber")
    invoice_date: str | None = Field(default=None, alias="invoiceDate")
    status_code: int | None = Field(default=None, alias="status")
    sum_gross: str | float | None = Field(default=None, alias="sumGross")
    contact_name: str = ""
    buyer_note: str = ""
    address_country_code: str = ""
    delivery_country_code: str = ""
    has_delivery_address_override: bool = False
    is_sensitive_country: bool = False
    has_unreleased_sku: bool = False
    order_reference: str = ""

    @field_validator("status_code", mode="before")
    @classmethod
    def _coerce_status(cls, value: object) -> int | None:
        if value is None or value == "":
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return None
        return None

    @field_validator(
        "id",
        "invoice_number",
        "contact_name",
        "buyer_note",
        "address_country_code",
        "delivery_country_code",
        "order_reference",
        mode="before",
    )
    @classmethod
    def _coerce_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value)

    @classmethod
    def from_api_object(cls, raw: dict[str, Any]) -> InvoiceSummary:
        contact = raw.get("contact")
        contact_name = ""
        if isinstance(contact, dict):
            org = str(contact.get("name") or "").strip()
            first = str(contact.get("surename") or "").strip()  # sevDesk: Vorname
            last = str(contact.get("familyname") or "").strip()
            person = f"{first} {last}".strip()
            if org and person:
                contact_name = f"{org} | {person}"
            elif org:
                contact_name = org
            else:
                contact_name = person
        cid = raw.get("id")

        country_code = ""
        for key in (
            "addressCountry",
            "addressCountryCode",
            "country",
            "countryCode",
            "invoiceAddressCountry",
        ):
            country_code = _extract_country_code(raw.get(key))
            if country_code:
                break

        if not country_code and isinstance(contact, dict):
            for key in ("addressCountry", "country", "countryCode"):
                country_code = _extract_country_code(contact.get(key))
                if country_code:
                    break
            if not country_code:
                address_obj = contact.get("address")
                if isinstance(address_obj, dict):
                    for key in ("country", "countryCode", "addressCountry"):
                        country_code = _extract_country_code(address_obj.get(key))
                        if country_code:
                            break

        delivery_country_code = ""
        for key in ("deliveryAddressCountry", "deliveryCountry", "shippingCountry"):
            delivery_country_code = _extract_country_code(raw.get(key))
            if delivery_country_code:
                break

        def _norm_text(value: object) -> str:
            return str(value or "").strip().lower()

        billing_signature = "|".join(
            _norm_text(raw.get(key))
            for key in ("street", "zip", "city", "address")
        )
        delivery_signature = "|".join(
            _norm_text(raw.get(key))
            for key in (
                "deliveryStreet",
                "deliveryZip",
                "deliveryCity",
                "deliveryAddress",
                "shippingStreet",
                "shippingZip",
                "shippingCity",
                "shippingAddress",
            )
        )
        has_delivery_override = bool(
            delivery_signature.strip("|") and delivery_signature != billing_signature
        )

        buyer_note = str(raw.get("buyerNote") or "").strip()

        # Wix order reference stored in customerInternalNote or related fields
        order_reference = ""
        for ref_key in ("reference", "customerInternalNote", "customerInternalNoteText",
                        "referenceNumber", "orderNumber"):
            val = str(raw.get(ref_key) or "").strip()
            if val:
                order_reference = val
                break

        payload = {
            **raw,
            "id": str(cid) if cid is not None else "",
            "contact_name": contact_name,
            "buyer_note": buyer_note,
            "address_country_code": country_code,
            "delivery_country_code": delivery_country_code,
            "has_delivery_address_override": has_delivery_override,
            "is_sensitive_country": country_code.upper() in DEFAULT_SENSITIVE_COUNTRY_CODES,
            "order_reference": order_reference,
        }
        return cls.model_validate(payload)

    @property
    def formatted_date(self) -> str:
        """Invoice date as DD.MM.YYYY."""
        return _format_date_de(self.invoice_date)

    @property
    def formatted_brutto(self) -> str:
        """Gross amount formatted in German locale (e.g. 1.234,56 €)."""
        return _format_amount_de(self.sum_gross)

    def status_label(self) -> str:
        if self.status_code is None:
            return "—"
        return _INVOICE_STATUS_DE.get(self.status_code, str(self.status_code))

    def status_display_label(self) -> str:
        """Return the UI label with Entwurf visually prioritized."""
        label = self.status_label()
        if self.status_code == 100:
            return f"✳ {label}"
        return label

    @property
    def display_country(self) -> str:
        return self.delivery_country_code or self.address_country_code

    def has_plc_label_candidate(self) -> bool:
        """Detect invoices that likely need PLC label handling."""
        hay = f"{self.order_reference} {self.buyer_note}".strip().lower()
        if not hay:
            return False
        return any(
            token in hay
            for token in (
                "plc",
                "post label center",
                "postlabelcenter",
                "shipping label",
                "versandlabel",
            )
        ) or bool(re.search(r"\bplc[-_ ]?\d+", hay))

    def indicator_icon_keys(self) -> list[str]:
        """Return icon keys used by the hints cell delegate."""
        keys: list[str] = []
        if self.has_unreleased_sku:
            keys.append("print")
        if self.buyer_note.strip():
            keys.append("printondemand")
        if self.has_delivery_address_override:
            keys.append("alternateshippingaddress")
        if self.is_sensitive_country:
            keys.append("country")
        return keys

    def indicator_symbols(self) -> str:
        """Compact marker string for the invoice list."""
        markers: list[str] = []
        if self.has_unreleased_sku:
            markers.append("🖨")
        if self.buyer_note.strip():
            markers.append("✎")
        if self.has_delivery_address_override:
            markers.append("⌂")
        if self.is_sensitive_country:
            markers.append("⚠")
        return " ".join(markers)

    def indicator_tooltip(self) -> str:
        """Detailed explanation for the compact marker cell."""
        lines: list[str] = []
        if self.has_unreleased_sku:
            lines.append("🖨 SKU-Flag aktiv (unreleased/print-relevant)")
        if self.buyer_note.strip():
            lines.append(f"✎ Käufernotiz: {self.buyer_note}")
        if self.has_delivery_address_override:
            lines.append("⌂ Abweichende Lieferanschrift vorhanden")
        if self.is_sensitive_country:
            lines.append(
                f"⚠ Heikles Zielland: {self.address_country_code or self.delivery_country_code or 'unbekannt'}"
            )
        return "\n".join(lines)

    def as_table_row(self) -> dict[str, str]:
        """Keys match German column headers used in :class:`DataTable`."""
        indicator_symbols = self.indicator_symbols()
        icon_keys = self.indicator_icon_keys()

        row: dict[str, str] = {
            "RE-NR": self.invoice_number or "—",
            "Datum": self.formatted_date,
            "Status": self.status_display_label(),
            "BETRAG": self.formatted_brutto,
            "Kunde": self.contact_name or "—",
            "Hinweise": indicator_symbols,
            "AKTIONEN": "",
            "ID": self.id,
        }

        row["__align__Hinweise"] = "center"
        row["__align__BETRAG"] = "right"
        row["__icons__Hinweise"] = icon_keys
        row["__plc__enabled"] = True
        row["__has_order_ref__"] = bool(self.order_reference.strip())
        if indicator_symbols:
            row["__tooltip__Hinweise"] = self.indicator_tooltip()
            row["__fg__Hinweise"] = "#ef4444"
        row["__tooltip__AKTIONEN"] = "PLC / Rückerstattung / Download-Links"
        if self.status_code == 100:
            row["__tooltip__Status"] = "Entwurf: diese Rechnung muss im Tagesgeschäft abgearbeitet werden"
            row["__fg__Status"] = "#9a3412"
            row["__bg__Status"] = "#fff7ed"

        return row

    def detail_lines(self) -> str:
        """Multi-line description for the detail panel."""
        lines = [
            f"ID: {self.id}",
            f"Nummer: {self.invoice_number or '—'}",
            f"Datum: {self.formatted_date}",
            f"Status: {self.status_label()} ({self.status_code if self.status_code is not None else '—'})",
            f"Brutto: {self.formatted_brutto}",
            f"Kunde: {self.contact_name or '—'}",
            f"Land: {self.display_country or '—'}",
        ]
        if self.has_delivery_address_override:
            lines.append("Lieferanschrift: abweichend")
        if self.delivery_country_code:
            lines.append(f"Lieferland: {self.delivery_country_code}")
        if self.is_sensitive_country:
            lines.append("Achtung: heikles Land")
        if self.buyer_note.strip():
            lines.append(f"Notiz: {self.buyer_note}")
        return "\n".join(lines)


class InvoiceClient:
    """List and fetch invoices from sevDesk."""

    def __init__(self, connection: SevdeskConnection) -> None:
        self._conn = connection

    def list_invoice_summaries(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        embed_contact: bool = True,
        status: int | None = None,
    ) -> list[InvoiceSummary]:
        """Return invoice rows (newest first by API default).

        If *status* is set, it is passed to the API as ``status`` (sevDesk may support
        filtering). If the API ignores it, filter client-side.
        """
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if embed_contact:
            params["embed"] = "contact"
        if status is not None:
            params["status"] = status

        response = self._conn.get("/Invoice", params=params)
        payload = response.json()
        objects = payload.get("objects")
        if not isinstance(objects, list):
            logger.warning("Unexpected Invoice list payload: %s", type(objects))
            return []

        result: list[InvoiceSummary] = []
        for obj in objects:
            if isinstance(obj, dict):
                summary = InvoiceSummary.from_api_object(obj)
                if status is not None and summary.status_code != status:
                    continue
                result.append(summary)

        # Keep UI chronology stable: newest sevDesk import first (ID descending).
        result.sort(
            key=lambda item: int(item.id) if item.id.isdigit() else -1,
            reverse=True,
        )

        if status is not None and not result and objects:
            logger.debug(
                "Status filter %s yielded no rows after parse; API may ignore query param.",
                status,
            )
        return result

    def fetch_invoice_by_id(self, invoice_id: str) -> dict[str, Any]:
        """Return one invoice object as returned by sevDesk."""
        response = self._conn.get(f"/Invoice/{str(invoice_id).strip()}")
        payload = response.json()
        if isinstance(payload, dict):
            objects = payload.get("objects")
            if isinstance(objects, list):
                for item in objects:
                    if isinstance(item, dict):
                        return item
            if isinstance(objects, dict):
                return objects
            return payload
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    return item
        return {}

    def send_invoice_document(
        self,
        invoice_id: str,
        *,
        send_type: str = "PRN",
        send_draft: bool = False,
    ) -> dict[str, Any]:
        """Trigger sevDesk ``sendBy`` for one invoice."""
        body = {
            "sendType": str(send_type).strip() or "PRN",
            "sendDraft": bool(send_draft),
        }
        response = self._conn.put(f"/Invoice/{str(invoice_id).strip()}/sendBy", json=body)
        return response.json() if response.content else {}

    def render_invoice_pdf(self, invoice_id: str) -> dict[str, Any]:
        """Ask sevDesk to render invoice PDF asynchronously."""
        response = self._conn.post(f"/Invoice/{str(invoice_id).strip()}/render", json={})
        return response.json() if response.content else {}

    def get_invoice_pdf(self, invoice_id: str) -> bytes:
        """Load rendered invoice PDF bytes from sevDesk."""
        response = self._conn.get(
            f"/Invoice/{str(invoice_id).strip()}/getPdf",
            params={"download": "true", "preventSendBy": "true"},
            headers={"Accept": "application/pdf,application/json"},
        )
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if response.content and response.content.startswith(b"%PDF"):
            return response.content

        payload: Any
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(
                f"sevDesk PDF: ungültige Antwort (content-type={content_type})"
            ) from exc

        decoded = self._extract_pdf_from_payload(payload)
        if decoded:
            return decoded
        raise ValueError("sevDesk PDF: kein PDF/base64 geliefert")

    def _extract_pdf_from_payload(self, payload: object) -> bytes | None:
        if not isinstance(payload, dict):
            return None
        for key in ("base64", "pdfBase64", "documentBase64"):
            raw = payload.get(key)
            if not raw:
                continue
            try:
                decoded = base64.b64decode(str(raw), validate=False)
            except Exception:
                continue
            if decoded.startswith(b"%PDF"):
                return decoded
        response_block = payload.get("response")
        if isinstance(response_block, dict):
            decoded = self._extract_pdf_from_payload(response_block)
            if decoded:
                return decoded
        objects = payload.get("objects")
        if isinstance(objects, list):
            for item in objects:
                decoded = self._extract_pdf_from_payload(item)
                if decoded:
                    return decoded
        return None
