"""Tests for the config module."""

from __future__ import annotations

from pathlib import Path

import pytest

from knowgate_cli import config as cfg


class TestConfigDefaults:
    """Defaults are returned for a missing or empty config file."""

    def test_returns_all_defaults_when_file_missing(self, isolated_config_dir: Path) -> None:
        data = cfg.load()
        assert data == cfg.DEFAULTS

    def test_get_returns_default_for_missing_key(self, isolated_config_dir: Path) -> None:
        # api_url is in DEFAULTS — not "missing" but the fallback path
        assert cfg.get("api_url") == "http://localhost:8000"

    def test_unknown_key_raises(self, isolated_config_dir: Path) -> None:
        with pytest.raises(cfg.ConfigError, match="Unknown config key"):
            cfg.get("nope")


class TestConfigWriteRead:
    """set + get round-trips correctly."""

    def test_set_persists_value(self, isolated_config_dir: Path) -> None:
        path = cfg.set_value("api_url", "http://example.test:9999")
        assert path.exists()
        assert cfg.get("api_url") == "http://example.test:9999"

    def test_set_rejects_unknown_key(self, isolated_config_dir: Path) -> None:
        with pytest.raises(cfg.ConfigError, match="Unknown config key"):
            cfg.set_value("nope", "x")

    def test_atomic_write_via_temp_file(self, isolated_config_dir: Path) -> None:
        """A successful set should not leave a .tmp file behind."""
        cfg.set_value("api_url", "http://a")
        path = cfg.config_path()
        assert not path.with_suffix(path.suffix + ".tmp").exists()

    def test_list_all_returns_every_key(self, isolated_config_dir: Path) -> None:
        cfg.set_value("api_url", "http://b")
        cfg.set_value("default_language", "vi")
        data = cfg.list_all()
        assert data["api_url"] == "http://b"
        assert data["default_language"] == "vi"
        # output_format is still the default
        assert data["output_format"] == "human"


class TestConfigMalformed:
    """Malformed TOML gives a friendly error, not a stack trace."""

    def test_invalid_toml_raises_config_error(self, isolated_config_dir: Path) -> None:
        path = cfg.config_path()
        path.write_text("this is not = valid TOML [[[")
        with pytest.raises(cfg.ConfigError, match="not valid TOML"):
            cfg.load()
