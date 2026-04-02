"""PDF layout tooling facade — QR-Code, blank pages, covers, ISBN."""
from __future__ import annotations

import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class LayoutToolsService:
    """Coordinate layout operations using PyMuPDF and segno."""

    # ------------------------------------------------------------------
    # Tool description (for overview cards)
    # ------------------------------------------------------------------

    def describe_tools(self) -> list[tuple[str, str]]:
        return [
            ("Leerseiten", "PDFs um neutrale Seiten erweitern"),
            ("QR-Code", "URLs/Text als QR erzeugen (segno)"),
            ("Deckblatt", "Titel-Layouts aus Vorlagen"),
            ("ISBN / Barcode", "stdnum + Renderer"),
        ]

    # ------------------------------------------------------------------
    # QR-Code generation
    # ------------------------------------------------------------------

    def generate_qr_png(
        self,
        text: str,
        *,
        scale: int = 10,
        dark: str = "#000000",
        light: str = "#ffffff",
    ) -> bytes:
        """Return a QR-Code as PNG bytes."""
        try:
            import segno  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("segno not installed") from exc

        qr = segno.make(text, error="m")
        buf = io.BytesIO()
        qr.save(buf, kind="png", scale=scale, dark=dark, light=light)
        return buf.getvalue()

    def validate_isbn(self, isbn_str: str) -> tuple[bool, str]:
        """Validate ISBN-10 or ISBN-13. Returns (is_valid, canonical_or_error)."""
        try:
            from stdnum import isbn as _isbn  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("python-stdnum not installed") from exc

        s = isbn_str.strip()
        if _isbn.is_valid(s):
            return True, _isbn.format(s)
        return False, f"Ungueltige ISBN: {_isbn.compact(s)}"

    # ------------------------------------------------------------------
    # Blank-page insertion
    # ------------------------------------------------------------------

    def insert_blank_pages(
        self,
        source_pdf: bytes | Path,
        *,
        insert_after: list[int],
        width_pt: float = 595.28,
        height_pt: float = 841.89,
    ) -> bytes:
        """Insert blank A4 pages after the given 0-based page indices."""
        try:
            import fitz  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("PyMuPDF not installed") from exc

        raw = Path(source_pdf).read_bytes() if isinstance(source_pdf, Path) else source_pdf
        doc = fitz.open(stream=raw, filetype="pdf")
        for pos in sorted(set(insert_after), reverse=True):
            insert_at = max(0, min(pos + 1, len(doc)))
            doc.insert_page(insert_at, width=width_pt, height=height_pt)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Cover page
    # ------------------------------------------------------------------

    def generate_cover_pdf(
        self,
        title: str,
        subtitle: str = "",
        *,
        width_pt: float = 595.28,
        height_pt: float = 841.89,
        font_size_title: float = 32.0,
        font_size_subtitle: float = 18.0,
    ) -> bytes:
        """Generate a minimal text-based cover page PDF."""
        try:
            import fitz  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("PyMuPDF not installed") from exc

        doc = fitz.open()
        page = doc.new_page(width=width_pt, height=height_pt)
        x_title = width_pt * 0.1
        y_title = height_pt * 0.4
        page.insert_text((x_title, y_title), title, fontsize=font_size_title, color=(0, 0, 0))
        if subtitle:
            page.insert_text(
                (x_title, y_title + font_size_title * 1.6),
                subtitle,
                fontsize=font_size_subtitle,
                color=(0.3, 0.3, 0.3),
            )
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()
