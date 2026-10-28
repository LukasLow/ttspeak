"""Shared constants: defaults, emotions, languages, preset speakers."""

from __future__ import annotations

from .errors import UsageError

APP_VERSION = "0.1.0"

AUTO_LANGUAGE = "auto"
GENDERS = ("female", "male")

BUILTIN_DEFAULTS: dict[str, object] = {
    "model": "voxtral:4b",
    "voice": None,
    "language": AUTO_LANGUAGE,
    "default_gender": "female",
    "voices": {},
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


def normalize_language(value: str, *, allow_auto: bool = False) -> str:
    """Map ``de``, ``DE``, ``de-DE`` or ``German`` to the canonical name."""
    raw = value.strip()
    if not raw:
        raise UsageError("Language must not be empty.")
    if raw.lower() == AUTO_LANGUAGE:
        if allow_auto:
            return AUTO_LANGUAGE
        raise UsageError("'auto' is only valid as a configured language, not as a segment language.")
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


def normalize_gender(value: str) -> str:
    raw = value.strip().lower()
    if raw not in GENDERS:
        raise UsageError(f"Unsupported gender '{value}'. Choose one of: {', '.join(GENDERS)}.")
    return raw


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
