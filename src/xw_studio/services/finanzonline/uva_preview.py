"""Phase 1 UVA preview: legacy-style VAT summary grouped by tax labels."""
from __future__ import annotations

import logging
import re
from collections import OrderedDict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Protocol

from pydantic import BaseModel, Field

from xw_studio.services.finanzonline.uva_selection import (
    UvaDocumentSelector,
    UvaSelectionStats,
)
from xw_studio.services.http_client import SevdeskConnection

logger = logging.getLogger(__name__)

_DECIMAL_2 = Decimal("0.01")
_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_FOREIGN_MARKERS = (
    "DEUTSCHE",
    "ITALIENISCHE",
    "SPANISCHE",
    "FRANZÖSISCHE",
    "FRANZOESISCHE",
    "LUXEMBURGISCHE",
    "SCHWEDISCHE",
    "NIEDERLÄNDISCHE",
    "NIEDERLAENDISCHE",
    "BELGISCHE",
    "FINNISCHE",
    "DÄNISCHE",
    "DAENISCHE",
    "SLOWENISCHE",
    "TSCHECHISCHE",
    "IVA",
    "TVA",
    "MOMS",
    "BTW",
    "PVM",
    "DPH",
    "DDV",
)


class UvaPreviewGroup(BaseModel):
    """One VAT group shown in the preview."""

    label: str
    vat_amount: str
    gross_amount: str
    net_amount: str


class UvaPreviewSection(BaseModel):
    """Sales or input-tax preview section."""

    total_vat: str
    total_gross: str
    total_net: str
    groups: list[UvaPreviewGroup] = Field(default_factory=list)


class UvaPreviewResult(BaseModel):
    """Human-readable phase-1 preview model."""

    year: int
    month: int
    sales: UvaPreviewSection
    input_tax: UvaPreviewSection
    sales_stats: UvaSelectionStats = Field(default_factory=UvaSelectionStats)
    input_tax_stats: UvaSelectionStats = Field(default_factory=UvaSelectionStats)
    warnings: list[str] = Field(default_factory=list)


class UvaPreviewProvider(Protocol):
    """Abstract source for preview documents."""

    def load_sales_documents(self, year: int, month: int) -> list[dict[str, Any]]:
        ...

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, Any]]:
        ...


class SevdeskUvaPreviewProvider:
    """Best-effort preview provider using sevDesk list endpoints."""

    def __init__(
        self,
        connection: SevdeskConnection,
        *,
        page_size: int = 250,
        max_pages: int = 12,
    ) -> None:
        self._connection = connection
        self._page_size = page_size
        self._max_pages = max_pages
        self._payment_cache: dict[tuple[str, str, int, int], tuple[str | None, str | None]] = {}

    def load_sales_documents(self, year: int, month: int) -> list[dict[str, Any]]:
        docs = self._load_resource("/Invoice")
        result: list[dict[str, Any]] = []
        for doc in docs:
            if not self._is_period_match(doc, year, month, ("paidDate", "invoiceDate", "date")):
                continue
            status = str(doc.get("status") or "").strip()
            if status and status not in {"1000", "300", "750"} and not doc.get("paidDate"):
                continue
            result.append(self._enrich_payment_metadata("Invoice", doc, year, month))
        return result

    def load_purchase_documents(self, year: int, month: int) -> list[dict[str, Any]]:
        docs = self._load_resource("/Voucher")
        result: list[dict[str, Any]] = []
        for doc in docs:
            if not self._is_period_match(doc, year, month, ("payDate", "voucherDate", "date")):
                continue
            credit_debit = str(doc.get("creditDebit") or "").upper().strip()
            if credit_debit and credit_debit != "C":
                continue
            result.append(self._enrich_payment_metadata("Voucher", doc, year, month))
        return result

    def _load_resource(self, path: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        offset = 0
        for _ in range(self._max_pages):
            response = self._connection.get(path, params={"limit": self._page_size, "offset": offset})
            payload = response.json()
            objects = payload.get("objects")
            if not isinstance(objects, list) or not objects:
                break
            result.extend(obj for obj in objects if isinstance(obj, dict))
            if len(objects) < self._page_size:
                break
            offset += self._page_size
        return result

    def _enrich_payment_metadata(
        self,
        resource: str,
        document: dict[str, Any],
        year: int,
        month: int,
    ) -> dict[str, Any]:
        if document.get("paidDate") or document.get("payDate"):
            return document
        if not _looks_paid_like(document):
            return document
        doc_id = document.get("id")
        if doc_id in (None, ""):
            return document

        cache_key = (resource, str(doc_id), year, month)
        if cache_key not in self._payment_cache:
            self._payment_cache[cache_key] = self._load_payment_metadata(resource, str(doc_id), year, month)
        payment_date, paid_amount = self._payment_cache[cache_key]
        if payment_date is None and paid_amount is None:
            return document

        enriched = dict(document)
        if payment_date is not None:
            enriched["xw_payment_date"] = payment_date
        if paid_amount is not None:
            enriched["xw_paid_amount"] = paid_amount
        return enriched

    def _load_payment_metadata(self, resource: str, doc_id: str, year: int, month: int) -> tuple[str | None, str | None]:
        events: list[dict[str, Any]] = []
        for suffix in ("getCheckAccountTransactionLogs", "getCheckAccountTransactions"):
            try:
                response = self._connection.get(f"/{resource}/{doc_id}/{suffix}")
                payload = response.json()
            except Exception as exc:
                logger.debug("Payment metadata lookup failed for %s/%s via %s: %s", resource, doc_id, suffix, exc)
                continue
            objects = payload.get("objects") if isinstance(payload, dict) else None
            if isinstance(objects, list):
                events.extend(item for item in objects if isinstance(item, dict))

        if not events:
            return None, None

        any_payment_date: datetime | None = None
        period_payment_date: datetime | None = None
        period_paid_amount = Decimal("0.00")

        for event in events:
            event_date = _extract_payment_event_date(event)
            if event_date is not None and (any_payment_date is None or event_date > any_payment_date):
                any_payment_date = event_date
            if event_date is None or event_date.year != year or event_date.month != month:
                continue
            if period_payment_date is None or event_date > period_payment_date:
                period_payment_date = event_date
            amount = _extract_payment_event_amount(event)
            if amount > Decimal("0.00"):
                period_paid_amount += amount

        payment_date = period_payment_date or any_payment_date
        payment_date_text = payment_date.isoformat() if payment_date is not None else None
        paid_amount_text = _format_plain(period_paid_amount) if period_paid_amount > Decimal("0.00") else None
        return payment_date_text, paid_amount_text

    @staticmethod
    def _is_period_match(
        document: dict[str, Any],
        year: int,
        month: int,
        date_keys: tuple[str, ...],
    ) -> bool:
        for key in date_keys:
            value = document.get(key)
            dt = _parse_date(value)
            if dt is not None and dt.year == year and dt.month == month:
                return True
        return False


class UvaPreviewService:
    """Build a legacy-like grouped VAT preview for the selected month."""

    def __init__(
        self,
        provider: UvaPreviewProvider | None = None,
        selector: UvaDocumentSelector | None = None,
    ) -> None:
        self._provider = provider
        self._selector = selector or UvaDocumentSelector()

    def build_preview(self, year: int, month: int) -> UvaPreviewResult:
        sales_docs = self._provider.load_sales_documents(year, month) if self._provider is not None else []
        purchase_docs = self._provider.load_purchase_documents(year, month) if self._provider is not None else []
        sales_selection = self._selector.select_sales_documents(year, month, sales_docs)
        purchase_selection = self._selector.select_purchase_documents(year, month, purchase_docs)
        return UvaPreviewResult(
            year=year,
            month=month,
            sales=self._build_section(sales_selection.documents),
            input_tax=self._build_section(purchase_selection.documents),
            sales_stats=sales_selection.stats,
            input_tax_stats=purchase_selection.stats,
            warnings=[*sales_selection.warnings, *purchase_selection.warnings],
        )

    def render_preview_text(self, preview: UvaPreviewResult) -> str:
        sales_lines = self._render_section(
            title="Mehrwertsteuer",
            tax_label="Mehrwertsteuer",
            section=preview.sales,
        )
        input_lines = self._render_section(
            title="Vorsteuer",
            tax_label="Vorsteuer",
            section=preview.input_tax,
        )
        lines = sales_lines + ["", ""] + input_lines
        if preview.warnings:
            lines.extend(["", "", "Hinweise:"])
            lines.extend(f"- {warning}" for warning in preview.warnings)
        return "\n".join(lines).strip()

    def _build_section(self, documents: list[dict[str, Any]]) -> UvaPreviewSection:
        groups: OrderedDict[str, dict[str, Decimal]] = OrderedDict()
        total_vat = Decimal("0.00")
        total_gross = Decimal("0.00")
        total_net = Decimal("0.00")

        for document in documents:
            gross_amount, net_amount, vat_amount = _extract_amounts(document)
            label = _normalize_tax_label(document, net_amount=net_amount, vat_amount=vat_amount)
            bucket = groups.setdefault(
                label,
                {"vat": Decimal("0.00"), "gross": Decimal("0.00"), "net": Decimal("0.00")},
            )
            bucket["vat"] += vat_amount
            bucket["gross"] += gross_amount
            bucket["net"] += net_amount
            total_vat += vat_amount
            total_gross += gross_amount
            total_net += net_amount

        group_models = [
            UvaPreviewGroup(
                label=label,
                vat_amount=_format_plain(values["vat"]),
                gross_amount=_format_plain(values["gross"]),
                net_amount=_format_plain(values["net"]),
            )
            for label, values in groups.items()
        ]
        return UvaPreviewSection(
            total_vat=_format_plain(total_vat),
            total_gross=_format_plain(total_gross),
            total_net=_format_plain(total_net),
            groups=group_models,
        )

    @staticmethod
    def _render_section(title: str, tax_label: str, section: UvaPreviewSection) -> list[str]:
        lines = [
            title,
            f"EUR {_format_euro_text(section.total_vat)}",
            "",
            f"Brutto: EUR {_format_euro_text(section.total_gross)}",
            f"Netto: EUR {_format_euro_text(section.total_net)}",
        ]
        for group in section.groups:
            lines.extend(["", group.label])
            is_sales_ig_delivery = (
                title == "Mehrwertsteuer"
                and "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG" in group.label
            )
            if is_sales_ig_delivery:
                lines.append(f"Netto: EUR {_format_euro_text(group.net_amount)}")
                continue
            lines.extend(
                [
                    f"{tax_label}: EUR {_format_euro_text(group.vat_amount)}",
                    f"Brutto: EUR {_format_euro_text(group.gross_amount)}",
                    f"Netto: EUR {_format_euro_text(group.net_amount)}",
                ]
            )
        return lines


def _looks_paid_like(document: dict[str, Any]) -> bool:
    status = str(document.get("status") or document.get("statusText") or "").strip().lower()
    if status in {"300", "750", "1000", "paid", "bezahlt", "partial", "teilweise"}:
        return True
    for key in ("paid", "isPaid", "partiallyPaid", "isPartiallyPaid"):
        value = document.get(key)
        if isinstance(value, bool) and value:
            return True
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "ja"}:
            return True
    return False


def _extract_payment_event_date(event: dict[str, Any]) -> datetime | None:
    for key in ("bookingDate", "valueDate", "entryDate", "date", "create"):
        dt = _parse_date(event.get(key))
        if dt is not None:
            return dt
    return None


def _extract_payment_event_amount(event: dict[str, Any]) -> Decimal:
    for key in ("amountPaid", "amount", "value"):
        amount = _to_decimal(event.get(key))
        if amount > Decimal("0.00"):
            return amount
    return Decimal("0.00")


def _to_decimal(value: object) -> Decimal:
    if value in (None, ""):
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value.quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
    try:
        text = str(value).strip().replace(" ", "").replace(",", ".")
        return Decimal(text).quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _format_plain(value: Decimal) -> str:
    return f"{value.quantize(_DECIMAL_2, rounding=ROUND_HALF_UP):.2f}"


def _format_euro_text(value: str) -> str:
    amount = _to_decimal(value)
    formatted = f"{amount:,.2f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", " ")


def _parse_date(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            continue
    return None


def _extract_amounts(document: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal]:
    gross_amount = _first_decimal(document, "sumGross", "sumGrossAccounting", "sumGrossForeignCurrency")
    net_amount = _first_decimal(document, "sumNet", "sumNetAccounting")
    vat_amount = _first_decimal(document, "sumTax", "sumTaxAccounting")

    if net_amount == Decimal("0.00") and gross_amount != Decimal("0.00"):
        net_amount = gross_amount - vat_amount
    if vat_amount == Decimal("0.00") and gross_amount != Decimal("0.00") and net_amount != Decimal("0.00"):
        vat_amount = gross_amount - net_amount
    return gross_amount, net_amount, vat_amount


def _first_decimal(document: dict[str, Any], *keys: str) -> Decimal:
    for key in keys:
        if key in document and document.get(key) not in (None, ""):
            return _to_decimal(document.get(key))
    return Decimal("0.00")


def _normalize_tax_label(document: dict[str, Any], *, net_amount: Decimal, vat_amount: Decimal) -> str:
    raw = " ".join(str(document.get("taxText") or "").split()).strip()
    if raw:
        upper = raw.upper()
        if "REVERSE" in upper and "CHARGE" in upper:
            return "REVERSE CHARGE"
        if "INNERGEMEINSCHAFT" in upper and "LIEFER" in upper:
            return "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG (EU)"
        if "AUSFUHR" in upper:
            return "STEUERFREIE AUSFUHRLIEFERUNG (§ 7 USTG 1994)"
        if any(marker in upper for marker in _FOREIGN_MARKERS):
            return upper
        rate = _extract_percent(upper)
        if rate is not None:
            return f"MIT {rate}% MEHRWERTSTEUER"
        return upper

    inferred_rate = _infer_rate(net_amount, vat_amount)
    return f"MIT {inferred_rate}% MEHRWERTSTEUER"


def _extract_percent(label: str) -> int | None:
    match = _PERCENT_RE.search(label)
    if match is None:
        return None
    try:
        value = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    if value == value.to_integral_value():
        return int(value)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _infer_rate(net_amount: Decimal, vat_amount: Decimal) -> int:
    if net_amount == Decimal("0.00") or vat_amount == Decimal("0.00"):
        return 0
    ratio = (vat_amount / net_amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(ratio)
