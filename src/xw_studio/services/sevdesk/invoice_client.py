"""sevDesk Invoice API client (read-focused)."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from xw_studio.services.http_client import raise_for_sevdesk

logger = logging.getLogger(__name__)

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
            contact_name = str(
                contact.get("name")
                or contact.get("surename")
                or contact.get("familyname")
                or ""
            ).strip()
        cid = raw.get("id")
        payload = {**raw, "id": str(cid) if cid is not None else "", "contact_name": contact_name}
        return cls.model_validate(payload)

    def status_label(self) -> str:
        if self.status_code is None:
            return "—"
        return _INVOICE_STATUS_DE.get(self.status_code, str(self.status_code))

    def as_table_row(self) -> dict[str, str]:
        """Keys match German column headers used in :class:`DataTable`."""
        return {
            "Rechnungsnr.": self.invoice_number or "—",
            "Datum": self.invoice_date or "—",
            "Status": self.status_label(),
            "Brutto EUR": "—" if self.sum_gross is None else str(self.sum_gross),
            "Kunde": self.contact_name or "—",
            "ID": self.id,
        }


class InvoiceClient:
    """List and fetch invoices from sevDesk."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def list_invoice_summaries(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        embed_contact: bool = True,
    ) -> list[InvoiceSummary]:
        """Return invoice rows (newest first by API default)."""
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if embed_contact:
            params["embed"] = "contact"
        response = self._client.get("/Invoice", params=params)
        raise_for_sevdesk(response)
        payload = response.json()
        objects = payload.get("objects")
        if not isinstance(objects, list):
            logger.warning("Unexpected Invoice list payload: %s", type(objects))
            return []
        result: list[InvoiceSummary] = []
        for obj in objects:
            if isinstance(obj, dict):
                result.append(InvoiceSummary.from_api_object(obj))
        return result
