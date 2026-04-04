"""Silent printer routing for automated START workflows."""
from __future__ import annotations

import logging
from typing import Sequence

import fitz
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from xw_studio.core.config import PrintingSection

logger = logging.getLogger(__name__)


def _preferred_printer_name(printing: PrintingSection, profile_id: str, fallback_index: int) -> str:
    profile = printing.resolve_profile(profile_id)
    if profile is not None and profile.printer_name.strip():
        return profile.printer_name.strip()
    names = [str(name).strip() for name in printing.configured_printer_names if str(name).strip()]
    if 0 <= fallback_index < len(names):
        return names[fallback_index]
    if names:
        return names[0]
    return ""


def _build_printer(*, preferred_name: str) -> QPrinter:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    available = [p.printerName() for p in QPrinterInfo.availablePrinters()]
    if preferred_name and preferred_name in available:
        printer.setPrinterName(preferred_name)
        return printer
    default_name = QPrinterInfo.defaultPrinter().printerName().strip()
    if default_name:
        printer.setPrinterName(default_name)
    return printer


def print_pdf_bytes_silent(
    pdf_bytes: bytes,
    *,
    printing: PrintingSection,
    dpi: int,
    profile_id: str = "invoice",
    fallback_index: int = 0,
) -> str:
    """Print PDF bytes silently to configured printer and return printer name."""
    preferred_name = _preferred_printer_name(printing, profile_id, fallback_index)
    printer = _build_printer(preferred_name=preferred_name)
    selected_name = printer.printerName().strip()

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_count = len(doc)
        if page_count <= 0:
            raise RuntimeError("Leeres PDF")

        printer.setResolution(int(dpi))
        painter = QPainter()
        if not painter.begin(printer):
            raise RuntimeError("QPainter konnte Drucker nicht starten")

        try:
            for page_num in range(page_count):
                if page_num > 0:
                    printer.newPage()
                page = doc[page_num]
                scale = float(dpi) / 72.0
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                img = QImage(
                    pix.samples,
                    pix.width,
                    pix.height,
                    pix.stride,
                    QImage.Format.Format_RGB888,
                )
                painter.drawImage(painter.viewport(), img)
        finally:
            painter.end()
    finally:
        doc.close()

    return selected_name or preferred_name or "(Defaultdrucker)"


def print_pdf_file_silent(
    pdf_path: str,
    *,
    printer_name: str,
    dpi: int,
) -> str:
    """Print a PDF file path silently to an explicit printer name."""
    with open(pdf_path, "rb") as handle:
        data = handle.read()
    printer = _build_printer(preferred_name=printer_name)
    selected_name = printer.printerName().strip()

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        page_count = len(doc)
        if page_count <= 0:
            raise RuntimeError("Leeres PDF")
        printer.setResolution(int(dpi))
        painter = QPainter()
        if not painter.begin(printer):
            raise RuntimeError("QPainter konnte Drucker nicht starten")
        try:
            for page_num in range(page_count):
                if page_num > 0:
                    printer.newPage()
                page = doc[page_num]
                scale = float(dpi) / 72.0
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                img = QImage(
                    pix.samples,
                    pix.width,
                    pix.height,
                    pix.stride,
                    QImage.Format.Format_RGB888,
                )
                painter.drawImage(painter.viewport(), img)
        finally:
            painter.end()
    finally:
        doc.close()

    return selected_name or printer_name or "(Defaultdrucker)"


def print_text_label_silent(
    lines: Sequence[str],
    *,
    printing: PrintingSection,
    profile_id: str = "label",
    fallback_index: int = 1,
) -> str:
    """Print a simple address label text block silently and return printer name."""
    preferred_name = _preferred_printer_name(printing, profile_id, fallback_index)
    printer = _build_printer(preferred_name=preferred_name)
    selected_name = printer.printerName().strip()

    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError("QPainter konnte Labeldruck nicht starten")
    try:
        rect = QRectF(painter.viewport())
        text = "\n".join(str(line).strip() for line in lines if str(line).strip())
        if not text:
            text = "(keine Labeldaten)"
        painter.drawText(rect.adjusted(40, 40, -40, -40), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), text)
    finally:
        painter.end()

    return selected_name or preferred_name or "(Defaultdrucker)"
