"""Legacy-compatible invoice printer using the blueprint Qt/PyMuPDF backend."""
from __future__ import annotations

import logging
import os
import tempfile
import threading

from xw_studio.core.config import PrintingSection
from xw_studio.services.printing.silent_printer import print_pdf_file_silent

logger = logging.getLogger(__name__)


def _looks_like_pdf(content: bytes) -> bool:
    if not content:
        return False
    return b"%PDF-" in bytes(content[:1024])


def _schedule_file_deletion(path: str, delay_seconds: float = 7200.0) -> None:
    def _cleanup() -> None:
        try:
            os.remove(path)
        except OSError:
            pass

    timer = threading.Timer(delay_seconds, _cleanup)
    timer.daemon = True
    timer.start()


class InvoicePrinter:
    """Drop-in equivalent to old app's InvoicePrinter with new print engine."""

    def __init__(self, printing: PrintingSection) -> None:
        self._printing = printing

    def _printer_name(self) -> str:
        profile = self._printing.resolve_profile("invoice")
        if profile is not None and profile.printer_name.strip():
            return profile.printer_name.strip()
        explicit = str(self._printing.invoice_printer or "").strip()
        if explicit:
            return explicit
        names = [str(name).strip() for name in self._printing.configured_printer_names if str(name).strip()]
        return names[0] if names else ""

    def print_pdf_bytes(self, pdf_bytes: bytes) -> None:
        printer_name = self._printer_name()
        if not printer_name:
            raise RuntimeError("Kein Rechnungsdrucker konfiguriert")
        if not _looks_like_pdf(pdf_bytes):
            raise RuntimeError("Rechnungs-PDF ungueltig (kein PDF-Header gefunden)")

        temp_path = ""
        scheduled = False
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as handle:
                handle.write(pdf_bytes)
                temp_path = handle.name
            self._print_file(temp_path, printer_name)
            scheduled = True
        finally:
            if temp_path and not scheduled:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _print_file(self, pdf_path: str, printer_name: str) -> None:
        try:
            size = os.path.getsize(pdf_path)
        except OSError:
            size = -1
        logger.info(
            "Invoice print dispatch: printer='%s' file='%s' size=%s",
            printer_name,
            pdf_path,
            size,
        )
        dpi = int(self._printing.invoice_dpi or 300)
        print_pdf_file_silent(pdf_path, printer_name=printer_name, dpi=dpi)
        _schedule_file_deletion(pdf_path)
