"""FinanzOnline / UVA SOAP integration (injectable backend for zeep or mocks)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from xw_studio.core.config import AppConfig
from xw_studio.services.finanzonline.uva_soap import (
    UnconfiguredUvaSoapBackend,
    UvaSoapBackend,
    UvaSubmitResult,
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
        self._uva_backend: UvaSoapBackend = uva_backend or UnconfiguredUvaSoapBackend()

    # ------------------------------------------------------------------
    # Credential helpers — SecretService > env > config > None
    # ------------------------------------------------------------------

    def participant_id(self) -> str | None:
        """FinanzOnline TeilnehmerId (FON_TEILNEHMER_ID)."""
        if self._secrets:
            val = self._secrets.get_secret("FON_TEILNEHMER_ID")
            if val:
                return val
        return self._config.app.name  # last-resort placeholder; real value via SecretService

    def user_id(self) -> str | None:
        """FinanzOnline BenutzerId (FON_BENUTZER_ID)."""
        if self._secrets:
            return self._secrets.get_secret("FON_BENUTZER_ID") or None
        return None

    def fon_pin(self) -> str | None:
        """FinanzOnline PIN (FON_PIN)."""
        if self._secrets:
            return self._secrets.get_secret("FON_PIN") or None
        return None

    def has_credentials(self) -> bool:
        """True when all three FON credentials are available."""
        return bool(self.participant_id() and self.user_id() and self.fon_pin())

    # ------------------------------------------------------------------

    def submit_uva(self, payload: dict[str, Any]) -> UvaSubmitResult:
        """Submit UVA payload via configured SOAP backend."""
        return self._uva_backend.submit_uva(payload)
