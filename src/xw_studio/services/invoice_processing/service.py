"""Orchestrates invoice-related operations (no UI)."""
from __future__ import annotations

import json
import logging

from xw_studio.repositories.settings_kv import SettingKvRepository
from xw_studio.services.sevdesk.invoice_client import InvoiceClient, InvoiceSummary
from xw_studio.services.sevdesk.invoice_client import DEFAULT_SENSITIVE_COUNTRY_CODES

logger = logging.getLogger(__name__)

_SENSITIVE_COUNTRIES_KEY = "rechnungen.sensitive_country_codes"


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
        logger.info(
            "Loaded %s invoices from sevDesk (status=%s offset=%s limit=%s)",
            len(summaries),
            status,
            offset,
            limit,
        )
        return [s.as_table_row() for s in summaries]

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
        rows = [s.as_table_row() for s in summaries]
        return rows, summaries

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
