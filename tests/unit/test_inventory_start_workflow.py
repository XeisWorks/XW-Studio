"""Tests for START preflight and execution workflow."""
from __future__ import annotations

import json

from xw_studio.core.config import AppConfig, PrintingSection
from xw_studio.services.inventory.service import (
    InventoryService,
    StartMode,
)


class _RepoStub:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}

    def get_value_json(self, key: str) -> str | None:
        return self.values.get(key)

    def set_value_json(self, key: str, value_json: str) -> None:
        self.values[key] = value_json


def test_preflight_prints_only_when_stock_insufficient() -> None:
    repo = _RepoStub(
        {
            "daily_business.pending_requirements": json.dumps({"XW-4-001": 5, "XW-6-003": 2}),
            "inventory.stock_levels": json.dumps({"XW-4-001": 5, "XW-6-003": 1}),
        }
    )
    cfg = AppConfig(printing=PrintingSection(buffer_quantity=3))
    service = InventoryService(cfg, repo)

    preflight = service.build_start_preflight(open_invoice_count=4)

    assert preflight.missing_position_data is False
    by_sku = {d.sku: d for d in preflight.decisions}

    assert by_sku["XW-4-001"].will_print is False
    assert by_sku["XW-4-001"].final_print_qty == 0
    assert by_sku["XW-6-003"].will_print is True
    assert by_sku["XW-6-003"].missing_qty == 1
    assert by_sku["XW-6-003"].final_print_qty == 4


def test_execute_full_mode_updates_stock_with_buffer_and_consumption() -> None:
    repo = _RepoStub(
        {
            "daily_business.pending_requirements": json.dumps({"XW-4-001": 5, "XW-6-003": 2}),
            "inventory.stock_levels": json.dumps({"XW-4-001": 5, "XW-6-003": 1}),
        }
    )
    cfg = AppConfig(printing=PrintingSection(buffer_quantity=3))
    service = InventoryService(cfg, repo)

    preflight = service.build_start_preflight(open_invoice_count=4)
    report = service.execute_start_workflow(preflight, StartMode.INVOICES_AND_PRINT)

    assert report.stock_updated is True
    assert report.printed_skus == ["XW-6-003"]

    stock_after = json.loads(repo.values["inventory.stock_levels"])
    # XW-4-001: on_hand=5, required=5, printed=0 -> 0
    assert stock_after["XW-4-001"] == 0
    # XW-6-003: on_hand=1, required=2, printed=(1+3)=4 -> 3
    assert stock_after["XW-6-003"] == 3


def test_execute_invoices_mode_keeps_stock_unchanged() -> None:
    raw_stock = json.dumps({"XW-7-100": 9})
    repo = _RepoStub(
        {
            "daily_business.pending_requirements": json.dumps({"XW-7-100": 2}),
            "inventory.stock_levels": raw_stock,
        }
    )
    service = InventoryService(AppConfig(), repo)

    preflight = service.build_start_preflight(open_invoice_count=2)
    report = service.execute_start_workflow(preflight, StartMode.INVOICES_ONLY)

    assert report.stock_updated is False
    assert repo.values["inventory.stock_levels"] == raw_stock
