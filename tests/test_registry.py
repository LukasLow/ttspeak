import pytest

from ttspeak.constants import normalize_language
from ttspeak.errors import ModelNotFound, UsageError
from ttspeak.registry import load_registry, resolve_model, validate_voice


def test_registry_has_qwen_models(env, monkeypatch):
    monkeypatch.delenv("TTSPEAK_REGISTRY", raising=False)
    models = load_registry()
    assert "qwen3:0.6b" in models
    assert "qwen3:1.7b-design" in models
    assert models["qwen3:0.6b"].method == "custom_voice"


def test_aliases_and_repo_lookup(env, monkeypatch):
    monkeypatch.delenv("TTSPEAK_REGISTRY", raising=False)
    models = load_registry()
    assert resolve_model("qwen3", models).id == "qwen3:0.6b"
    assert resolve_model("voxtral", models).id == "voxtral:4b"
    assert resolve_model("qwen3:0.6b:latest", models).id == "qwen3:0.6b"
    assert resolve_model("mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit", models).id == "qwen3:0.6b"


def test_unknown_model(env, monkeypatch):
    monkeypatch.delenv("TTSPEAK_REGISTRY", raising=False)
    with pytest.raises(ModelNotFound) as exc:
        resolve_model("qwen3:nope")
    assert "Available" in str(exc.value)


def test_validate_voice(env):
    spec = resolve_model("fake:custom")
    assert validate_voice(spec, "serena") == "Serena"
    with pytest.raises(ModelNotFound):
        validate_voice(spec, "Nobody")


def test_language_normalization():
    assert normalize_language("de") == "German"
    assert normalize_language("DE-de") == "German"
    assert normalize_language("german") == "German"
    assert normalize_language("ja") == "Japanese"
    with pytest.raises(UsageError):
        normalize_language("klingon")
