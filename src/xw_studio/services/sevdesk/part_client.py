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
    return SevdeskPart(id=pid, sku=sku, name=name, price_eur=price, stock_qty=max(0, stock))


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
