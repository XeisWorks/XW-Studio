from __future__ import annotations

from typing import Any

from xw_studio.services.wix.client import WixOrdersClient


def test_pick_exact_order_match_uses_exact_number() -> None:
    orders: list[dict[str, Any]] = [
        {"id": "a", "number": "20463"},
        {"id": "b", "number": "20460"},
    ]

    picked = WixOrdersClient._pick_exact_order_match("20460", orders)  # noqa: SLF001

    assert picked.get("id") == "b"


def test_line_item_is_digital_detects_wix_item_type_flags() -> None:
    assert WixOrdersClient.line_item_is_digital({"itemType": {"preset": "DIGITAL"}})
    assert WixOrdersClient.line_item_is_digital({"physicalProperties": {"shippable": False}})
    assert WixOrdersClient.line_item_is_digital({"productType": "digital"})
    assert not WixOrdersClient.line_item_is_digital({"itemType": {"preset": "PHYSICAL"}})


def test_is_reference_digital_only_checks_all_line_items() -> None:
    class _Client(WixOrdersClient):
        def __init__(self) -> None:
            pass

        def _resolve_order(self, reference: str) -> dict[str, Any]:
            if reference == "all-digital":
                return {
                    "lineItems": [
                        {"itemType": {"preset": "DIGITAL"}},
                        {"physicalProperties": {"shippable": "false"}},
                    ]
                }
            if reference == "mixed":
                return {
                    "lineItems": [
                        {"itemType": {"preset": "DIGITAL"}},
                        {"itemType": {"preset": "PHYSICAL"}},
                    ]
                }
            return {}

    client = _Client()

    assert client.is_reference_digital_only("all-digital") is True
    assert client.is_reference_digital_only("mixed") is False
    assert client.is_reference_digital_only("missing") is False


def test_best_address_lines_prefers_shipping_then_billing() -> None:
    order_shipping = {
        "buyerInfo": {"firstName": "Max", "lastName": "Mustermann"},
        "shippingInfo": {
            "shippingDestination": {
                "addressLine1": "Musterstrasse 1",
                "postalCode": "1010",
                "city": "Wien",
                "country": "AT",
            }
        },
        "billingInfo": {
            "contactDetails": {"company": "Fallback GmbH"},
            "address": {"addressLine1": "Fallbackweg 9"},
        },
    }
    lines = WixOrdersClient.best_address_lines_from_order(order_shipping)
    assert lines[0] == "Max Mustermann"
    assert "Musterstrasse 1" in lines
    assert "Austria" in lines

    order_billing_only = {
        "billingInfo": {
            "contactDetails": {"company": "Billing GmbH"},
            "address": {
                "addressLine1": "Rechnungsweg 7",
                "postalCode": "5020",
                "city": "Salzburg",
                "country": "AT",
            },
        }
    }
    lines2 = WixOrdersClient.best_address_lines_from_order(order_billing_only)
    assert lines2[0] == "Billing GmbH"
    assert "Rechnungsweg 7" in lines2
    assert "Austria" in lines2


def test_best_address_lines_supports_nested_shipping_address_variants() -> None:
    order = {
        "shippingInfo": {
            "shipmentDetails": {
                "firstName": "Jakob",
                "lastName": "Aichberger",
            },
            "shippingDestination": {
                "address": {
                    "addressLine1": "Wolfsbacher Straße 12",
                    "postalCode": "3354",
                    "city": "Wolfsbach",
                    "countryCode": "AT",
                }
            },
        }
    }

    lines = WixOrdersClient.best_address_lines_from_order(order)

    assert lines == [
        "Jakob Aichberger",
        "Wolfsbacher Straße 12",
        "3354 Wolfsbach",
        "Austria",
    ]


def test_best_address_lines_merges_structured_street_address_number() -> None:
    order = {
        "buyerInfo": {"firstName": "Florian", "lastName": "Brandner"},
        "shippingInfo": {
            "shippingDestination": {
                "streetAddress": {"name": "Auerdörfl", "number": "16", "apt": ""},
                "postalCode": "20038",
                "city": "Berchtesgaden",
                "countryCode": "DE",
            }
        },
        "billingInfo": {
            "address": {
                "streetAddress": {"name": "Auerdörfl", "number": "16"},
                "postalCode": "20038",
                "city": "Berchtesgaden",
                "countryCode": "DE",
            }
        },
    }

    lines = WixOrdersClient.best_address_lines_from_order(order)

    assert lines == [
        "Florian Brandner",
        "Auerdörfl 16",
        "20038 Berchtesgaden",
        "Germany",
    ]
