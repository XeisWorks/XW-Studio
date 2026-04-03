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
        return {
            "Rechnungsnr.": self.invoice_number or "—",
            "Datum": self.formatted_date,
            "Status": self.status_label(),
            "Brutto": self.formatted_brutto,
            "Kunde": self.contact_name or "—",
            "Land": self.address_country_code or "—",
            "Notiz": "\u270e" if self.buyer_note.strip() else "",
            "ID": self.id,
        }

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
