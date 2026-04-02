"""FinanzOnline / UVA SOAP integration (injectable backend for zeep or mocks)."""
from __future__ import annotations

from typing import Any

from xw_studio.core.config import AppConfig
from xw_studio.services.finanzonline.uva_soap import (
    UnconfiguredUvaSoapBackend,
    UvaSoapBackend,
    UvaSubmitResult,
)

class FinanzOnlineClient:
    """SOAP entry point; production wires :class:`ZeepUvaSoapBackend` when ready."""

    def __init__(
        self,
        config: AppConfig,
        *,
        uva_backend: UvaSoapBackend | None = None,
    ) -> None:
        self._config = config
        self._uva_backend: UvaSoapBackend = uva_backend or UnconfiguredUvaSoapBackend()

    def submit_uva(self, payload: dict[str, Any]) -> UvaSubmitResult:
        """Submit UVA payload via configured SOAP backend."""
        return self._uva_backend.submit_uva(payload)
