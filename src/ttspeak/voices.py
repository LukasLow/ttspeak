"""Cloned voice profiles (reference audio + transcript)."""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths
from .errors import ModelNotFound, UsageError, VoiceError
from .registry import METHOD_CLONE, resolve_model
from .store import require_installed
from .util import confirm, read_json, sha256_file, slugify, utc_now, write_json

PROFILE_NAME = "profile.json"
REFERENCE_NAME = "reference.wav"


@dataclass
class VoiceProfile:
    name: str
    slug: str
    model: str
    ref_text: str
    path: Path
    audio: Path
    sha256: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": 1,
            "name": self.name,
            "slug": self.slug,
            "model": self.model,
            "ref_text": self.ref_text,
            "audio": self.audio.name,
            "sha256": self.sha256,
            "created_at": self.created_at,
        }


def _profile_dir(slug: str) -> Path:
    return paths.voices_dir() / slug


def _load_profile(directory: Path) -> VoiceProfile | None:
    data = read_json(directory / PROFILE_NAME, default=None)
    if not isinstance(data, dict):
        return None
    try:
        audio_name = str(data.get("audio", REFERENCE_NAME))
        audio = directory / audio_name
        return VoiceProfile(
            name=str(data["name"]),
            slug=str(data.get("slug", directory.name)),
            model=str(data["model"]),
            ref_text=str(data["ref_text"]),
            path=directory,
            audio=audio,
            sha256=str(data.get("sha256", "")),
            created_at=str(data.get("created_at", "")),
        )
    except (KeyError, TypeError):
        return None


def list_profiles() -> list[VoiceProfile]:
    root = paths.voices_dir()
    if not root.is_dir():
        return []
    profiles: list[VoiceProfile] = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            profile = _load_profile(entry)
            if profile is not None:
                profiles.append(profile)
    return profiles


def get_profile(name: str) -> VoiceProfile | None:
    wanted = name.lstrip("@").strip().lower()
    for profile in list_profiles():
        if profile.name.lower() == wanted or profile.slug == wanted:
            return profile
    return None


def profiles_for_model(model_id: str) -> list[VoiceProfile]:
    from .registry import resolve_model

    try:
        canonical = resolve_model(model_id).id
    except ModelNotFound:
        canonical = model_id
    return [profile for profile in list_profiles() if profile.model == canonical]


def add_profile(
    name: str,
    audio: Path,
    ref_text: str,
    *,
    model: str | None = None,
    force: bool = False,
) -> VoiceProfile:
    display_name = name.strip()
    if not display_name or any(sep in display_name for sep in ("/", "\\", "\x00")):
        raise VoiceError("Voice name must be a non-empty name without path separators.")
    if len(display_name) > 64:
        raise VoiceError("Voice name must be at most 64 characters.")
    if display_name.startswith("@"):
        raise VoiceError("Voice names must not start with '@'; it is reserved for lookup.")

    ref_text = ref_text.strip()
    if not ref_text:
        raise VoiceError("A transcript of the reference audio is required (--text).")

    source = audio.expanduser()
    if not source.is_file():
        raise VoiceError(f"Reference audio not found: {source}")

    spec = resolve_model(model or "qwen3:0.6b-base")
    if spec.method != METHOD_CLONE:
        raise VoiceError(
            f"Model {spec.id} cannot clone voices (method: {spec.method}). "
            "Use a Base model such as qwen3:0.6b-base."
        )
    require_installed(spec.id)

    slug = slugify(display_name)
    directory = _profile_dir(slug)
    existing = _load_profile(directory)
    if existing is not None and not force:
        raise VoiceError(f"Voice profile '{existing.name}' already exists. Use --force to replace it.")

    directory.mkdir(parents=True, exist_ok=True)
    target_audio = directory / REFERENCE_NAME
    if source.resolve() != target_audio.resolve():
        shutil.copy2(source, target_audio)

    profile = VoiceProfile(
        name=display_name,
        slug=slug,
        model=spec.id,
        ref_text=ref_text,
        path=directory,
        audio=target_audio,
        sha256=sha256_file(target_audio),
        created_at=utc_now(),
    )
    write_json(directory / PROFILE_NAME, profile.to_dict())
    return profile


def remove_profile(name: str, *, assume_yes: bool = False) -> VoiceProfile:
    profile = get_profile(name)
    if profile is None:
        raise VoiceError(f"Voice profile '{name}' does not exist.")
    if not confirm(
        f"Remove voice profile '{profile.name}' and its reference audio at {profile.path}?",
        assume_yes=assume_yes,
    ):
        raise UsageError("Cancelled.")
    shutil.rmtree(profile.path)
    return profile


def prune_profiles(keep: Iterable[str], *, assume_yes: bool = False) -> list[str]:
    keep_slugs = {slugify(item.lstrip("@")) for item in keep}
    removable = [profile for profile in list_profiles() if profile.slug not in keep_slugs]
    if not removable:
        return []
    names = ", ".join(profile.name for profile in removable)
    if not confirm(f"Remove {len(removable)} voice profile(s): {names}?", assume_yes=assume_yes):
        raise UsageError("Cancelled.")
    removed: list[str] = []
    for profile in removable:
        shutil.rmtree(profile.path)
        removed.append(profile.name)
    return removed
