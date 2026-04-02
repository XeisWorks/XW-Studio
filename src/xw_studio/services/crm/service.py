"""CRM facade — live contact sync and deduplication."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from xw_studio.core.config import AppConfig
from xw_studio.services.crm.matching import find_duplicate_candidates
from xw_studio.services.crm.types import ContactRecord, DuplicateCandidate

if TYPE_CHECKING:
    from xw_studio.services.sevdesk.contact_client import ContactClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MergeResult:
    """Result of a CRM duplicate merge decision."""

    master_id: str
    duplicate_id: str
    merged: ContactRecord


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

    def merge_contacts(
        self,
        master: ContactRecord,
        duplicate: ContactRecord,
    ) -> MergeResult:
        """Merge duplicate into master using deterministic field fallback rules.

        This is an in-memory merge operation used by the CRM wizard.
        Live sevDesk writeback can be added in a following step.
        """

        merged = ContactRecord(
            id=master.id,
            name=(master.name or "").strip() or (duplicate.name or "").strip(),
            email=(master.email or "").strip() or (duplicate.email or "").strip() or None,
            phone=(master.phone or "").strip() or (duplicate.phone or "").strip() or None,
            city=(master.city or "").strip() or (duplicate.city or "").strip() or None,
        )
        logger.info("CRM merge prepared: master=%s duplicate=%s", master.id, duplicate.id)
        return MergeResult(
            master_id=master.id,
            duplicate_id=duplicate.id,
            merged=merged,
        )
