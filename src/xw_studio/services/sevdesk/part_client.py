"""sevDesk Part API client for product sync comparisons."""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict

from xw_studio.services.http_client import SevdeskConnection

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100


class SevdeskPart(BaseModel):
    """Minimal product/article row from sevDesk."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    sku: str = ""
    name: str = ""
    price_eur: str = ""
    stock_qty: int = 0
    # False => digital product (stockEnabled:false in sevDesk) — show ∞ in UI
    stock_enabled: bool = True


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _parse_part(raw: dict[str, Any]) -> SevdeskPart:
    pid = str(raw.get("id") or "")
    sku = str(
        raw.get("partNumber")
        or raw.get("partnumber")
        or raw.get("sku")
        or raw.get("code")
        or ""
    )
    name = str(raw.get("name") or raw.get("text") or "")
    price = str(
        raw.get("price")
        or raw.get("priceNet")
        or raw.get("priceGross")
        or ""
    )
    stock = _to_int(raw.get("stock") or raw.get("quantity") or raw.get("stockAmount") or 0)
    stock_enabled_raw = raw.get("stockEnabled")
    # sevDesk returns "1"/1/True for enabled, "0"/0/False for disabled
    if isinstance(stock_enabled_raw, bool):
        stock_enabled = stock_enabled_raw
    elif isinstance(stock_enabled_raw, (int, float)):
        stock_enabled = bool(int(stock_enabled_raw))
    elif isinstance(stock_enabled_raw, str):
        stock_enabled = stock_enabled_raw.strip() not in ("0", "false", "")
    else:
        stock_enabled = True  # default: assume physical
    return SevdeskPart(
        id=pid, sku=sku, name=name, price_eur=price,
        stock_qty=max(0, stock), stock_enabled=stock_enabled,
    )


class PartClient:
    """Read sevDesk products for cross-system sync checks."""

    def __init__(self, connection: SevdeskConnection) -> None:
        self._conn = connection

    def list_parts(self, *, max_pages: int = 20) -> list[SevdeskPart]:
        rows: list[SevdeskPart] = []
        offset = 0
        for _ in range(max_pages):
            params = {"limit": _PAGE_SIZE, "offset": offset}
            try:
                response = self._conn.get("/Part", params=params)
            except Exception as exc:  # noqa: BLE001
                logger.warning("PartClient.list_parts failed at offset %s: %s", offset, exc)
                break
            payload = response.json()
            objects = payload.get("objects") if isinstance(payload, dict) else None
            if not isinstance(objects, list):
                break
            for raw in objects:
                if isinstance(raw, dict):
                    rows.append(_parse_part(raw))
            if len(objects) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
        logger.info("PartClient: fetched %s parts", len(rows))
        return rows

    def find_part_by_sku(self, sku: str) -> SevdeskPart | None:
        """Look up a single Part by its partNumber/SKU via GET /Part?partNumber=…."""
        try:
            response = self._conn.get("/Part", params={"partNumber": sku})
            payload = response.json()
            objects = payload.get("objects") if isinstance(payload, dict) else []
            if not isinstance(objects, list) or not objects:
                return None
            for raw in objects:
                if isinstance(raw, dict):
                    return _parse_part(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("find_part_by_sku(%r) failed: %s", sku, exc)
        return None

    def get_part_stock(self, part_id: str) -> int:
        """Return current stock for a single sevDesk Part.

        Uses GET /Part/{partId}/getStock which returns {"objects": <number>}.
        Falls back to full Part fetch if the dedicated endpoint is unavailable.
        """
        try:
            response = self._conn.get(f"/Part/{part_id}/getStock")
            payload = response.json()
            raw_stock = payload.get("objects") if isinstance(payload, dict) else None
            if raw_stock is not None:
                return max(0, int(float(raw_stock)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_part_stock via /getStock failed for %s: %s", part_id, exc)
        # Fallback: full Part fetch
        try:
            response = self._conn.get(f"/Part/{part_id}")
            payload = response.json()
            objects = payload.get("objects") if isinstance(payload, dict) else []
            if isinstance(objects, list) and objects:
                raw = objects[0]
            elif isinstance(objects, dict):
                raw = objects
            else:
                return 0
            return max(0, int(float(raw.get("stock") or 0)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_part_stock fallback failed for %s: %s", part_id, exc)
            return 0

    def set_part_stock(self, part_id: str, new_stock: int) -> None:
        """Write a new stock value to sevDesk via PUT /Part/{partId}.

        sevDesk accepts partial updates — only `stock` is sent.
        """
        try:
            self._conn.put(f"/Part/{part_id}", json={"stock": float(new_stock)})
            logger.info("sevDesk Part %s stock set to %d", part_id, new_stock)
        except Exception as exc:  # noqa: BLE001
            logger.error("set_part_stock failed for Part %s: %s", part_id, exc)
            raise
