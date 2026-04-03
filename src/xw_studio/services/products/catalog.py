"""ProductCatalogService — canonical product registry with SKU resolution.

Source of truth for product metadata, print rules, and file paths.
All writes to sevDesk Part stock go through PartClient (separate concern).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xw_studio.services.sevdesk.part_client import SevdeskPart

logger = logging.getLogger(__name__)


@dataclass
class PrintRule:
    """Per-product print configuration."""

    min_stock_target: int = 5
    """If on-hand stock falls at or below this, trigger a reprint."""

    reprint_batch_qty: int = 3
    """How many copies to print per reprint run."""


@dataclass
class Product:
    """Canonical product entity resolved from the pipeline DB."""

    id: str  # UUID string
    sku: str
    name: str
    category: str = ""
    is_digital: bool = False
    sevdesk_part_id: str = ""
    wix_product_id: str = ""
    print_file_path: str = ""
    print_rule: PrintRule = field(default_factory=PrintRule)
    status: str = "draft"  # draft / review / live

    @property
    def print_path(self) -> Path | None:
        """Return Path if print_file_path is non-empty, else None."""
        p = self.print_file_path.strip()
        return Path(p) if p else None


@dataclass
class StockStatus:
    """Stock snapshot for a single product (read from sevDesk or cache)."""

    sku: str
    product_name: str
    is_digital: bool
    on_hand: int
    min_stock_target: int
    reprint_batch_qty: int

    @property
    def is_unlimited(self) -> bool:
        return self.is_digital

    @property
    def needs_reprint(self) -> bool:
        """True when physical stock is at or below the target threshold."""
        return not self.is_digital and self.on_hand <= self.min_stock_target

    @property
    def display_stock(self) -> str:
        if self.is_digital:
            return "∞"
        return str(self.on_hand)

    @property
    def status_label(self) -> str:
        if self.is_digital:
            return "Digital"
        if self.on_hand == 0:
            return f"Leer — muss gedruckt werden ({self.reprint_batch_qty} Stk)"
        if self.needs_reprint:
            return (
                f"Niedrig ({self.on_hand} Stk) — "
                f"Nachdruck empfohlen ({self.reprint_batch_qty} Stk)"
            )
        return f"Im Lager ({self.on_hand} Stk)"


class ProductCatalogService:
    """Central registry for canonical product metadata.

    In Phase A/B this operates as an in-memory + sevDesk-backed service.
    Once DB migration 002 is applied and a database session is available,
    the implementation can be swapped to use the `product` table directly.
    The interface stays stable.
    """

    def __init__(self) -> None:
        # In-memory cache: canonical SKU -> Product
        self._by_sku: dict[str, Product] = {}
        # Alias map: any_sku -> canonical_sku
        self._alias_map: dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # Upsert from external sources                                         #
    # ------------------------------------------------------------------ #

    def upsert_from_sevdesk(self, part: SevdeskPart) -> Product:
        """Register or update a product from a sevDesk Part object."""
        canonical_sku = part.sku.strip().upper()
        if not canonical_sku:
            canonical_sku = f"SEVDESK-{part.id}"

        existing = self._by_sku.get(canonical_sku)
        if existing is not None:
            # Update mutable fields
            existing.sevdesk_part_id = part.id
            existing.name = part.name or existing.name
            existing.is_digital = not part.stock_enabled
            return existing

        product = Product(
            id=str(uuid.uuid4()),
            sku=canonical_sku,
            name=part.name,
            sevdesk_part_id=part.id,
            is_digital=not part.stock_enabled,
            print_rule=PrintRule(),
        )
        self._by_sku[canonical_sku] = product
        logger.debug("Registered product %s from sevDesk Part %s", canonical_sku, part.id)
        return product

    # ------------------------------------------------------------------ #
    # SKU resolution                                                       #
    # ------------------------------------------------------------------ #

    def resolve_sku(self, raw_sku: str) -> Product | None:
        """Return Product for raw_sku including alias lookup."""
        sku = raw_sku.strip().upper()
        product = self._by_sku.get(sku)
        if product is not None:
            return product
        canonical = self._alias_map.get(sku)
        if canonical is not None:
            return self._by_sku.get(canonical)
        return None

    def register_alias(self, alias_sku: str, canonical_sku: str) -> None:
        alias = alias_sku.strip().upper()
        canonical = canonical_sku.strip().upper()
        if canonical not in self._by_sku:
            raise KeyError(f"Canonical SKU {canonical!r} not found in catalog")
        self._alias_map[alias] = canonical
        logger.debug("Alias %s -> %s registered", alias, canonical)

    # ------------------------------------------------------------------ #
    # Print rule management                                                #
    # ------------------------------------------------------------------ #

    def set_print_rule(
        self,
        sku: str,
        *,
        min_stock_target: int,
        reprint_batch_qty: int,
    ) -> None:
        product = self.resolve_sku(sku)
        if product is None:
            raise KeyError(f"Product {sku!r} not found")
        product.print_rule = PrintRule(
            min_stock_target=min_stock_target,
            reprint_batch_qty=reprint_batch_qty,
        )

    def set_print_file_path(self, sku: str, path: str) -> None:
        product = self.resolve_sku(sku)
        if product is None:
            raise KeyError(f"Product {sku!r} not found")
        product.print_file_path = path

    # ------------------------------------------------------------------ #
    # Listing                                                              #
    # ------------------------------------------------------------------ #

    def list_all(self) -> list[Product]:
        return list(self._by_sku.values())

    def get_by_sku(self, sku: str) -> Product | None:
        return self.resolve_sku(sku)
