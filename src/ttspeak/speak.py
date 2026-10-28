"""Resolve settings and run one or more synthesis segments."""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import audio, config, paths, voices
from .constants import (
    AUTO_LANGUAGE,
    LANGUAGE_NAMES,
    compose_instruct,
    normalize_gender,
    normalize_language,
)
from .engines.base import SynthesisRequest, SynthesisResult
from .engines.mock import MockEngine
from .errors import UsageError, VoiceError
from .language import LanguageSegment, segment_text
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
from .voice_map import resolve_alias

_CODE_BY_NAME = {name: code for code, name in LANGUAGE_NAMES.items()}


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
class SegmentPlan:
    text: str
    code: str
    language: str
    spec: ModelSpec
    speaker: str | None = None
    profile: voices.VoiceProfile | None = None
    voice_alias: str | None = None


@dataclass
class SegmentResult:
    plan: SegmentPlan
    result: SynthesisResult


@dataclass
class SpeakResult:
    result: SynthesisResult
    spec: ModelSpec
    engine: str
    speaker: str | None = None
    profile: voices.VoiceProfile | None = None
    instruct: str | None = None
    language: str = AUTO_LANGUAGE
    languages: list[str] = field(default_factory=list)
    segments: list[SegmentResult] = field(default_factory=list)
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


def _choice_from_alias(
    alias,
    options: SpeakOptions,
) -> tuple[ModelSpec, voices.VoiceProfile | None, str | None, str]:
    model_id = options.model if options.model_explicit else alias.model
    spec = resolve_model(model_id)
    if spec.method not in {METHOD_CUSTOM_VOICE, METHOD_PRESET_VOICE}:
        raise VoiceError(
            f"Configured voice '{alias.alias}' needs a preset-voice model, "
            f"but {spec.id} uses {spec.method}."
        )
    speaker = validate_voice(spec, alias.speaker)
    return spec, None, speaker, alias.alias


def _explicit_choice(
    options: SpeakOptions,
    settings: dict[str, object],
    voice_value: str,
) -> tuple[ModelSpec, voices.VoiceProfile | None, str | None, str | None]:
    profile = _select_profile(voice_value)
    voices_map = settings.get("voices") or {}
    default_gender = normalize_gender(str(settings.get("default_gender") or "female"))
    alias = None if profile is not None else resolve_alias(
        voices_map if isinstance(voices_map, dict) else {},
        voice_value,
        default_gender=default_gender,
    )

    if alias is not None:
        return _choice_from_alias(alias, options)

    model_value = options.model if options.model_explicit else settings.get("model")
    if profile is not None and not options.model_explicit:
        model_value = profile.model
    if model_value is None:
        if profile is not None:
            model_value = profile.model
        else:
            raise UsageError("No model configured. Set one with: ttspeak config set model voxtral:4b")
    spec = resolve_model(str(model_value))

    if profile is not None:
        if spec.method != METHOD_CLONE:
            raise VoiceError(
                f"Voice '{profile.name}' is a cloned profile and needs a Base model, "
                f"but {spec.id} uses {spec.method}. "
                "Omit -m or use a Base model such as qwen3:0.6b-base."
            )
        if not profile.audio.is_file():
            raise VoiceError(f"Reference audio for '{profile.name}' is missing: {profile.audio}")
        return spec, profile, None, profile.name

    if spec.method in {METHOD_CUSTOM_VOICE, METHOD_PRESET_VOICE}:
        speaker = validate_voice(spec, voice_value)
        return spec, None, speaker, voice_value

    if spec.method == METHOD_VOICE_DESIGN:
        raise VoiceError(
            f"Model {spec.id} designs a voice from text; use --instruct instead of --voice."
        )

    if spec.method == METHOD_CLONE:
        raise VoiceError(
            f"Voice '{voice_value}' is not a cloned profile. "
            f"Create one with: ttspeak voice add {voice_value} --audio ref.wav --text \"...\""
        )

    raise UsageError(f"Unsupported model method: {spec.method}")


def _fallback_choice(
    options: SpeakOptions,
    settings: dict[str, object],
) -> tuple[ModelSpec, voices.VoiceProfile | None, str | None, str | None]:
    voice_value = str(settings.get("voice") or "").strip() or None
    if voice_value:
        return _explicit_choice(options, settings, voice_value)

    model_value = options.model if options.model_explicit else settings.get("model")
    if not model_value:
        raise UsageError("No model configured. Set one with: ttspeak config set model voxtral:4b")
    spec = resolve_model(str(model_value))

    if spec.method in {METHOD_CUSTOM_VOICE, METHOD_PRESET_VOICE}:
        speaker = spec.default_voice or (spec.voices[0] if spec.voices else None)
        if not speaker:
            raise UsageError(f"Model {spec.id} has no preset voices.")
        return spec, None, speaker, None

    if spec.method == METHOD_VOICE_DESIGN:
        return spec, None, None, None

    if spec.method == METHOD_CLONE:
        raise VoiceError(
            f"Model {spec.id} clones voices. Select a profile with --voice NAME "
            "or create one with: ttspeak voice add ..."
        )

    raise UsageError(f"Unsupported model method: {spec.method}")


def _choice_for_code(
    code: str,
    options: SpeakOptions,
    settings: dict[str, object],
) -> tuple[ModelSpec, voices.VoiceProfile | None, str | None, str | None]:
    # An explicit -m/run model keeps its own voice rules; configured language
    # voices are for the normal, model-less auto path.
    if not options.model_explicit:
        voices_map = settings.get("voices") or {}
        default_gender = normalize_gender(str(settings.get("default_gender") or "female"))
        alias = resolve_alias(
            voices_map if isinstance(voices_map, dict) else {},
            code,
            default_gender=default_gender,
        )
        if alias is not None:
            return _choice_from_alias(alias, options)
    return _fallback_choice(options, settings)


def _build_plans(
    options: SpeakOptions,
    settings: dict[str, object],
) -> list[SegmentPlan]:
    text = options.text.strip()
    language_value = str(settings.get("language") or AUTO_LANGUAGE).strip()
    if language_value.lower() == AUTO_LANGUAGE:
        raw_segments = segment_text(text, default_language="de")
    else:
        name = normalize_language(language_value)
        raw_segments = [LanguageSegment(text=text, code=_CODE_BY_NAME[name])]

    forced_value = options.voice
    forced_choice = None
    if forced_value:
        forced_choice = _explicit_choice(options, settings, str(forced_value))

    plans: list[SegmentPlan] = []
    for segment in raw_segments:
        choice = forced_choice or _choice_for_code(segment.code, options, settings)
        spec, profile, speaker, alias = choice
        plans.append(
            SegmentPlan(
                text=segment.text,
                code=segment.code,
                language=segment.name,
                spec=spec,
                speaker=speaker,
                profile=profile,
                voice_alias=alias,
            )
        )
    return plans


def _validate_plan(plan: SegmentPlan, instruct: str | None, warnings: list[str]) -> None:
    if plan.spec.languages and plan.language not in plan.spec.languages:
        raise UsageError(
            f"{plan.spec.id} does not support {plan.language} for segment "
            f"'{plan.text[:48]}'. Supported: {', '.join(plan.spec.languages)}."
        )

    if plan.spec.method in {METHOD_CUSTOM_VOICE, METHOD_PRESET_VOICE}:
        if plan.profile is not None:
            raise VoiceError(f"{plan.spec.id} cannot use a cloned profile.")
        if not plan.speaker:
            raise UsageError(f"Model {plan.spec.id} has no preset voices.")
        if plan.spec.method == METHOD_PRESET_VOICE and instruct:
            warning = (
                f"{plan.spec.id} uses voice presets; --emotion/--instruct are ignored. "
                "Choose a language voice such as de_female or de_male."
            )
            if warning not in warnings:
                warnings.append(warning)
        return

    if plan.spec.method == METHOD_VOICE_DESIGN:
        if plan.speaker:
            raise VoiceError(f"Model {plan.spec.id} designs a voice; use --instruct instead.")
        if not instruct:
            raise UsageError(
                f"Model {plan.spec.id} needs a voice description. Pass --instruct \"...\" "
                "or --emotion."
            )
        return

    if plan.spec.method == METHOD_CLONE:
        if plan.profile is None:
            raise VoiceError(
                f"Model {plan.spec.id} clones voices. Select a profile with --voice NAME "
                "or create one with: ttspeak voice add ..."
            )
        if not plan.profile.audio.is_file():
            raise VoiceError(f"Reference audio for '{plan.profile.name}' is missing.")
        if instruct:
            warning = "Style instructions on cloned voices are model-dependent and may be ignored."
            if warning not in warnings:
                warnings.append(warning)
        return

    raise UsageError(f"Unsupported model method: {plan.spec.method}")


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


def _synthesize(
    plan: SegmentPlan,
    *,
    engine_name: str,
    output: Path | None,
    stream: bool,
    instruct: str | None,
    speed: float,
) -> SynthesisResult:
    request = SynthesisRequest(
        text=plan.text,
        output=output,
        method=plan.spec.method,
        speaker=plan.speaker,
        language=plan.language,
        instruct=instruct,
        speed=speed,
        ref_audio=plan.profile.audio if plan.profile else None,
        ref_text=plan.profile.ref_text if plan.profile else None,
        stream=stream,
    )
    if engine_name == "mock":
        return MockEngine().synthesize(request)

    installed = require_installed(plan.spec.id)
    request.model_path = installed.path
    from .engines.mlx import MlxEngine

    return MlxEngine().synthesize(request)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def speak(options: SpeakOptions) -> SpeakResult:
    text = options.text.strip()
    if not text:
        raise UsageError("Text must not be empty.")

    settings = _effective(options)
    plans = _build_plans(options, settings)
    if not plans:
        raise UsageError("Text must contain at least one language segment.")

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
    for plan in plans:
        _validate_plan(plan, instruct, warnings)

    segment_results: list[SegmentResult] = []
    if stream:
        for plan in plans:
            result = _synthesize(
                plan,
                engine_name=engine_name,
                output=None,
                stream=True,
                instruct=instruct,
                speed=speed,
            )
            segment_results.append(SegmentResult(plan=plan, result=result))
        combined = SynthesisResult(
            output=None,
            duration=sum(item.result.duration for item in segment_results),
            sample_rate=segment_results[0].result.sample_rate,
            chunks=sum(item.result.chunks for item in segment_results),
            streamed=True,
        )
    else:
        assert output is not None
        paths.tmp_dir().mkdir(parents=True, exist_ok=True)
        segment_paths: list[Path] = []
        combined_path: Path | None = None
        temp_wav: Path | None = None
        try:
            if len(plans) == 1:
                plan = plans[0]
                worker_output = output
                if fmt != "wav":
                    temp_wav = paths.tmp_dir() / f"ttspeak-{uuid.uuid4().hex}.wav"
                    worker_output = temp_wav
                result = _synthesize(
                    plan,
                    engine_name=engine_name,
                    output=worker_output,
                    stream=False,
                    instruct=instruct,
                    speed=speed,
                )
                if temp_wav is not None:
                    audio.transcode(temp_wav, output, fmt)
                    result = SynthesisResult(
                        output=output,
                        duration=result.duration,
                        sample_rate=result.sample_rate,
                        chunks=result.chunks,
                        streamed=False,
                    )
                segment_results.append(SegmentResult(plan=plan, result=result))
                combined = result
            else:
                for index, plan in enumerate(plans):
                    segment_path = paths.tmp_dir() / f"ttspeak-{uuid.uuid4().hex}-{index}.wav"
                    result = _synthesize(
                        plan,
                        engine_name=engine_name,
                        output=segment_path,
                        stream=False,
                        instruct=instruct,
                        speed=speed,
                    )
                    segment_paths.append(segment_path)
                    segment_results.append(SegmentResult(plan=plan, result=result))

                combined_path = paths.tmp_dir() / f"ttspeak-{uuid.uuid4().hex}-combined.wav"
                duration = audio.concat_wavs(segment_paths, combined_path)
                audio.transcode(combined_path, output, fmt)
                combined = SynthesisResult(
                    output=output,
                    duration=duration,
                    sample_rate=segment_results[0].result.sample_rate,
                    chunks=sum(item.result.chunks for item in segment_results),
                    streamed=False,
                )
        finally:
            for path in segment_paths:
                path.unlink(missing_ok=True)
            if combined_path is not None:
                combined_path.unlink(missing_ok=True)
            if temp_wav is not None:
                temp_wav.unlink(missing_ok=True)

    if play and not combined.streamed and combined.output is not None:
        play_audio(combined.output)

    first = plans[0]
    return SpeakResult(
        result=combined,
        spec=first.spec,
        engine=engine_name,
        speaker=first.speaker,
        profile=first.profile,
        instruct=instruct,
        language=first.language,
        languages=_unique([plan.language for plan in plans]),
        segments=segment_results,
        speed=speed,
        format=fmt,
        warnings=warnings,
    )


def _segment_label(segment: SegmentResult) -> str:
    plan = segment.plan
    if plan.profile is not None:
        return f"{plan.profile.name} (cloned)"
    if plan.speaker:
        return plan.speaker
    if plan.spec.method == METHOD_VOICE_DESIGN:
        return "designed voice"
    return "-"


def voice_label(result: SpeakResult) -> str:
    if result.segments:
        labels = [_segment_label(segment) for segment in result.segments]
    else:
        if result.profile is not None:
            labels = [f"{result.profile.name} (cloned)"]
        elif result.speaker:
            labels = [result.speaker]
        elif result.spec.method == METHOD_VOICE_DESIGN:
            labels = ["designed voice"]
        else:
            labels = ["-"]
    return ", ".join(_unique(labels))


def print_result(result: SpeakResult, *, quiet: bool = False) -> None:
    if result.warnings:
        for warning in result.warnings:
            print(f"warning: {warning}", file=sys.stderr)
    if not quiet:
        if len(result.segments) > 1:
            models = _unique([segment.plan.spec.id for segment in result.segments])
            print(f"Model:    {', '.join(models)}")
            print(f"Voice:    {voice_label(result)}")
            print(f"Language: {', '.join(result.languages)}  Speed: {result.speed:g}")
            print(
                "Segments: "
                + ", ".join(
                    f"{segment.plan.language}->{_segment_label(segment)}"
                    for segment in result.segments
                )
            )
        else:
            print(f"Model:    {result.spec.id} ({result.engine})")
            print(f"Voice:    {voice_label(result)}")
            print(f"Language: {result.language}  Speed: {result.speed:g}")
    if result.result.streamed:
        print(f"Played live ({result.result.duration:.2f}s, no file written).")
    else:
        print(f"Wrote {result.output} ({result.result.duration:.2f}s)")
