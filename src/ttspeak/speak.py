"""Resolve settings and run one synthesis."""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import audio, config, paths, voices
from .constants import compose_instruct, normalize_language
from .engines.base import SynthesisRequest, SynthesisResult
from .engines.mock import MockEngine
from .errors import UsageError, VoiceError
from .registry import (
    METHOD_CLONE,
    METHOD_CUSTOM_VOICE,
    METHOD_PRESET_VOICE,
    METHOD_VOICE_DESIGN,
    ModelSpec,
    resolve_model,
    validate_voice,
)
from .store import require_installed
from .util import default_output_path, play_audio


@dataclass
class SpeakOptions:
    text: str
    model: str | None = None
    model_explicit: bool = False
    voice: str | None = None
    language: str | None = None
    speed: float | None = None
    emotion: str | None = None
    instruct: str | None = None
    play: bool | None = None
    output: str | None = None
    engine: str | None = None


@dataclass
class SpeakResult:
    result: SynthesisResult
    spec: ModelSpec
    engine: str
    speaker: str | None = None
    profile: voices.VoiceProfile | None = None
    instruct: str | None = None
    language: str = "German"
    speed: float = 1.0
    format: str = "wav"
    warnings: list[str] = field(default_factory=list)

    @property
    def output(self) -> Path | None:
        return self.result.output


def _effective(options: SpeakOptions) -> dict[str, object]:
    settings = config.load_effective()
    if options.model is not None:
        settings["model"] = options.model
    if options.voice is not None:
        settings["voice"] = options.voice
    if options.language is not None:
        settings["language"] = options.language
    if options.speed is not None:
        if not 0.5 <= options.speed <= 2.0:
            raise UsageError("--speed must be between 0.5 and 2.0.")
        settings["speed"] = options.speed
    if options.emotion is not None:
        settings["emotion"] = options.emotion
    if options.instruct is not None:
        settings["instruct"] = options.instruct
    if options.play is not None:
        settings["play"] = options.play
    return settings


def _select_profile(voice: str | None) -> voices.VoiceProfile | None:
    if not voice:
        return None
    return voices.get_profile(voice)


def _resolve_model_and_voice(
    options: SpeakOptions,
    settings: dict[str, object],
) -> tuple[ModelSpec, voices.VoiceProfile | None, str | None, str | None]:
    voice_value = str(settings.get("voice") or "").strip() or None
    profile = _select_profile(voice_value)

    model_value = str(settings.get("model") or "").strip() or None
    if profile is not None and not options.model_explicit:
        spec = resolve_model(profile.model)
    elif model_value is None:
        if profile is not None:
            spec = resolve_model(profile.model)
        else:
            raise UsageError("No model configured. Set one with: ttspeak config set model voxtral:4b")
    else:
        spec = resolve_model(model_value)

    if profile is not None:
        if spec.method != METHOD_CLONE:
            raise VoiceError(
                f"Voice '{profile.name}' is a cloned profile and needs a Base model, "
                f"but {spec.id} uses {spec.method}. "
                "Omit -m or use a Base model such as qwen3:0.6b-base."
            )
        if not profile.audio.is_file():
            raise VoiceError(f"Reference audio for '{profile.name}' is missing: {profile.audio}")
        if options.voice is not None and spec.method != METHOD_CLONE:
            raise VoiceError("Cloned voices require a Base model.")
        return spec, profile, None, None

    if spec.method in {METHOD_CUSTOM_VOICE, METHOD_PRESET_VOICE}:
        if not voice_value:
            voice_value = spec.default_voice or (spec.voices[0] if spec.voices else None)
        if not voice_value:
            raise UsageError(f"Model {spec.id} has no preset voices.")
        speaker = validate_voice(spec, voice_value)
        return spec, None, speaker, None

    if spec.method == METHOD_VOICE_DESIGN:
        if voice_value:
            raise VoiceError(
                f"Model {spec.id} designs a voice from text; use --instruct instead of --voice."
            )
        return spec, None, None, None

    if spec.method == METHOD_CLONE:
        if voice_value:
            raise VoiceError(
                f"Voice '{voice_value}' is not a cloned profile. "
                f"Create one with: ttspeak voice add {voice_value} --audio ref.wav --text \"...\""
            )
        raise VoiceError(
            f"Model {spec.id} clones voices. Select a profile with --voice NAME "
            "or create one with: ttspeak voice add ..."
        )

    raise UsageError(f"Unsupported model method: {spec.method}")


def _resolve_output(
    raw: str | None,
    *,
    play: bool,
    engine_name: str,
) -> tuple[Path | None, str]:
    if raw:
        if raw.endswith(("/", os.sep)):
            raise UsageError(f"--output must be a file, not a directory: {raw}")
        output = audio.normalize_output(Path(raw).expanduser())
        if output.exists() and output.is_dir():
            raise UsageError(f"--output must be a file, not a directory: {output}")
        fmt = audio.output_format(output)
        audio.require_encoder(fmt)
        output.parent.mkdir(parents=True, exist_ok=True)
        return output, fmt

    # No -o: live streaming when the MLX worker can play audio itself.
    if play and engine_name == "mlx":
        return None, "wav"

    output = default_output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    return output, "wav"


def _engine_name(raw: str | None) -> str:
    name = (raw or os.environ.get("TTSPEAK_ENGINE") or "mlx").strip().lower()
    if name not in {"mlx", "mock"}:
        raise UsageError(f"Unknown engine '{name}'. Choose mlx or mock.")
    return name


def speak(options: SpeakOptions) -> SpeakResult:
    text = options.text.strip()
    if not text:
        raise UsageError("Text must not be empty.")

    settings = _effective(options)
    spec, profile, speaker, _ = _resolve_model_and_voice(options, settings)
    language = normalize_language(str(settings.get("language") or "German"))
    instruct = compose_instruct(
        str(settings["emotion"]) if settings.get("emotion") else None,
        str(settings["instruct"]) if settings.get("instruct") else None,
    )
    speed = float(settings.get("speed") or 1.0)
    play = bool(settings.get("play", True))
    engine_name = _engine_name(options.engine)
    output, fmt = _resolve_output(options.output, play=play, engine_name=engine_name)
    stream = output is None

    warnings: list[str] = []
    if spec.method == METHOD_CLONE and instruct:
        warnings.append("Style instructions on cloned voices are model-dependent and may be ignored.")
    if spec.method == METHOD_PRESET_VOICE and instruct:
        warnings.append(
            f"{spec.id} uses voice presets; --emotion/--instruct are ignored. "
            "Choose a voice such as de_female or de_male."
        )
    if spec.languages and language not in spec.languages:
        raise UsageError(
            f"{spec.id} does not support {language}. "
            f"Supported: {', '.join(spec.languages)}."
        )
    if spec.method == METHOD_VOICE_DESIGN and not instruct:
        raise UsageError(
            f"Model {spec.id} needs a voice description. Pass --instruct \"...\" "
            "or --emotion."
        )

    temp_wav: Path | None = None
    worker_output = output
    if output is not None and fmt != "wav":
        paths.tmp_dir().mkdir(parents=True, exist_ok=True)
        temp_wav = paths.tmp_dir() / f"ttspeak-{uuid.uuid4().hex}.wav"
        worker_output = temp_wav

    request = SynthesisRequest(
        text=text,
        output=worker_output,
        method=spec.method,
        speaker=speaker,
        language=language,
        instruct=instruct,
        speed=speed,
        ref_audio=profile.audio if profile else None,
        ref_text=profile.ref_text if profile else None,
        stream=stream,
    )

    try:
        if engine_name == "mock":
            result = MockEngine().synthesize(request)
        else:
            installed = require_installed(spec.id)
            request.model_path = installed.path
            from .engines.mlx import MlxEngine

            result = MlxEngine().synthesize(request)

        if temp_wav is not None:
            assert output is not None
            audio.transcode(temp_wav, output, fmt)
            result = SynthesisResult(
                output=output,
                duration=result.duration,
                sample_rate=result.sample_rate,
                chunks=result.chunks,
                streamed=False,
            )
    finally:
        if temp_wav is not None:
            temp_wav.unlink(missing_ok=True)

    if play and not result.streamed and result.output is not None:
        play_audio(result.output)

    return SpeakResult(
        result=result,
        spec=spec,
        engine=engine_name,
        speaker=speaker,
        profile=profile,
        instruct=instruct,
        language=language,
        speed=speed,
        format=fmt,
        warnings=warnings,
    )


def voice_label(result: SpeakResult) -> str:
    if result.profile is not None:
        return f"{result.profile.name} (cloned)"
    if result.speaker:
        return result.speaker
    if result.spec.method == METHOD_VOICE_DESIGN:
        return "designed voice"
    return "-"


def print_result(result: SpeakResult, *, quiet: bool = False) -> None:
    if result.warnings:
        for warning in result.warnings:
            print(f"warning: {warning}", file=sys.stderr)
    if not quiet:
        print(f"Model:    {result.spec.id} ({result.engine})")
        print(f"Voice:    {voice_label(result)}")
        print(f"Language: {result.language}  Speed: {result.speed:g}")
    if result.result.streamed:
        print(f"Played live ({result.result.duration:.2f}s, no file written).")
    else:
        print(f"Wrote {result.output} ({result.result.duration:.2f}s)")
