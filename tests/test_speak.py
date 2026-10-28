import io
import json
import os
import wave

import pytest

from ttspeak import speak as speak_module
from ttspeak import store, voices
from ttspeak.engines.base import SynthesisResult
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
    with pytest.raises(UsageError, match="Unsupported output format"):
        speak(
            SpeakOptions(
                text="Hallo",
                model="fake:custom",
                model_explicit=True,
                play=False,
                output=str(tmp_path / "out.xyz"),
                engine="mock",
            )
        )


def test_preset_voice_model_uses_default_voice(env, tmp_path, monkeypatch):
    captured = capture_engine(monkeypatch)
    result = speak(
        SpeakOptions(
            text="Guten Tag",
            model="fake:preset",
            model_explicit=True,
            play=False,
            output=str(tmp_path / "preset.wav"),
            engine="mock",
        )
    )
    request = captured["request"]
    assert request.method == "preset_voice"
    assert request.speaker == "de_female"
    assert result.speaker == "de_female"


def test_preset_voice_model_rejects_unsupported_language(env, tmp_path):
    with pytest.raises(UsageError, match="does not support English"):
        speak(
            SpeakOptions(
                text="Hello",
                model="fake:preset",
                model_explicit=True,
                language="en",
                play=False,
                output=str(tmp_path / "preset.wav"),
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


def test_live_streaming_uses_mlx_stream(env, monkeypatch):
    store.pull_model("fake:custom", progress=quiet_progress())
    captured = {}

    class FakeMlx:
        def __init__(self):
            pass

        def synthesize(self, request):
            captured["request"] = request
            return SynthesisResult(
                output=None,
                duration=1.0,
                sample_rate=24000,
                chunks=3,
                streamed=True,
            )

    monkeypatch.setattr("ttspeak.engines.mlx.MlxEngine", FakeMlx)
    monkeypatch.setattr(speak_module, "play_audio", lambda path: pytest.fail("double playback"))
    result = speak(
        SpeakOptions(
            text="Hallo",
            model="fake:custom",
            model_explicit=True,
            play=True,
            engine="mlx",
        )
    )
    assert captured["request"].stream is True
    assert captured["request"].output is None
    assert result.result.streamed is True
    assert result.output is None


def test_output_file_disables_streaming(env, tmp_path, monkeypatch):
    store.pull_model("fake:custom", progress=quiet_progress())
    captured = {}
    played = []

    class FakeMlx:
        def __init__(self):
            pass

        def synthesize(self, request):
            captured["request"] = request
            assert request.output is not None
            request.output.write_bytes(b"RIFFfake")
            return SynthesisResult(output=request.output, duration=1.0, sample_rate=24000)

    monkeypatch.setattr("ttspeak.engines.mlx.MlxEngine", FakeMlx)
    monkeypatch.setattr(speak_module, "play_audio", lambda path: played.append(path))
    output = tmp_path / "file.wav"
    result = speak(
        SpeakOptions(
            text="Hallo",
            model="fake:custom",
            model_explicit=True,
            play=True,
            output=str(output),
            engine="mlx",
        )
    )
    assert captured["request"].stream is False
    assert result.result.streamed is False
    assert played == [output]


def test_mp3_output_uses_ffmpeg(env, tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ffmpeg = bin_dir / "ffmpeg"
    ffmpeg.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "source = args[args.index('-i') + 1]\n"
        "pathlib.Path(args[-1]).write_bytes(b'ID3fake')\n",
        encoding="utf-8",
    )
    ffmpeg.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    output = tmp_path / "out.mp3"
    result = speak(
        SpeakOptions(
            text="Hallo",
            model="fake:custom",
            model_explicit=True,
            play=False,
            output=str(output),
            engine="mock",
        )
    )
    assert result.output == output
    assert output.read_bytes() == b"ID3fake"
    assert not list((env.root / "tmp").glob("ttspeak-*.wav"))


def test_mp3_requires_ffmpeg(env, tmp_path, monkeypatch):
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    with pytest.raises(UsageError, match="needs ffmpeg"):
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


def test_output_without_suffix_gets_wav(env, tmp_path):
    result = speak(
        SpeakOptions(
            text="Hallo",
            model="fake:custom",
            model_explicit=True,
            play=False,
            output=str(tmp_path / "audio"),
            engine="mock",
        )
    )
    assert result.output == tmp_path / "audio.wav"
    assert result.output.is_file()


def _configured_voices(monkeypatch, tmp_path, data):
    defaults = tmp_path / "defaults.json"
    defaults.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("TTSPEAK_DEFAULTS", str(defaults))


def _voice_defaults():
    return {
        "model": "fake:custom",
        "language": "auto",
        "default_gender": "female",
        "voices": {
            "de": "de_female",
            "de_female": {"model": "fake:custom", "voice": "Serena"},
            "en": "en_female",
            "en_female": {"model": "fake:custom", "voice": "Ryan"},
            "ru": "ru_female",
            "ru_female": {"model": "fake:custom", "voice": "Serena"},
        },
    }


def test_auto_segments_use_configured_voices_and_one_file(env, tmp_path, monkeypatch):
    _configured_voices(monkeypatch, tmp_path, _voice_defaults())
    output = tmp_path / "mixed.wav"
    result = speak(
        SpeakOptions(
            text="Guten Abend. Good evening. Добрый вечер.",
            play=False,
            output=str(output),
            engine="mock",
        )
    )
    assert output.is_file()
    assert result.languages == ["German", "English", "Russian"]
    assert [segment.plan.speaker for segment in result.segments] == [
        "Serena",
        "Ryan",
        "Serena",
    ]
    assert [segment.plan.voice_alias for segment in result.segments] == [
        "de_female",
        "en_female",
        "ru_female",
    ]
    assert result.result.duration > 0


def test_single_russian_word_uses_configured_ru_voice(env, tmp_path, monkeypatch):
    _configured_voices(monkeypatch, tmp_path, _voice_defaults())
    result = speak(
        SpeakOptions(
            text="Когда",
            play=False,
            output=str(tmp_path / "ru.wav"),
            engine="mock",
        )
    )
    assert result.languages == ["Russian"]
    assert result.segments[0].plan.spec.id == "fake:custom"
    assert result.segments[0].plan.voice_alias == "ru_female"
    assert result.segments[0].plan.speaker == "Serena"


def test_explicit_voice_alias_forces_one_voice(env, tmp_path, monkeypatch):
    _configured_voices(monkeypatch, tmp_path, _voice_defaults())
    result = speak(
        SpeakOptions(
            text="Good evening. Guten Abend.",
            voice="de",
            play=False,
            output=str(tmp_path / "alias.wav"),
            engine="mock",
        )
    )
    assert len(result.segments) == 2
    assert {segment.plan.spec.id for segment in result.segments} == {"fake:custom"}
    assert {segment.plan.speaker for segment in result.segments} == {"Serena"}


def test_live_multi_language_uses_one_stream_per_segment(env, monkeypatch, tmp_path):
    _configured_voices(monkeypatch, tmp_path, _voice_defaults())
    store.pull_model("fake:custom", progress=quiet_progress())
    requests = []

    class FakeMlx:
        def __init__(self):
            pass

        def synthesize(self, request):
            requests.append(request)
            return SynthesisResult(
                output=None,
                duration=1.0,
                sample_rate=24000,
                chunks=2,
                streamed=True,
            )

    monkeypatch.setattr("ttspeak.engines.mlx.MlxEngine", FakeMlx)
    monkeypatch.setattr(speak_module, "play_audio", lambda path: pytest.fail("double playback"))
    result = speak(
        SpeakOptions(
            text="Guten Abend. Good evening. Добрый вечер.",
            play=True,
            engine="mlx",
        )
    )
    assert len(requests) == 3
    assert all(request.stream is True and request.output is None for request in requests)
    assert [request.language for request in requests] == ["German", "English", "Russian"]
    assert result.result.streamed is True
    assert result.output is None
    assert result.result.duration == 3.0
