import json

import pytest

from ttspeak import config
from ttspeak.constants import BUILTIN_DEFAULTS
from ttspeak.errors import ConfigError, UsageError


def test_builtin_defaults(env):
    effective = config.load_effective()
    assert effective["model"] == BUILTIN_DEFAULTS["model"]
    assert effective["language"] == "German"
    assert effective["play"] is True


def test_user_overrides_builtin(env):
    config.set_user_value("model", "fake:custom")
    config.set_user_value("speed", "1.25")
    config.set_user_value("play", "false")
    effective = config.load_effective()
    assert effective["model"] == "fake:custom"
    assert effective["speed"] == 1.25
    assert effective["play"] is False


def test_declarative_then_user_then_env(env, monkeypatch, tmp_path):
    defaults = tmp_path / "defaults.json"
    defaults.write_text(json.dumps({"model": "fake:design", "language": "de"}), encoding="utf-8")
    monkeypatch.setenv("TTSPEAK_DEFAULTS", str(defaults))

    assert config.load_effective()["model"] == "fake:design"
    assert config.load_effective()["language"] == "German"

    config.set_user_value("model", "fake:custom")
    assert config.load_effective()["model"] == "fake:custom"

    monkeypatch.setenv("TTSPEAK_MODEL", "fake:base")
    assert config.load_effective()["model"] == "fake:base"


def test_language_is_normalized(env):
    value = config.set_user_value("language", "de-DE")
    assert value == "German"
    assert config.load_effective()["language"] == "German"


def test_invalid_values(env):
    with pytest.raises(ConfigError):
        config.set_user_value("speed", "9")
    with pytest.raises(ConfigError):
        config.set_user_value("play", "maybe")
    with pytest.raises(ConfigError):
        config.set_user_value("emotion", "furious")
    with pytest.raises(UsageError):
        config.set_user_value("nope", "x")


def test_unset(env):
    config.set_user_value("voice", "Ryan")
    assert config.unset_user_value("voice") is True
    assert config.unset_user_value("voice") is False
    assert config.load_effective()["voice"] == BUILTIN_DEFAULTS["voice"]


def test_missing_declarative_file_is_an_error(env, monkeypatch, tmp_path):
    monkeypatch.setenv("TTSPEAK_DEFAULTS", str(tmp_path / "missing.json"))
    with pytest.raises(ConfigError):
        config.load_effective()
