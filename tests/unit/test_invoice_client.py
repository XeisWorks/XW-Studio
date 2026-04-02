"""Tests for sevDesk invoice DTO parsing."""
import httpx

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
    assert row["Brutto EUR"] == "19.99"


def test_invoice_client_list_parses_objects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/Invoice")
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
    inv = InvoiceClient(client)
    rows = inv.list_invoice_summaries(embed_contact=False)
    assert len(rows) == 1
    assert rows[0].invoice_number == "A"
    assert rows[0].status_label() == "Bezahlt"
