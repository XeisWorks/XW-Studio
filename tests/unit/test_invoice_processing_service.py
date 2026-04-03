"""Tests for invoice processing service post-processing rules."""
from __future__ import annotations

import json

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
    svc = InvoiceProcessingService(_InvoiceClientStub(rows), repo)  # type: ignore[arg-type]

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
    svc = InvoiceProcessingService(_InvoiceClientStub(rows), None)  # type: ignore[arg-type]

    result = svc.load_invoice_summaries()

    assert result[0].is_sensitive_country is True
