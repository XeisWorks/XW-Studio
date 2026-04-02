"""UVA / ZM submission orchestration (SOAP via zeep — implement per filing type)."""
from __future__ import annotations

import logging
from typing import Any

from xw_studio.core.config import AppConfig
from xw_studio.services.finanzonline.client import FinanzOnlineClient
from xw_studio.services.finanzonline.uva_soap import UvaSubmitResult

logger = logging.getLogger(__name__)


class UvaService:
    """High-level UVA workflow; keeps SOAP details out of the UI."""

    def __init__(self, config: AppConfig, client: FinanzOnlineClient) -> None:
        self._config = config
        self._client = client

    def describe_capabilities(self) -> str:
        """Human-readable status for the Steuern > UVA tab."""
        has_url = bool(self._config.database_url)
        return (
            "UVA-Modul: SOAP-Anbindung (zeep) wird pro Meldungstyp ergaenzt.\n"
            f"PostgreSQL-Konfiguration: {'ja' if has_url else 'nein (nur .env lokale Entwicklung)'}"
        )

    def mock_build_payload(self, year: int, month: int) -> dict[str, Any]:
        """Deterministic placeholder for UI/tests (no network)."""
        return {"jahr": year, "monat": month, "status": "entwurf", "quelle": "xw_studio"}

    def submit_uva(self, payload: dict[str, Any]) -> UvaSubmitResult:
        """Delegate to SOAP client (mock backend or zeep when configured)."""
        return self._client.submit_uva(payload)
