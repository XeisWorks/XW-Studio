"""sevDesk Contact API client (minimal)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from xw_studio.services.http_client import SevdeskConnection


class ContactSummary(BaseModel):
    """Subset of Contact returned by sevDesk."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str | None = None


class ContactClient:
    """Fetch contact details by id (e.g. when Invoice embed is insufficient)."""

    def __init__(self, connection: SevdeskConnection) -> None:
        self._conn = connection

    def get_contact(self, contact_id: str) -> ContactSummary:
        """GET ``/Contact/{id}`` — raises if not found or API error."""
        response = self._conn.get(f"/Contact/{contact_id}")
        data = response.json()
        obj: dict[str, Any]
        if isinstance(data, dict) and "objects" in data:
            seq = data["objects"]
            if not isinstance(seq, list) or not seq:
                raise ValueError("Empty objects in Contact response")
            first = seq[0]
            if not isinstance(first, dict):
                raise ValueError("Invalid Contact object")
            obj = first
        elif isinstance(data, dict):
            obj = data
        else:
            raise ValueError("Unexpected Contact payload")
        cid = obj.get("id", contact_id)
        return ContactSummary.model_validate({**obj, "id": str(cid)})
