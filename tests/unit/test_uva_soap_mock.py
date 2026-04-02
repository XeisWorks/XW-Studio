"""UVA SOAP backend mocks (no network)."""
from __future__ import annotations

import pytest

from xw_studio.core.config import AppConfig
from xw_studio.services.finanzonline.client import FinanzOnlineClient
from xw_studio.services.finanzonline.uva_service import UvaService
from xw_studio.services.finanzonline.uva_soap import (
    MockUvaSoapBackend,
    UvaSoapUnavailableError,
    UvaSubmitResult,
)


def test_unconfigured_client_raises() -> None:
    client = FinanzOnlineClient(AppConfig())
    with pytest.raises(UvaSoapUnavailableError):
        client.submit_uva({"jahr": 2026, "monat": 1})


def test_mock_backend_returns_result() -> None:
    mock = MockUvaSoapBackend()
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    out = client.submit_uva({"jahr": 2026, "monat": 3})
    assert out.ok is True
    assert out.reference_id == "MOCK-REF-001"
    assert len(mock.calls) == 1
    assert mock.calls[0]["jahr"] == 2026


def test_uva_service_uses_injected_client() -> None:
    mock = MockUvaSoapBackend(
        result=UvaSubmitResult(ok=True, reference_id="X-9", message="ok"),
    )
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    svc = UvaService(AppConfig(), client)
    got = svc.submit_uva({"a": 1})
    assert got.reference_id == "X-9"


def test_mock_can_raise() -> None:
    err = ValueError("SOAP fault (test)")
    mock = MockUvaSoapBackend(error=err)
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    with pytest.raises(ValueError, match="SOAP fault"):
        client.submit_uva({})
