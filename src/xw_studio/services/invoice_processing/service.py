"""Orchestrates invoice-related operations (no UI)."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from xw_studio.repositories.settings_kv import SettingKvRepository
from xw_studio.services.sevdesk.invoice_client import InvoiceClient, InvoiceSummary
from xw_studio.services.sevdesk.invoice_client import DEFAULT_SENSITIVE_COUNTRY_CODES

logger = logging.getLogger(__name__)

_SENSITIVE_COUNTRIES_KEY = "rechnungen.sensitive_country_codes"
_SKU_FLAGS_KEY = "rechnungen.sku_flags"
_FULFILLMENT_STATUS_KEY = "rechnungen.fulfillment_status"

_DEFAULT_SKU_FLAGS = {
    "exact": ["XW-010", "XW-011", "XW-600.0"],
    "prefixes": ["XW-4", "XW-6", "XW-7", "XW-12"],
}
_SKU_TOKEN_RE = re.compile(r"\bXW-[A-Z0-9][A-Z0-9.-]*\b", re.IGNORECASE)


@dataclass(frozen=True)
class FulfillmentFlags:
    """Persisted fulfillment state shown in the invoice table chips."""

    label_printed: bool = False
    invoice_printed: bool = False
    product_ready: bool = False
    mail_sent: bool = False
    wix_fulfilled: bool = False
    payment_applicable: bool = False
    payment_booked: bool = False
    last_run_iso: str = ""
    last_error: str = ""

    def as_row_payload(self) -> dict[str, object]:
        return {
            "label_printed": self.label_printed,
            "invoice_printed": self.invoice_printed,
            "product_ready": self.product_ready,
            "mail_sent": self.mail_sent,
            "wix_fulfilled": self.wix_fulfilled,
            "payment_applicable": self.payment_applicable,
            "payment_booked": self.payment_booked,
            "last_run_iso": self.last_run_iso,
            "last_error": self.last_error,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "FulfillmentFlags":
        if not isinstance(payload, dict):
            return cls()
        return cls(
            label_printed=bool(payload.get("label_printed")),
            invoice_printed=bool(payload.get("invoice_printed")),
            product_ready=bool(payload.get("product_ready")),
            mail_sent=bool(payload.get("mail_sent")),
            wix_fulfilled=bool(payload.get("wix_fulfilled")),
            payment_applicable=bool(payload.get("payment_applicable")),
            payment_booked=bool(payload.get("payment_booked")),
            last_run_iso=str(payload.get("last_run_iso") or ""),
            last_error=str(payload.get("last_error") or ""),
        )


class InvoiceProcessingService:
    """Facade over sevDesk invoice clients for the Rechnungen module."""

    def __init__(
        self,
        invoice_client: InvoiceClient,
        settings_repo: SettingKvRepository | None = None,
    ) -> None:
        self._invoices = invoice_client
        self._settings_repo = settings_repo

    def load_invoice_table_rows(
        self,
        *,
        status: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, str]]:
        """Load invoices and return rows for :class:`DataTable` (German keys)."""
        summaries = self._invoices.list_invoice_summaries(
            limit=limit,
            offset=offset,
            status=status,
        )
        self._apply_sensitive_country_flags(summaries)
        self._apply_unreleased_sku_flags(summaries)
        logger.info(
            "Loaded %s invoices from sevDesk (status=%s offset=%s limit=%s)",
            len(summaries),
            status,
            offset,
            limit,
        )
        return self._rows_with_fulfillment(summaries)

    def load_invoice_summaries(
        self,
        *,
        status: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InvoiceSummary]:
        """Return typed summaries (e.g. for detail panel / export)."""
        summaries = self._invoices.list_invoice_summaries(
            limit=limit,
            offset=offset,
            status=status,
        )
        self._apply_sensitive_country_flags(summaries)
        self._apply_unreleased_sku_flags(summaries)
        return summaries

    def load_invoice_batch(
        self,
        *,
        status: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, str]], list[InvoiceSummary]]:
        """Return table rows and parallel summaries for detail view."""
        summaries = self._invoices.list_invoice_summaries(
            limit=limit,
            offset=offset,
            status=status,
        )
        self._apply_sensitive_country_flags(summaries)
        self._apply_unreleased_sku_flags(summaries)
        rows = [s.as_table_row() for s in summaries]
        return self._rows_with_fulfillment(summaries, rows), summaries

    def read_fulfillment_flags(self, invoice_id: str) -> FulfillmentFlags:
        all_flags = self._load_fulfillment_flags_map()
        return all_flags.get(str(invoice_id), FulfillmentFlags())

    def write_fulfillment_flags(self, invoice_id: str, flags: FulfillmentFlags) -> None:
        if self._settings_repo is None:
            return
        all_flags = self._load_fulfillment_flags_map()
        all_flags[str(invoice_id)] = flags
        payload = {
            key: value.as_row_payload()
            for key, value in all_flags.items()
        }
        self._settings_repo.set_value_json(
            _FULFILLMENT_STATUS_KEY,
            json.dumps(payload, ensure_ascii=False),
        )

    def write_fulfillment_flags_batch(self, updates: dict[str, FulfillmentFlags]) -> None:
        if self._settings_repo is None or not updates:
            return
        all_flags = self._load_fulfillment_flags_map()
        for invoice_id, flags in updates.items():
            all_flags[str(invoice_id)] = flags
        payload = {
            key: value.as_row_payload()
            for key, value in all_flags.items()
        }
        self._settings_repo.set_value_json(
            _FULFILLMENT_STATUS_KEY,
            json.dumps(payload, ensure_ascii=False),
        )

    def _load_fulfillment_flags_map(self) -> dict[str, FulfillmentFlags]:
        if self._settings_repo is None:
            return {}
        raw = self._settings_repo.get_value_json(_FULFILLMENT_STATUS_KEY)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, FulfillmentFlags] = {}
        for key, payload in data.items():
            if not isinstance(key, str) or not key.strip():
                continue
            out[key] = FulfillmentFlags.from_payload(payload)
        return out

    def _rows_with_fulfillment(
        self,
        summaries: list[InvoiceSummary],
        rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        row_list = rows if rows is not None else [s.as_table_row() for s in summaries]
        states = self._load_fulfillment_flags_map()
        for summary, row in zip(summaries, row_list):
            flags = states.get(summary.id)
            if flags is None:
                flags = FulfillmentFlags(
                    product_ready=bool(summary.order_reference.strip()),
                    payment_applicable=bool(summary.order_reference.strip()),
                )
            row["FULFILLMENT"] = ""
            row["__fulfillment__"] = flags.as_row_payload()
            row["__tooltip__FULFILLMENT"] = "Label | Rechnung | Produkt | Mail | Wix | Zahlung"
            row["__align__FULFILLMENT"] = "center"
        return row_list

    def count_invoices(self, *, status: int | None = None, batch_size: int = 200) -> int:
        """Count invoices by paging through API results to avoid hard caps in UI badges."""
        safe_batch = max(10, int(batch_size))
        offset = 0
        total = 0
        while True:
            rows = self._invoices.list_invoice_summaries(
                limit=safe_batch,
                offset=offset,
                status=status,
            )
            count = len(rows)
            total += count
            if count < safe_batch:
                break
            offset += safe_batch
        return total

    def _load_sensitive_country_codes(self) -> set[str]:
        if self._settings_repo is None:
            return set(DEFAULT_SENSITIVE_COUNTRY_CODES)
        raw = self._settings_repo.get_value_json(_SENSITIVE_COUNTRIES_KEY)
        if not raw:
            return set(DEFAULT_SENSITIVE_COUNTRY_CODES)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return set(DEFAULT_SENSITIVE_COUNTRY_CODES)
        if not isinstance(data, list):
            return set(DEFAULT_SENSITIVE_COUNTRY_CODES)
        parsed = {
            str(item).strip().upper()
            for item in data
            if str(item).strip()
        }
        return parsed or set(DEFAULT_SENSITIVE_COUNTRY_CODES)

    def _apply_sensitive_country_flags(self, summaries: list[InvoiceSummary]) -> None:
        sensitive_codes = self._load_sensitive_country_codes()
        for summary in summaries:
            code = summary.address_country_code.strip().upper()
            delivery_code = summary.delivery_country_code.strip().upper()
            summary.is_sensitive_country = code in sensitive_codes or delivery_code in sensitive_codes

    def _load_sku_flags(self) -> tuple[set[str], tuple[str, ...]]:
        if self._settings_repo is None:
            return self._default_sku_flags()
        raw = self._settings_repo.get_value_json(_SKU_FLAGS_KEY)
        if not raw:
            return self._default_sku_flags()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return self._default_sku_flags()
        if not isinstance(data, dict):
            return self._default_sku_flags()

        exact_raw = data.get("exact")
        prefixes_raw = data.get("prefixes")
        if not isinstance(exact_raw, list) or not isinstance(prefixes_raw, list):
            return self._default_sku_flags()

        exact = {str(item).strip().upper() for item in exact_raw if str(item).strip()}
        prefixes = tuple(str(item).strip().upper() for item in prefixes_raw if str(item).strip())
        if not exact and not prefixes:
            return self._default_sku_flags()
        return exact, prefixes

    def _default_sku_flags(self) -> tuple[set[str], tuple[str, ...]]:
        exact = {str(item).strip().upper() for item in _DEFAULT_SKU_FLAGS["exact"]}
        prefixes = tuple(str(item).strip().upper() for item in _DEFAULT_SKU_FLAGS["prefixes"])
        return exact, prefixes

    def _apply_unreleased_sku_flags(self, summaries: list[InvoiceSummary]) -> None:
        exact, prefixes = self._load_sku_flags()
        for summary in summaries:
            hay = " ".join(
                [
                    summary.order_reference,
                    summary.buyer_note,
                    summary.invoice_number,
                ]
            )
            tokens = {match.group(0).upper() for match in _SKU_TOKEN_RE.finditer(hay)}
            summary.has_unreleased_sku = any(
                token in exact or any(token.startswith(prefix) for prefix in prefixes)
                for token in tokens
            )
