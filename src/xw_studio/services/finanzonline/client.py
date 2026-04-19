"""FinanzOnline / UVA SOAP integration (injectable backend for zeep or mocks)."""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from xw_studio.core.config import AppConfig
from xw_studio.services.finanzonline.uva_soap import (
    UnconfiguredUvaSoapBackend,
    UvaSoapBackend,
    UvaSubmitResult,
    ZeepUvaSoapBackend,
)

if TYPE_CHECKING:
    from xw_studio.services.secrets.service import SecretService

logger = logging.getLogger(__name__)


class FinanzOnlineClient:
    """SOAP entry point; credentials resolved via SecretService → config fallback."""

    def __init__(
        self,
        config: AppConfig,
        *,
        uva_backend: UvaSoapBackend | None = None,
        secret_service: "SecretService | None" = None,
    ) -> None:
        self._config = config
        self._secrets = secret_service
        self._uva_backend: UvaSoapBackend = uva_backend or self._build_default_backend()

    # ------------------------------------------------------------------
    # Credential helpers — SecretService > env > config > None
    # ------------------------------------------------------------------

    def participant_id(self) -> str | None:
        """FinanzOnline TeilnehmerId (FON_TEILNEHMER_ID)."""
        if self._secrets:
            val = self._secrets.get_secret("FON_TEILNEHMER_ID")
            if val:
                return val
        env_val = (os.getenv("FON_TEILNEHMER_ID", "") or "").strip()
        return env_val or None

    def user_id(self) -> str | None:
        """FinanzOnline BenutzerId (FON_BENUTZER_ID)."""
        if self._secrets:
            value = self._secrets.get_secret("FON_BENUTZER_ID")
            if value:
                return value
        env_val = (os.getenv("FON_BENUTZER_ID", "") or "").strip()
        return env_val or None

    def fon_pin(self) -> str | None:
        """FinanzOnline PIN (FON_PIN)."""
        if self._secrets:
            value = self._secrets.get_secret("FON_PIN")
            if value:
                return value
        env_val = (os.getenv("FON_PIN", "") or "").strip()
        return env_val or None

    def has_credentials(self) -> bool:
        """True when all three FON credentials are available."""
        return bool(self.participant_id() and self.user_id() and self.fon_pin())

    def backend_mode(self) -> str:
        """Human-readable backend mode for UI/status text."""
        if isinstance(self._uva_backend, ZeepUvaSoapBackend):
            return "live/test" if self._config.finanzonline.test_mode else "live"
        return "mock/off"

    # ------------------------------------------------------------------

    def submit_uva(self, payload: dict[str, Any]) -> UvaSubmitResult:
        """Submit UVA payload via configured SOAP backend."""
        return self._uva_backend.submit_uva(payload)

    def _build_default_backend(self) -> UvaSoapBackend:
        wsdl = ((self._config.finanzonline.wsdl_url or "") or os.getenv("FON_SOAP_WSDL") or "").strip()
        operation = (
            (self._config.finanzonline.operation_name or "")
            or os.getenv("FON_SOAP_OPERATION")
            or "submitUva"
        ).strip() or "submitUva"
        participant_id = self.participant_id() or ""
        user_id = self.user_id() or ""
        pin = self.fon_pin() or ""

        if wsdl and participant_id and user_id and pin:
            static_kwargs = {
                "teilnehmer_id": participant_id,
                "benutzer_id": user_id,
                "pin": pin,
            }
            logger.info("FinanzOnlineClient: using Zeep live backend (%s)", operation)
            return ZeepUvaSoapBackend(
                wsdl_url=wsdl,
                operation_name=operation,
                static_kwargs=static_kwargs,
            )

        missing_parts: list[str] = []
        if not wsdl:
            missing_parts.append("FON_SOAP_WSDL / finanzonline.wsdl_url")
        if not participant_id:
            missing_parts.append("FON_TEILNEHMER_ID")
        if not user_id:
            missing_parts.append("FON_BENUTZER_ID")
        if not pin:
            missing_parts.append("FON_PIN")
        reason = "FinanzOnline SOAP nicht konfiguriert. Fehlend: " + ", ".join(missing_parts)
        logger.info("FinanzOnlineClient: using unconfigured/mock backend (%s)", reason)
        return UnconfiguredUvaSoapBackend(reason=reason)
