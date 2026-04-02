"""Shared httpx factory and helpers for external REST APIs."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from xw_studio.core.config import AppConfig
from xw_studio.core.exceptions import SevdeskApiError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def build_sevdesk_http_client(config: AppConfig) -> httpx.Client:
    """Create a configured httpx client for sevDesk API v1.

    Authentication: raw API token in ``Authorization`` header (sevDesk convention).
    """
    token = (config.sevdesk.api_token or "").strip()
    base = config.sevdesk.base_url.rstrip("/")
    headers = {
        "Authorization": token,
        "Accept": "application/json",
    }
    return httpx.Client(base_url=base, headers=headers, timeout=DEFAULT_TIMEOUT)


def raise_for_sevdesk(response: httpx.Response) -> None:
    """Raise :class:`SevdeskApiError` when the response is not successful."""
    if response.is_success:
        return
    text = response.text[:800] if response.text else ""
    logger.warning("sevDesk HTTP %s: %s", response.status_code, text)
    raise SevdeskApiError(
        f"sevDesk API request failed ({response.status_code}): {text}",
        status_code=response.status_code,
    )


@dataclass
class SevdeskConnection:
    """Holds one shared httpx client for all sevDesk service clients."""

    client: httpx.Client


def build_sevdesk_connection(config: AppConfig) -> SevdeskConnection:
    """Factory for DI registration."""
    return SevdeskConnection(client=build_sevdesk_http_client(config))
