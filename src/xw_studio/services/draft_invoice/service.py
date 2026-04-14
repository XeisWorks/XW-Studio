"""Create and repair sevDesk invoice drafts from Wix order numbers."""
from __future__ import annotations

from datetime import date
import logging
from typing import Any

from xw_studio.services.http_client import SevdeskConnection
from xw_studio.services.sevdesk.contact_client import ContactClient
from xw_studio.services.sevdesk.invoice_client import InvoiceClient
from xw_studio.services.sevdesk.part_client import PartClient
from xw_studio.services.wix.client import WixOrdersClient
from xw_studio.services.wix.client import _parse_order_line_item

logger = logging.getLogger(__name__)


class DraftInvoiceService:
    """Build and repair sevDesk invoice drafts from Wix order data."""

    def __init__(
        self,
        connection: SevdeskConnection,
        wix_orders: WixOrdersClient,
        part_client: PartClient,
        contact_client: ContactClient,
        invoice_client: InvoiceClient,
    ) -> None:
        self._conn = connection
        self._wix_orders = wix_orders
        self._parts = part_client
        self._contacts = contact_client
        self._invoices = invoice_client

    def create_draft_from_wix_order_number(self, wix_order_number: str) -> dict[str, str]:
        """Create an Entwurf in sevDesk from a Wix order number."""
        reference = str(wix_order_number or "").strip()
        if not reference:
            raise ValueError("Wix-Order-Nr fehlt.")
        if not self._wix_orders.has_credentials():
            raise ValueError("Wix API nicht konfiguriert (API-Key/Account/Site-ID fehlt).")

        order = self._resolve_order_required(reference)
        order_number = str(order.get("number") or reference).strip()
        self.ensure_products_for_wix_order_number(order_number)

        contact_id = self._resolve_or_create_contact(order)
        sev_user_id = self._resolve_default_sev_user_id()
        positions = self._build_positions(order)

        invoice_date = date.today().isoformat()
        invoice: dict[str, Any] = {
            "objectName": "Invoice",
            "mapAll": True,
            "invoiceDate": invoice_date,
            "deliveryDate": invoice_date,
            "status": 100,
            "invoiceType": "RE",
            "currency": "EUR",
            "contact": {"id": contact_id, "objectName": "Contact"},
            "discount": 0,
            "taxRate": 0,
            "taxType": "default",
            "customerInternalNote": order_number,
            "showNet": False,
            "header": "Rechnung",
            "address": self._build_address_text(order),
        }

        next_invoice_number = self._get_next_invoice_number()
        if next_invoice_number:
            invoice["invoiceNumber"] = next_invoice_number
        if sev_user_id:
            invoice["contactPerson"] = {"id": sev_user_id, "objectName": "SevUser"}

        payload = {
            "invoice": invoice,
            "invoicePosSave": positions,
            "invoicePosDelete": None,
            "discountSave": [],
            "discountDelete": None,
            "takeDefaultAddress": False,
        }
        response = self._conn.post("/Invoice/Factory/saveInvoice", json=payload)
        data = response.json() if response.content else {}
        created_invoice = self._extract_created_invoice(data)
        created_id = str(created_invoice.get("id") or "").strip()
        created_number = str(created_invoice.get("invoiceNumber") or "").strip()
        if not created_id:
            raise RuntimeError("sevDesk hat keinen Rechnungsentwurf zurueckgegeben.")

        logger.info("DraftInvoiceService: draft created for Wix order %s -> invoice %s", order_number, created_id)
        return {
            "invoice_id": created_id,
            "invoice_number": created_number or "(Entwurf)",
            "wix_order_number": order_number,
            "positions": str(len(positions)),
        }

    def preview_wix_order_number(self, wix_order_number: str) -> dict[str, Any]:
        """Return preview data for the draft popup before creation."""
        reference = str(wix_order_number or "").strip()
        if not reference:
            raise ValueError("Wix-Order-Nr fehlt.")
        if not self._wix_orders.has_credentials():
            raise ValueError("Wix API nicht konfiguriert (API-Key/Account/Site-ID fehlt).")

        order = self._resolve_order_required(reference)
        order_number = str(order.get("number") or reference).strip()
        items = self._wix_orders.fetch_order_line_items(order_number)
        if not items:
            raise ValueError("Wix-Order enthaelt keine Positionen.")

        missing_skus: list[str] = []
        auto_create_skus: list[str] = []
        preview_items: list[dict[str, str]] = []
        for item in items:
            sku = str(item.sku or "").strip()
            if not sku:
                missing_skus.append(f"(ohne SKU) {item.name}")
                preview_items.append(
                    {
                        "sku": "-",
                        "name": str(item.name or "").strip() or "(ohne Name)",
                        "qty": str(max(1, int(item.qty or 1))),
                        "status": "Nicht mappbar (SKU fehlt)",
                    }
                )
                continue
            part = self._parts.find_part_by_sku(sku)
            if part is None or not str(part.id).strip():
                auto_create_skus.append(sku)
                preview_items.append(
                    {
                        "sku": sku,
                        "name": str(item.name or "").strip() or sku,
                        "qty": str(max(1, int(item.qty or 1))),
                        "status": "Auto-Anlage in sevDesk",
                    }
                )
                continue
            preview_items.append(
                {
                    "sku": sku,
                    "name": str(item.name or part.name or sku).strip(),
                    "qty": str(max(1, int(item.qty or 1))),
                    "status": f"OK -> Part {part.id}",
                }
            )

        buyer = order.get("buyerInfo") if isinstance(order.get("buyerInfo"), dict) else {}
        customer = " ".join(
            part
            for part in (str(buyer.get("firstName") or "").strip(), str(buyer.get("lastName") or "").strip())
            if part
        ).strip()
        return {
            "wix_order_number": order_number,
            "customer": customer or "-",
            "email": str(buyer.get("email") or "").strip() or "-",
            "items": preview_items,
            "missing_skus": sorted(set(missing_skus)),
            "auto_create_skus": sorted(set(auto_create_skus)),
            "can_create": not bool(missing_skus),
        }

    def ensure_products_for_wix_order_number(self, wix_order_number: str) -> list[str]:
        """Create missing sevDesk parts for one Wix order before draft creation."""
        order = self._resolve_order_required(wix_order_number)
        created: list[str] = []
        for raw_item in self._order_line_items(order):
            item = _parse_order_line_item(raw_item)
            sku = str(item.sku or "").strip().upper()
            if not sku:
                continue
            if self._parts.find_part_by_sku(sku) is not None:
                continue
            payload = self._build_part_payload(raw_item)
            created_part = self._parts.create_part(payload)
            if created_part.id.strip():
                created.append(sku)
        if created:
            logger.info("DraftInvoiceService: auto-created sevDesk parts for %s", ", ".join(sorted(set(created))))
        return created

    def repair_draft_product_mapping(self, invoice_id: str, wix_order_number: str) -> bool:
        """Patch an existing draft so invoice positions point to real sevDesk parts."""
        order = self._resolve_order_required(wix_order_number)
        self.ensure_products_for_wix_order_number(wix_order_number)
        invoice = self._invoices.fetch_invoice_by_id(invoice_id)
        positions = self._invoices.fetch_invoice_positions(invoice_id)
        if not invoice or not positions:
            return False
        patched_positions = self._patched_positions_for_order(order, positions)
        if patched_positions == positions:
            return False
        self._invoices.update_invoice_draft(invoice, patched_positions)
        logger.info("DraftInvoiceService: repaired draft %s for Wix order %s", invoice_id, wix_order_number)
        return True

    def _build_positions(self, order: dict[str, Any]) -> list[dict[str, Any]]:
        raw_items = self._order_line_items(order)
        if not raw_items:
            raise ValueError("Wix-Order enthaelt keine Positionen.")

        missing_skus: list[str] = []
        positions: list[dict[str, Any]] = []
        for index, raw_item in enumerate(raw_items):
            item = _parse_order_line_item(raw_item)
            sku = str(item.sku or "").strip().upper()
            if not sku:
                missing_skus.append(f"(ohne SKU) {item.name}")
                continue
            part = self._parts.find_part_by_sku(sku)
            if part is None or not str(part.id).strip():
                missing_skus.append(sku)
                continue
            qty = max(1, int(item.qty or 1))
            price = self._to_float(part.price_eur)
            if price <= 0:
                price = self._line_item_unit_price(raw_item)
            positions.append(
                {
                    "objectName": "InvoicePos",
                    "mapAll": True,
                    "unity": {"id": 1, "objectName": "Unity"},
                    "taxRate": 19,
                    "quantity": float(qty),
                    "price": price,
                    "name": str(item.name or part.name or sku).strip(),
                    "text": str(item.note or "").strip(),
                    "positionNumber": index,
                    "part": {"id": str(part.id), "objectName": "Part"},
                }
            )

        if missing_skus:
            joined = ", ".join(sorted(set(missing_skus)))
            raise ValueError(
                "Rechnungsentwurf abgebrochen: folgende Wix-Produkte sind nicht eindeutig auf sevDesk-Artikel gemappt: "
                f"{joined}"
            )
        if not positions:
            raise ValueError("Rechnungsentwurf abgebrochen: keine gueltigen Positionen gefunden.")
        return positions

    def _patched_positions_for_order(
        self,
        order: dict[str, Any],
        positions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        raw_items = self._order_line_items(order)
        if not raw_items or not positions:
            return list(positions or [])
        patched = [dict(position) for position in positions]
        limit = min(len(raw_items), len(patched))
        for index in range(limit):
            raw_item = raw_items[index]
            item = _parse_order_line_item(raw_item)
            sku = str(item.sku or "").strip().upper()
            if not sku:
                continue
            part = self._parts.find_part_by_sku(sku)
            if part is None or not part.id.strip():
                continue
            updated = dict(patched[index])
            updated["part"] = {"id": str(part.id), "objectName": "Part"}
            updated["name"] = str(item.name or part.name or sku).strip()
            updated["text"] = str(item.note or updated.get("text") or "").strip()
            patched[index] = updated
        return patched

    @staticmethod
    def _order_line_items(order: dict[str, Any]) -> list[dict[str, Any]]:
        raw_items = order.get("lineItems") if isinstance(order, dict) else None
        if not isinstance(raw_items, list):
            return []
        return [item for item in raw_items if isinstance(item, dict)]

    def _build_part_payload(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        item = _parse_order_line_item(raw_item)
        sku = str(item.sku or "").strip().upper()
        name = str(item.name or sku).strip() or sku
        return {
            "name": name,
            "partNumber": sku,
            "text": str(item.note or "").strip(),
            "priceGross": round(self._line_item_unit_price(raw_item), 2),
            "taxRate": 19.0,
            "unity": {"id": 1, "objectName": "Unity"},
            "stockEnabled": not self._wix_orders.line_item_is_digital(raw_item),
            "stock": 0,
            "status": 100,
        }

    def _resolve_order_required(self, reference: str) -> dict[str, Any]:
        order = self._wix_orders.resolve_order(str(reference or "").strip())
        if not order:
            raise ValueError(f"Wix-Order '{reference}' wurde nicht gefunden.")
        return order

    def _resolve_or_create_contact(self, order: dict[str, Any]) -> str:
        buyer = order.get("buyerInfo") if isinstance(order.get("buyerInfo"), dict) else {}
        email = str(buyer.get("email") or "").strip().lower()
        if email:
            contacts = self._contacts.list_contacts(max_pages=20, depth=1)
            for contact in contacts:
                if str(contact.email or "").strip().lower() == email:
                    return str(contact.id)

        billing = order.get("billingInfo") if isinstance(order.get("billingInfo"), dict) else {}
        contact_details = billing.get("contactDetails") if isinstance(billing.get("contactDetails"), dict) else {}
        first = str(contact_details.get("firstName") or "").strip()
        last = str(contact_details.get("lastName") or "").strip()
        company = str(contact_details.get("company") or "").strip()
        name = company or " ".join(part for part in (first, last) if part).strip() or email or "Wix Kunde"
        payload: dict[str, Any] = {
            "name": name,
            "status": 1000,
            "category": {"id": "3", "objectName": "Category"},
            "description": "Automatisch erstellt aus Wix-Bestellung",
        }
        response = self._conn.post("/Contact", json=payload)
        data = response.json() if response.content else {}
        contact_obj = self._extract_first_object(data)
        contact_id = str(contact_obj.get("id") or "").strip()
        if not contact_id:
            raise RuntimeError("Kontakt konnte in sevDesk nicht erstellt werden.")
        return contact_id

    def _resolve_default_sev_user_id(self) -> str:
        try:
            response = self._conn.get("/SevUser", params={"limit": 1, "offset": 0})
        except Exception:
            return ""
        data = response.json() if response.content else {}
        first = self._extract_first_object(data)
        return str(first.get("id") or "").strip()

    def _get_next_invoice_number(self) -> str:
        try:
            response = self._conn.get("/Invoice/Factory/getNextInvoiceNumber", params={"invoiceType": "RE"})
        except Exception:
            return ""
        payload = response.json() if response.content else {}
        if isinstance(payload, dict):
            objects = payload.get("objects")
            if isinstance(objects, list) and objects:
                first = objects[0]
                if isinstance(first, dict):
                    return str(first.get("invoiceNumber") or first.get("value") or "").strip()
                return str(first).strip()
            if isinstance(objects, dict):
                return str(objects.get("invoiceNumber") or objects.get("value") or "").strip()
        return ""

    def _build_address_text(self, order: dict[str, Any]) -> str:
        return "\n".join(WixOrdersClient.best_address_lines_from_order(order))

    @staticmethod
    def _extract_first_object(payload: object) -> dict[str, Any]:
        if isinstance(payload, dict):
            objects = payload.get("objects")
            if isinstance(objects, list) and objects and isinstance(objects[0], dict):
                return objects[0]
            if isinstance(objects, dict):
                return objects
            return payload
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return payload[0]
        return {}

    @staticmethod
    def _extract_created_invoice(payload: object) -> dict[str, Any]:
        if isinstance(payload, dict):
            invoice = payload.get("invoice")
            if isinstance(invoice, dict):
                return invoice
            objects = payload.get("objects")
            if isinstance(objects, list) and objects and isinstance(objects[0], dict):
                return objects[0]
            if isinstance(objects, dict):
                return objects
            return payload
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return payload[0]
        return {}

    @staticmethod
    def _line_item_unit_price(raw_item: dict[str, Any]) -> float:
        for key in ("price", "lineItemPrice", "priceBeforeDiscountsAndTax", "priceBeforeDiscounts"):
            value = DraftInvoiceService._extract_amount(raw_item.get(key))
            if value is not None:
                return value
        total = DraftInvoiceService._extract_amount(raw_item.get("totalPriceBeforeTax"))
        try:
            qty = max(1, int(raw_item.get("quantity") or 1))
        except (TypeError, ValueError):
            qty = 1
        if total is not None:
            return total / max(qty, 1)
        return 0.0

    @staticmethod
    def _extract_amount(value: object) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.replace(",", ".").strip()
            if not text:
                return None
            try:
                return float(text)
            except ValueError:
                return None
        if isinstance(value, dict):
            amount = value.get("amount")
            if amount is None:
                return None
            return DraftInvoiceService._extract_amount(amount)
        return None

    @staticmethod
    def _to_float(value: object) -> float:
        try:
            return float(str(value).strip().replace(",", "."))
        except (TypeError, ValueError):
            return 0.0
