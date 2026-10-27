"""Shared constants: defaults, emotions, languages, preset speakers."""

from __future__ import annotations

from .errors import UsageError

APP_VERSION = "0.1.0"

BUILTIN_DEFAULTS: dict[str, object] = {
    "model": "qwen3:0.6b",
    "voice": None,
    "language": "German",
    "speed": 1.0,
    "play": True,
    "emotion": None,
    "instruct": None,
}

CONFIG_KEYS = tuple(BUILTIN_DEFAULTS)
BOOL_KEYS = {"play"}
FLOAT_KEYS = {"speed"}

EMOTION_INSTRUCTS: dict[str, str | None] = {
    "neutral": None,
    "happy": "Speak in a happy, warm and cheerful tone.",
    "sad": "Speak in a sad, soft and subdued tone.",
    "angry": "Speak in an angry, intense tone.",
    "excited": "Speak with excitement and high energy.",
    "calm": "Speak calmly, slowly and gently.",
    "serious": "Speak in a serious, measured tone.",
    "whisper": "Speak in a soft whisper.",
}

LANGUAGE_NAMES: dict[str, str] = {
    "zh": "Chinese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "de": "German",
    "fr": "French",
    "ru": "Russian",
    "pt": "Portuguese",
    "es": "Spanish",
    "it": "Italian",
}

PRESET_VOICES: tuple[str, ...] = (
    "Vivian",
    "Serena",
    "Uncle_Fu",
    "Dylan",
    "Eric",
    "Ryan",
    "Aiden",
    "Ono_Anna",
    "Sohee",
)


def normalize_language(value: str) -> str:
    """Map ``de``, ``DE``, ``de-DE`` or ``German`` to the canonical name."""
    raw = value.strip()
    if not raw:
        raise UsageError("Language must not be empty.")
    if raw.lower() in LANGUAGE_NAMES:
        return LANGUAGE_NAMES[raw.lower()]
    prefix = raw.split("-")[0].split("_")[0].lower()
    if prefix in LANGUAGE_NAMES:
        return LANGUAGE_NAMES[prefix]
    for name in LANGUAGE_NAMES.values():
        if raw.lower() == name.lower():
            return name
    supported = ", ".join(f"{code}={name}" for code, name in LANGUAGE_NAMES.items())
    raise UsageError(f"Unsupported language '{value}'. Supported: {supported}.")


def compose_instruct(emotion: str | None, instruct: str | None) -> str | None:
    """Combine an emotion preset with a free-form instruction."""
    parts: list[str] = []
    if emotion:
        key = emotion.strip().lower()
        if key not in EMOTION_INSTRUCTS:
            raise UsageError(
                f"Unknown emotion '{emotion}'. Choose one of: {', '.join(EMOTION_INSTRUCTS)}."
            )
        preset = EMOTION_INSTRUCTS[key]
        if preset:
            parts.append(preset)
    if instruct and instruct.strip():
        parts.append(instruct.strip())
    return " ".join(parts) or None
