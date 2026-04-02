"""Key-value settings in PostgreSQL."""
from __future__ import annotations

from sqlalchemy.orm import Session

from xw_studio.models.settings_kv import SettingKV


class SettingKvRepository:
    """Read/write JSON text blobs by string key."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_value_json(self, key: str) -> str | None:
        row = self._session.get(SettingKV, key)
        return None if row is None else row.value_json

    def set_value_json(self, key: str, value_json: str) -> SettingKV:
        row = self._session.get(SettingKV, key)
        if row is not None:
            row.value_json = value_json
            return row
        entity = SettingKV(key=key, value_json=value_json)
        self._session.add(entity)
        self._session.flush()
        return entity
