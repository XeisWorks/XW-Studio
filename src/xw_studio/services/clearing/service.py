"""Payment clearing between PSPs (Stripe/Mollie) and sevDesk invoices."""
from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass

from xw_studio.repositories.settings_kv import SettingKvRepository

logger = logging.getLogger(__name__)

_QUEUE_MOLLIE_KEY = "daily_business.queue.mollie"


@dataclass(frozen=True)
class ClearingRow:
    """One pending payment-to-invoice matching row."""

    ref: str
    customer: str
    amount: str
    status: str
    note: str


class PaymentClearingService:
    """Reconcile external payments with open invoices (skeleton).

    Future: inject Stripe/Mollie HTTP clients and sevDesk InvoiceClient.
    """

    def __init__(self, settings_repo: SettingKvRepository | None = None) -> None:
        self._repo = settings_repo

    def describe(self) -> str:
        return (
            "Clearing: Zuordnung von PSP-Zahlungen zu sevDesk-Rechnungen "
            "(DB-Queue + Filter + CSV-Export)."
        )

    def list_pending(self) -> list[ClearingRow]:
        """Load pending clearing queue rows from settings repository."""
        if self._repo is None:
            return []
        raw = self._repo.get_value_json(_QUEUE_MOLLIE_KEY)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid clearing JSON in %s", _QUEUE_MOLLIE_KEY)
            return []
        if not isinstance(data, list):
            return []
        rows: list[ClearingRow] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            rows.append(
                ClearingRow(
                    ref=str(item.get("ref") or ""),
                    customer=str(item.get("customer") or ""),
                    amount=str(item.get("amount") or ""),
                    status=str(item.get("status") or ""),
                    note=str(item.get("note") or ""),
                )
            )
        return rows

    def filter_rows(self, rows: list[ClearingRow], needle: str = "", status: str = "") -> list[ClearingRow]:
        """Filter by free-text and optional status."""
        search = needle.lower().strip()
        want_status = status.lower().strip()
        out: list[ClearingRow] = []
        for row in rows:
            if want_status and row.status.lower().strip() != want_status:
                continue
            hay = f"{row.ref} {row.customer} {row.amount} {row.status} {row.note}".lower()
            if search and search not in hay:
                continue
            out.append(row)
        return out

    def export_csv(self, rows: list[ClearingRow]) -> str:
        """Return CSV payload for selected rows."""
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";")
        writer.writerow(["Ref", "Kunde", "Betrag", "Status", "Hinweis"])
        for row in rows:
            writer.writerow([row.ref, row.customer, row.amount, row.status, row.note])
        return buf.getvalue()
