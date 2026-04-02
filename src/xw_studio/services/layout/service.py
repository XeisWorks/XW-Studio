"""PDF layout tooling facade (blank pages, QR, covers) — skeleton."""
from __future__ import annotations

import logging

logging.getLogger(__name__)


class LayoutToolsService:
    """Coordinate layout operations; wire PyMuPDF/pypdf in later tasks."""

    def describe_tools(self) -> list[tuple[str, str]]:
        return [
            ("Leerseiten", "PDFs um neutrale Seiten erweitern"),
            ("QR-Code", "URLs/Text als QR erzeugen (segno)"),
            ("Deckblatt", "Titel-Layouts aus Vorlagen"),
            ("ISBN / Barcode", "stdnum + Renderer"),
        ]
