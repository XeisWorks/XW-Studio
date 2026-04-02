"""Orchestrates invoice-related operations (no UI)."""
from __future__ import annotations

import logging

from xw_studio.services.sevdesk.invoice_client import InvoiceClient

logger = logging.getLogger(__name__)


class InvoiceProcessingService:
    """Facade over sevDesk invoice clients for the Rechnungen module."""

    def __init__(self, invoice_client: InvoiceClient) -> None:
        self._invoices = invoice_client

    def load_invoice_table_rows(self) -> list[dict[str, str]]:
        """Load invoices and return rows for :class:`DataTable` (German keys)."""
        summaries = self._invoices.list_invoice_summaries(limit=200, offset=0)
        logger.info("Loaded %s invoices from sevDesk", len(summaries))
        return [s.as_table_row() for s in summaries]
