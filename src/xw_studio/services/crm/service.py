"""CRM facade — live contact sync and deduplication."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from xw_studio.core.config import AppConfig
from xw_studio.services.crm.matching import find_duplicate_candidates
from xw_studio.services.crm.types import ContactRecord, DuplicateCandidate

if TYPE_CHECKING:
    from xw_studio.services.sevdesk.contact_client import ContactClient

logger = logging.getLogger(__name__)


class CrmService:
    """Customer data operations backed by sevDesk ContactClient."""

    def __init__(
        self,
        config: AppConfig,
        contact_client: "ContactClient | None" = None,
    ) -> None:
        self._config = config
        self._contact_client = contact_client

    def has_live_connection(self) -> bool:
        """True when a real ContactClient is wired (API token is set)."""
        return self._contact_client is not None

    def duplicate_threshold(self) -> int:
        return int(self._config.crm.fuzzy_match_threshold)

    def fetch_live_contacts(self) -> list[ContactRecord]:
        """Pull contacts from sevDesk.  Raises if no client is available."""
        if self._contact_client is None:
            raise RuntimeError("Kein sevDesk-Token konfiguriert.")
        return self._contact_client.list_contacts()

    def find_duplicates_in_memory(self, rows: list[ContactRecord]) -> list[DuplicateCandidate]:
        """Run duplicate scan for preloaded contacts (e.g. after sync)."""
        dups = find_duplicate_candidates(rows, threshold=self.duplicate_threshold())
        logger.info("CRM duplicate scan: %s candidates from %s contacts", len(dups), len(rows))
        return dups
