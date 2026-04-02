"""Printing services (PDF raster path via PyMuPDF + QPrinter)."""

from xw_studio.services.printing.pdf_renderer import (
    INVOICE_DPI,
    MUSIC_DPI,
    page_indices_from_qprinter,
    print_pdf,
)

__all__ = ["INVOICE_DPI", "MUSIC_DPI", "page_indices_from_qprinter", "print_pdf"]

