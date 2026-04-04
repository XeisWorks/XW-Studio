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

_ORDERS_BASE = "https://www.wixapis.com/ecom/v1"
_UNRELEASED_PREFIXES = ("XW-600", "XW-010")


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


class WixOrderItem(BaseModel):
    """Single line item from a Wix order — used in the Stücke panel."""

    model_config = ConfigDict(extra="ignore")

    line_item_id: str = ""
    sku: str = ""
    name: str = ""
    qty: int = 1
    note: str = ""
    is_unreleased: bool = False


def _parse_order_line_item(raw: dict[str, Any]) -> WixOrderItem:
    """Extract a normalized WixOrderItem from a Wix ecom lineItem dict."""
    line_item_id = str(raw.get("id") or "").strip()
    # SKU is nested: physicalProperties.sku or catalogReference.catalogItemOptions.sku
    sku = ""
    phys = raw.get("physicalProperties")
    if isinstance(phys, dict):
        sku = str(phys.get("sku") or "").strip()
    if not sku:
        cat = raw.get("catalogReference") or {}
        if isinstance(cat, dict):
            opts = cat.get("catalogItemOptions") or {}
            if isinstance(opts, dict):
                sku = str(opts.get("sku") or "").strip()

    # Product name
    product_name = raw.get("productName") or {}
    if isinstance(product_name, dict):
        name = str(product_name.get("translated") or product_name.get("original") or "").strip()
    else:
        name = str(product_name or raw.get("name") or raw.get("title") or "").strip()
    if not name and sku:
        name = sku

    # Quantity
    try:
        qty = int(raw.get("quantity") or 1)
    except (TypeError, ValueError):
        qty = 1
    qty = max(qty, 1)

    # Note from line item description or options
    note = ""
    desc = raw.get("descriptionLines") or []
    if isinstance(desc, list):
        parts: list[str] = []
        for entry in desc:
            if not isinstance(entry, dict):
                continue
            label = str((entry.get("name") or {}).get("translated") or
                        (entry.get("name") or {}).get("original") or "").strip()
            value_obj = entry.get("plainText") or entry.get("colorInfo") or {}
            value = str((value_obj.get("translated") or value_obj.get("original") or "")
                        if isinstance(value_obj, dict) else value_obj).strip()
            if label and value:
                parts.append(f"{label}: {value}")
            elif value:
                parts.append(value)
        note = " | ".join(parts)

    is_unreleased = any(sku.upper().startswith(p) for p in _UNRELEASED_PREFIXES)

    return WixOrderItem(
        line_item_id=line_item_id,
        sku=sku,
        name=name,
        qty=qty,
        note=note,
        is_unreleased=is_unreleased,
    )


class WixOrdersClient:
    """Fetch Wix ecom orders and their line items.

    Credentials from :class:`SecretService` (same keys as WixProductsClient).
    """

    def __init__(
        self,
        *,
        secret_service: "SecretService | None" = None,
        orders_base: str = _ORDERS_BASE,
    ) -> None:
        self._secrets = secret_service
        self._orders_base = orders_base.rstrip("/")

    def _api_key(self) -> str:
        return self._secrets.get_secret("WIX_API_KEY") if self._secrets else ""

    def _site_id(self) -> str:
        return self._secrets.get_secret("WIX_SITE_ID") if self._secrets else ""

    def _account_id(self) -> str:
        return self._secrets.get_secret("WIX_ACCOUNT_ID") if self._secrets else ""

    def has_credentials(self) -> bool:
        return bool(self._api_key() and self._site_id())

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {
            "Authorization": self._api_key(),
            "wix-site-id": self._site_id(),
            "Content-Type": "application/json",
        }
        acc = self._account_id()
        if acc:
            h["wix-account-id"] = acc
        return h

    def _get_order_by_id(self, order_id: str) -> dict[str, Any]:
        with httpx.Client(timeout=_TIMEOUT) as client:
            try:
                resp = client.get(
                    f"{self._orders_base}/orders/{order_id}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                payload = resp.json()
                return payload.get("order") or payload or {}
            except httpx.HTTPError as exc:
                logger.warning("WixOrdersClient GET order/%s failed: %s", order_id, exc)
                return {}

    def _search_order_by_number(self, number: str) -> dict[str, Any]:
        body = {"filter": {"number": {"$eq": number}}, "paging": {"limit": 1}}
        with httpx.Client(timeout=_TIMEOUT) as client:
            try:
                resp = client.post(
                    f"{self._orders_base}/orders/search",
                    headers=self._headers(),
                    json=body,
                )
                resp.raise_for_status()
                payload = resp.json()
                orders = payload.get("orders") or []
                return orders[0] if orders else {}
            except httpx.HTTPError as exc:
                logger.warning("WixOrdersClient search number=%s failed: %s", number, exc)
                return {}

    def _resolve_order(self, reference: str) -> dict[str, Any]:
        ref = str(reference or "").strip()
        if not ref or not self.has_credentials():
            return {}
        if self._looks_like_uuid(ref):
            return self._get_order_by_id(ref)
        order = self._search_order_by_number(ref)
        if not order and not ref.startswith("00"):
            digits = "".join(c for c in ref if c.isdigit())
            if digits and digits != ref:
                order = self._search_order_by_number(digits)
        return order

    def _resolve_order_id(self, reference: str) -> str:
        order = self._resolve_order(reference)
        return str(order.get("id") or "").strip()

    def resolve_order(self, reference: str) -> dict[str, Any]:
        """Resolve an order by order number/reference or UUID."""
        return self._resolve_order(reference)

    def resolve_order_summary(self, reference: str) -> dict[str, str]:
        """Return normalized customer/order fields used by the details panel."""
        order = self._resolve_order(reference)
        if not order:
            return {}

        buyer = order.get("buyerInfo") if isinstance(order.get("buyerInfo"), dict) else {}
        shipping = order.get("shippingInfo") if isinstance(order.get("shippingInfo"), dict) else {}
        shipping_address = shipping.get("shippingDestination") if isinstance(shipping.get("shippingDestination"), dict) else {}

        first = str(buyer.get("firstName") or "").strip()
        last = str(buyer.get("lastName") or "").strip()
        full_name = " ".join(part for part in (first, last) if part).strip()
        email = str(buyer.get("email") or "").strip()
        city = str(shipping_address.get("city") or "").strip()
        street1 = str(shipping_address.get("addressLine1") or "").strip()
        street2 = str(shipping_address.get("addressLine2") or "").strip()
        postal_code = str(shipping_address.get("postalCode") or "").strip()
        country = str(shipping_address.get("country") or "").strip()
        shipping_lines = [line for line in (street1, street2, " ".join(part for part in (postal_code, city) if part), country) if line]
        return {
            "wix_order_id": str(order.get("id") or "").strip(),
            "wix_order_number": str(order.get("number") or "").strip(),
            "wix_customer_name": full_name,
            "wix_customer_email": email,
            "wix_shipping_street": street1,
            "wix_shipping_street2": street2,
            "wix_shipping_zip": postal_code,
            "wix_shipping_city": city,
            "wix_shipping_country": country,
            "wix_shipping_address": "\n".join(shipping_lines),
        }

    def resolve_order_dashboard_url(self, reference: str) -> str:
        """Return Wix dashboard URL for an order reference (number or UUID)."""
        order = self._resolve_order(reference)
        order_id = str(order.get("id") or "").strip()
        site_id = self._site_id().strip()
        if not order_id or not site_id:
            return ""
        return f"https://manage.wix.com/dashboard/{site_id}/ecom-platform/order-details/{order_id}"

    def list_fulfillments(self, reference: str) -> list[dict[str, Any]]:
        order_id = self._resolve_order_id(reference)
        if not order_id or not self.has_credentials():
            return []
        with httpx.Client(timeout=_TIMEOUT) as client:
            try:
                resp = client.get(
                    f"{self._orders_base}/fulfillments/orders/{order_id}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                payload = resp.json()
                if isinstance(payload, dict):
                    data = payload.get("fulfillments")
                    if isinstance(data, list):
                        return [item for item in data if isinstance(item, dict)]
                if isinstance(payload, list):
                    return [item for item in payload if isinstance(item, dict)]
                return []
            except httpx.HTTPError as exc:
                logger.warning("WixOrdersClient list fulfillments failed: %s", exc)
                return []

    def get_fulfillable_items(self, reference: str) -> list[dict[str, Any]]:
        order_id = self._resolve_order_id(reference)
        if not order_id or not self.has_credentials():
            return []
        with httpx.Client(timeout=_TIMEOUT) as client:
            try:
                resp = client.get(
                    f"{self._orders_base}/fulfillments/orders/{order_id}/fulfillable-items",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                payload = resp.json()
                if isinstance(payload, dict):
                    data = payload.get("fulfillableLineItems")
                    if isinstance(data, list):
                        return [item for item in data if isinstance(item, dict)]
                if isinstance(payload, list):
                    return [item for item in payload if isinstance(item, dict)]
                return []
            except httpx.HTTPError as exc:
                logger.warning("WixOrdersClient get fulfillable items failed: %s", exc)
                return []

    def create_fulfillment(
        self,
        reference: str,
        line_items: list[dict[str, Any]],
        *,
        notify_customer: bool = False,
    ) -> dict[str, Any]:
        order_id = self._resolve_order_id(reference)
        items = [item for item in line_items if isinstance(item, dict)]
        if not order_id or not items or not self.has_credentials():
            return {}
        payload = {
            "fulfillment": {
                "lineItems": items,
                "status": "Fulfilled",
            },
            "notifyCustomer": bool(notify_customer),
        }
        with httpx.Client(timeout=_TIMEOUT) as client:
            try:
                resp = client.post(
                    f"{self._orders_base}/fulfillments/orders/{order_id}/create-fulfillment",
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json() if resp.content else {}
            except httpx.HTTPError as exc:
                logger.warning("WixOrdersClient create fulfillment failed: %s", exc)
                return {}

    def get_order_refundability(self, order_id: str) -> dict[str, Any]:
        real_id = str(order_id or "").strip()
        if not real_id or not self.has_credentials():
            return {}
        body = {"orderId": real_id}
        with httpx.Client(timeout=_TIMEOUT) as client:
            try:
                resp = client.post(
                    f"{self._orders_base}/order-billing/get-order-refundability",
                    headers=self._headers(),
                    json=body,
                )
                resp.raise_for_status()
                return resp.json() if resp.content else {}
            except httpx.HTTPError as exc:
                logger.warning(
                    "WixOrdersClient refundability order_id=%s failed: %s",
                    real_id,
                    exc,
                )
                return {}

    def refund_order_payments(
        self,
        order_id: str,
        payment_refunds: list[dict[str, Any]],
        *,
        send_customer_email: bool = True,
        customer_reason: str = "",
    ) -> dict[str, Any]:
        real_id = str(order_id or "").strip()
        refunds = [entry for entry in payment_refunds if isinstance(entry, dict)]
        if not real_id or not refunds or not self.has_credentials():
            return {}

        body: dict[str, Any] = {
            "orderId": real_id,
            "paymentRefunds": refunds,
            "sideEffects": {
                "notifications": {
                    "sendCustomerEmail": bool(send_customer_email),
                },
            },
        }
        if customer_reason.strip():
            body["customerReason"] = customer_reason.strip()

        with httpx.Client(timeout=_TIMEOUT) as client:
            try:
                resp = client.post(
                    f"{self._orders_base}/order-billing/refund-payments",
                    headers=self._headers(),
                    json=body,
                )
                resp.raise_for_status()
                return resp.json() if resp.content else {}
            except httpx.HTTPError as exc:
                logger.warning("WixOrdersClient refund payments order_id=%s failed: %s", real_id, exc)
                return {}

    def refund_full_order(
        self,
        reference: str,
        *,
        send_customer_email: bool = True,
        customer_reason: str = "",
    ) -> dict[str, Any]:
        """Refund all currently refundable payments for an order reference."""
        order = self._resolve_order(reference)
        order_id = str(order.get("id") or "").strip()
        if not order_id:
            return {}

        refundability = self.get_order_refundability(order_id)
        payments = refundability.get("payments")
        if not isinstance(payments, list):
            payments = []

        payment_refunds: list[dict[str, Any]] = []
        for entry in payments:
            if not isinstance(entry, dict) or not entry.get("refundable"):
                continue
            payment = entry.get("payment")
            if not isinstance(payment, dict):
                continue
            payment_id = str(payment.get("paymentId") or "").strip()
            amount_obj = entry.get("availableRefundAmount")
            if not isinstance(amount_obj, dict):
                continue
            amount = str(amount_obj.get("amount") or "").strip()
            if not payment_id or not amount:
                continue
            payment_refunds.append(
                {
                    "paymentId": payment_id,
                    "amount": {"amount": amount},
                }
            )

        if not payment_refunds:
            return {}

        return self.refund_order_payments(
            order_id,
            payment_refunds,
            send_customer_email=send_customer_email,
            customer_reason=customer_reason,
        )

    @staticmethod
    def _looks_like_uuid(value: str) -> bool:
        parts = value.split("-")
        return len(parts) == 5 and len(value) == 36

    def fetch_order_line_items(self, reference: str) -> list[WixOrderItem]:
        """Resolve a sevDesk order reference to Wix line items.

        *reference* can be a Wix order number (digits) or order UUID.
        Returns an empty list when credentials are missing or order not found.
        """
        ref = str(reference or "").strip()
        if not ref or not self.has_credentials():
            return []

        order = self._resolve_order(ref)

        if not order:
            logger.info("WixOrdersClient: no order found for reference=%r", ref)
            return []

        raw_items = order.get("lineItems") or []
        items = [_parse_order_line_item(item) for item in raw_items if isinstance(item, dict)]
        logger.info(
            "WixOrdersClient: reference=%r → %s line items",
            ref, len(items),
        )
        return items
