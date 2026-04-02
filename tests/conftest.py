"""Shared test fixtures for XeisWorks Studio."""
from __future__ import annotations

import pytest

from xw_studio.core.config import AppConfig
from xw_studio.core.container import Container


@pytest.fixture
def app_config() -> AppConfig:
    """Minimal test configuration."""
    return AppConfig()


@pytest.fixture
def container(app_config: AppConfig) -> Container:
    """DI container with test config."""
    return Container(app_config)
