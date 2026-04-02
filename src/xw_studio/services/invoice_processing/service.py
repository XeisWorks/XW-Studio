"""Orchestrates invoice-related operations (no UI)."""
from __future__ import annotations

import logging

from xw_studio.services.sevdesk.invoice_client import InvoiceClient, InvoiceSummary

logger = logging.getLogger(__name__)


class InvoiceProcessingService:
    """Facade over sevDesk invoice clients for the Rechnungen module."""

    def __init__(self, invoice_client: InvoiceClient) -> None:
        self._invoices = invoice_client

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
        return self._invoices.list_invoice_summaries(
            limit=limit,
            offset=offset,
            status=status,
        )

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
        rows = [s.as_table_row() for s in summaries]
        return rows, summaries
