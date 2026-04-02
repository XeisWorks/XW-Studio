"""Tests for CRM merge service behavior."""
from __future__ import annotations

from xw_studio.core.config import AppConfig
from xw_studio.services.crm.service import CrmService
from xw_studio.services.crm.types import ContactRecord


def test_merge_prefers_master_non_empty_fields() -> None:
    service = CrmService(AppConfig(), contact_client=None)
    master = ContactRecord(
        id="100",
        name="XeisWorks GmbH",
        email="office@xeisworks.test",
        phone="+43-1-1000",
        city="Wien",
    )
    duplicate = ContactRecord(
        id="101",
        name="XeisWorks",
        email="other@xeisworks.test",
        phone="+43-1-2000",
        city="Graz",
    )

    result = service.merge_contacts(master, duplicate)

    assert result.master_id == "100"
    assert result.duplicate_id == "101"
    assert result.merged.name == "XeisWorks GmbH"
    assert result.merged.email == "office@xeisworks.test"
    assert result.merged.phone == "+43-1-1000"
    assert result.merged.city == "Wien"


def test_merge_fills_missing_master_fields_from_duplicate() -> None:
    service = CrmService(AppConfig(), contact_client=None)
    master = ContactRecord(
        id="100",
        name="",
        email=None,
        phone="",
        city=None,
    )
    duplicate = ContactRecord(
        id="101",
        name="Musikhaus Nord",
        email="kontakt@musikhaus.test",
        phone="+43-1-3000",
        city="Linz",
    )

    result = service.merge_contacts(master, duplicate)

    assert result.merged.id == "100"
    assert result.merged.name == "Musikhaus Nord"
    assert result.merged.email == "kontakt@musikhaus.test"
    assert result.merged.phone == "+43-1-3000"
    assert result.merged.city == "Linz"