"""Render PDF pages to a QPrinter via PyMuPDF (high-DPI raster path)."""
from __future__ import annotations

import logging

import fitz  # PyMuPDF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtPrintSupport import QPrinter

logger = logging.getLogger(__name__)

MUSIC_DPI = 600
INVOICE_DPI = 300


def _expand_ranges(page_ranges: list[range] | None, page_count: int) -> list[int]:
    if not page_ranges:
        return list(range(page_count))
    pages: list[int] = []
    for pr in page_ranges:
        for p in pr:
            if 0 <= p < page_count and p not in pages:
                pages.append(p)
    return pages if pages else list(range(page_count))


def print_pdf(
    pdf_path: str,
    printer: QPrinter,
    dpi: int = MUSIC_DPI,
    page_ranges: list[range] | None = None,
) -> None:
    """Print *pdf_path* using *printer*, rasterizing each page at *dpi*.

    Music scores should use :data:`MUSIC_DPI` (600); invoices often use
    :data:`INVOICE_DPI` (300).
    """
    doc = fitz.open(pdf_path)
    try:
        page_indices = _expand_ranges(page_ranges, len(doc))
        printer.setResolution(dpi)
        painter = QPainter()
        if not painter.begin(printer):
            logger.error("QPainter.begin(printer) failed")
            return

        for i, page_num in enumerate(page_indices):
            if i > 0:
                printer.newPage()
            page = doc[page_num]
            mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = QImage(
                pix.samples,
                pix.width,
                pix.height,
                pix.stride,
                QImage.Format.Format_RGB888,
            )
            painter.drawImage(painter.viewport(), img)

        painter.end()
    finally:
        doc.close()
