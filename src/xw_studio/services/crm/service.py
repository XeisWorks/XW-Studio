"""CRM facade — deduplication and future merge workflow."""
from __future__ import annotations

import logging

from xw_studio.core.config import AppConfig
from xw_studio.services.crm.matching import find_duplicate_candidates
from xw_studio.services.crm.types import ContactRecord, DuplicateCandidate

logger = logging.getLogger(__name__)


class CrmService:
    """Customer data operations; expand with sevDesk ContactClient calls."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def duplicate_threshold(self) -> int:
        return int(self._config.crm.fuzzy_match_threshold)

    def find_duplicates_in_memory(self, rows: list[ContactRecord]) -> list[DuplicateCandidate]:
        """Run duplicate scan for preloaded contacts (e.g. after sync)."""
        dups = find_duplicate_candidates(rows, threshold=self.duplicate_threshold())
        logger.info("CRM duplicate scan: %s candidates from %s contacts", len(dups), len(rows))
        return dups
