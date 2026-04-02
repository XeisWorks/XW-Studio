"""FinanzOnline / UVA SOAP integration (stub for future zeep client)."""
from __future__ import annotations

import logging
from typing import Any

from xw_studio.core.config import AppConfig

logger = logging.getLogger(__name__)


class FinanzOnlineClient:
    """Thin placeholder; real implementation uses zeep + credentials from secure storage."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def submit_uva(self, _payload: dict[str, Any]) -> None:
        """SOAP UVA submission — not implemented in scaffold."""
        logger.warning("FinanzOnline UVA submission not implemented (Phase 2).")
        raise NotImplementedError(
            "FinanzOnline SOAP client: implement with zeep and FinanzOnline credentials",
        )
