"""Daily-Business queue/counter access (DB-backed with safe fallbacks)."""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from xw_studio.services.sevdesk.invoice_client import InvoiceSummary

from xw_studio.repositories.settings_kv import SettingKvRepository

if TYPE_CHECKING:
    from xw_studio.services.invoice_processing.service import InvoiceProcessingService

_PENDING_COUNTS_KEY = "daily_business.pending_counts"
_URGENCY_RULES_KEY = "daily_business.urgency_rules"
_QUEUE_KEYS = {
    "mollie": "daily_business.queue.mollie",
    "gutscheine": "daily_business.queue.gutscheine",
    "downloads": "daily_business.queue.downloads",
    "refunds": "daily_business.queue.refunds",
}

_DEFAULT_URGENCY_RULES: dict[str, list[str]] = {
    "generic": ["offen", "fehl", "pending", "ueberweis", "überweis"],
    "mollie": ["auth", "authorized", "chargeback", "missing auth"],
    "gutscheine": ["ungueltig", "ungültig", "einloes", "einlös"],
    "downloads": ["link fehlt", "download fehlt", "retry", "fehlgeschlagen"],
    "refunds": ["refund", "rueckerstattung", "rückerstattung", "auszahlung"],
}

_CHANNEL_TOOLTIPS: dict[str, str] = {
    "mollie": "Dringend: Mollie-Auth/Zahlung offen",
    "gutscheine": "Dringend: Gutschein-Pruefung offen",
    "downloads": "Dringend: Download-Link/Versand offen",
    "refunds": "Dringend: Rueckerstattung/Zahlung offen",
}


class DailyBusinessService:
    """Read queue counters and optional queue rows from settings storage."""

    def __init__(
        self,
        settings_repo: SettingKvRepository | None = None,
        invoice_processing: "InvoiceProcessingService | None" = None,
    ) -> None:
        self._repo = settings_repo
        self._invoice_processing = invoice_processing
        self._live_cache_ts = 0.0
        self._live_cache: dict[str, list[dict[str, str]]] = {
            "mollie": [],
            "gutscheine": [],
            "downloads": [],
            "refunds": [],
        }

    def load_counts(self, open_invoice_count: int = 0) -> dict[str, int]:
        result = {
            "rechnungen": max(0, int(open_invoice_count)),
            "mollie": 0,
            "gutscheine": 0,
            "downloads": 0,
            "refunds": 0,
        }
        if self._repo is None:
            live = self._load_live_queue_map()
            for key in ("mollie", "gutscheine", "downloads", "refunds"):
                result[key] = len(live.get(key, []))
            return result
        raw = self._repo.get_value_json(_PENDING_COUNTS_KEY)
        if not raw:
            live = self._load_live_queue_map()
            for key in ("mollie", "gutscheine", "downloads", "refunds"):
                result[key] = len(live.get(key, []))
            return result
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            live = self._load_live_queue_map()
            for key in ("mollie", "gutscheine", "downloads", "refunds"):
                result[key] = len(live.get(key, []))
            return result
        if not isinstance(data, dict):
            live = self._load_live_queue_map()
            for key in ("mollie", "gutscheine", "downloads", "refunds"):
                result[key] = len(live.get(key, []))
            return result
        for key in ("mollie", "gutscheine", "downloads", "refunds"):
            value = data.get(key)
            if isinstance(value, int):
                result[key] = max(0, value)
        for key in ("mollie", "gutscheine", "downloads", "refunds"):
            if result[key] == 0:
                result[key] = len(self._load_live_queue_map().get(key, []))
        return result

    def load_queue_rows(self, queue_name: str, fallback_count: int = 0) -> list[dict[str, str]]:
        key = _QUEUE_KEYS.get(queue_name)
        if not key:
            return []
        urgency_rules = self._load_urgency_rules()
        rows = self._read_queue_rows(key, queue_name, urgency_rules)
        if rows:
            return rows

        live_rows = self._load_live_queue_map().get(queue_name, [])
        if live_rows:
            return [
                self._normalize_row(dict(row), idx, queue_name, urgency_rules)
                for idx, row in enumerate(live_rows, 1)
            ]

        # Fallback: synthesize lightweight rows from count for immediate usability.
        fallback_n = max(0, int(fallback_count))
        return [
            {
                "Ref": f"{queue_name.upper()}-{i + 1:03d}",
                "Kunde": "—",
                "Betrag": "—",
                "Status": "Offen",
                "Hinweis": "Detaildaten folgen mit API-Integration",
                "Mark.": "🔴",
                "__tooltip__Mark.": "Dringend: offene Aufgabe",
                "__fg__Mark.": "#ef4444",
            }
            for i in range(fallback_n)
        ]

    def _read_queue_rows(
        self,
        key: str,
        queue_name: str,
        urgency_rules: dict[str, list[str]],
    ) -> list[dict[str, str]]:
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
            result.append(self._normalize_row(item, idx, queue_name, urgency_rules))
        return result

    def _load_live_queue_map(self) -> dict[str, list[dict[str, str]]]:
        if self._invoice_processing is None:
            return self._live_cache

        now = time.monotonic()
        if now - self._live_cache_ts <= 30.0:
            return self._live_cache

        try:
            invoices = self._invoice_processing.load_invoice_summaries(status=200, limit=300, offset=0)
        except Exception:
            self._live_cache_ts = now
            return self._live_cache

        live: dict[str, list[dict[str, str]]] = {
            "mollie": [],
            "gutscheine": [],
            "downloads": [],
            "refunds": [],
        }
        for inv in invoices:
            queue = self._classify_invoice_queue(inv)
            if queue is None:
                continue
            live[queue].append(self._invoice_to_queue_row(inv, queue))

        self._live_cache = live
        self._live_cache_ts = now
        return self._live_cache

    @staticmethod
    def _invoice_to_queue_row(inv: InvoiceSummary, queue_name: str) -> dict[str, str]:
        ref = inv.invoice_number or inv.id or "—"
        note = inv.buyer_note.strip()
        base_hint = {
            "mollie": "Live aus offenen Rechnungen (Mollie-Hinweis erkannt)",
            "gutscheine": "Live aus offenen Rechnungen (Gutschein-Hinweis erkannt)",
            "downloads": "Live aus offenen Rechnungen (Download-Hinweis erkannt)",
            "refunds": "Live aus offenen Rechnungen (Refund-Hinweis erkannt)",
        }.get(queue_name, "Live aus offenen Rechnungen")
        hint = base_hint if not note else f"{base_hint} | Notiz: {note}"
        row = {
            "Ref": ref,
            "Kunde": inv.contact_name or "—",
            "Betrag": inv.formatted_brutto,
            "Status": inv.status_label(),
            "Hinweis": hint,
        }
        if note:
            row["__tooltip__Hinweis"] = note
        return row

    @staticmethod
    def _classify_invoice_queue(inv: InvoiceSummary) -> str | None:
        hay = (
            f"{inv.order_reference} {inv.buyer_note} {inv.invoice_number} {inv.contact_name}"
        ).lower()
        if any(k in hay for k in ("refund", "rueckerstattung", "rückerstattung", "storno", "chargeback")):
            return "refunds"
        if any(k in hay for k in ("gutschein", "voucher", "coupon", "gift card")):
            return "gutscheine"
        if any(k in hay for k in ("download", "digital", "pdf-link", "link")):
            return "downloads"
        if any(k in hay for k in ("mollie", "auth", "authorized", "payment")):
            return "mollie"
        return None

    def _load_urgency_rules(self) -> dict[str, list[str]]:
        normalized: dict[str, list[str]] = {
            key: list(values)
            for key, values in _DEFAULT_URGENCY_RULES.items()
        }
        if self._repo is None:
            return normalized

        raw = self._repo.get_value_json(_URGENCY_RULES_KEY)
        if not raw:
            return normalized
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return normalized
        if not isinstance(data, dict):
            return normalized

        for key in ("generic", "mollie", "gutscheine", "downloads", "refunds"):
            candidate = data.get(key)
            if not isinstance(candidate, list):
                continue
            vals = [str(v).strip().lower() for v in candidate if str(v).strip()]
            if vals:
                normalized[key] = vals
        return normalized

    @staticmethod
    def _normalize_row(
        item: dict[str, Any],
        index: int,
        queue_name: str,
        urgency_rules: dict[str, list[str]],
    ) -> dict[str, str]:
        def pick(*keys: str, default: str = "") -> str:
            for key in keys:
                value = item.get(key)
                if value is not None and str(value).strip() != "":
                    return str(value).strip()
            return default

        note = pick("Hinweis", "note", "hint", "buyer_note", default="")
        status = pick("Status", "status", default="Offen")
        marker = ""
        marker_tip = ""

        urgency_hay = f"{status} {note}".lower()
        generic_urgent = any(keyword in urgency_hay for keyword in urgency_rules.get("generic", []))

        channel_keywords = urgency_rules.get(queue_name, [])
        channel_urgent = any(k in urgency_hay for k in channel_keywords)
        channel_tip = _CHANNEL_TOOLTIPS.get(queue_name, "")

        if generic_urgent or channel_urgent:
            marker = "🔴"
            marker_tip = channel_tip or "Dringend: offene Sendung/Zahlung"

        row = {
            "Ref": pick("Ref", "ref", "id", "reference", default=f"ITEM-{index:03d}"),
            "Kunde": pick("Kunde", "customer", "name", "buyer", default="—"),
            "Betrag": pick("Betrag", "amount", "total", default="—"),
            "Status": pick("Status", "status", default="Offen"),
            "Hinweis": pick("Hinweis", "note", "hint", "buyer_note", default=""),
            "Mark.": marker,
        }
        if marker:
            row["__tooltip__Mark."] = marker_tip
            row["__fg__Mark."] = "#ef4444"
        if note:
            row["__tooltip__Hinweis"] = note
        return row
