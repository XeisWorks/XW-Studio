"""Legacy-compatible Brother bPAC label printer."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from xw_studio.core.config import PrintingSection


class LabelPrinter:
    """Equivalent behavior to old app LabelPrinter (LBX + object 'Empfaenger')."""

    def __init__(self, printing: PrintingSection) -> None:
        self._printing = printing

    def _printer_name(self) -> str:
        profile = self._printing.resolve_profile("label")
        if profile is not None and profile.printer_name.strip():
            return profile.printer_name.strip()
        explicit = str(self._printing.label_printer or "").strip()
        if explicit:
            return explicit
        names = [str(name).strip() for name in self._printing.configured_printer_names if str(name).strip()]
        if len(names) > 1:
            return names[1]
        return names[0] if names else ""

    def _template_path(self, override: str | None = None) -> str:
        candidate = str(override or self._printing.label_template_path or "").strip()
        if not candidate:
            raise RuntimeError("Etikettenvorlage fehlt")
        path = Path(candidate)
        if not path.is_absolute():
            root = Path(__file__).resolve().parents[4]
            path = (root / path).resolve()
        if not path.exists():
            raise RuntimeError("Etikettenvorlage fehlt")
        return str(path)

    def print_address(
        self,
        lines: list[str],
        *,
        template_path: str | None = None,
        overlay_object: str | None = None,
        overlay_text: str | None = None,
    ) -> None:
        printer_name = self._printer_name()
        if not printer_name:
            raise RuntimeError("Kein Etikettendrucker konfiguriert")
        template = self._template_path(template_path)
        multiline_text = "\r\n".join(str(line) for line in lines)

        pythoncom_mod = None
        try:
            import pythoncom  # type: ignore[import-untyped]
            import win32com.client  # type: ignore[import-untyped]
            pythoncom_mod = pythoncom
        except ImportError as exc:
            raise RuntimeError("Etikettendruck erfordert Windows (pywin32).") from exc

        temp_path = ""
        doc = None
        pythoncom_mod.CoInitialize()
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".lbx") as handle:
                temp_path = handle.name
            shutil.copyfile(template, temp_path)

            doc = win32com.client.Dispatch("bpac.Document")
            opened = bool(doc.Open(temp_path))
            if not opened:
                raise RuntimeError("LBX konnte nicht geladen werden")

            obj = doc.GetObject("Empfaenger")
            if not obj:
                raise RuntimeError("LBX-Objekt 'Empfaenger' nicht gefunden")
            obj.Text = multiline_text

            if overlay_object:
                overlay = doc.GetObject(overlay_object)
                if not overlay:
                    raise RuntimeError(f"LBX-Objekt '{overlay_object}' nicht gefunden")
                if overlay_text is not None:
                    overlay.Text = overlay_text

            if not doc.SetPrinter(printer_name, True):
                raise RuntimeError("Etikettendrucker nicht gefunden")
            if hasattr(doc, "SetMediaByName"):
                try:
                    doc.SetMediaByName("DK-11202")
                except Exception:
                    pass
            if hasattr(doc, "StartPrint") and callable(doc.StartPrint):
                if not bool(doc.StartPrint("Address Label", 0)):
                    raise RuntimeError("StartPrint fehlgeschlagen")
            if not hasattr(doc, "PrintOut"):
                raise RuntimeError("Etikettendruck fehlgeschlagen")
            ok = doc.PrintOut(False, False) if callable(doc.PrintOut) else bool(doc.PrintOut)
            if not ok:
                raise RuntimeError("Etikettendruck fehlgeschlagen")
            if hasattr(doc, "EndPrint") and callable(doc.EndPrint):
                doc.EndPrint()
        finally:
            if doc is not None:
                try:
                    doc.Close()
                except Exception:
                    pass
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            if pythoncom_mod is not None:
                pythoncom_mod.CoUninitialize()
