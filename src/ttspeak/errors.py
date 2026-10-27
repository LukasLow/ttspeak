"""Error types with user-facing messages."""

from __future__ import annotations


class TtspeakError(Exception):
    """Base class for expected, user-facing failures."""

    exit_code = 1


class UsageError(TtspeakError):
    """Invalid command line or configuration input."""

    exit_code = 2


class ConfigError(TtspeakError):
    """Invalid or unreadable configuration."""


class ModelNotFound(TtspeakError):
    """Unknown model id."""


class ModelNotInstalled(TtspeakError):
    """Model is known but its weights are not present."""


class VoiceError(TtspeakError):
    """Voice profile problem."""


class EngineError(TtspeakError):
    """Speech engine failed or is not available."""
