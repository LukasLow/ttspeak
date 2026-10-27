"""Generate the built-in model registry from Hugging Face metadata (dev helper)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "ttspeak" / "data" / "registry.json"

QWEN_VOICES = [
    "Vivian",
    "Serena",
    "Uncle_Fu",
    "Dylan",
    "Eric",
    "Ryan",
    "Aiden",
    "Ono_Anna",
    "Sohee",
]
QWEN_LANGUAGES = [
    "Chinese",
    "English",
    "Japanese",
    "Korean",
    "German",
    "French",
    "Russian",
    "Portuguese",
    "Spanish",
    "Italian",
]
VOXTRAL_VOICES = [
    "de_female",
    "de_male",
    "casual_female",
    "casual_male",
    "cheerful_female",
    "neutral_female",
    "neutral_male",
    "fr_female",
    "fr_male",
    "es_female",
    "es_male",
    "it_female",
    "it_male",
    "pt_female",
    "pt_male",
    "nl_female",
    "nl_male",
    "ar_male",
    "hi_female",
    "hi_male",
]
VOXTRAL_LANGUAGES = [
    "English",
    "French",
    "Spanish",
    "German",
    "Italian",
    "Portuguese",
    "Dutch",
    "Arabic",
    "Hindi",
]


def repo_size(repo: str) -> int | None:
    url = f"https://huggingface.co/api/models/{repo}?blobs=true"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        print(f"  {repo}: HTTP {exc.code}")
        return None
    return sum(int(item.get("size") or 0) for item in data.get("siblings", []))


def qwen_entry(size: str, kind: str, quant: str, repo: str) -> dict[str, object]:
    base_id = {
        ("0.6B", "CustomVoice"): "qwen3:0.6b",
        ("1.7B", "CustomVoice"): "qwen3:1.7b",
        ("0.6B", "Base"): "qwen3:0.6b-base",
        ("1.7B", "Base"): "qwen3:1.7b-base",
        ("1.7B", "VoiceDesign"): "qwen3:1.7b-design",
    }[(size, kind)]
    suffix = "" if quant == "8bit" else f"-{quant}"
    method = {
        "CustomVoice": "custom_voice",
        "Base": "clone",
        "VoiceDesign": "voice_design",
    }[kind]
    labels = {
        "CustomVoice": "preset voices + emotion control",
        "Base": "voice cloning",
        "VoiceDesign": "voice design from text",
    }
    entry: dict[str, object] = {
        "id": f"{base_id}{suffix}",
        "repo": repo,
        "method": method,
        "description": f"Qwen3-TTS {size} {kind}, {quant}. {labels[kind]}.",
        "voices": QWEN_VOICES if method == "custom_voice" else [],
        "languages": QWEN_LANGUAGES,
        "default_voice": "Serena" if method == "custom_voice" else None,
    }
    size_bytes = repo_size(repo)
    if size_bytes:
        entry["size_hint"] = size_bytes
    return entry


def voxtral_entry(quant: str, repo: str) -> dict[str, object]:
    suffix = "" if quant == "4bit" else f"-{quant}"
    entry: dict[str, object] = {
        "id": f"voxtral:4b{suffix}",
        "repo": repo,
        "method": "preset_voice",
        "description": (
            f"Voxtral 4B TTS, {quant}, 20 voices and 9 languages including German."
        ),
        "voices": VOXTRAL_VOICES,
        "languages": VOXTRAL_LANGUAGES,
        "default_voice": "de_female",
    }
    size_bytes = repo_size(repo)
    if size_bytes:
        entry["size_hint"] = size_bytes
    return entry


def main() -> None:
    models: list[dict[str, object]] = []

    print("Voxtral")
    for quant in ("4bit", "6bit", "bf16"):
        repo = f"mlx-community/Voxtral-4B-TTS-2603-mlx-{quant}"
        models.append(voxtral_entry(quant, repo))
        time.sleep(0.2)

    for size in ("0.6B", "1.7B"):
        for kind in ("CustomVoice", "Base", "VoiceDesign"):
            if size == "0.6B" and kind == "VoiceDesign":
                continue
            for quant in ("4bit", "6bit", "8bit", "bf16"):
                repo = f"mlx-community/Qwen3-TTS-12Hz-{size}-{kind}-{quant}"
                print(f"Qwen {size} {kind} {quant}")
                models.append(qwen_entry(size, kind, quant, repo))
                time.sleep(0.2)

    data = {
        "version": 1,
        "updated": "2026-10-27",
        "models": models,
    }
    TARGET.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(models)} models to {TARGET}")


if __name__ == "__main__":
    main()
