"""Payment clearing between PSPs (Stripe/Mollie) and sevDesk invoices."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PaymentClearingService:
    """Reconcile external payments with open invoices (skeleton).

    Future: inject Stripe/Mollie HTTP clients and sevDesk InvoiceClient.
    """

    def describe(self) -> str:
        return (
            "Clearing: Zuordnung von Stripe/Mollie-Zahlungen zu sevDesk-Rechnungen "
            "(Service-Geruest, keine Live-API in dieser Version)."
        )

    def list_pending_mock(self) -> list[dict[str, Any]]:
        """Empty placeholder list for the UI table."""
        return []
