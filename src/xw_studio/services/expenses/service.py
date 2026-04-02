"""Expense audit / Ausgaben-Check (skeleton)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ExpenseAuditService:
    """Review and classify expenses for tax reporting."""

    def describe(self) -> str:
        return (
            "Ausgaben-Check: Belege pruefen und fuer UVA/FIBU vorbereiten "
            "(Service-Gerlueest)."
        )

    def list_open_mock(self) -> list[dict[str, Any]]:
        return []
