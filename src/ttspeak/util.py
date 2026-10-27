"""Small standard-library helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import UsageError


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1000


def slugify(value: str) -> str:
    """Turn a model id or voice name into a safe directory name."""
    slug = value.strip().lower()
    slug = slug.replace("@", "")
    slug = re.sub(r"[^a-z0-9._-]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-.")
    return slug or "item"


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError) as exc:
        from .errors import ConfigError

        raise ConfigError(f"Cannot read JSON file {path}: {exc}") from exc


def write_json(path: Path, data: Any, *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        if private:
            os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def confirm(prompt: str, *, assume_yes: bool = False) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise UsageError(f"{prompt} Refusing to continue without --yes in a non-interactive shell.")
    answer = input(f"{prompt} [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def default_output_path() -> Path:
    from . import paths

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return paths.output_dir() / f"ttspeak-{stamp}.wav"


def find_player() -> list[str] | None:
    if sys.platform == "darwin" and shutil.which("afplay"):
        return ["afplay"]
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
    if sys.platform.startswith("linux") and shutil.which("aplay"):
        return ["aplay", "-q"]
    return None


def play_audio(path: Path) -> None:
    player = find_player()
    if player is None:
        print(f"No audio player found; file kept at {path}", file=sys.stderr)
        return
    try:
        subprocess.run([*player, str(path)], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise UsageError(f"Could not play {path}: {exc}") from exc


def format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    minutes, rest = divmod(seconds, 60)
    if minutes:
        return f"{int(minutes)}m {rest:.1f}s"
    return f"{seconds:.1f}s"


def elapsed(start: float) -> str:
    return format_duration(time.monotonic() - start)
