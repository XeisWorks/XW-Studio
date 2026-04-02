"""Inventory and print-plan coordination for START preflight."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum

from xw_studio.core.config import AppConfig
from xw_studio.repositories.settings_kv import SettingKvRepository

logger = logging.getLogger(__name__)

_STOCK_KEY = "inventory.stock_levels"
_REQUIREMENTS_KEY = "daily_business.pending_requirements"
_PRODUCTS_KEY = "inventory.products"


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


class StartMode(str, Enum):
    """Execution mode selected in START dialog."""

    INVOICES_ONLY = "invoices"
    INVOICES_AND_PRINT = "full"


@dataclass(frozen=True)
class StartExecutionReport:
    """Result payload for START execution after dialog confirmation."""

    mode: StartMode
    open_invoice_count: int
    decisions_count: int
    printed_skus: list[str]
    consumed_skus: list[str]
    stock_updated: bool


@dataclass(frozen=True)
class ProductRow:
    """Single product row for UI tables."""

    sku: str
    name: str
    category: str
    on_hand: int
    price_eur: str
    wix_id: str
    sevdesk_id: str


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

    def execute_start_workflow(
        self,
        preflight: StartPreflight,
        mode: StartMode,
    ) -> StartExecutionReport:
        """Execute START side effects for the selected *mode*.

        In ``INVOICES_AND_PRINT`` mode this updates inventory.stock_levels with
        post-run amounts (required quantities consumed, shortage printed with
        configured buffer).
        """
        if mode == StartMode.INVOICES_ONLY:
            return StartExecutionReport(
                mode=mode,
                open_invoice_count=preflight.open_invoice_count,
                decisions_count=len(preflight.decisions),
                printed_skus=[],
                consumed_skus=[],
                stock_updated=False,
            )

        if preflight.missing_position_data or not preflight.decisions:
            return StartExecutionReport(
                mode=mode,
                open_invoice_count=preflight.open_invoice_count,
                decisions_count=len(preflight.decisions),
                printed_skus=[],
                consumed_skus=[],
                stock_updated=False,
            )

        stock_levels = self.load_stock_levels()
        printed_skus: list[str] = []
        consumed_skus: list[str] = []

        for decision in preflight.decisions:
            current = max(0, int(stock_levels.get(decision.sku, decision.on_hand_qty)))
            produced = max(0, int(decision.final_print_qty)) if decision.will_print else 0
            consumed = max(0, int(decision.required_qty))
            final_stock = max(0, current + produced - consumed)
            stock_levels[decision.sku] = final_stock

            if produced > 0:
                printed_skus.append(decision.sku)
            if consumed > 0:
                consumed_skus.append(decision.sku)

        self._save_stock_levels(stock_levels)
        return StartExecutionReport(
            mode=mode,
            open_invoice_count=preflight.open_invoice_count,
            decisions_count=len(preflight.decisions),
            printed_skus=printed_skus,
            consumed_skus=consumed_skus,
            stock_updated=True,
        )

    def _save_stock_levels(self, stock_levels: dict[str, int]) -> None:
        if self._settings_repo is None:
            return
        clean: dict[str, int] = {}
        for sku, qty in stock_levels.items():
            if not isinstance(sku, str) or not sku:
                continue
            clean[sku] = max(0, int(qty))
        self._settings_repo.set_value_json(_STOCK_KEY, json.dumps(clean, ensure_ascii=False))

    def describe(self) -> str:
        return (
            "Produkte / Inventar: Bestand, Druckplaene, Wix/sevDesk-Abgleich — "
            "persistiert spaeter in PostgreSQL."
        )

    def list_products(self) -> list[ProductRow]:
        """Return product catalogue rows from DB (``inventory.products`` JSON array).

        Each entry must be a JSON object with optional keys:
        ``sku``, ``name``, ``category``, ``on_hand``, ``price_eur``, ``wix_id``, ``sevdesk_id``.
        Returns an empty list when no DB connection or data is available.
        """
        if self._settings_repo is None:
            return []
        raw = self._settings_repo.get_value_json(_PRODUCTS_KEY)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in %s", _PRODUCTS_KEY)
            return []
        if not isinstance(data, list):
            return []
        rows: list[ProductRow] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                on_hand = int(item.get("on_hand") or 0)
            except (TypeError, ValueError):
                on_hand = 0
            rows.append(
                ProductRow(
                    sku=str(item.get("sku") or ""),
                    name=str(item.get("name") or ""),
                    category=str(item.get("category") or ""),
                    on_hand=on_hand,
                    price_eur=str(item.get("price_eur") or ""),
                    wix_id=str(item.get("wix_id") or ""),
                    sevdesk_id=str(item.get("sevdesk_id") or ""),
                )
            )
        return rows
