"""PDF print dialog for Rechnungen module."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from xw_studio.services.printing.pdf_renderer import INVOICE_DPI, print_pdf

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)


def run_invoice_pdf_print(parent: QWidget, container: Container) -> None:
    """Pick a PDF, show print dialog, print at invoice DPI from config."""
    path, _ = QFileDialog.getOpenFileName(
        parent,
        "PDF auswählen",
        "",
        "PDF (*.pdf);;Alle Dateien (*.*)",
    )
    if not path:
        return

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    dialog = QPrintDialog(printer, parent)
    if dialog.exec() != QPrintDialog.DialogCode.Accepted:
        return

    dpi = int(container.config.printing.invoice_dpi or INVOICE_DPI)
    try:
        print_pdf(path, printer, dpi=dpi, page_ranges=None)
    except Exception as exc:
        logger.exception("Print failed: %s", exc)
        QMessageBox.critical(
            parent,
            "Druck fehlgeschlagen",
            f"Die PDF konnte nicht gedruckt werden:\n\n{exc}",
        )
