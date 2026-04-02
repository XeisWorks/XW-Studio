"""Daily-Business queue/counter access (DB-backed with safe fallbacks)."""
from __future__ import annotations

import json
from typing import Any

from xw_studio.repositories.settings_kv import SettingKvRepository

_PENDING_COUNTS_KEY = "daily_business.pending_counts"
_QUEUE_KEYS = {
    "mollie": "daily_business.queue.mollie",
    "gutscheine": "daily_business.queue.gutscheine",
    "downloads": "daily_business.queue.downloads",
    "refunds": "daily_business.queue.refunds",
}


class DailyBusinessService:
    """Read queue counters and optional queue rows from settings storage."""

    def __init__(self, settings_repo: SettingKvRepository | None = None) -> None:
        self._repo = settings_repo

    def load_counts(self, open_invoice_count: int = 0) -> dict[str, int]:
        result = {
            "rechnungen": max(0, int(open_invoice_count)),
            "mollie": 0,
            "gutscheine": 0,
            "downloads": 0,
            "refunds": 0,
        }
        if self._repo is None:
            return result
        raw = self._repo.get_value_json(_PENDING_COUNTS_KEY)
        if not raw:
            return result
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return result
        if not isinstance(data, dict):
            return result
        for key in ("mollie", "gutscheine", "downloads", "refunds"):
            value = data.get(key)
            if isinstance(value, int):
                result[key] = max(0, value)
        return result

    def load_queue_rows(self, queue_name: str, fallback_count: int = 0) -> list[dict[str, str]]:
        key = _QUEUE_KEYS.get(queue_name)
        if not key:
            return []
        rows = self._read_queue_rows(key)
        if rows:
            return rows

        # Fallback: synthesize lightweight rows from count for immediate usability.
        fallback_n = max(0, int(fallback_count))
        return [
            {
                "Ref": f"{queue_name.upper()}-{i + 1:03d}",
                "Kunde": "—",
                "Betrag": "—",
                "Status": "Offen",
                "Hinweis": "Detaildaten folgen mit API-Integration",
            }
            for i in range(fallback_n)
        ]

    def _read_queue_rows(self, key: str) -> list[dict[str, str]]:
        if self._repo is None:
            return []
        raw = self._repo.get_value_json(key)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []

        result: list[dict[str, str]] = []
        for idx, item in enumerate(data, 1):
            if not isinstance(item, dict):
                continue
            result.append(self._normalize_row(item, idx))
        return result

    @staticmethod
    def _normalize_row(item: dict[str, Any], index: int) -> dict[str, str]:
        def pick(*keys: str, default: str = "") -> str:
            for key in keys:
                value = item.get(key)
                if value is not None and str(value).strip() != "":
                    return str(value).strip()
            return default

        return {
            "Ref": pick("ref", "id", "reference", default=f"ITEM-{index:03d}"),
            "Kunde": pick("customer", "name", "buyer", default="—"),
            "Betrag": pick("amount", "total", default="—"),
            "Status": pick("status", default="Offen"),
            "Hinweis": pick("note", "hint", default=""),
        }
