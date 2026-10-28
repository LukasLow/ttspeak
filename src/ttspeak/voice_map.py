"""Resolve configured language and gender aliases to model + speaker pairs."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import GENDERS
from .errors import ConfigError


@dataclass(frozen=True)
class VoiceSpec:
    alias: str
    model: str
    speaker: str


def _validate_entry(alias: str, entry: dict[str, object]) -> VoiceSpec:
    model = str(entry.get("model") or "").strip()
    speaker = str(entry.get("voice") or "").strip()
    if not model or not speaker:
        raise ConfigError(f"Voice '{alias}' needs both 'model' and 'voice'.")
    return VoiceSpec(alias=alias, model=model, speaker=speaker)


def resolve_alias(
    voices: dict[str, object] | None,
    name: str,
    *,
    default_gender: str = "female",
) -> VoiceSpec | None:
    """Resolve ``de`` -> ``de_female`` -> ``{model, voice}`` or return None."""
    if not voices:
        return None
    if default_gender not in GENDERS:
        raise ConfigError(
            f"Unknown default gender '{default_gender}'. Choose one of: {', '.join(GENDERS)}."
        )

    current = name.strip()
    if not current:
        return None
    seen: set[str] = set()

    while current:
        if current in seen:
            chain = " -> ".join([*seen, current])
            raise ConfigError(f"Voice alias cycle: {chain}.")
        seen.add(current)

        entry = voices.get(current)
        if entry is None:
            # Generic language alias: `de` falls back to `de_female`.
            fallback = f"{current}_{default_gender}"
            if "_" not in current and fallback in voices:
                current = fallback
                continue
            return None

        if isinstance(entry, str):
            current = entry.strip()
            continue
        if isinstance(entry, dict):
            return _validate_entry(current, entry)
        raise ConfigError(
            f"Voice '{current}' must be an alias string or an object with model and voice."
        )

    return None
