"""Orchestrates invoice-related operations (no UI)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from xw_studio.repositories.settings_kv import SettingKvRepository
from xw_studio.core.config import AppConfig
from xw_studio.services.printing.invoice_printer import InvoicePrinter
from xw_studio.services.printing.label_printer import LabelPrinter
from xw_studio.services.sevdesk.invoice_client import InvoiceClient, InvoiceSummary
from xw_studio.services.sevdesk.invoice_client import DEFAULT_SENSITIVE_COUNTRY_CODES
from xw_studio.services.wix.client import WixOrdersClient

logger = logging.getLogger(__name__)

_SENSITIVE_COUNTRIES_KEY = "rechnungen.sensitive_country_codes"
_SKU_FLAGS_KEY = "rechnungen.sku_flags"
_FULFILLMENT_STATUS_KEY = "rechnungen.fulfillment_status"

_DEFAULT_SKU_FLAGS = {
    "exact": ["XW-010", "XW-011", "XW-600.0"],
    "prefixes": ["XW-4", "XW-6", "XW-7", "XW-12"],
}
_SKU_TOKEN_RE = re.compile(r"\bXW-[A-Z0-9][A-Z0-9.-]*\b", re.IGNORECASE)


@dataclass(frozen=True)
class FulfillmentFlags:
    """Persisted fulfillment state shown in the invoice table chips."""

    label_printed: bool = False
    invoice_printed: bool = False
    product_ready: bool = False
    mail_sent: bool = False
    wix_fulfilled: bool = False
    payment_applicable: bool = False
    payment_booked: bool = False
    last_run_iso: str = ""
    last_error: str = ""

    def as_row_payload(self) -> dict[str, object]:
        return {
            "label_printed": self.label_printed,
            "invoice_printed": self.invoice_printed,
            "product_ready": self.product_ready,
            "mail_sent": self.mail_sent,
            "wix_fulfilled": self.wix_fulfilled,
            "payment_applicable": self.payment_applicable,
            "payment_booked": self.payment_booked,
            "last_run_iso": self.last_run_iso,
            "last_error": self.last_error,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "FulfillmentFlags":
        if not isinstance(payload, dict):
            return cls()
        return cls(
            label_printed=bool(payload.get("label_printed")),
            invoice_printed=bool(payload.get("invoice_printed")),
            product_ready=bool(payload.get("product_ready")),
            mail_sent=bool(payload.get("mail_sent")),
            wix_fulfilled=bool(payload.get("wix_fulfilled")),
            payment_applicable=bool(payload.get("payment_applicable")),
            payment_booked=bool(payload.get("payment_booked")),
            last_run_iso=str(payload.get("last_run_iso") or ""),
            last_error=str(payload.get("last_error") or ""),
        )


class InvoiceProcessingService:
    """Facade over sevDesk invoice clients for the Rechnungen module."""

    def __init__(
        self,
        config: AppConfig,
        invoice_client: InvoiceClient,
        settings_repo: SettingKvRepository | None = None,
        wix_orders: WixOrdersClient | None = None,
    ) -> None:
        self._invoices = invoice_client
        self._settings_repo = settings_repo
        self._wix_orders = wix_orders
        self._invoice_printer = InvoicePrinter(config.printing)
        self._label_printer = LabelPrinter(config.printing)
        self._wix_address_cache: dict[str, list[str]] = {}
        self._wix_digital_cache: dict[str, bool] = {}

    def load_invoice_table_rows(
        self,
        *,
        status: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, str]]:
        """Load invoices and return rows for :class:`DataTable` (German keys)."""
        summaries = self._invoices.list_invoice_summaries(
            limit=limit,
            offset=offset,
            status=status,
        )
        self._apply_sensitive_country_flags(summaries)
        self._apply_unreleased_sku_flags(summaries)
        logger.info(
            "Loaded %s invoices from sevDesk (status=%s offset=%s limit=%s)",
            len(summaries),
            status,
            offset,
            limit,
        )
        return self._rows_with_fulfillment(summaries)

    def load_invoice_summaries(
        self,
        *,
        status: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InvoiceSummary]:
        """Return typed summaries (e.g. for detail panel / export)."""
        summaries = self._invoices.list_invoice_summaries(
            limit=limit,
            offset=offset,
            status=status,
        )
        self._apply_sensitive_country_flags(summaries)
        self._apply_unreleased_sku_flags(summaries)
        return summaries

    def load_invoice_batch(
        self,
        *,
        status: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, str]], list[InvoiceSummary]]:
        """Return table rows and parallel summaries for detail view."""
        summaries = self._invoices.list_invoice_summaries(
            limit=limit,
            offset=offset,
            status=status,
        )
        self._apply_sensitive_country_flags(summaries)
        self._apply_unreleased_sku_flags(summaries)
        rows = [s.as_table_row() for s in summaries]
        return self._rows_with_fulfillment(summaries, rows), summaries

    def read_fulfillment_flags(self, invoice_id: str) -> FulfillmentFlags:
        all_flags = self._load_fulfillment_flags_map()
        return all_flags.get(str(invoice_id), FulfillmentFlags())

    def write_fulfillment_flags(self, invoice_id: str, flags: FulfillmentFlags) -> None:
        if self._settings_repo is None:
            return
        all_flags = self._load_fulfillment_flags_map()
        all_flags[str(invoice_id)] = flags
        payload = {
            key: value.as_row_payload()
            for key, value in all_flags.items()
        }
        self._settings_repo.set_value_json(
            _FULFILLMENT_STATUS_KEY,
            json.dumps(payload, ensure_ascii=False),
        )

    def write_fulfillment_flags_batch(self, updates: dict[str, FulfillmentFlags]) -> None:
        if self._settings_repo is None or not updates:
            return
        all_flags = self._load_fulfillment_flags_map()
        for invoice_id, flags in updates.items():
            all_flags[str(invoice_id)] = flags
        payload = {
            key: value.as_row_payload()
            for key, value in all_flags.items()
        }
        self._settings_repo.set_value_json(
            _FULFILLMENT_STATUS_KEY,
            json.dumps(payload, ensure_ascii=False),
        )

    def run_start_fullflow(
        self,
        *,
        full_mode: bool,
        should_abort: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        """Execute invoice processing flow for all open drafts (status=100)."""
        started = time.perf_counter()
        summaries = self._load_all_open_drafts(limit_per_page=100, max_pages=20)
        if full_mode:
            self._prefetch_wix_order_context(summaries)
        updates: dict[str, FulfillmentFlags] = {}
        processed = 0
        failures = 0
        successful = 0
        aborted = False
        for summary in summaries:
            if should_abort is not None and should_abort():
                aborted = True
                logger.info("START aborted before invoice %s", summary.id)
                break
            processed += 1
            flags = self.read_fulfillment_flags(summary.id)
            try:
                digital_only = full_mode and self._is_digital_only(summary)
                flags = self._run_finalize_step(summary, flags, digital_only=digital_only)
                if full_mode and not digital_only:
                    flags = self._run_invoice_print_step(summary, flags)
                    flags = self._run_label_print_step(summary, flags)
                    flags = self._run_product_step(summary, flags)
                flags = self._run_mail_step(summary, flags)
                successful += 1
            except Exception as exc:
                failures += 1
                flags = self._with_error(flags, exc)
            updates[summary.id] = flags
        self.write_fulfillment_flags_batch(updates)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "START metric total_ms=%s processed=%s failures=%s full_mode=%s",
            elapsed_ms,
            processed,
            failures,
            full_mode,
        )
        return {
            "processed": processed,
            "failures": failures,
            "successful": successful,
            "full_mode": full_mode,
            "aborted": aborted,
        }

    def _prefetch_wix_order_context(self, summaries: list[InvoiceSummary]) -> None:
        if self._wix_orders is None or not self._wix_orders.has_credentials():
            return
        refs = sorted({s.order_reference.strip() for s in summaries if s.order_reference.strip()})
        if not refs:
            return

        missing = [
            ref
            for ref in refs
            if ref not in self._wix_address_cache or ref not in self._wix_digital_cache
        ]
        if not missing:
            return

        started = time.perf_counter()
        workers = max(2, min(8, len(missing)))

        def load_ref(ref: str) -> tuple[str, list[str], bool]:
            lines = self._wix_orders.resolve_order_address_lines(ref)
            digital_only = self._wix_orders.is_reference_digital_only(ref)
            return ref, lines, bool(digital_only)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(load_ref, ref) for ref in missing]
            for fut in as_completed(futures):
                try:
                    ref, lines, digital_only = fut.result()
                    self._wix_address_cache[ref] = list(lines)
                    self._wix_digital_cache[ref] = digital_only
                except Exception as exc:
                    logger.warning("Wix prefetch failed: %s", exc)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "START metric wix_prefetch_ms=%s refs=%s workers=%s",
            elapsed_ms,
            len(missing),
            workers,
        )

    def _get_wix_address_lines_cached(self, reference: str) -> list[str]:
        ref = str(reference or "").strip()
        if not ref or self._wix_orders is None or not self._wix_orders.has_credentials():
            return []
        cached = self._wix_address_cache.get(ref)
        if cached is not None:
            return list(cached)
        lines = self._wix_orders.resolve_order_address_lines(ref)
        self._wix_address_cache[ref] = list(lines)
        return list(lines)

    def _is_digital_only(self, summary: InvoiceSummary) -> bool:
        ref = str(summary.order_reference or "").strip()
        if not ref or self._wix_orders is None or not self._wix_orders.has_credentials():
            return False
        cached = self._wix_digital_cache.get(ref)
        if cached is not None:
            return bool(cached)
        try:
            resolved = bool(self._wix_orders.is_reference_digital_only(ref))
        except Exception as exc:
            logger.warning("Wix digital-only resolve failed ref=%s: %s", ref, exc)
            resolved = False
        self._wix_digital_cache[ref] = resolved
        return resolved

    def retry_fulfillment_step(self, invoice_id: str, step: str) -> FulfillmentFlags:
        """Retry one fulfillment step for a single invoice and persist state."""
        summary = self._load_summary_by_id(invoice_id)
        flags = self.read_fulfillment_flags(summary.id)
        if step == "label_printed":
            next_flags = self._run_label_print_step(summary, flags)
        elif step == "invoice_printed":
            next_flags = self._run_invoice_print_step(summary, flags)
        elif step == "product_ready":
            next_flags = self._run_product_step(summary, flags)
        elif step == "mail_sent":
            next_flags = self._run_mail_step(summary, flags)
        elif step == "wix_fulfilled":
            next_flags = self._run_product_step(summary, flags)
        else:
            raise ValueError(f"Unbekannter Schritt: {step}")
        self.write_fulfillment_flags(summary.id, next_flags)
        return next_flags

    def print_label_for_invoice(
        self,
        invoice_id: str,
        *,
        override_lines: list[str] | None = None,
    ) -> FulfillmentFlags:
        """Print one shipping label for *invoice_id* and persist ``label_printed``.

        ``override_lines`` allows UI-edited address lines to be used instead of the
        address resolved from Wix/sevDesk.
        """
        summary = self._load_summary_by_id(invoice_id)
        flags = self.read_fulfillment_flags(summary.id)
        lines = [
            str(line or "").strip()
            for line in (override_lines or [])
            if str(line or "").strip()
        ]
        if not lines:
            full = self._invoices.fetch_invoice_by_id(summary.id)
            lines = self._shipping_lines_from_invoice(full, summary)
        if not lines:
            raise RuntimeError("Keine Lieferadresse für Labeldruck")
        self._label_printer.print_address(lines)
        stamped = self._stamp(flags)
        next_flags = FulfillmentFlags(
            label_printed=True,
            invoice_printed=stamped.invoice_printed,
            product_ready=stamped.product_ready,
            mail_sent=stamped.mail_sent,
            wix_fulfilled=stamped.wix_fulfilled,
            payment_applicable=stamped.payment_applicable,
            payment_booked=stamped.payment_booked,
            last_run_iso=stamped.last_run_iso,
            last_error="",
        )
        self.write_fulfillment_flags(summary.id, next_flags)
        return next_flags

    def _load_all_open_drafts(self, *, limit_per_page: int, max_pages: int) -> list[InvoiceSummary]:
        all_rows: list[InvoiceSummary] = []
        offset = 0
        for _ in range(max_pages):
            batch = self.load_invoice_summaries(status=100, limit=limit_per_page, offset=offset)
            if not batch:
                break
            all_rows.extend(batch)
            if len(batch) < limit_per_page:
                break
            offset += limit_per_page
        return all_rows

    def _load_summary_by_id(self, invoice_id: str) -> InvoiceSummary:
        raw = self._invoices.fetch_invoice_by_id(invoice_id)
        if not raw:
            raise ValueError(f"Rechnung {invoice_id} nicht gefunden")
        summary = InvoiceSummary.from_api_object(raw)
        self._apply_sensitive_country_flags([summary])
        self._apply_unreleased_sku_flags([summary])
        return summary

    def _stamp(self, flags: FulfillmentFlags) -> FulfillmentFlags:
        return FulfillmentFlags(
            label_printed=flags.label_printed,
            invoice_printed=flags.invoice_printed,
            product_ready=flags.product_ready,
            mail_sent=flags.mail_sent,
            wix_fulfilled=flags.wix_fulfilled,
            payment_applicable=flags.payment_applicable,
            payment_booked=flags.payment_booked,
            last_run_iso=datetime.utcnow().isoformat(timespec="seconds"),
            last_error=flags.last_error,
        )

    def _with_error(self, flags: FulfillmentFlags, exc: Exception) -> FulfillmentFlags:
        stamped = self._stamp(flags)
        return FulfillmentFlags(
            label_printed=stamped.label_printed,
            invoice_printed=stamped.invoice_printed,
            product_ready=stamped.product_ready,
            mail_sent=stamped.mail_sent,
            wix_fulfilled=stamped.wix_fulfilled,
            payment_applicable=stamped.payment_applicable,
            payment_booked=stamped.payment_booked,
            last_run_iso=stamped.last_run_iso,
            last_error=str(exc),
        )

    def _run_finalize_step(
        self,
        summary: InvoiceSummary,
        flags: FulfillmentFlags,
        *,
        digital_only: bool = False,
    ) -> FulfillmentFlags:
        send_type = "VM" if digital_only or not summary.order_reference.strip() else "PRN"
        self._invoices.send_invoice_document(summary.id, send_type=send_type, send_draft=False)
        stamped = self._stamp(flags)
        return FulfillmentFlags(
            label_printed=stamped.label_printed,
            invoice_printed=stamped.invoice_printed,
            product_ready=stamped.product_ready,
            mail_sent=stamped.mail_sent or send_type == "VM",
            wix_fulfilled=stamped.wix_fulfilled,
            payment_applicable=stamped.payment_applicable or bool(summary.order_reference.strip()),
            payment_booked=stamped.payment_booked,
            last_run_iso=stamped.last_run_iso,
            last_error="",
        )

    def _run_invoice_print_step(self, summary: InvoiceSummary, flags: FulfillmentFlags) -> FulfillmentFlags:
        # Keep old app behavior: fetch invoice PDF bytes and dispatch to invoice printer.
        self._invoices.render_invoice_pdf(summary.id)
        pdf_bytes = self._invoices.get_invoice_pdf(summary.id)
        if not pdf_bytes:
            raise RuntimeError("PDF nicht verfügbar")
        self._invoice_printer.print_pdf_bytes(pdf_bytes)
        logger.info("Invoice %s printed", summary.invoice_number or summary.id)
        stamped = self._stamp(flags)
        return FulfillmentFlags(
            label_printed=stamped.label_printed,
            invoice_printed=True,
            product_ready=stamped.product_ready,
            mail_sent=stamped.mail_sent,
            wix_fulfilled=stamped.wix_fulfilled,
            payment_applicable=stamped.payment_applicable,
            payment_booked=stamped.payment_booked,
            last_run_iso=stamped.last_run_iso,
            last_error="",
        )

    def _run_label_print_step(self, summary: InvoiceSummary, flags: FulfillmentFlags) -> FulfillmentFlags:
        if not flags.invoice_printed:
            raise RuntimeError("Labeldruck erst nach Rechnungsdruck möglich")
        full = self._invoices.fetch_invoice_by_id(summary.id)
        lines = self._shipping_lines_from_invoice(full, summary)
        if not lines:
            raise RuntimeError("Keine Lieferadresse für Labeldruck")
        self._label_printer.print_address(lines)
        logger.info("Invoice %s label printed", summary.invoice_number or summary.id)
        stamped = self._stamp(flags)
        return FulfillmentFlags(
            label_printed=True,
            invoice_printed=stamped.invoice_printed,
            product_ready=stamped.product_ready,
            mail_sent=stamped.mail_sent,
            wix_fulfilled=stamped.wix_fulfilled,
            payment_applicable=stamped.payment_applicable,
            payment_booked=stamped.payment_booked,
            last_run_iso=stamped.last_run_iso,
            last_error="",
        )

    def _run_product_step(self, summary: InvoiceSummary, flags: FulfillmentFlags) -> FulfillmentFlags:
        if not summary.order_reference.strip() or self._wix_orders is None:
            stamped = self._stamp(flags)
            return FulfillmentFlags(
                label_printed=stamped.label_printed,
                invoice_printed=stamped.invoice_printed,
                product_ready=False,
                mail_sent=stamped.mail_sent,
                wix_fulfilled=False,
                payment_applicable=stamped.payment_applicable,
                payment_booked=stamped.payment_booked,
                last_run_iso=stamped.last_run_iso,
                last_error="",
            )

        items = self._wix_orders.get_fulfillable_items(summary.order_reference)
        if not items:
            # Already fulfilled or not applicable.
            stamped = self._stamp(flags)
            return FulfillmentFlags(
                label_printed=stamped.label_printed,
                invoice_printed=stamped.invoice_printed,
                product_ready=True,
                mail_sent=stamped.mail_sent,
                wix_fulfilled=True,
                payment_applicable=stamped.payment_applicable,
                payment_booked=stamped.payment_booked,
                last_run_iso=stamped.last_run_iso,
                last_error="",
            )

        created = self._wix_orders.create_fulfillment(summary.order_reference, items)
        if not created:
            raise RuntimeError("Wix-Fulfillment konnte nicht erstellt werden")
        stamped = self._stamp(flags)
        return FulfillmentFlags(
            label_printed=stamped.label_printed,
            invoice_printed=stamped.invoice_printed,
            product_ready=True,
            mail_sent=stamped.mail_sent,
            wix_fulfilled=True,
            payment_applicable=stamped.payment_applicable,
            payment_booked=stamped.payment_booked,
            last_run_iso=stamped.last_run_iso,
            last_error="",
        )

    def _run_mail_step(self, summary: InvoiceSummary, flags: FulfillmentFlags) -> FulfillmentFlags:
        if flags.mail_sent:
            return self._stamp(flags)
        self._invoices.send_invoice_document(summary.id, send_type="VM", send_draft=False)
        stamped = self._stamp(flags)
        return FulfillmentFlags(
            label_printed=stamped.label_printed,
            invoice_printed=stamped.invoice_printed,
            product_ready=stamped.product_ready,
            mail_sent=True,
            wix_fulfilled=stamped.wix_fulfilled,
            payment_applicable=stamped.payment_applicable,
            payment_booked=stamped.payment_booked,
            last_run_iso=stamped.last_run_iso,
            last_error="",
        )

    def _shipping_lines_from_invoice(self, invoice: dict[str, Any], summary: InvoiceSummary) -> list[str]:
        if summary.order_reference.strip():
            wix_lines = self._get_wix_address_lines_cached(summary.order_reference)
            if wix_lines:
                return wix_lines

        contact = invoice.get("contact") if isinstance(invoice.get("contact"), dict) else {}
        delivery_name = str(invoice.get("deliveryName") or "").strip()
        name = delivery_name or str(invoice.get("name") or contact.get("name") or summary.contact_name or "").strip()

        street = str(
            invoice.get("deliveryStreet")
            or invoice.get("shippingStreet")
            or invoice.get("street")
            or ""
        ).strip()
        zip_code = str(
            invoice.get("deliveryZip")
            or invoice.get("shippingZip")
            or invoice.get("zip")
            or ""
        ).strip()
        city = str(
            invoice.get("deliveryCity")
            or invoice.get("shippingCity")
            or invoice.get("city")
            or ""
        ).strip()
        country = str(
            invoice.get("deliveryAddressCountry")
            or invoice.get("shippingCountry")
            or invoice.get("addressCountryCode")
            or summary.display_country
            or ""
        ).strip()

        city_line = " ".join(part for part in (zip_code, city) if part)
        lines = [line for line in (name, street, city_line, country) if str(line).strip()]
        return lines

    def _load_fulfillment_flags_map(self) -> dict[str, FulfillmentFlags]:
        if self._settings_repo is None:
            return {}
        raw = self._settings_repo.get_value_json(_FULFILLMENT_STATUS_KEY)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, FulfillmentFlags] = {}
        for key, payload in data.items():
            if not isinstance(key, str) or not key.strip():
                continue
            out[key] = FulfillmentFlags.from_payload(payload)
        return out

    def _rows_with_fulfillment(
        self,
        summaries: list[InvoiceSummary],
        rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        row_list = rows if rows is not None else [s.as_table_row() for s in summaries]
        states = self._load_fulfillment_flags_map()
        for summary, row in zip(summaries, row_list):
            flags = states.get(summary.id)
            if flags is None:
                flags = FulfillmentFlags(
                    product_ready=bool(summary.order_reference.strip()),
                    payment_applicable=bool(summary.order_reference.strip()),
                )
            row["FULFILLMENT"] = ""
            row["__fulfillment__"] = flags.as_row_payload()
            row["__tooltip__FULFILLMENT"] = "Label | Rechnung | Produkt | Mail | Wix | Zahlung"
            row["__align__FULFILLMENT"] = "center"
        return row_list

    def count_invoices(self, *, status: int | None = None, batch_size: int = 200) -> int:
        """Count invoices by paging through API results to avoid hard caps in UI badges."""
        safe_batch = max(10, int(batch_size))
        offset = 0
        total = 0
        while True:
            rows = self._invoices.list_invoice_summaries(
                limit=safe_batch,
                offset=offset,
                status=status,
            )
            count = len(rows)
            total += count
            if count < safe_batch:
                break
            offset += safe_batch
        return total

    def _load_sensitive_country_codes(self) -> set[str]:
        if self._settings_repo is None:
            return set(DEFAULT_SENSITIVE_COUNTRY_CODES)
        raw = self._settings_repo.get_value_json(_SENSITIVE_COUNTRIES_KEY)
        if not raw:
            return set(DEFAULT_SENSITIVE_COUNTRY_CODES)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return set(DEFAULT_SENSITIVE_COUNTRY_CODES)
        if not isinstance(data, list):
            return set(DEFAULT_SENSITIVE_COUNTRY_CODES)
        parsed = {
            str(item).strip().upper()
            for item in data
            if str(item).strip()
        }
        return parsed or set(DEFAULT_SENSITIVE_COUNTRY_CODES)

    def _apply_sensitive_country_flags(self, summaries: list[InvoiceSummary]) -> None:
        sensitive_codes = self._load_sensitive_country_codes()
        for summary in summaries:
            code = summary.address_country_code.strip().upper()
            delivery_code = summary.delivery_country_code.strip().upper()
            summary.is_sensitive_country = code in sensitive_codes or delivery_code in sensitive_codes

    def _load_sku_flags(self) -> tuple[set[str], tuple[str, ...]]:
        if self._settings_repo is None:
            return self._default_sku_flags()
        raw = self._settings_repo.get_value_json(_SKU_FLAGS_KEY)
        if not raw:
            return self._default_sku_flags()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return self._default_sku_flags()
        if not isinstance(data, dict):
            return self._default_sku_flags()

        exact_raw = data.get("exact")
        prefixes_raw = data.get("prefixes")
        if not isinstance(exact_raw, list) or not isinstance(prefixes_raw, list):
            return self._default_sku_flags()

        exact = {str(item).strip().upper() for item in exact_raw if str(item).strip()}
        prefixes = tuple(str(item).strip().upper() for item in prefixes_raw if str(item).strip())
        if not exact and not prefixes:
            return self._default_sku_flags()
        return exact, prefixes

    def _default_sku_flags(self) -> tuple[set[str], tuple[str, ...]]:
        exact = {str(item).strip().upper() for item in _DEFAULT_SKU_FLAGS["exact"]}
        prefixes = tuple(str(item).strip().upper() for item in _DEFAULT_SKU_FLAGS["prefixes"])
        return exact, prefixes

    def _apply_unreleased_sku_flags(self, summaries: list[InvoiceSummary]) -> None:
        exact, prefixes = self._load_sku_flags()
        for summary in summaries:
            hay = " ".join(
                [
                    summary.order_reference,
                    summary.buyer_note,
                    summary.invoice_number,
                ]
            )
            tokens = {match.group(0).upper() for match in _SKU_TOKEN_RE.finditer(hay)}
            summary.has_unreleased_sku = any(
                token in exact or any(token.startswith(prefix) for prefix in prefixes)
                for token in tokens
            )
