import io
import wave

import pytest

from ttspeak import speak as speak_module
from ttspeak import store, voices
from ttspeak.engines.mock import MockEngine
from ttspeak.errors import ModelNotInstalled, UsageError, VoiceError
from ttspeak.speak import SpeakOptions, speak


def quiet_progress() -> store.PullProgress:
    return store.PullProgress(stream=io.StringIO())


def capture_engine(monkeypatch):
    captured = {}
    original = MockEngine.synthesize

    def wrapped(self, request):
        captured["request"] = request
        return original(self, request)

    monkeypatch.setattr(MockEngine, "synthesize", wrapped)
    return captured


def test_mock_synthesis_writes_valid_wav(env, tmp_path):
    output = tmp_path / "out.wav"
    result = speak(
        SpeakOptions(
            text="Hallo Welt",
            model="fake:custom",
            model_explicit=True,
            play=False,
            output=str(output),
            engine="mock",
        )
    )
    assert output.is_file()
    with wave.open(str(output), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 24000
        assert handle.getnframes() > 0
    assert result.result.duration > 0
    assert result.spec.id == "fake:custom"
    assert result.speaker == "Serena"


def test_mock_does_not_require_installed_model(env, tmp_path):
    result = speak(
        SpeakOptions(
            text="Hallo",
            model="fake:custom",
            model_explicit=True,
            play=False,
            output=str(tmp_path / "out.wav"),
            engine="mock",
        )
    )
    assert result.output.is_file()


def test_default_output_goes_to_data_root(env):
    result = speak(
        SpeakOptions(
            text="Hallo",
            model="fake:custom",
            model_explicit=True,
            play=False,
            engine="mock",
        )
    )
    assert result.output.parent == env.root / "output"
    assert result.output.suffix == ".wav"


def test_emotion_language_speed_and_voice(env, tmp_path, monkeypatch):
    captured = capture_engine(monkeypatch)
    result = speak(
        SpeakOptions(
            text="Guten Tag",
            model="fake:custom",
            model_explicit=True,
            voice="ryan",
            emotion="happy",
            instruct="Slightly slower.",
            language="de",
            speed=0.9,
            play=False,
            output=str(tmp_path / "out.wav"),
            engine="mock",
        )
    )
    request = captured["request"]
    assert request.speaker == "Ryan"
    assert request.language == "German"
    assert request.speed == 0.9
    assert "happy" in request.instruct.lower()
    assert "Slightly slower." in request.instruct
    assert result.language == "German"


def test_invalid_speed_and_output(env, tmp_path):
    with pytest.raises(UsageError):
        speak(
            SpeakOptions(
                text="Hallo",
                model="fake:custom",
                model_explicit=True,
                play=False,
                output=str(tmp_path / "out.wav"),
                speed=3.0,
                engine="mock",
            )
        )
    with pytest.raises(UsageError, match="WAV"):
        speak(
            SpeakOptions(
                text="Hallo",
                model="fake:custom",
                model_explicit=True,
                play=False,
                output=str(tmp_path / "out.mp3"),
                engine="mock",
            )
        )


def test_voice_design_requires_instruction(env, tmp_path):
    options = SpeakOptions(
        text="Hallo",
        model="fake:design",
        model_explicit=True,
        play=False,
        output=str(tmp_path / "out.wav"),
        engine="mock",
    )
    with pytest.raises(UsageError, match="voice description"):
        speak(options)
    options.instruct = "A warm, low female voice."
    result = speak(options)
    assert result.spec.method == "voice_design"


def test_clone_model_without_profile_is_an_error(env, tmp_path):
    with pytest.raises(VoiceError):
        speak(
            SpeakOptions(
                text="Hallo",
                model="fake:base",
                model_explicit=True,
                play=False,
                output=str(tmp_path / "out.wav"),
                engine="mock",
            )
        )


def test_cloned_profile_is_used_for_synthesis(env, tmp_path, monkeypatch, reference_wav):
    store.pull_model("fake:base", progress=quiet_progress())
    profile = voices.add_profile("Lukas", reference_wav, "Hallo, ich bin Lukas.", model="fake:base")
    captured = capture_engine(monkeypatch)
    result = speak(
        SpeakOptions(
            text="Guten Morgen",
            voice="@Lukas",
            play=False,
            output=str(tmp_path / "out.wav"),
            engine="mock",
        )
    )
    request = captured["request"]
    assert request.method == "clone"
    assert request.ref_audio == profile.audio
    assert request.ref_text == "Hallo, ich bin Lukas."
    assert result.profile is not None
    assert result.spec.id == "fake:base"


def test_explicit_custom_model_with_profile_is_an_error(env, reference_wav):
    store.pull_model("fake:base", progress=quiet_progress())
    voices.add_profile("Lukas", reference_wav, "Hallo.", model="fake:base")
    with pytest.raises(VoiceError):
        speak(
            SpeakOptions(
                text="Hallo",
                model="fake:custom",
                model_explicit=True,
                voice="Lukas",
                play=False,
                output="/tmp/never.wav",
                engine="mock",
            )
        )


def test_playback_is_called_when_enabled(env, tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(speak_module, "play_audio", lambda path: called.append(path))
    result = speak(
        SpeakOptions(
            text="Hallo",
            model="fake:custom",
            model_explicit=True,
            play=True,
            output=str(tmp_path / "out.wav"),
            engine="mock",
        )
    )
    assert called == [result.output]


def test_mlx_requires_installed_model(env, tmp_path):
    with pytest.raises(ModelNotInstalled):
        speak(
            SpeakOptions(
                text="Hallo",
                model="fake:custom",
                model_explicit=True,
                play=False,
                output=str(tmp_path / "out.wav"),
                engine="mlx",
            )
        )
