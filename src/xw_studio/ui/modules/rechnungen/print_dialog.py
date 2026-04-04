"""PDF print dialog for Rechnungen module."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import fitz
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from xw_studio.core.printer_detect import discover_printers, evaluate_printer_status
from xw_studio.core.types import PrinterStatus
from xw_studio.services.products.print_decision import PieceBlock
from xw_studio.services.printing.pdf_renderer import (
    INVOICE_DPI,
    MUSIC_DPI,
    page_indices_from_qprinter,
    print_pdf,
)

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)


def _check_printer_runtime(parent: QWidget, container: Container, printer: QPrinter | None = None) -> bool:
    configured = list(container.config.printing.configured_printer_names)
    discovered = discover_printers()
    status = evaluate_printer_status(discovered, configured)
    if status == PrinterStatus.RED:
        QMessageBox.warning(
            parent,
            "Druck nicht verfuegbar",
            "Kein konfigurierter Drucker ist verfuegbar (Ampel rot).",
        )
        return False

    if printer is not None and configured:
        name = (printer.printerName() or "").strip()
        if name and name not in configured:
            QMessageBox.warning(
                parent,
                "Falscher Drucker",
                "Der gewaehlt Drucker ist nicht in den konfigurierten Druckern enthalten.",
            )
            return False
    return True


def _print_with_dialog(
    parent: QWidget,
    container: Container,
    *,
    title: str,
    dpi: int,
) -> None:
    if not _check_printer_runtime(parent, container):
        return

    path, _ = QFileDialog.getOpenFileName(
        parent,
        title,
        "",
        "PDF (*.pdf);;Alle Dateien (*.*)",
    )
    if not path:
        return

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    default_name = QPrinterInfo.defaultPrinter().printerName()
    if default_name:
        printer.setPrinterName(default_name)
    dialog = QPrintDialog(printer, parent)
    if dialog.exec() != QPrintDialog.DialogCode.Accepted:
        return

    if not _check_printer_runtime(parent, container, printer):
        return

    doc = fitz.open(path)
    try:
        page_count = len(doc)
    finally:
        doc.close()

    indices = page_indices_from_qprinter(printer, page_count)
    try:
        print_pdf(path, printer, dpi=dpi, pages=indices)
    except Exception as exc:
        logger.exception("Print failed: %s", exc)
        QMessageBox.critical(
            parent,
            "Druck fehlgeschlagen",
            f"Die PDF konnte nicht gedruckt werden:\n\n{exc}",
        )


def run_invoice_pdf_print(parent: QWidget, container: Container) -> None:
    """Pick a PDF, show print dialog, print at invoice DPI (respects page range from dialog)."""
    dpi = int(container.config.printing.invoice_dpi or INVOICE_DPI)
    _print_with_dialog(
        parent,
        container,
        title="PDF auswählen (Rechnung)",
        dpi=dpi,
    )


def run_label_pdf_print(parent: QWidget, container: Container) -> None:
    """Pick a label PDF, show print dialog, print at invoice DPI."""
    dpi = int(container.config.printing.invoice_dpi or INVOICE_DPI)
    _print_with_dialog(
        parent,
        container,
        title="PDF auswählen (Label)",
        dpi=dpi,
    )


def run_plc_label_pdf_print(
    parent: QWidget,
    container: Container,
    *,
    invoice_number: str,
) -> None:
    """Pick and print PLC label PDF for a specific invoice row."""
    dpi = int(container.config.printing.invoice_dpi or INVOICE_DPI)
    title = f"PLC-Label PDF auswählen ({invoice_number})" if invoice_number else "PLC-Label PDF auswählen"
    _print_with_dialog(
        parent,
        container,
        title=title,
        dpi=dpi,
    )


def run_music_pdf_print(parent: QWidget, container: Container) -> None:
    """Pick a PDF, show print dialog, print at music DPI for score quality."""
    dpi = int(container.config.printing.music_dpi or MUSIC_DPI)
    _print_with_dialog(
        parent,
        container,
        title="PDF auswählen (Noten)",
        dpi=dpi,
    )


def run_piece_pdf_print(parent: QWidget, container: Container, *, piece: PieceBlock) -> bool:
    """Print one product PDF from the product pipeline path.

    Returns ``True`` when printing was started successfully.
    """
    if not _check_printer_runtime(parent, container):
        return False

    path_obj = piece.print_file_path
    if path_obj is None:
        QMessageBox.warning(
            parent,
            "Produktdruck",
            f"Kein PDF-Pfad für SKU {piece.sku} konfiguriert.",
        )
        return False
    path = str(path_obj)

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    default_name = QPrinterInfo.defaultPrinter().printerName()
    if default_name:
        printer.setPrinterName(default_name)
    dialog = QPrintDialog(printer, parent)
    if dialog.exec() != QPrintDialog.DialogCode.Accepted:
        return False

    if not _check_printer_runtime(parent, container, printer):
        return False

    doc = fitz.open(path)
    try:
        page_count = len(doc)
    finally:
        doc.close()

    indices = page_indices_from_qprinter(printer, page_count)
    dpi = int(container.config.printing.music_dpi or MUSIC_DPI)
    try:
        print_pdf(path, printer, dpi=dpi, pages=indices)
        return True
    except Exception as exc:
        logger.exception("Product print failed: %s", exc)
        QMessageBox.critical(
            parent,
            "Produktdruck fehlgeschlagen",
            f"Die Produkt-PDF konnte nicht gedruckt werden:\n\n{exc}",
        )
        return False
