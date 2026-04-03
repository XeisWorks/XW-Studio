"""sevDesk Invoice API client (read-focused)."""
from __future__ import annotations

import logging
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

        country = raw.get("addressCountry")
        country_code = ""
        if isinstance(country, dict):
            country_code = str(
                country.get("translationCode") or country.get("code") or ""
            ).strip()

        delivery_country_code = ""
        for key in ("deliveryAddressCountry", "deliveryCountry", "shippingCountry"):
            candidate = raw.get(key)
            if isinstance(candidate, dict):
                delivery_country_code = str(
                    candidate.get("translationCode") or candidate.get("code") or ""
                ).strip()
            elif isinstance(candidate, str):
                delivery_country_code = candidate.strip()
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

    def as_table_row(self) -> dict[str, str]:
        """Keys match German column headers used in :class:`DataTable`."""
        note_marker = "🔴" if self.buyer_note.strip() else ""
        delivery_marker = "🔴" if self.has_delivery_address_override else ""
        country_marker = "🔴" if self.is_sensitive_country else ""

        row: dict[str, str] = {
            "Rechnungsnr.": self.invoice_number or "—",
            "Datum": self.formatted_date,
            "Status": self.status_label(),
            "Brutto": self.formatted_brutto,
            "Kunde": self.contact_name or "—",
            "Land": self.address_country_code or "—",
            "Notiz": note_marker,
            "Lieferabw.": delivery_marker,
            "Heikles Land": country_marker,
            "ID": self.id,
        }

        if self.buyer_note.strip():
            row["__tooltip__Notiz"] = self.buyer_note
            row["__fg__Notiz"] = "#ef4444"
        if self.has_delivery_address_override:
            row["__tooltip__Lieferabw."] = "Abweichende Lieferanschrift vorhanden"
            row["__fg__Lieferabw."] = "#ef4444"
        if self.is_sensitive_country:
            row["__tooltip__Heikles Land"] = (
                f"Heikles Zielland: {self.address_country_code or 'unbekannt'}"
            )
            row["__fg__Heikles Land"] = "#ef4444"

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
            f"Land: {self.address_country_code or '—'}",
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

        if status is not None and not result and objects:
            logger.debug(
                "Status filter %s yielded no rows after parse; API may ignore query param.",
                status,
            )
        return result
