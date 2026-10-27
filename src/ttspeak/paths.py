"""Filesystem locations used by ttspeak.

All paths are resolved lazily from the environment so tests can isolate a run by
setting ``TTSPEAK_HOME``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "ttspeak"


def home() -> Path:
    """Return the ttspeak data root."""
    override = os.environ.get("TTSPEAK_HOME")
    if override:
        return Path(override).expanduser()

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME

    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / APP_NAME


def models_dir() -> Path:
    return home() / "models"


def voices_dir() -> Path:
    return home() / "voices"


def runtime_dir() -> Path:
    return home() / "runtime"


def runtime_python() -> Path:
    return runtime_dir() / "venv" / "bin" / "python"


def output_dir() -> Path:
    return home() / "output"


def config_path() -> Path:
    return home() / "config.json"


def tmp_dir() -> Path:
    return home() / "tmp"


def ensure_runtime_dirs() -> None:
    for directory in (home(), models_dir(), voices_dir(), tmp_dir(), output_dir()):
        directory.mkdir(parents=True, exist_ok=True)
