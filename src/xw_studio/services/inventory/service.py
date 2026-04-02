"""Inventory and print-plan coordination for START preflight."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from xw_studio.core.config import AppConfig
from xw_studio.repositories.settings_kv import SettingKvRepository

logger = logging.getLogger(__name__)

_STOCK_KEY = "inventory.stock_levels"
_REQUIREMENTS_KEY = "daily_business.pending_requirements"


@dataclass(frozen=True)
class StartDecision:
    """Single SKU decision for START preflight."""

    sku: str
    required_qty: int
    on_hand_qty: int
    missing_qty: int
    final_print_qty: int
    will_print: bool


@dataclass(frozen=True)
class StartPreflight:
    """Preflight result for START dialog and orchestration."""

    open_invoice_count: int
    decisions: list[StartDecision]
    missing_position_data: bool


class InventoryService:
    """Stock levels and print buffer rules for daily START workflow."""

    def __init__(
        self,
        config: AppConfig,
        settings_repo: SettingKvRepository | None = None,
    ) -> None:
        self._config = config
        self._settings_repo = settings_repo

    def load_stock_levels(self) -> dict[str, int]:
        """Return stock levels by SKU (from DB setting if available)."""
        if self._settings_repo is None:
            return {}
        raw = self._settings_repo.get_value_json(_STOCK_KEY)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in %s", _STOCK_KEY)
            return {}
        if not isinstance(data, dict):
            return {}
        result: dict[str, int] = {}
        for key, value in data.items():
            if not isinstance(key, str):
                continue
            try:
                result[key] = max(0, int(value))
            except (TypeError, ValueError):
                continue
        return result

    def load_pending_requirements(self) -> dict[str, int]:
        """Return required print quantities by SKU for current queue."""
        if self._settings_repo is None:
            return {}
        raw = self._settings_repo.get_value_json(_REQUIREMENTS_KEY)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in %s", _REQUIREMENTS_KEY)
            return {}
        if not isinstance(data, dict):
            return {}
        result: dict[str, int] = {}
        for key, value in data.items():
            if not isinstance(key, str):
                continue
            try:
                qty = int(value)
            except (TypeError, ValueError):
                continue
            if qty > 0:
                result[key] = qty
        return result

    def build_start_preflight(self, open_invoice_count: int) -> StartPreflight:
        """Create decision list: print only when stock is below required quantity."""
        requirements = self.load_pending_requirements()
        if not requirements:
            return StartPreflight(
                open_invoice_count=max(0, int(open_invoice_count)),
                decisions=[],
                missing_position_data=True,
            )

        stock_levels = self.load_stock_levels()
        buffer_qty = max(0, int(self._config.printing.buffer_quantity))
        decisions: list[StartDecision] = []

        for sku in sorted(requirements):
            required = max(0, int(requirements.get(sku, 0)))
            on_hand = max(0, int(stock_levels.get(sku, 0)))
            missing = max(0, required - on_hand)
            will_print = missing > 0
            final_print_qty = missing + buffer_qty if will_print else 0
            decisions.append(
                StartDecision(
                    sku=sku,
                    required_qty=required,
                    on_hand_qty=on_hand,
                    missing_qty=missing,
                    final_print_qty=final_print_qty,
                    will_print=will_print,
                )
            )

        return StartPreflight(
            open_invoice_count=max(0, int(open_invoice_count)),
            decisions=decisions,
            missing_position_data=False,
        )

    def describe(self) -> str:
        return (
            "Produkte / Inventar: Bestand, Druckplaene, Wix/sevDesk-Abgleich — "
            "persistiert spaeter in PostgreSQL."
        )
