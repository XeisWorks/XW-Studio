from __future__ import annotations

from pathlib import Path

from xw_studio.services.finanzonline.uva_payload_service import UvaPayloadService
from xw_studio.services.finanzonline.uva_preview import UvaPreviewService


class _FakeProvider:
    def load_sales_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return [
            {"taxText": "MIT 0% MEHRWERTSTEUER", "sumGross": "80.87", "sumNet": "80.87", "sumTax": "0.00"},
            {"taxText": "MIT 10% MEHRWERTSTEUER", "sumGross": "7909.60", "sumNet": "7191.06", "sumTax": "718.54"},
            {"taxText": "MIT 13% MEHRWERTSTEUER", "sumGross": "1793.73", "sumNet": "1587.37", "sumTax": "206.36"},
            {"taxText": "MIT 20% MEHRWERTSTEUER", "sumGross": "69.39", "sumNet": "57.83", "sumTax": "11.56"},
            {"taxText": "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG (EU)", "sumGross": "4825.18", "sumNet": "4825.18", "sumTax": "0.00"},
            {"taxText": "REVERSE CHARGE", "sumGross": "122.83", "sumNet": "122.83", "sumTax": "0.00"},
            {"taxText": "DEUTSCHE MWST. 7%", "sumGross": "2438.60", "sumNet": "2272.96", "sumTax": "165.64"},
            {"taxText": "ITALIENISCHE IVA 4%", "sumGross": "114.90", "sumNet": "110.47", "sumTax": "4.43"},
            {"taxText": "STEUERFREIE AUSFUHRLIEFERUNG (§ 7 USTG 1994)", "sumGross": "865.13", "sumNet": "865.13", "sumTax": "0.00"},
            {"taxText": "LUXEMBURGISCHE TVA 3%", "sumGross": "31.80", "sumNet": "30.87", "sumTax": "0.93"},
            {"taxText": "SCHWEDISCHE MOMS 6%", "sumGross": "24.80", "sumNet": "20.83", "sumTax": "3.97"},
        ]

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return [
            {"taxText": "MIT 0% MEHRWERTSTEUER", "sumGross": "2446.99", "sumNet": "2446.99", "sumTax": "0.00"},
            {"taxText": "MIT 10% MEHRWERTSTEUER", "sumGross": "1384.93", "sumNet": "1259.03", "sumTax": "125.90"},
            {"taxText": "MIT 20% MEHRWERTSTEUER", "sumGross": "1048.11", "sumNet": "873.43", "sumTax": "174.68"},
            {"taxText": "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG (EU)", "sumGross": "76.62", "sumNet": "76.62", "sumTax": "0.00"},
            {"taxText": "REVERSE CHARGE", "sumGross": "650.82", "sumNet": "650.82", "sumTax": "0.00"},
        ]


def test_phase1_preview_matches_expected_fixture() -> None:
    service = UvaPreviewService(_FakeProvider())
    preview = service.build_preview(2026, 3)
    rendered = service.render_preview_text(preview)

    fixture = Path(__file__).resolve().parents[1] / "expected" / "UVA 03-26.txt"
    expected = fixture.read_text(encoding="utf-8").strip()

    assert rendered.strip() == expected


def test_phase1_payload_contains_preview_text() -> None:
    service = UvaPreviewService(_FakeProvider())
    preview = service.build_preview(2026, 3)

    assert preview.sales.total_vat == "1111.43"
    assert preview.input_tax.total_vat == "300.58"
    assert len(preview.sales.groups) == 11


def test_phase2_builds_expected_kennzahlen() -> None:
    payload_service = UvaPayloadService(UvaPreviewService(_FakeProvider()))
    payload = payload_service.build_payload(2026, 3)

    assert payload.kennzahlen.A000 == "14649.40"
    assert payload.kennzahlen.A017 == "4825.18"
    assert payload.kennzahlen.A021 == "122.83"
    assert payload.kennzahlen.A011 == "865.13"
    assert payload.kennzahlen.A022 == "57.83"
    assert payload.kennzahlen.A029 == "7191.06"
    assert payload.kennzahlen.A006 == "1587.37"
    assert payload.kennzahlen.A057 == "130.16"
    assert payload.kennzahlen.B070 == "76.62"
    assert payload.kennzahlen.B072 == "76.62"
    assert payload.kennzahlen.C060 == "300.58"
    assert payload.kennzahlen.C065 == "15.32"
    assert payload.kennzahlen.C066 == "130.16"


def test_phase2_kennzahlen_text_mentions_zahllast() -> None:
    payload_service = UvaPayloadService(UvaPreviewService(_FakeProvider()))
    payload = payload_service.build_payload(2026, 3)
    text = payload_service.render_kennzahlen_text(payload)

    assert "A022" in text
    assert "C060" in text
    assert "Zahllast" in text


class _CashBasisSelectionProvider:
    def load_sales_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return [
            {
                "id": 1,
                "invoiceNumber": "RE-1",
                "status": "1000",
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "120.00",
                "sumNet": "100.00",
                "sumTax": "20.00",
                "paidDate": "2026-03-05",
            },
            {
                "id": 2,
                "invoiceNumber": "RE-2",
                "status": "1000",
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "120.00",
                "sumNet": "100.00",
                "sumTax": "20.00",
                "invoiceDate": "2026-03-06",
                "paidDate": "2026-04-02",
            },
            {
                "id": 3,
                "invoiceNumber": "RE-3",
                "status": "300",
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "120.00",
                "sumNet": "100.00",
                "sumTax": "20.00",
                "paidDate": "2026-03-15",
                "paidAmount": "60.00",
            },
            {
                "id": 4,
                "invoiceNumber": "RE-4",
                "status": "cancelled",
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "120.00",
                "sumNet": "100.00",
                "sumTax": "20.00",
                "invoiceDate": "2026-03-18",
                "cancelled": True,
            },
        ]

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return [
            {
                "id": 10,
                "voucherNumber": "ER-100",
                "supplierNameAtSave": "Supplier GmbH",
                "status": "paid",
                "creditDebit": "C",
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "120.00",
                "sumNet": "100.00",
                "sumTax": "20.00",
                "payDate": "2026-03-07",
            },
            {
                "id": 11,
                "voucherNumber": "ER-100",
                "supplierNameAtSave": "Supplier GmbH",
                "status": "paid",
                "creditDebit": "C",
                "taxText": "MIT 20% MEHRWERTSTEUER",
                "sumGross": "120.00",
                "sumNet": "100.00",
                "sumTax": "20.00",
                "payDate": "2026-03-08",
            },
        ]


def test_phase2_uses_cash_basis_partial_payments_and_dedupes_duplicates() -> None:
    payload_service = UvaPayloadService(UvaPreviewService(_CashBasisSelectionProvider()))
    payload = payload_service.build_payload(2026, 3)

    assert payload.kennzahlen.A022 == "150.00"
    assert payload.kennzahlen.C060 == "20.00"
    assert any("storniert" in warning.lower() for warning in payload.warnings)
    assert any("duplik" in warning.lower() for warning in payload.warnings)


class _PaidWithoutDateProvider:
    def load_sales_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return [
            {
                "id": 200,
                "invoiceNumber": "RE-FALLBACK-1",
                "status": "1000",
                "invoiceDate": "2026-03-10",
                "taxText": "MIT 10% MEHRWERTSTEUER",
                "sumGross": "110.00",
                "sumNet": "100.00",
                "sumTax": "10.00",
            }
        ]

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, object]]:
        assert (year, month) == (2026, 3)
        return []


def test_paid_like_document_without_paid_date_falls_back_to_period_date() -> None:
    payload_service = UvaPayloadService(UvaPreviewService(_PaidWithoutDateProvider()))
    payload = payload_service.build_payload(2026, 3)

    assert payload.kennzahlen.A029 == "100.00"
    assert any("belegdatum" in warning.lower() for warning in payload.warnings)
