"""Tests for daily business queue normalization and urgency markers."""
from __future__ import annotations

import json

from xw_studio.services.daily_business.service import DailyBusinessService


class _RepoStub:
    def __init__(self, payloads: dict[str, str]) -> None:
        self._payloads = payloads

    def get_value_json(self, key: str) -> str | None:
        return self._payloads.get(key)


def test_mollie_queue_marks_auth_as_urgent() -> None:
    repo = _RepoStub(
        {
            "daily_business.queue.mollie": json.dumps(
                [{"ref": "M1", "status": "Authorized pending", "note": "missing auth"}]
            )
        }
    )
    svc = DailyBusinessService(repo)  # type: ignore[arg-type]

    rows = svc.load_queue_rows("mollie")

    assert len(rows) == 1
    assert rows[0]["Mark."] == "🔴"
    assert "Mollie-Auth" in rows[0]["__tooltip__Mark."]


def test_download_queue_no_urgency_when_clean() -> None:
    repo = _RepoStub(
        {
            "daily_business.queue.downloads": json.dumps(
                [{"ref": "D1", "status": "Bereit", "note": "Link gesendet"}]
            )
        }
    )
    svc = DailyBusinessService(repo)  # type: ignore[arg-type]

    rows = svc.load_queue_rows("downloads")

    assert len(rows) == 1
    assert rows[0]["Mark."] == ""


def test_custom_urgency_rules_from_settings_override_defaults() -> None:
    repo = _RepoStub(
        {
            "daily_business.urgency_rules": json.dumps(
                {
                    "generic": ["needs-review"],
                    "downloads": ["manual check"],
                }
            ),
            "daily_business.queue.downloads": json.dumps(
                [{"ref": "D2", "status": "READY", "note": "manual check by team"}]
            ),
        }
    )
    svc = DailyBusinessService(repo)  # type: ignore[arg-type]

    rows = svc.load_queue_rows("downloads")

    assert len(rows) == 1
    assert rows[0]["Mark."] == "🔴"
    assert "Download-Link" in rows[0]["__tooltip__Mark."]
