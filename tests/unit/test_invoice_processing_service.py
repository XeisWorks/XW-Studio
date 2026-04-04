"""Tests for invoice processing service post-processing rules."""
from __future__ import annotations

import json

from xw_studio.core.config import AppConfig
from xw_studio.services.invoice_processing.service import InvoiceProcessingService
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary


class _InvoiceClientStub:
    def __init__(self, rows: list[InvoiceSummary]) -> None:
        self._rows = rows

    def list_invoice_summaries(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: int | None = None,
    ) -> list[InvoiceSummary]:
        return list(self._rows)


class _RepoStub:
    def __init__(self, data: dict[str, str]) -> None:
        self._data = data

    def get_value_json(self, key: str) -> str | None:
        return self._data.get(key)


class _WixOrdersStub:
    def __init__(self) -> None:
        self.calls = 0

    def has_credentials(self) -> bool:
        return True

    def resolve_order_address_lines(self, reference: str) -> list[str]:
        self.calls += 1
        if reference == "12345":
            return ["Wix Name", "Wix Strasse 1", "1010 Wien", "AT"]
        return []


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
