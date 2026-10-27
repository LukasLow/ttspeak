from ttspeak.engines.mlx import (
    MISTRAL_COMMON_VERSION,
    MLX_AUDIO_VERSION,
    _pip_packages,
    _version_tuple,
)


def test_runtime_pins_voxtral_dependencies():
    packages = _pip_packages(None)
    assert f"mlx-audio[tts]=={MLX_AUDIO_VERSION}" in packages
    assert f"mistral-common[audio]=={MISTRAL_COMMON_VERSION}" in packages
    assert MISTRAL_COMMON_VERSION == "1.12.0"


def test_runtime_version_override():
    packages = _pip_packages("0.6.3")
    assert "mlx-audio[tts]==0.6.3" in packages
    assert f"mistral-common[audio]=={MISTRAL_COMMON_VERSION}" in packages


def test_version_tuple_ordering():
    assert _version_tuple("1.12.0") > _version_tuple("1.9.1")
    assert _version_tuple("0.6.2") == (0, 6, 2)
    assert _version_tuple("1.12.0rc1") == (1, 12, 0)
