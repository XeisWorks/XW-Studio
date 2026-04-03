"""Tests for sevDesk invoice DTO parsing."""
import httpx

from xw_studio.core.config import AppConfig
from xw_studio.services.http_client import SevdeskConnection
from xw_studio.services.sevdesk.invoice_client import InvoiceClient, InvoiceSummary


def test_invoice_summary_from_api_object() -> None:
    raw = {
        "id": 12,
        "invoiceNumber": "R-99",
        "invoiceDate": "2024-03-01",
        "status": "200",
        "sumGross": 19.99,
        "contact": {"name": "Test GmbH"},
    }
    summary = InvoiceSummary.from_api_object(raw)
    assert summary.id == "12"
    assert summary.invoice_number == "R-99"
    assert summary.status_code == 200
    assert summary.contact_name == "Test GmbH"
    row = summary.as_table_row()
    assert row["Rechnungsnr."] == "R-99"
    assert row["Status"] == "Offen"
    assert row["Datum"] == "01.03.2024"
    assert row["Brutto"] == "19,99 €"
    assert "Test GmbH" in summary.detail_lines()
    assert summary.formatted_date == "01.03.2024"
    assert "19,99 €" in summary.formatted_brutto


def test_invoice_summary_flags_delivery_override_and_sensitive_country() -> None:
    raw = {
        "id": 99,
        "invoiceNumber": "R-100",
        "invoiceDate": "2024-04-01",
        "status": 200,
        "sumGross": 49.0,
        "contact": {"name": "Risk Co"},
        "addressCountry": {"code": "RU"},
        "street": "Alpha 1",
        "zip": "1010",
        "city": "Wien",
        "deliveryStreet": "Beta 9",
        "deliveryZip": "9999",
        "deliveryCity": "Berlin",
        "buyerNote": "Bitte ohne Klingeln",
    }

    summary = InvoiceSummary.from_api_object(raw)
    assert summary.has_delivery_address_override is True
    assert summary.is_sensitive_country is True
    row = summary.as_table_row()
    assert row["Notiz"] == "🔴"
    assert row["Lieferabw."] == "🔴"
    assert row["Heikles Land"] == "🔴"
    assert row["__tooltip__Notiz"] == "Bitte ohne Klingeln"
    assert "Heikles Zielland" in row["__tooltip__Heikles Land"]
    details = summary.detail_lines()
    assert "Lieferanschrift: abweichend" in details
    assert "Achtung: heikles Land" in details


def test_invoice_client_list_parses_objects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/Invoice" in str(request.url)
        body = {
            "objects": [
                {
                    "id": 1,
                    "invoiceNumber": "A",
                    "invoiceDate": "2024-01-01",
                    "status": 1000,
                    "sumGross": "10",
                    "contact": {"name": "ACME"},
                }
            ]
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://example.test/api/v1")
    cfg = AppConfig()
    conn = SevdeskConnection(client=client, config=cfg)
    inv = InvoiceClient(conn)
    rows = inv.list_invoice_summaries(embed_contact=False)
    assert len(rows) == 1
    assert rows[0].invoice_number == "A"
    assert rows[0].status_label() == "Bezahlt"
