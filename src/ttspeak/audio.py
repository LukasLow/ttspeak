"""Output formats and optional ffmpeg transcoding."""

from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

from .errors import EngineError, UsageError

# ffmpeg codec arguments for non-WAV formats. WAV is written natively by the
# worker; ffmpeg is only needed for the formats below.
FORMAT_CODECS: dict[str, list[str]] = {
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "flac": ["-c:a", "flac"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
    "opus": ["-c:a", "libopus", "-b:a", "128k"],
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
}
SUPPORTED_FORMATS = ("wav", *FORMAT_CODECS)


def normalize_output(path: Path) -> Path:
    """Append .wav when the user supplied no extension."""
    if not path.suffix:
        return path.with_suffix(".wav")
    return path


def output_format(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix not in SUPPORTED_FORMATS:
        raise UsageError(
            f"Unsupported output format '.{suffix}'. "
            f"Supported: {', '.join(SUPPORTED_FORMATS)}."
        )
    return suffix


def require_encoder(fmt: str) -> None:
    if fmt == "wav":
        return
    if shutil.which("ffmpeg") is None:
        raise UsageError(
            f"{fmt.upper()} output needs ffmpeg. Install it (for example "
            "`nix shell nixpkgs#ffmpeg`) or use a .wav output."
        )


def transcode(wav: Path, target: Path, fmt: str) -> Path:
    """Convert the worker's WAV into the requested format, then remove the WAV."""
    if fmt == "wav":
        if wav != target:
            shutil.move(str(wav), target)
        return target

    require_encoder(fmt)
    command = [
        shutil.which("ffmpeg") or "ffmpeg",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(wav),
        *FORMAT_CODECS[fmt],
        str(target),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        target.unlink(missing_ok=True)
        detail = (exc.stderr or exc.stdout or "").strip()
        raise EngineError(f"ffmpeg failed to write {target}: {detail}") from exc
    finally:
        wav.unlink(missing_ok=True)
    return target


def concat_wavs(paths: list[Path], target: Path, *, gap_seconds: float = 0.08) -> float:
    """Concatenate mono/stereo PCM WAVs into one file and return its duration."""
    if not paths:
        raise EngineError("No audio segments to concatenate.")
    target.parent.mkdir(parents=True, exist_ok=True)

    params: tuple[int, int, int] | None = None
    frames: list[bytes] = []
    total_frames = 0
    for path in paths:
        try:
            with wave.open(str(path), "rb") as handle:
                current = (
                    handle.getnchannels(),
                    handle.getsampwidth(),
                    handle.getframerate(),
                )
                if params is None:
                    params = current
                elif current != params:
                    raise EngineError(
                        f"Cannot concatenate {path}: WAV format differs from the first segment."
                    )
                data = handle.readframes(handle.getnframes())
                frames.append(data)
                total_frames += handle.getnframes()
        except (OSError, wave.Error) as exc:
            raise EngineError(f"Cannot read WAV segment {path}: {exc}") from exc

    assert params is not None
    channels, sample_width, rate = params
    gap_frames = max(0, int(gap_seconds * rate))
    gap = b"\x00" * (gap_frames * channels * sample_width)

    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sample_width)
        handle.setframerate(rate)
        for index, data in enumerate(frames):
            if index and gap:
                handle.writeframes(gap)
                total_frames += gap_frames
            handle.writeframes(data)

    return total_frames / rate if rate else 0.0
