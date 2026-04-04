"""PrintDecisionEngine — decides what to print, how many, and why.

Integrates:
- ProductCatalogService  (SKU resolution + print rules)
- PartClient             (sevDesk stock read/write)
- WixOrdersClient        (order line items)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from xw_studio.services.products.catalog import Product, StockStatus

if TYPE_CHECKING:
    from xw_studio.services.products.catalog import ProductCatalogService
    from xw_studio.services.sevdesk.invoice_client import InvoiceSummary
    from xw_studio.services.sevdesk.part_client import PartClient
    from xw_studio.services.wix.client import WixOrderItem, WixOrdersClient

logger = logging.getLogger(__name__)


@dataclass
class PieceBlock:
    """One line in the Stuecke panel — one SKU from a Wix order."""

    sku: str
    name: str
    qty_needed: int
    note: str = ""
    is_unreleased: bool = False

    # Filled in from pipeline (may be None if product not in catalog)
    product: Product | None = None
    stock_status: StockStatus | None = None

    @property
    def needs_print(self) -> bool:
        """True when this SKU requires physical printing."""
        if self.product is None or self.product.is_digital:
            return False
        if self.stock_status is None:
            return True  # unknown — assume print needed
        return self.stock_status.on_hand < self.qty_needed

    @property
    def print_qty(self) -> int:
        """How many copies to print: max(qty_needed, reprint_batch_qty)."""
        if self.product is None or self.product.is_digital:
            return 0
        if self.stock_status is None:
            return self.qty_needed
        short = max(0, self.qty_needed - self.stock_status.on_hand)
        if short == 0:
            return 0
        batch = self.product.print_rule.reprint_batch_qty
        return max(short, batch)

    @property
    def stock_label(self) -> str:
        """Human-readable stock indicator for the Stuecke panel."""
        if self.product is None:
            return "Unbekanntes Produkt"
        if self.product.is_digital:
            return "Digital ∞"
        if self.stock_status is None:
            return "Bestand unbekannt"
        on_hand = self.stock_status.on_hand
        target = self.product.print_rule.min_stock_target
        if on_hand == 0:
            batch = self.product.print_rule.reprint_batch_qty
            return f"⚠ Leer — Drucken! ({batch} Stk)"
        if on_hand < self.qty_needed:
            short = self.qty_needed - on_hand
            return f"⚠ Zu wenig ({on_hand} Stk, {short} fehlen)"
        if on_hand <= target:
            return f"⚡ Niedrig ({on_hand}/{target})"
        return f"✓ Im Lager ({on_hand} Stk)"

    @property
    def print_file_path(self) -> Path | None:
        if self.product is None:
            return None
        return self.product.print_path


@dataclass
class InvoicePrintPlan:
    """Complete print plan for one invoice's Wix order."""

    invoice_ref: str
    pieces: list[PieceBlock] = field(default_factory=list)

    @property
    def has_print_work(self) -> bool:
        return any(p.needs_print for p in self.pieces)

    @property
    def total_print_items(self) -> int:
        return sum(p.print_qty for p in self.pieces if p.needs_print)

    def printable_pieces(self) -> list[PieceBlock]:
        return [p for p in self.pieces if p.needs_print and not (p.product is not None and p.product.is_digital)]

    def missing_file_pieces(self) -> list[PieceBlock]:
        """Pieces that need printing but have no print file configured."""
        return [
            p for p in self.pieces
            if p.needs_print and p.print_file_path is None
        ]

    # Internal helper consumed above
    def _piece_is_digital(self, p: PieceBlock) -> bool:
        return p.product is not None and p.product.is_digital


class PrintDecisionEngine:
    """Central service coordinating stock checks and print decisions.

    Injected with:
      - catalog: ProductCatalogService
      - part_client: PartClient (for sevDesk stock reads)
    """

    def __init__(
        self,
        catalog: ProductCatalogService,
        part_client: PartClient,
    ) -> None:
        self._catalog = catalog
        self._part_client = part_client
        self._legacy_pdf_paths = self._load_legacy_pdf_paths()

    # ------------------------------------------------------------------ #
    # Main entry points                                                    #
    # ------------------------------------------------------------------ #

    def get_piece_blocks(
        self,
        wix_items: list[WixOrderItem],
        invoice_ref: str = "",
    ) -> list[PieceBlock]:
        """Build PieceBlock list from Wix order items, enriched with stock data."""
        blocks: list[PieceBlock] = []
        for item in wix_items:
            block = self._build_block(item)
            blocks.append(block)
        logger.debug(
            "PrintDecisionEngine: %d piece blocks for invoice %r (%d need print)",
            len(blocks),
            invoice_ref,
            sum(1 for b in blocks if b.needs_print),
        )
        return blocks

    def create_plan(
        self,
        wix_items: list[WixOrderItem],
        invoice_ref: str,
    ) -> InvoicePrintPlan:
        """Create a full InvoicePrintPlan for one invoice."""
        pieces = self.get_piece_blocks(wix_items, invoice_ref)
        return InvoicePrintPlan(invoice_ref=invoice_ref, pieces=pieces)

    def record_print_and_update_sevdesk(
        self,
        piece: PieceBlock,
        qty_printed: int,
        invoice_ref: str = "",
    ) -> int:
        """After physical printing: increment sevDesk Part stock, return new stock.

        Args:
            piece: The PieceBlock that was printed.
            qty_printed: How many copies were actually printed.
            invoice_ref: Invoice number for audit trail.

        Returns:
            New stock level written to sevDesk.
        """
        if piece.product is None or piece.product.is_digital:
            return 0
        if not piece.product.sevdesk_part_id:
            logger.warning(
                "record_print_and_update_sevdesk: no sevdesk_part_id for SKU %s",
                piece.sku,
            )
            return 0

        current = self._part_client.get_part_stock(piece.product.sevdesk_part_id)
        new_stock = current + qty_printed
        self._part_client.set_part_stock(piece.product.sevdesk_part_id, new_stock)
        logger.info(
            "Stock updated for SKU %s (sevDesk %s): %d -> %d (invoice=%s)",
            piece.sku,
            piece.product.sevdesk_part_id,
            current,
            new_stock,
            invoice_ref,
        )
        return new_stock

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _build_block(self, item: WixOrderItem) -> PieceBlock:
        product = self._catalog.resolve_sku(item.sku)
        stock_status: StockStatus | None = None

        if product is not None and not product.print_file_path.strip():
            legacy_pdf = self._legacy_pdf_paths.get(item.sku.strip().upper())
            if legacy_pdf:
                product.print_file_path = legacy_pdf

        if product is not None and not product.is_digital and product.sevdesk_part_id:
            on_hand = self._fetch_stock_safe(product.sevdesk_part_id)
            stock_status = StockStatus(
                sku=product.sku,
                product_name=product.name,
                is_digital=False,
                on_hand=on_hand,
                min_stock_target=product.print_rule.min_stock_target,
                reprint_batch_qty=product.print_rule.reprint_batch_qty,
            )
        elif product is not None and product.is_digital:
            stock_status = StockStatus(
                sku=product.sku,
                product_name=product.name,
                is_digital=True,
                on_hand=0,
                min_stock_target=0,
                reprint_batch_qty=0,
            )
        else:
            # Product not in catalog yet — try sevDesk direct SKU lookup
            stock_status = self._fetch_stock_by_sku_safe(item.sku)

        return PieceBlock(
            sku=item.sku,
            name=item.name,
            qty_needed=item.qty,
            note=item.note,
            is_unreleased=item.is_unreleased,
            product=product,
            stock_status=stock_status,
        )

    def _load_legacy_pdf_paths(self) -> dict[str, str]:
        inventory_path = self._detect_legacy_inventory_store_path()
        if inventory_path is None:
            return {}
        try:
            payload = json.loads(inventory_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not load legacy inventory store (%s): %s", inventory_path, exc)
            return {}
        records = payload.get("records") if isinstance(payload, dict) else {}
        if not isinstance(records, dict):
            return {}

        out: dict[str, str] = {}
        for raw_sku, raw_record in records.items():
            if not isinstance(raw_record, dict):
                continue
            sku = str(raw_sku or "").strip().upper()
            if not sku:
                continue
            pdfs = raw_record.get("pdfs")
            if not isinstance(pdfs, list):
                continue
            resolved = self._resolve_default_legacy_pdf_path(inventory_path, pdfs)
            if resolved:
                out[sku] = resolved
        if out:
            logger.info("Loaded %d legacy PDF paths from %s", len(out), inventory_path)
        return out

    @staticmethod
    def _resolve_default_legacy_pdf_path(inventory_path: Path, pdfs: list[object]) -> str:
        for raw in pdfs:
            if not isinstance(raw, dict):
                continue
            path_raw = str(raw.get("path") or "").strip()
            if not path_raw:
                continue
            path = Path(path_raw)
            if not path.is_absolute():
                path = (inventory_path.parent / path).resolve()
            if path.exists():
                return str(path)
        return ""

    @staticmethod
    def _detect_legacy_inventory_store_path() -> Path | None:
        env_path = str(os.getenv("XW_LEGACY_INVENTORY_STORE_PATH") or "").strip()
        candidates: list[Path] = []
        if env_path:
            candidates.append(Path(env_path).expanduser())

        repo_root = Path(__file__).resolve().parents[4]
        candidates.extend(
            [
                repo_root / "data" / "inventory_store.json",
                repo_root.parent / "sevDesk" / "sevdesk_wix_fulfillment" / "data" / "inventory_store.json",
            ]
        )

        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved.exists() and resolved.is_file():
                return resolved
        return None

    def _fetch_stock_by_sku_safe(self, sku: str) -> StockStatus | None:
        """Fallback: find sevDesk Part by SKU and return a transient StockStatus."""
        try:
            part = self._part_client.find_part_by_sku(sku)
            if part is None:
                return None
            if not part.stock_enabled:
                return StockStatus(
                    sku=sku,
                    product_name=part.name,
                    is_digital=True,
                    on_hand=0,
                    min_stock_target=0,
                    reprint_batch_qty=0,
                )
            # Use default print rule values for unknown products
            return StockStatus(
                sku=sku,
                product_name=part.name,
                is_digital=False,
                on_hand=part.stock_qty,
                min_stock_target=5,  # sensible default
                reprint_batch_qty=3,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("_fetch_stock_by_sku_safe(%r) failed: %s", sku, exc)
            return None

    def _fetch_stock_safe(self, sevdesk_part_id: str) -> int:
        try:
            return self._part_client.get_part_stock(sevdesk_part_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Could not fetch stock for sevDesk Part %s: %s", sevdesk_part_id, exc
            )
            return -1
