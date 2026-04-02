"""PDF print dialog for Rechnungen module."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import fitz
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from xw_studio.services.printing.pdf_renderer import (
    INVOICE_DPI,
    MUSIC_DPI,
    page_indices_from_qprinter,
    print_pdf,
)

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)


def _print_with_dialog(
    parent: QWidget,
    container: Container,
    *,
    title: str,
    dpi: int,
) -> None:
    path, _ = QFileDialog.getOpenFileName(
        parent,
        title,
        "",
        "PDF (*.pdf);;Alle Dateien (*.*)",
    )
    if not path:
        return

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    dialog = QPrintDialog(printer, parent)
    if dialog.exec() != QPrintDialog.DialogCode.Accepted:
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


def run_music_pdf_print(parent: QWidget, container: Container) -> None:
    """Pick a PDF, show print dialog, print at music DPI for score quality."""
    dpi = int(container.config.printing.music_dpi or MUSIC_DPI)
    _print_with_dialog(
        parent,
        container,
        title="PDF auswählen (Noten)",
        dpi=dpi,
    )
