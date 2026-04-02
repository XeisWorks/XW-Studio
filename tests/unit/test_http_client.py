"""Tests for HTTP helpers."""
import httpx
import pytest

from xw_studio.core.exceptions import SevdeskApiError
from xw_studio.services.http_client import raise_for_sevdesk


def test_raise_for_sevdesk_success() -> None:
    response = httpx.Response(200, json={"ok": True})
    raise_for_sevdesk(response)


def test_raise_for_sevdesk_raises_on_error() -> None:
    response = httpx.Response(401, text="unauthorized")
    with pytest.raises(SevdeskApiError) as excinfo:
        raise_for_sevdesk(response)
    assert excinfo.value.status_code == 401
