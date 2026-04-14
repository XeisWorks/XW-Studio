"""End-to-end test for legacy printing parity: invoice + label steps in fullflow."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, call, Mock

from xw_studio.core.config import AppConfig
from xw_studio.services.invoice_processing.service import (
    InvoiceProcessingService,
    FulfillmentFlags,
)
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary


class _InvoiceClientE2E:
    def __init__(self) -> None:
        self.render_calls: list[str] = []
        self.send_calls: list[tuple[str, str, bool]] = []

    def list_invoice_summaries(self, *, limit: int, offset: int, status: int | None = None):
        if offset > 0 or status != 100:
            return []
        return [
            InvoiceSummary(
                id="INV-001",
                invoice_number="R-001",
                contact_name="John Doe",
                address_country_code="AT",
            )
        ]

    def render_invoice_pdf(self, invoice_id: str) -> None:
        self.render_calls.append(invoice_id)

    def get_invoice_pdf(self, invoice_id: str) -> bytes:
        # Return fake PDF bytes (PDF header required by InvoicePrinter).
        return b"%PDF-1.4\ntest pdf content"

    def fetch_invoice_by_id(self, invoice_id: str) -> dict:
        return {
            "id": invoice_id,
            "invoiceNumber": "R-001",
            "name": "John Doe",
            "street": "Main St 1",
            "zip": "6020",
            "city": "Innsbruck",
            "addressCountryCode": "AT",
            "contact": {
                "name": "John Doe",
            },
        }

    def send_invoice_document(self, invoice_id: str, *, send_type: str, send_draft: bool) -> None:
        self.send_calls.append((invoice_id, send_type, send_draft))


class _WixOrdersDigitalOnlyStub:
    def has_credentials(self) -> bool:
        return True

    def resolve_order_address_lines(self, reference: str) -> list[str]:
        return []

    def is_reference_digital_only(self, reference: str) -> bool:
        return True


class _WixOrdersPhysicalStub:
    def has_credentials(self) -> bool:
        return True

    def resolve_order_address_lines(self, reference: str) -> list[str]:
        return ["John Doe", "Main St 1", "6020 Innsbruck", "AT"]

    def is_reference_digital_only(self, reference: str) -> bool:
        return False

    def get_fulfillable_items(self, reference: str) -> list[dict]:
        return [{"id": "line-1"}]

    def create_fulfillment(self, reference: str, items: list[dict]) -> dict:
        return {"id": "ful-1"}


class _SettingsRepoE2E:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get_value_json(self, key: str) -> str | None:
        return self.values.get(key)

    def set_value_json(self, key: str, value_json: str) -> None:
        self.values[key] = value_json


def test_invoice_print_step_uses_legacy_printer() -> None:
    """Verify that _run_invoice_print_step calls InvoicePrinter.print_pdf_bytes."""
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()

    service = InvoiceProcessingService(config, invoice_client, repo, None)

    # Patch both the actual printer dispatch AND configure a printer name.
    with patch("xw_studio.services.printing.invoice_printer.print_pdf_file_silent") as mock_print, \
         patch("xw_studio.services.printing.invoice_printer.InvoicePrinter._printer_name") as mock_printer_name:
        mock_printer_name.return_value = "TestPrinter"

        summary = InvoiceSummary(
            id="INV-001",
            invoice_number="R-001",
            contact_name="John Doe",
        )
        flags = FulfillmentFlags(invoice_printed=False)

        result = service._run_invoice_print_step(summary, flags)

        assert result.invoice_printed is True
        assert result.last_error == ""
        assert "INV-001" in invoice_client.render_calls
        # Verify that silent_printer.print_pdf_file_silent was called (blueprint backend).
        assert mock_print.called


def test_label_print_step_uses_shipping_address_fallback() -> None:
    """Verify that label address extraction uses shipping fields first, then billing."""
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()

    service = InvoiceProcessingService(config, invoice_client, repo, None)

    summary = InvoiceSummary(
        id="INV-001",
        invoice_number="R-001",
        contact_name="John Doe",
        display_country="AT",
    )

    # Full invoice with delivery fields.
    full_invoice = {
        "id": "INV-001",
        "name": "John Doe",
        "street": "Billing St 1",
        "zip": "1010",
        "city": "Wien",
        "addressCountryCode": "AT",
        "deliveryName": "Jane Doe",
        "deliveryStreet": "Delivery St 5",
        "deliveryZip": "6020",
        "deliveryCity": "Innsbruck",
        "deliveryAddressCountry": "AT",
    }

    lines = service._shipping_lines_from_invoice(full_invoice, summary)

    # Should use delivery fields, not billing.
    assert "Jane Doe" in lines  # delivery name, not billing name
    assert "Delivery St 5" in lines
    # Zip and city are combined into one line
    assert any("6020" in line for line in lines)  # delivery zip should be in some line


def test_label_print_step_falls_back_to_billing_when_no_delivery() -> None:
    """Verify fallback to billing address when no delivery fields."""
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()

    service = InvoiceProcessingService(config, invoice_client, repo, None)

    summary = InvoiceSummary(
        id="INV-002",
        invoice_number="R-002",
        contact_name="Fallback Name",
        display_country="DE",
    )

    # Invoice with only billing fields (no delivery).
    full_invoice = {
        "id": "INV-002",
        "name": "John Doe",
        "street": "Main St 1",
        "zip": "1010",
        "city": "Wien",
        "addressCountryCode": "AT",
    }

    lines = service._shipping_lines_from_invoice(full_invoice, summary)

    # Should use billing address.
    assert "John Doe" in lines
    assert "Main St 1" in lines
    # Zip and city are combined
    assert any("1010" in line for line in lines)


def test_fullflow_invoice_and_label_steps() -> None:
    """Verify that run_start_fullflow can execute both printing steps."""
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()

    service = InvoiceProcessingService(config, invoice_client, repo, None)

    with patch("xw_studio.services.printing.invoice_printer.print_pdf_file_silent") as mock_inv_print, \
         patch("xw_studio.services.printing.label_printer.LabelPrinter.print_address") as mock_label_print, \
         patch("xw_studio.services.printing.invoice_printer.InvoicePrinter._printer_name") as mock_printer_name, \
         patch("xw_studio.services.printing.label_printer.LabelPrinter._printer_name") as mock_label_printer_name:

        mock_printer_name.return_value = "TestPrinter"
        mock_label_printer_name.return_value = "TestLabelPrinter"

        result = service.run_start_fullflow(full_mode=True)

        assert result["processed"] == 1
        assert result["failures"] == 0
        assert mock_inv_print.called


def test_fullflow_skips_print_for_digital_only_wix_orders() -> None:
    """Digital-only Wix orders should be mailed/finalized without print or label output."""
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()
    wix_orders = _WixOrdersDigitalOnlyStub()

    service = InvoiceProcessingService(config, invoice_client, repo, wix_orders)

    invoice_client.list_invoice_summaries = lambda **_: [
        InvoiceSummary(
            id="INV-DIGI-001",
            invoice_number="R-DIGI-001",
            contact_name="John Doe",
            order_reference="WIX-12345",
        )
    ]

    with patch("xw_studio.services.printing.invoice_printer.print_pdf_file_silent") as mock_inv_print, \
         patch("xw_studio.services.printing.label_printer.LabelPrinter.print_address") as mock_label_print:
        result = service.run_start_fullflow(full_mode=True)

    assert result["processed"] == 1
    assert result["failures"] == 0
    assert result["successful"] == 1
    assert invoice_client.send_calls == [("INV-DIGI-001", "VM", False)]
    assert not mock_inv_print.called
    assert not mock_label_print.called


def test_start_fullflow_honors_abort_between_invoices() -> None:
    """Abort callback should stop the batch before starting the next invoice."""
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()

    service = InvoiceProcessingService(config, invoice_client, repo, None)

    invoice_client.list_invoice_summaries = lambda **kwargs: (
        [
            InvoiceSummary(id="INV-001", invoice_number="R-001", contact_name="John Doe"),
            InvoiceSummary(id="INV-002", invoice_number="R-002", contact_name="Jane Doe"),
        ]
        if kwargs.get("offset", 0) == 0 and kwargs.get("status") == 100
        else []
    )

    state = {"checks": 0}

    def should_abort() -> bool:
        state["checks"] += 1
        return state["checks"] > 1

    result = service.run_start_fullflow(full_mode=False, should_abort=should_abort)

    assert result["processed"] == 1
    assert result["successful"] == 1
    assert result["failures"] == 0
    assert result["aborted"] is True
    assert invoice_client.send_calls == [("INV-001", "VM", False)]


def test_print_label_for_invoice_uses_override_lines_and_persists_flag() -> None:
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()
    service = InvoiceProcessingService(config, invoice_client, repo, None)

    with patch("xw_studio.services.printing.label_printer.LabelPrinter.print_address") as mock_label_print:
        result = service.print_label_for_invoice(
            "INV-001",
            override_lines=["John Doe", "Edited Street 9", "6020 Innsbruck", "AT"],
        )

    mock_label_print.assert_called_once_with(["John Doe", "Edited Street 9", "6020 Innsbruck", "AT"])
    assert result.label_printed is True
    stored = repo.get_value_json("rechnungen.fulfillment_status") or ""
    assert "label_printed" in stored


def test_fulfillment_flags_persist_across_batch() -> None:
    """Verify that fulfillment flags are persisted when fullflow runs."""
    config = AppConfig()
    invoice_client = _InvoiceClientE2E()
    repo = _SettingsRepoE2E()

    service = InvoiceProcessingService(config, invoice_client, repo, None)

    flags = FulfillmentFlags(invoice_printed=True, last_run_iso="2026-04-04T09:00:00")
    service.write_fulfillment_flags("123", flags)

    loaded = service.read_fulfillment_flags("123")

    assert loaded.invoice_printed is True
    assert loaded.last_run_iso == "2026-04-04T09:00:00"
