"""Tests for invoice processing service post-processing rules."""
from __future__ import annotations

import json

from xw_studio.core.config import AppConfig
from xw_studio.services.invoice_processing.service import InvoiceProcessingService
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary


class _InvoiceClientStub:
    def __init__(self, rows: list[InvoiceSummary]) -> None:
        self._rows = rows
        self.render_calls: list[str] = []

    def list_invoice_summaries(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: int | None = None,
    ) -> list[InvoiceSummary]:
        return list(self._rows)

    def fetch_invoice_by_id(self, invoice_id: str) -> dict[str, object]:
        return {
            "id": invoice_id,
            "invoiceNumber": "RE-TEST-1",
            "name": "Max Mustermann",
            "contact": {"emails": [{"value": "max@example.test"}]},
        }

    def render_invoice_pdf(self, invoice_id: str) -> None:
        self.render_calls.append(invoice_id)

    def get_invoice_pdf(self, invoice_id: str) -> bytes:
        return b"%PDF-1.4\nstub"

    def send_invoice_document(self, invoice_id: str, *, send_type: str, send_draft: bool) -> None:
        self.last_send_document = {
            "invoice_id": invoice_id,
            "send_type": send_type,
            "send_draft": send_draft,
        }


class _RepoStub:
    def __init__(self, data: dict[str, str]) -> None:
        self._data = data

    def get_value_json(self, key: str) -> str | None:
        return self._data.get(key)

    def set_value_json(self, key: str, value_json: str) -> None:
        self._data[key] = value_json


class _WixOrdersStub:
    def __init__(self) -> None:
        self.calls = 0
        self._digital_only = False
        self._fulfillment_status = "NOT_FULFILLED"
        self._fulfillable_items: list[dict[str, str]] = []
        self._fulfillments: list[dict[str, str]] = []
        self.orders: dict[str, dict[str, object]] = {}

    def has_credentials(self) -> bool:
        return True

    def resolve_order_address_lines(self, reference: str) -> list[str]:
        self.calls += 1
        if reference == "12345":
            return ["Wix Name", "Wix Strasse 1", "1010 Wien", "AT"]
        return []

    def list_fulfillments(self, reference: str) -> list[dict[str, str]]:
        return list(self._fulfillments)

    def resolve_order_summary(self, reference: str) -> dict[str, str]:
        return {
            "wix_customer_email": "wix@example.test",
            "wix_customer_name": "Wix Name",
        }

    def resolve_order(self, reference: str) -> dict[str, object]:
        return dict(self.orders.get(reference, {}))

    @staticmethod
    def shipping_address_lines_from_order(order: dict[str, object]) -> list[str]:
        value = order.get("shipping_lines")
        return list(value) if isinstance(value, list) else []

    @staticmethod
    def billing_address_lines_from_order(order: dict[str, object]) -> list[str]:
        value = order.get("billing_lines")
        return list(value) if isinstance(value, list) else []

    def is_reference_digital_only(self, reference: str) -> bool:
        return self._digital_only

    def get_fulfillable_items(self, reference: str) -> list[dict[str, str]]:
        return list(self._fulfillable_items)

    def create_fulfillment(self, reference: str, items: list[dict[str, str]]) -> dict[str, str]:
        return {"id": "fulfillment-1"} if items else {}

    def fulfillment_status(self, reference: str) -> str:
        return self._fulfillment_status


class _MailServiceStub:
    def __init__(self, *, configured: bool = True) -> None:
        self.configured = configured
        self.calls: list[dict[str, object]] = []

    def is_configured(self) -> bool:
        return self.configured

    @staticmethod
    def plain_text_to_html(value: str) -> str:
        return "<p>" + value.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"

    def send_mail(
        self,
        *,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str = "",
        attachments: list[object] | None = None,
    ) -> None:
        self.calls.append(
            {
                "to_email": to_email,
                "subject": subject,
                "text_body": text_body,
                "html_body": html_body,
                "attachments": list(attachments or []),
            }
        )


class _DraftServiceStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def repair_draft_product_mapping(self, invoice_id: str, wix_order_number: str) -> bool:
        self.calls.append((invoice_id, wix_order_number))
        return True


def test_sensitive_country_override_from_settings() -> None:
    rows = [
        InvoiceSummary(
            id="1",
            invoice_number="R-1",
            address_country_code="AT",
            delivery_country_code="KP",
            is_sensitive_country=False,
        )
    ]
    repo = _RepoStub({"rechnungen.sensitive_country_codes": json.dumps(["AT"])})
    svc = InvoiceProcessingService(AppConfig(), _InvoiceClientStub(rows), repo)  # type: ignore[arg-type]

    result = svc.load_invoice_summaries()

    assert len(result) == 1
    assert result[0].is_sensitive_country is True


def test_sensitive_country_falls_back_to_default_list() -> None:
    rows = [
        InvoiceSummary(
            id="2",
            invoice_number="R-2",
            address_country_code="RU",
            is_sensitive_country=False,
        )
    ]
    svc = InvoiceProcessingService(AppConfig(), _InvoiceClientStub(rows), None)  # type: ignore[arg-type]

    result = svc.load_invoice_summaries()

    assert result[0].is_sensitive_country is True


def test_unreleased_sku_flags_from_settings() -> None:
    rows = [
        InvoiceSummary(
            id="3",
            invoice_number="R-3",
            order_reference="WIX XW-6-003",
            has_unreleased_sku=False,
        )
    ]
    repo = _RepoStub(
        {
            "rechnungen.sku_flags": json.dumps(
                {
                    "exact": ["XW-123"],
                    "prefixes": ["XW-6"],
                }
            )
        }
    )
    svc = InvoiceProcessingService(AppConfig(), _InvoiceClientStub(rows), repo)  # type: ignore[arg-type]

    result = svc.load_invoice_summaries()

    assert len(result) == 1
    assert result[0].has_unreleased_sku is True


def test_unreleased_sku_flags_fall_back_to_defaults() -> None:
    rows = [
        InvoiceSummary(
            id="4",
            invoice_number="R-4",
            order_reference="XW-010",
            has_unreleased_sku=False,
        )
    ]
    svc = InvoiceProcessingService(AppConfig(), _InvoiceClientStub(rows), None)  # type: ignore[arg-type]

    result = svc.load_invoice_summaries()

    assert result[0].has_unreleased_sku is True


def test_shipping_lines_prefer_wix_when_available() -> None:
    summary = InvoiceSummary(id="5", invoiceNumber="R-5", order_reference="12345")
    wix = _WixOrdersStub()
    svc = InvoiceProcessingService(
        AppConfig(),
        _InvoiceClientStub([summary]),  # type: ignore[arg-type]
        None,
        wix,  # type: ignore[arg-type]
    )

    lines = svc._shipping_lines_from_invoice({}, summary)  # noqa: SLF001

    assert lines == ["Wix Name", "Wix Strasse 1", "1010 Wien", "AT"]
    assert wix.calls == 1


def test_shipping_lines_use_wix_cache_for_same_reference() -> None:
    summary = InvoiceSummary(id="6", invoiceNumber="R-6", order_reference="12345")
    wix = _WixOrdersStub()
    svc = InvoiceProcessingService(
        AppConfig(),
        _InvoiceClientStub([summary]),  # type: ignore[arg-type]
        None,
        wix,  # type: ignore[arg-type]
    )

    first = svc._shipping_lines_from_invoice({}, summary)  # noqa: SLF001
    second = svc._shipping_lines_from_invoice({}, summary)  # noqa: SLF001

    assert first == second
    assert wix.calls == 1


def test_mail_step_uses_saved_template_when_available() -> None:
    summary = InvoiceSummary(id="7", invoiceNumber="RE-TEST-1", contact_name="Max Mustermann")
    client = _InvoiceClientStub([summary])
    mailer = _MailServiceStub()
    repo = _RepoStub(
        {
            "rechnungen.fulfillment_mail_subject": "Rechnung {{invoice_number}}",
            "rechnungen.fulfillment_mail_template_html": "Hallo {{customer_name}},\n\nRE={{invoice_number}}",
        }
    )
    svc = InvoiceProcessingService(AppConfig(), client, repo, None, mailer)  # type: ignore[arg-type]

    flags = svc._run_mail_step(summary, svc.read_fulfillment_flags("7"))  # noqa: SLF001

    assert flags.mail_sent is True
    assert mailer.calls[0]["to_email"] == "max@example.test"
    assert mailer.calls[0]["subject"] == "Rechnung RE-TEST-1"
    assert "Hallo Max Mustermann" in str(mailer.calls[0]["text_body"])
    attachments = mailer.calls[0]["attachments"]
    assert len(attachments) == 1
    assert getattr(attachments[0], "filename", "") == "RE-TEST-1.pdf"
    assert client.render_calls == ["7"]


def test_mail_step_honors_recipient_override() -> None:
    summary = InvoiceSummary(id="8", invoiceNumber="RE-TEST-2", contact_name="Max Mustermann")
    client = _InvoiceClientStub([summary])
    mailer = _MailServiceStub()
    svc = InvoiceProcessingService(AppConfig(), client, _RepoStub({}), None, mailer)  # type: ignore[arg-type]

    flags = svc._run_mail_step(  # noqa: SLF001
        summary,
        svc.read_fulfillment_flags("8"),
        recipient_override="bernhard.holl@gmx.at",
    )

    assert flags.mail_sent is True
    assert mailer.calls[0]["to_email"] == "bernhard.holl@gmx.at"


def test_product_step_marks_digital_fulfilled_without_warning() -> None:
    summary = InvoiceSummary(id="9", invoiceNumber="RE-TEST-9", order_reference="12345")
    wix = _WixOrdersStub()
    wix._digital_only = True
    wix._fulfillment_status = "FULFILLED"
    svc = InvoiceProcessingService(
        AppConfig(),
        _InvoiceClientStub([summary]),  # type: ignore[arg-type]
        None,
        wix,  # type: ignore[arg-type]
    )

    flags = svc._run_product_step(summary, svc.read_fulfillment_flags("9"))  # noqa: SLF001

    assert flags.product_ready is True
    assert flags.wix_fulfilled is True
    assert flags.last_warning == ""


def test_product_step_returns_warning_for_unconfirmed_physical_fulfillment() -> None:
    summary = InvoiceSummary(id="10", invoiceNumber="RE-TEST-10", order_reference="54321")
    wix = _WixOrdersStub()
    svc = InvoiceProcessingService(
        AppConfig(),
        _InvoiceClientStub([summary]),  # type: ignore[arg-type]
        None,
        wix,  # type: ignore[arg-type]
    )

    flags = svc._run_product_step(summary, svc.read_fulfillment_flags("10"))  # noqa: SLF001

    assert flags.product_ready is True
    assert flags.wix_fulfilled is False
    assert "Wix-Fulfillment nicht bestaetigt" in flags.last_warning


def test_invoice_list_hints_follow_legacy_alarm_rules() -> None:
    wix = _WixOrdersStub()
    wix.orders["20519"] = {
        "buyerNote": "Bitte rasch liefern",
        "shipping_lines": ["Max Muster", "Via Roma 1", "00100 Rom", "Italy"],
        "billing_lines": ["Max Muster", "Hauptplatz 1", "8010 Graz", "Austria"],
        "lineItems": [
            {"physicalProperties": {"sku": "XW-700.1"}},
            {"physicalProperties": {"sku": "XW-100"}},
        ],
    }
    repo = _RepoStub(
        {
            "rechnungen.allowed_country_codes": json.dumps(["Austria", "Germany"]),
            "rechnungen.sku_flags": json.dumps({"exact": ["XW-010"], "prefixes": ["XW-7"]}),
        }
    )
    svc = InvoiceProcessingService(
        AppConfig(),
        _InvoiceClientStub([]),  # type: ignore[arg-type]
        repo,
        wix,  # type: ignore[arg-type]
    )

    hints = svc.resolve_invoice_list_hints("20519")

    assert hints.buyer_note == "Bitte rasch liefern"
    assert hints.address_mismatch is True
    assert hints.unreleased_sku is True
    assert hints.country_invalid is True
    assert hints.icon_keys() == ["print", "printondemand", "alternateshippingaddress", "country"]
    assert "Lieferland außerhalb Freigabe" in hints.tooltip()


def test_start_fullflow_repairs_draft_products_before_finalize() -> None:
    summary = InvoiceSummary(id="11", invoiceNumber="RE-TEST-11", order_reference="20519")
    client = _InvoiceClientStub([summary])
    wix = _WixOrdersStub()
    mailer = _MailServiceStub()
    drafts = _DraftServiceStub()
    svc = InvoiceProcessingService(
        AppConfig(),
        client,  # type: ignore[arg-type]
        _RepoStub({}),
        wix,  # type: ignore[arg-type]
        mailer,  # type: ignore[arg-type]
        drafts,  # type: ignore[arg-type]
    )

    result = svc.run_start_fullflow(full_mode=False)

    assert result["successful"] == 1
    assert drafts.calls == [("11", "20519")]
    assert client.last_send_document["invoice_id"] == "11"
    assert mailer.calls[0]["to_email"] == "wix@example.test"
