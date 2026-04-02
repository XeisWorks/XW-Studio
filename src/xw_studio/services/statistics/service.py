"""Revenue / business statistics (skeleton)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class StatisticsService:
    """Aggregate KPIs from sevDesk / DB once Phase 5 data is populated."""

    def describe(self) -> str:
        return (
            "Statistik: Umsatz, Kanaele, Export (Anbindung an PostgreSQL-Cache folgt)."
        )

    def summary_mock(self) -> dict[str, Any]:
        return {"hinweis": "Mock-Daten — echte Aggregation in Phase 6+", "umsatz": "—"}
