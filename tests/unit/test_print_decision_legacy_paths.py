from __future__ import annotations

import json
from pathlib import Path

from xw_studio.services.products.catalog import Product, ProductCatalogService
from xw_studio.services.products.print_decision import PrintDecisionEngine
from xw_studio.services.wix.client import WixOrderItem


class _PartClientStub:
    def get_part_stock(self, _part_id: str) -> int:
        return 0

    def set_part_stock(self, _part_id: str, _stock: int) -> None:
        return None

    def find_part_by_sku(self, _sku: str):
        return None


def test_engine_uses_legacy_inventory_pdf_paths(monkeypatch, tmp_path: Path) -> None:
    legacy_pdf = tmp_path / "legacy_piece.pdf"
    legacy_pdf.write_bytes(b"%PDF-1.4\n")
    inventory_store = tmp_path / "inventory_store.json"
    inventory_store.write_text(
        json.dumps(
            {
                "records": {
                    "XW-4-123": {
                        "pdfs": [
                            {
                                "title": "Standard",
                                "path": str(legacy_pdf),
                                "is_default": True,
                            }
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("XW_LEGACY_INVENTORY_STORE_PATH", str(inventory_store))

    catalog = ProductCatalogService()
    product = Product(id="1", sku="XW-4-123", name="Test Piece", is_digital=False)
    catalog._by_sku[product.sku] = product  # noqa: SLF001

    engine = PrintDecisionEngine(catalog, _PartClientStub())  # type: ignore[arg-type]

    blocks = engine.get_piece_blocks(
        [WixOrderItem(line_item_id="l1", sku="XW-4-123", name="Test Piece", qty=1)],
        "RE-1",
    )

    assert blocks
    assert blocks[0].print_file_path is not None
    assert blocks[0].print_file_path == legacy_pdf
