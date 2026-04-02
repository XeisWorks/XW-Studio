"""Tests for configuration loading."""
from xw_studio.core.config import AppConfig, load_config


def test_default_config_values() -> None:
    config = AppConfig()
    assert config.app.name == "XeisWorks Studio"
    assert config.app.theme == "dark_teal"
    assert config.printing.music_dpi == 600
    assert config.printing.invoice_dpi == 300
    assert config.printing.buffer_quantity == 3
    assert config.printing.configured_printer_names == []
    assert config.crm.fuzzy_match_threshold == 75


def test_load_config_with_missing_file() -> None:
    config = load_config("nonexistent.yaml")
    assert config.app.name == "XeisWorks Studio"
