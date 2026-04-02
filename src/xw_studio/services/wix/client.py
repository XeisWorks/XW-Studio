"""Wix Store REST client — products and order status."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from xw_studio.services.secrets.service import SecretService

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0
_PRODUCTS_PAGE_SIZE = 100


class WixProduct(BaseModel):
    """Minimal Wix Catalog product row for sync."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str = ""
    sku: str = ""
    price: str = ""
    visible: bool = True
    inventory_quantity: int = 0


def _parse_product(raw: dict[str, Any]) -> WixProduct:
    pid = str(raw.get("id") or "")
    name = str(raw.get("name") or "")
    sku = ""
    price = ""
    variants: list[Any] = raw.get("variants") or []
    if variants and isinstance(variants[0], dict):
        v = variants[0]
        sku = str(v.get("sku") or "")
        pricing = v.get("priceData") or {}
        if isinstance(pricing, dict):
            price = str(pricing.get("price") or "")
    if not sku:
        sku = str(raw.get("sku") or "")
    visible = bool(raw.get("visible", True))
    inv = raw.get("stock") or {}
    qty = 0
    if isinstance(inv, dict):
        try:
            qty = int(inv.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
    return WixProduct(id=pid, name=name, sku=sku, price=price, visible=visible, inventory_quantity=qty)


class WixProductsClient:
    """Read Wix Stores Catalog (v3) products.

    Credentials come from :class:`SecretService` (DB/env):
    - WIX_API_KEY  — bearer token
    - WIX_SITE_ID  — target site
    - WIX_ACCOUNT_ID — (optional) Wix account header
    """

    def __init__(
        self,
        *,
        secret_service: "SecretService | None" = None,
        base_url: str = "https://www.wixapis.com/stores/v3",
    ) -> None:
        self._secrets = secret_service
        self._base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Credential helpers
    # ------------------------------------------------------------------

    def _api_key(self) -> str:
        if self._secrets:
            return self._secrets.get_secret("WIX_API_KEY") or ""
        return ""

    def _site_id(self) -> str:
        if self._secrets:
            return self._secrets.get_secret("WIX_SITE_ID") or ""
        return ""

    def _account_id(self) -> str:
        if self._secrets:
            return self._secrets.get_secret("WIX_ACCOUNT_ID") or ""
        return ""

    def has_credentials(self) -> bool:
        return bool(self._api_key() and self._site_id())

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------

    def list_products(self, *, include_hidden: bool = True) -> list[WixProduct]:
        """Fetch all products from Wix Catalog (paginated).

        Returns an empty list when credentials are not configured — no exception.
        """
        if not self.has_credentials():
            logger.info("WixProductsClient: no credentials — returning empty list")
            return []

        api_key = self._api_key()
        site_id = self._site_id()
        account_id = self._account_id()

        headers: dict[str, str] = {
            "Authorization": api_key,
            "wix-site-id": site_id,
            "Content-Type": "application/json",
        }
        if account_id:
            headers["wix-account-id"] = account_id

        results: list[WixProduct] = []
        cursor: str | None = None
        page = 0
        max_pages = 50

        with httpx.Client(timeout=_TIMEOUT) as client:
            while page < max_pages:
                body: dict[str, Any] = {
                    "query": {
                        "paging": {"limit": _PRODUCTS_PAGE_SIZE},
                    }
                }
                if cursor:
                    body["query"]["cursorPaging"] = {"cursor": cursor}

                try:
                    resp = client.post(
                        f"{self._base_url}/catalog/products/query",
                        headers=headers,
                        json=body,
                    )
                    resp.raise_for_status()
                except httpx.HTTPError:
                    logger.exception("WixProductsClient: HTTP error on page %s", page)
                    break

                data = resp.json()
                products: list[Any] = data.get("products") or []
                if not isinstance(products, list):
                    break
                for raw in products:
                    if isinstance(raw, dict):
                        results.append(_parse_product(raw))

                # Check for next cursor
                meta = data.get("metadata") or data.get("pagingMetadata") or {}
                cursor = (meta.get("cursors") or {}).get("next") if isinstance(meta, dict) else None
                if not cursor or len(products) < _PRODUCTS_PAGE_SIZE:
                    break
                page += 1

        logger.info("WixProductsClient: fetched %s products", len(results))
        return results
