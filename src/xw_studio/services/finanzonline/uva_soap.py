"""UVA SOAP submission contract and injectable backends (zeep to be wired later)."""
from __future__ import annotations

import logging
from typing import Any, Protocol

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class UvaSoapUnavailableError(RuntimeError):
    """Raised when no FinanzOnline/zeep backend is configured."""


class UvaSubmitResult(BaseModel):
    """Outcome of an (mock or real) UVA SOAP round-trip."""

    ok: bool
    reference_id: str | None = None
    message: str = Field(default="")


class UvaSoapBackend(Protocol):
    """Pluggable SOAP layer — production uses zeep; tests use :class:`MockUvaSoapBackend`."""

    def submit_uva(self, payload: dict[str, Any]) -> UvaSubmitResult:
        ...


class UnconfiguredUvaSoapBackend:
    """Default backend until zeep endpoints and credentials are wired."""

    def submit_uva(self, payload: dict[str, Any]) -> UvaSubmitResult:
        logger.warning("FinanzOnline UVA submission not configured; payload keys: %s", tuple(payload))
        raise UvaSoapUnavailableError(
            "FinanzOnline SOAP client is not configured (zeep backend missing).",
        )


class MockUvaSoapBackend:
    """Test double simulating a successful FinanzOnline response (no network)."""

    def __init__(
        self,
        *,
        result: UvaSubmitResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result or UvaSubmitResult(
            ok=True,
            reference_id="MOCK-REF-001",
            message="accepted (mock)",
        )
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def submit_uva(self, payload: dict[str, Any]) -> UvaSubmitResult:
        self.calls.append(dict(payload))
        if self._error is not None:
            raise self._error
        return self._result.model_copy()
