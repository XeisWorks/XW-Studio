"""Expense audit / Ausgaben-Check (skeleton)."""
from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass

from xw_studio.repositories.settings_kv import SettingKvRepository

logger = logging.getLogger(__name__)

_EXPENSES_KEY = "expenses.open_items"


@dataclass(frozen=True)
class ExpenseRow:
    """One expense row for review/export."""

    ref: str
    supplier: str
    gross_amount: str
    category: str
    status: str
    note: str


class ExpenseAuditService:
    """Review and classify expenses for tax reporting."""

    def __init__(self, settings_repo: SettingKvRepository | None = None) -> None:
        self._repo = settings_repo

    def describe(self) -> str:
        return (
            "Ausgaben-Check: Belege pruefen und fuer UVA/FIBU vorbereiten "
            "(DB-Liste + Filter + CSV-Export)."
        )

    def list_open(self) -> list[ExpenseRow]:
        if self._repo is None:
            return []
        raw = self._repo.get_value_json(_EXPENSES_KEY)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid expenses JSON in %s", _EXPENSES_KEY)
            return []
        if not isinstance(data, list):
            return []
        rows: list[ExpenseRow] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            rows.append(
                ExpenseRow(
                    ref=str(item.get("ref") or ""),
                    supplier=str(item.get("supplier") or ""),
                    gross_amount=str(item.get("gross_amount") or ""),
                    category=str(item.get("category") or ""),
                    status=str(item.get("status") or ""),
                    note=str(item.get("note") or ""),
                )
            )
        return rows

    def filter_rows(self, rows: list[ExpenseRow], needle: str = "", status: str = "") -> list[ExpenseRow]:
        search = needle.lower().strip()
        want_status = status.lower().strip()
        out: list[ExpenseRow] = []
        for row in rows:
            if want_status and row.status.lower().strip() != want_status:
                continue
            hay = f"{row.ref} {row.supplier} {row.gross_amount} {row.category} {row.status} {row.note}".lower()
            if search and search not in hay:
                continue
            out.append(row)
        return out

    def export_csv(self, rows: list[ExpenseRow]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";")
        writer.writerow(["Ref", "Lieferant", "Brutto", "Kategorie", "Status", "Hinweis"])
        for row in rows:
            writer.writerow([row.ref, row.supplier, row.gross_amount, row.category, row.status, row.note])
        return buf.getvalue()
