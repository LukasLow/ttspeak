"""Check which MLX model variants exist on Hugging Face (dev helper)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

BASE = "https://huggingface.co/api/models/{}"
QWEN_SIZES = ("0.6B", "1.7B")
QWEN_TYPES = ("Base", "CustomVoice", "VoiceDesign")
QWEN_QUANTS = ("4bit", "6bit", "8bit", "bf16")
VOXTRAL_QUANTS = ("4bit", "6bit", "8bit", "bf16")


def check(repo: str) -> dict[str, object] | None:
    try:
        with urllib.request.urlopen(BASE.format(repo), timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 404):
            return {"repo": repo, "error": exc.code}
        raise
    return {
        "repo": repo,
        "sha": data.get("sha"),
        "storage": data.get("usedStorage"),
        "safetensors": data.get("safetensors", {}).get("total"),
    }


def main() -> None:
    repos = [
        f"mlx-community/Qwen3-TTS-12Hz-{size}-{kind}-{quant}"
        for size in QWEN_SIZES
        for kind in QWEN_TYPES
        for quant in QWEN_QUANTS
    ]
    repos += [
        f"mlx-community/Voxtral-4B-TTS-2603-mlx-{quant}" for quant in VOXTRAL_QUANTS
    ]
    for repo in repos:
        info = check(repo)
        print(json.dumps(info) if info else f"MISSING {repo}")
        time.sleep(0.2)


if __name__ == "__main__":
    main()
