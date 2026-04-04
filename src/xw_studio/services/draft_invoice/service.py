"""Create sevDesk invoice drafts from Wix order numbers."""
from __future__ import annotations

from datetime import date
import logging
from typing import Any

from xw_studio.services.http_client import SevdeskConnection
from xw_studio.services.sevdesk.contact_client import ContactClient
from xw_studio.services.sevdesk.part_client import PartClient
from xw_studio.services.wix.client import WixOrdersClient

logger = logging.getLogger(__name__)


class DraftInvoiceService:
    """Build and submit sevDesk invoice drafts from a Wix order number."""

    def __init__(
        self,
        connection: SevdeskConnection,
        wix_orders: WixOrdersClient,
        part_client: PartClient,
        contact_client: ContactClient,
    ) -> None:
        self._conn = connection
        self._wix_orders = wix_orders
        self._parts = part_client
        self._contacts = contact_client

    def create_draft_from_wix_order_number(self, wix_order_number: str) -> dict[str, str]:
        """Create an Entwurf in sevDesk from a Wix order number."""
        reference = str(wix_order_number or "").strip()
        if not reference:
            raise ValueError("Wix-Order-Nr fehlt.")

        if not self._wix_orders.has_credentials():
            raise ValueError("Wix API nicht konfiguriert (API-Key/Account/Site-ID fehlt).")

        order = self._wix_orders.resolve_order(reference)
        if not order:
            raise ValueError(f"Wix-Order '{reference}' wurde nicht gefunden.")

        order_number = str(order.get("number") or reference).strip()
        contact_id = self._resolve_or_create_contact(order)
        sev_user_id = self._resolve_default_sev_user_id()
        positions = self._build_positions(order_number)

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
            raise RuntimeError("sevDesk hat keinen Rechnungsentwurf zurückgegeben.")

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

        order = self._wix_orders.resolve_order(reference)
        if not order:
            raise ValueError(f"Wix-Order '{reference}' wurde nicht gefunden.")

        order_number = str(order.get("number") or reference).strip()
        items = self._wix_orders.fetch_order_line_items(order_number)
        if not items:
            raise ValueError("Wix-Order enthält keine Positionen.")

        missing_skus: list[str] = []
        preview_items: list[dict[str, str]] = []
        for item in items:
            sku = str(item.sku or "").strip()
            if not sku:
                missing_skus.append(f"(ohne SKU) {item.name}")
                preview_items.append(
                    {
                        "sku": "—",
                        "name": str(item.name or "").strip() or "(ohne Name)",
                        "qty": str(max(1, int(item.qty or 1))),
                        "status": "Nicht mappbar (SKU fehlt)",
                    }
                )
                continue
            part = self._parts.find_part_by_sku(sku)
            if part is None or not str(part.id).strip():
                missing_skus.append(sku)
                preview_items.append(
                    {
                        "sku": sku,
                        "name": str(item.name or "").strip() or sku,
                        "qty": str(max(1, int(item.qty or 1))),
                        "status": "Nicht mappbar (sevDesk-Part fehlt)",
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

        buyer_obj = order.get("buyerInfo")
        buyer: dict[str, Any] = buyer_obj if isinstance(buyer_obj, dict) else {}
        customer = " ".join(
            part for part in (str(buyer.get("firstName") or "").strip(), str(buyer.get("lastName") or "").strip()) if part
        ).strip()
        return {
            "wix_order_number": order_number,
            "customer": customer or "—",
            "email": str(buyer.get("email") or "").strip() or "—",
            "items": preview_items,
            "missing_skus": sorted(set(missing_skus)),
            "can_create": not bool(missing_skus),
        }

    def _build_positions(self, order_reference: str) -> list[dict[str, Any]]:
        wix_items = self._wix_orders.fetch_order_line_items(order_reference)
        if not wix_items:
            raise ValueError("Wix-Order enthält keine Positionen.")

        missing_skus: list[str] = []
        positions: list[dict[str, Any]] = []

        for index, item in enumerate(wix_items):
            sku = str(item.sku or "").strip()
            if not sku:
                missing_skus.append(f"(ohne SKU) {item.name}")
                continue
            part = self._parts.find_part_by_sku(sku)
            if part is None or not str(part.id).strip():
                missing_skus.append(sku)
                continue

            try:
                qty = max(1, int(item.qty))
            except (TypeError, ValueError):
                qty = 1
            price = self._to_float(part.price_eur)
            name = str(item.name or part.name or sku).strip()

            pos: dict[str, Any] = {
                "objectName": "InvoicePos",
                "mapAll": True,
                "unity": {"id": 1, "objectName": "Unity"},
                "taxRate": 19,
                "quantity": float(qty),
                "price": price,
                "name": name,
                "text": str(item.note or "").strip(),
                "positionNumber": index,
                "part": {"id": str(part.id), "objectName": "Part"},
            }
            positions.append(pos)

        if missing_skus:
            joined = ", ".join(sorted(set(missing_skus)))
            raise ValueError(
                "Rechnungsentwurf abgebrochen: folgende Wix-Produkte sind nicht eindeutig auf sevDesk-Artikel gemappt: "
                f"{joined}"
            )

        if not positions:
            raise ValueError("Rechnungsentwurf abgebrochen: keine gültigen Positionen gefunden.")
        return positions

    def _resolve_or_create_contact(self, order: dict[str, Any]) -> str:
        buyer_obj = order.get("buyerInfo")
        buyer: dict[str, Any] = buyer_obj if isinstance(buyer_obj, dict) else {}
        email = str(buyer.get("email") or "").strip().lower()

        if email:
            contacts = self._contacts.list_contacts(max_pages=20, depth=1)
            for contact in contacts:
                if str(contact.email or "").strip().lower() == email:
                    return str(contact.id)

        billing_obj = order.get("billingInfo")
        billing: dict[str, Any] = billing_obj if isinstance(billing_obj, dict) else {}
        contact_obj = billing.get("contactDetails")
        contact_details: dict[str, Any] = contact_obj if isinstance(contact_obj, dict) else {}
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
        billing_obj = order.get("billingInfo")
        billing: dict[str, Any] = billing_obj if isinstance(billing_obj, dict) else {}
        address_obj = billing.get("address")
        address: dict[str, Any] = address_obj if isinstance(address_obj, dict) else {}
        details_obj = billing.get("contactDetails")
        details: dict[str, Any] = details_obj if isinstance(details_obj, dict) else {}

        company = str(details.get("company") or "").strip()
        first = str(details.get("firstName") or "").strip()
        last = str(details.get("lastName") or "").strip()
        street = str(address.get("addressLine1") or address.get("street") or "").strip()
        zip_code = str(address.get("postalCode") or "").strip()
        city = str(address.get("city") or "").strip()
        country = str(address.get("country") or "").strip()

        line_name = company or " ".join(part for part in (first, last) if part).strip()
        lines = [line_name, street, " ".join(part for part in (zip_code, city) if part), country]
        return "\n".join(part for part in lines if part)

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
    def _to_float(value: object) -> float:
        try:
            return float(str(value).strip().replace(",", "."))
        except (TypeError, ValueError):
            return 0.0
