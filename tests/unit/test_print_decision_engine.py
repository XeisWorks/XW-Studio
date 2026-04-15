from __future__ import annotations

import json

from xw_studio.services.products.catalog import ProductCatalogService
from xw_studio.services.products.print_decision import PrintDecisionEngine
from xw_studio.services.wix.client import WixOrderItem


class _PartClientStub:
    def find_part_by_sku(self, _sku: str):
        return None

    def get_part_stock(self, _part_id: str) -> int:
        return 0


def test_piece_block_imports_legacy_title_print_config(monkeypatch, tmp_path) -> None:
    pdf_path = tmp_path / "song-a.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")
    store_path = tmp_path / "inventory_store.json"
    store_path.write_text(
        json.dumps(
            {
                "records": {
                    "XW-010": {
                        "pdfs": [{"title": "Standard", "path": "", "is_default": True, "profile_id": "", "print_plan": []}],
                        "title_print_configs": {
                            "song_a": {
                                "title": "Song A",
                                "pdfs": [
                                    {
                                        "title": "Song A",
                                        "path": str(pdf_path),
                                        "is_default": True,
                                        "profile_id": "noten_a4_duplex",
                                        "print_plan": [{"range": "1-2", "profile_id": "canon_brochure_mono"}],
                                    }
                                ],
                            }
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XW_LEGACY_INVENTORY_STORE_PATH", str(store_path))

    engine = PrintDecisionEngine(ProductCatalogService(), _PartClientStub())
    blocks = engine.get_piece_blocks([WixOrderItem(sku="XW-010", name="Song A", qty=1, is_unreleased=True)])

    assert len(blocks) == 1
    block = blocks[0]
    assert block.print_file_path is not None
    assert str(block.print_file_path) == str(pdf_path)
    assert block.print_profile_id == "noten_a4_duplex"
    assert block.print_plan == [{"range": "1-2", "profile_id": "canon_brochure_mono"}]
    assert block.has_direct_print_config is True
