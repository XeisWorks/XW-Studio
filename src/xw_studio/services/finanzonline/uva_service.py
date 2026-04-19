"""UVA / ZM submission orchestration (SOAP via zeep — implement per filing type)."""
from __future__ import annotations

import logging
from typing import Any

from xw_studio.core.config import AppConfig
from xw_studio.services.finanzonline.client import FinanzOnlineClient
from xw_studio.services.finanzonline.uva_payload_service import UvaPayloadService
from xw_studio.services.finanzonline.uva_preview import UvaPreviewService
from xw_studio.services.finanzonline.uva_soap import UvaSubmitResult

logger = logging.getLogger(__name__)


class UvaService:
    """High-level UVA workflow; keeps SOAP details out of the UI."""

    def __init__(
        self,
        config: AppConfig,
        client: FinanzOnlineClient,
        preview_service: UvaPreviewService | None = None,
        payload_service: UvaPayloadService | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._preview_service = preview_service
        self._payload_service = payload_service

    def describe_capabilities(self) -> str:
        """Human-readable status for the Steuern > UVA tab."""
        has_url = bool(self._config.database_url)
        has_fon = self._client.has_credentials()
        mode = self._client.backend_mode()
        preview_mode = "aktiv" if self._preview_service is not None else "nicht aktiv"
        payload_mode = "aktiv" if self._payload_service is not None else "nicht aktiv"
        return (
            "UVA-Modul: Phase-1/2-Vorschau + SOAP-Anbindung (zeep) pro Meldungstyp.\n"
            f"Backend-Modus: {mode}\n"
            f"Preview-Berechnung: {preview_mode}\n"
            f"Kennzahlen-Berechnung: {payload_mode}\n"
            f"PostgreSQL: {'konfiguriert' if has_url else 'nicht konfiguriert (nur .env)'}\n"
            f"FinanzOnline-Zugangsdaten: {'vorhanden' if has_fon else 'fehlen (Einstellungen > Token)'}"
        )

    def build_preview(self, year: int, month: int) -> dict[str, Any]:
        """Build phase-1 monthly preview for the UI."""
        if self._preview_service is None:
            return {
                "jahr": year,
                "monat": month,
                "status": "entwurf",
                "quelle": "xw_studio",
                "hinweis": "Keine Preview-Quelle konfiguriert.",
            }
        preview = self._preview_service.build_preview(year, month)
        payload: dict[str, Any] = {
            "jahr": year,
            "monat": month,
            "status": "entwurf",
            "quelle": "xw_studio",
            "preview": preview.model_dump(),
            "preview_text": self._preview_service.render_preview_text(preview),
        }
        if self._payload_service is not None:
            calculated = self._payload_service.build_payload(year, month)
            payload["kennzahlen"] = calculated.kennzahlen.model_dump()
            payload["zahlbetrag"] = calculated.zahlbetrag
            payload["warnings"] = list(calculated.warnings)
            payload["kennzahlen_text"] = self._payload_service.render_kennzahlen_text(calculated)
        return payload

    def mock_build_payload(self, year: int, month: int) -> dict[str, Any]:
        """Phase-1 preview payload for UI/tests; kept under the legacy method name."""
        try:
            return self.build_preview(year, month)
        except Exception as exc:
            logger.exception("UVA preview failed for %s-%s", year, month)
            return {
                "jahr": year,
                "monat": month,
                "status": "fehler",
                "quelle": "xw_studio",
                "fehler": str(exc),
            }

    def build_submission_payload(self, year: int, month: int) -> dict[str, Any]:
        """Build the U30 submission payload from the calculated kennzahlen."""
        if self._payload_service is None:
            raise RuntimeError("Keine Kennzahlen-Berechnung für UVA konfiguriert.")
        calculated = self._payload_service.build_payload(year, month)
        kz = calculated.kennzahlen
        submission_kennzahlen = {
            "KZ000": kz.A000,
            "KZ011": kz.A011,
            "KZ017": kz.A017,
            "KZ021": kz.A021,
            "KZ022": kz.A022,
            "KZ029": kz.A029,
            "KZ006": kz.A006,
            "KZ057": kz.A057,
            "KZ070": kz.B070,
            "KZ072": kz.B072,
            "KZ060": kz.C060,
            "KZ065": kz.C065,
            "KZ066": kz.C066,
            "KZ090": kz.D090,
        }
        return {
            "meldung": "U30",
            "jahr": year,
            "monat": month,
            "zeitraum": f"{year:04d}-{month:02d}",
            "quelle": "xw_studio",
            "kennzahlen": submission_kennzahlen,
            "zahlbetrag": calculated.zahlbetrag,
            "warnings": list(calculated.warnings),
        }

    def submit_month(self, year: int, month: int) -> UvaSubmitResult:
        """Calculate and submit one monthly U30 payload."""
        return self.submit_uva(self.build_submission_payload(year, month))

    def submit_uva(self, payload: dict[str, Any]) -> UvaSubmitResult:
        """Delegate to SOAP client (mock backend or zeep when configured)."""
        return self._client.submit_uva(payload)
