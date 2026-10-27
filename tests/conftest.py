"""Shared fixtures: isolated home, fake static registry, CLI runner."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]

ENV_KEYS = [
    "TTSPEAK_HOME",
    "TTSPEAK_DEFAULTS",
    "TTSPEAK_MODEL",
    "TTSPEAK_VOICE",
    "TTSPEAK_LANGUAGE",
    "TTSPEAK_EMOTION",
    "TTSPEAK_INSTRUCT",
    "TTSPEAK_SPEED",
    "TTSPEAK_PLAY",
    "TTSPEAK_ENGINE",
    "TTSPEAK_PYTHON",
    "TTSPEAK_REGISTRY",
    "HF_TOKEN",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _file_entry(path: Path) -> dict[str, object]:
    return {
        "path": path.name,
        "url": path.as_uri(),
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    root = tmp_path / "home"
    blobs = tmp_path / "blobs"
    blobs.mkdir()
    weights = blobs / "model.safetensors"
    weights.write_bytes(b"fake-weights-" * 2048)
    config_file = blobs / "config.json"
    config_file.write_text('{"model_type": "qwen3_tts"}', encoding="utf-8")
    files = [_file_entry(weights), _file_entry(config_file)]

    broken = blobs / "broken.safetensors"
    broken.write_bytes(b"broken")
    broken_entry = _file_entry(broken)
    broken_entry["sha256"] = "0" * 64

    languages = ["German", "English", "French"]
    registry = {
        "version": 1,
        "models": [
            {
                "id": "fake:custom",
                "repo": "test/fake-custom",
                "method": "custom_voice",
                "description": "Fake custom voice model",
                "voices": ["Serena", "Ryan"],
                "languages": languages,
                "default_voice": "Serena",
                "size_hint": sum(int(item["size"]) for item in files),
                "source": "static",
                "files": files,
            },
            {
                "id": "fake:base",
                "repo": "test/fake-base",
                "method": "clone",
                "description": "Fake cloning model",
                "voices": [],
                "languages": languages,
                "source": "static",
                "files": files,
            },
            {
                "id": "fake:design",
                "repo": "test/fake-design",
                "method": "voice_design",
                "description": "Fake design model",
                "voices": [],
                "languages": languages,
                "source": "static",
                "files": files,
            },
            {
                "id": "fake:broken",
                "repo": "test/fake-broken",
                "method": "custom_voice",
                "description": "Checksum mismatch",
                "voices": ["Serena"],
                "languages": languages,
                "source": "static",
                "files": [broken_entry],
            },
            {
                "id": "fake:escape",
                "repo": "test/fake-escape",
                "method": "custom_voice",
                "description": "Path traversal attempt",
                "voices": ["Serena"],
                "languages": languages,
                "source": "static",
                "files": [
                    {
                        "path": "../escaped.txt",
                        "url": weights.as_uri(),
                        "size": weights.stat().st_size,
                    }
                ],
            },
        ],
    }
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    monkeypatch.setenv("TTSPEAK_HOME", str(root))
    monkeypatch.setenv("TTSPEAK_REGISTRY", str(registry_path))
    monkeypatch.setenv("TTSPEAK_ENGINE", "mock")
    monkeypatch.chdir(tmp_path)

    return SimpleNamespace(
        root=root,
        tmp=tmp_path,
        blobs=blobs,
        registry=registry_path,
        weights=weights,
        files=files,
    )


@pytest.fixture
def run_cli(env: SimpleNamespace, tmp_path: Path):
    def run(*args: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        existing = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(REPO / "src") + (os.pathsep + existing if existing else "")
        return subprocess.run(
            [sys.executable, "-m", "ttspeak", *args],
            check=False,
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )

    return run


@pytest.fixture
def reference_wav(tmp_path: Path) -> Path:
    import math
    import struct
    import wave

    path = tmp_path / "reference.wav"
    rate = 16000
    samples = []
    for index in range(rate // 2):
        value = 0.1 * math.sin(2 * math.pi * 180 * index / rate)
        samples.append(struct.pack("<h", int(value * 32767)))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"".join(samples))
    return path
