"""PC registry persistence."""
from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from xw_studio.models.pc_registry import PcRegistry


class PcRegistryRepository:
    """CRUD-style access for workstation rows."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_machine_id(self, machine_id: str) -> PcRegistry | None:
        return self._session.scalar(
            select(PcRegistry).where(PcRegistry.machine_id == machine_id),
        )

    def upsert_last_seen(
        self,
        machine_id: str,
        *,
        display_name: str | None = None,
        is_print_station: bool = False,
    ) -> PcRegistry:
        """Create or update ``last_seen_at`` and optional fields."""
        now = datetime.datetime.now(datetime.UTC)
        row = self.get_by_machine_id(machine_id)
        if row is not None:
            row.last_seen_at = now
            if display_name is not None:
                row.display_name = display_name
            row.is_print_station = is_print_station
            return row
        entity = PcRegistry(
            machine_id=machine_id,
            display_name=display_name,
            is_print_station=is_print_station,
            last_seen_at=now,
        )
        self._session.add(entity)
        self._session.flush()
        return entity
