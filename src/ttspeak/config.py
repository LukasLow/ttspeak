"""Configuration: built-in defaults, declarative defaults, user config, env."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import paths
from .constants import (
    BOOL_KEYS,
    BUILTIN_DEFAULTS,
    CONFIG_KEYS,
    EMOTION_INSTRUCTS,
    FLOAT_KEYS,
    normalize_language,
)
from .errors import ConfigError, UsageError
from .util import read_json, write_json

ENV_KEYS = {
    "TTSPEAK_MODEL": "model",
    "TTSPEAK_VOICE": "voice",
    "TTSPEAK_LANGUAGE": "language",
    "TTSPEAK_SPEED": "speed",
    "TTSPEAK_EMOTION": "emotion",
    "TTSPEAK_INSTRUCT": "instruct",
    "TTSPEAK_PLAY": "play",
}

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _coerce(key: str, value: Any) -> Any:
    if key not in CONFIG_KEYS:
        raise ConfigError(f"Unknown configuration key '{key}'. Known keys: {', '.join(CONFIG_KEYS)}.")

    if value is None:
        return None

    if key in BOOL_KEYS:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ConfigError(f"'{key}' expects true or false, got '{value}'.")

    if key in FLOAT_KEYS:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"'{key}' expects a number, got '{value}'.") from exc
        if not 0.5 <= number <= 2.0:
            raise ConfigError(f"'{key}' must be between 0.5 and 2.0.")
        return number

    text = str(value).strip()
    if key == "language":
        return normalize_language(text)
    if key == "emotion":
        if not text:
            return None
        key_lower = text.lower()
        if key_lower not in EMOTION_INSTRUCTS:
            raise ConfigError(
                f"Unknown emotion '{text}'. Choose one of: {', '.join(EMOTION_INSTRUCTS)}."
            )
        return key_lower
    if key in {"model", "voice", "instruct"} and not text:
        return None
    return text


def _read_mapping(path: Path, label: str) -> dict[str, Any]:
    data = read_json(path, default=None)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{label} at {path} must contain a JSON object.")
    result: dict[str, Any] = {}
    for key, value in data.items():
        result[key] = _coerce(key, value)
    return result


def load_declarative_defaults() -> dict[str, Any]:
    override = os.environ.get("TTSPEAK_DEFAULTS")
    if not override:
        return {}
    path = Path(override).expanduser()
    if not path.exists():
        raise ConfigError(f"TTSPEAK_DEFAULTS points to a missing file: {path}")
    return _read_mapping(path, "Declarative defaults")


def load_user_config() -> dict[str, Any]:
    path = paths.config_path()
    if not path.exists():
        return {}
    return _read_mapping(path, "User configuration")


def save_user_config(data: dict[str, Any]) -> None:
    write_json(paths.config_path(), data, private=True)


def env_overrides() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for env_name, key in ENV_KEYS.items():
        raw = os.environ.get(env_name)
        if raw is not None:
            result[key] = _coerce(key, raw)
    return result


def load_effective() -> dict[str, Any]:
    """Merge all layers: built-in < declarative < user < environment."""
    effective: dict[str, Any] = dict(BUILTIN_DEFAULTS)
    for layer in (load_declarative_defaults(), load_user_config(), env_overrides()):
        effective.update({key: value for key, value in layer.items() if value is not None})
    # Keep explicit None for nullable keys so callers can distinguish "unset".
    effective.setdefault("emotion", None)
    effective.setdefault("instruct", None)
    return effective


def get_user_value(key: str) -> Any:
    if key not in CONFIG_KEYS:
        raise UsageError(f"Unknown configuration key '{key}'. Known keys: {', '.join(CONFIG_KEYS)}.")
    return load_user_config().get(key)


def set_user_value(key: str, raw: Any) -> Any:
    if key not in CONFIG_KEYS:
        raise UsageError(f"Unknown configuration key '{key}'. Known keys: {', '.join(CONFIG_KEYS)}.")
    value = _coerce(key, raw)
    data = load_user_config()
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    save_user_config(data)
    return value


def unset_user_value(key: str) -> bool:
    if key not in CONFIG_KEYS:
        raise UsageError(f"Unknown configuration key '{key}'. Known keys: {', '.join(CONFIG_KEYS)}.")
    data = load_user_config()
    existed = key in data
    data.pop(key, None)
    save_user_config(data)
    return existed


def render_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)
