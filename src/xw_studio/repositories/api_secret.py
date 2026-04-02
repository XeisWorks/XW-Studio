"""Encrypted API secret rows (Fernet ciphertext)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from xw_studio.models.api_secret import ApiSecret


class ApiSecretRepository:
    """Store and load ciphertext by logical secret name."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_ciphertext(self, name: str) -> bytes | None:
        row = self._session.scalar(select(ApiSecret).where(ApiSecret.name == name))
        return None if row is None else row.ciphertext

    def upsert_ciphertext(self, name: str, ciphertext: bytes) -> ApiSecret:
        row = self._session.scalar(select(ApiSecret).where(ApiSecret.name == name))
        if row is not None:
            row.ciphertext = ciphertext
            return row
        entity = ApiSecret(name=name, ciphertext=ciphertext)
        self._session.add(entity)
        self._session.flush()
        return entity
