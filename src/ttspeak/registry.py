"""Model registry shipped with ttspeak (overridable for tests)."""

from __future__ import annotations

import difflib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ModelNotFound

METHOD_CUSTOM_VOICE = "custom_voice"
METHOD_VOICE_DESIGN = "voice_design"
METHOD_PRESET_VOICE = "preset_voice"
METHOD_CLONE = "clone"
METHODS = (METHOD_CUSTOM_VOICE, METHOD_VOICE_DESIGN, METHOD_PRESET_VOICE, METHOD_CLONE)

METHOD_LABELS = {
    METHOD_CUSTOM_VOICE: "preset voices + emotion instructions",
    METHOD_VOICE_DESIGN: "voice designed from a text description",
    METHOD_PRESET_VOICE: "preset voices (multilingual TTS)",
    METHOD_CLONE: "voice cloning from reference audio",
}


@dataclass(frozen=True)
class ModelSpec:
    id: str
    repo: str
    method: str
    description: str = ""
    voices: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    default_voice: str | None = None
    size_hint: int | None = None
    source: str = "hf"
    files: tuple[dict[str, Any], ...] = ()
    extra: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @classmethod
    def from_dict(cls, entry: dict[str, Any]) -> ModelSpec:
        return _build_spec(entry)

    def to_manifest(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "repo": self.repo,
            "method": self.method,
            "description": self.description,
            "voices": list(self.voices),
            "languages": list(self.languages),
            "default_voice": self.default_voice,
            "size_hint": self.size_hint,
            "source": self.source,
        }
        if self.files:
            data["files"] = list(self.files)
        return data


def _package_registry_path() -> Path:
    return Path(__file__).with_name("data") / "registry.json"


def registry_path() -> Path:
    override = os.environ.get("TTSPEAK_REGISTRY")
    if override:
        return Path(override).expanduser()
    return _package_registry_path()


def _build_spec(entry: dict[str, Any]) -> ModelSpec:
    model_id = entry.get("id")
    repo = entry.get("repo")
    method = entry.get("method")
    if not model_id or not repo or not method:
        raise ValueError(f"Registry entry needs id, repo and method: {entry!r}")
    if method not in METHODS:
        raise ValueError(f"Unknown method '{method}' for {model_id}")
    return ModelSpec(
        id=model_id,
        repo=repo,
        method=method,
        description=entry.get("description", ""),
        voices=tuple(entry.get("voices", ())),
        languages=tuple(entry.get("languages", ())),
        default_voice=entry.get("default_voice"),
        size_hint=entry.get("size_hint"),
        source=entry.get("source", "hf"),
        files=tuple(entry.get("files", ())),
        extra={k: v for k, v in entry.items() if k not in {"id", "repo", "method"}},
    )


def load_registry(path: Path | None = None) -> dict[str, ModelSpec]:
    target = path or registry_path()
    try:
        with target.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise ModelNotFound(f"Model registry not found: {target}") from exc
    except json.JSONDecodeError as exc:
        raise ModelNotFound(f"Invalid model registry {target}: {exc}") from exc

    entries = data.get("models", [])
    if not isinstance(entries, list):
        raise TypeError(f"Registry {target} must contain a 'models' list.")
    return {entry["id"]: _build_spec(entry) for entry in entries}


def _normalize_query(query: str) -> str:
    value = query.strip()
    value = value.removesuffix(":latest")
    return value


def resolve_model(query: str, registry: dict[str, ModelSpec] | None = None) -> ModelSpec:
    models = registry if registry is not None else load_registry()
    value = _normalize_query(query)

    if value in models:
        return models[value]
    if value == "qwen3" and "qwen3:0.6b" in models:
        return models["qwen3:0.6b"]
    if value == "voxtral" and "voxtral:4b" in models:
        return models["voxtral:4b"]
    for spec in models.values():
        if value == spec.repo:
            return spec

    candidates = difflib.get_close_matches(value, list(models), n=3, cutoff=0.4)
    hint = f" Did you mean: {', '.join(candidates)}?" if candidates else ""
    available = ", ".join(sorted(models))
    raise ModelNotFound(f"Unknown model '{query}'. Available: {available}.{hint}")


def installed_model_ids() -> list[str]:
    from .store import list_installed

    return [item.spec.id for item in list_installed()]


def validate_voice(spec: ModelSpec, voice: str) -> str:
    """Return the canonical preset speaker name for a model."""
    for candidate in spec.voices:
        if candidate.lower() == voice.lower():
            return candidate
    voices = ", ".join(spec.voices) or "none"
    raise ModelNotFound(f"Model {spec.id} has no preset voice '{voice}'. Available: {voices}.")
