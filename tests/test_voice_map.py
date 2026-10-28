import pytest

from ttspeak.errors import ConfigError
from ttspeak.voice_map import resolve_alias

VOICES = {
    "de": "de_female",
    "de_female": {"model": "voxtral:4b", "voice": "de_female"},
    "en": "en_female",
    "en_female": {"model": "voxtral:4b", "voice": "it_female"},
    "ru": "ru_female",
    "ru_female": {"model": "qwen3:1.7b", "voice": "Sohee"},
}


def test_resolves_language_alias_chain():
    voice = resolve_alias(VOICES, "de")
    assert voice is not None
    assert voice.alias == "de_female"
    assert voice.model == "voxtral:4b"
    assert voice.speaker == "de_female"


def test_resolves_generic_language_fallback():
    voice = resolve_alias(VOICES, "en_female")
    assert voice is not None
    assert voice.speaker == "it_female"


def test_unknown_alias_returns_none():
    assert resolve_alias(VOICES, "fr") is None


def test_alias_cycle_is_an_error():
    with pytest.raises(ConfigError, match="cycle"):
        resolve_alias({"a": "b", "b": "a"}, "a")


def test_invalid_voice_entry_is_an_error():
    with pytest.raises(ConfigError, match="needs both"):
        resolve_alias({"de": {"model": "voxtral:4b"}}, "de")
