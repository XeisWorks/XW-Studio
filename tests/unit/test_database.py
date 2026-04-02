"""Tests for database helpers."""
import pytest

from xw_studio.core.config import AppConfig
from xw_studio.core.database import create_engine_from_config


def test_create_engine_requires_database_url() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL"):
        create_engine_from_config(AppConfig())
