"""Out-of-process MLX worker.

Runs inside the isolated mlx-audio runtime. The request and result are JSON files
so that model loading / library logging on stdout cannot corrupt the protocol.

Usage: python worker_mlx.py /path/to/request.json
"""

from __future__ import annotations

import inspect
import json
import sys
import time
import traceback
import wave
from pathlib import Path
from typing import Any

import numpy as np
from chunking import split_text

TARGET_RMS_DB = -23.0
MAX_GAIN_DB = 18.0
SILENCE_THRESHOLD_DB = -50.0
KEEP_EDGE_SECONDS = 0.04
FADE_SECONDS = 0.015
CHUNK_GAP_SECONDS = 0.12


def log(message: str) -> None:
    print(f"[mlx] {message}", file=sys.stderr, flush=True)


def write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def supported_call(function, kwargs: dict[str, Any]):
    signature = inspect.signature(function)
    has_var_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    clean = {key: value for key, value in kwargs.items() if value is not None}
    if not has_var_kwargs:
        clean = {key: value for key, value in clean.items() if key in signature.parameters}
    return function(**clean)


def _trim_silence(samples: np.ndarray, rate: int) -> np.ndarray:
    threshold = 10.0 ** (SILENCE_THRESHOLD_DB / 20.0)
    mask = np.abs(samples) > threshold
    if not mask.any():
        return samples[:0]
    first = int(np.argmax(mask))
    last = len(mask) - int(np.argmax(mask[::-1]))
    pad = int(KEEP_EDGE_SECONDS * rate)
    return samples[max(0, first - pad) : min(len(samples), last + pad)]


def _rms_db(samples: np.ndarray) -> float:
    if samples.size == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    return 20.0 * float(np.log10(max(rms, 1e-9)))


def _fade(samples: np.ndarray, rate: int) -> np.ndarray:
    count = min(int(FADE_SECONDS * rate), samples.size // 2)
    if count <= 0:
        return samples
    ramp = np.linspace(0.0, 1.0, count, dtype=np.float32)
    samples[:count] *= ramp
    samples[-count:] *= ramp[::-1]
    return samples


def _postprocess_chunk(samples: np.ndarray, rate: int) -> tuple[np.ndarray, float]:
    trimmed = _trim_silence(samples, rate)
    if trimmed.size == 0:
        return trimmed, 0.0
    gain_db = max(-MAX_GAIN_DB, min(MAX_GAIN_DB, TARGET_RMS_DB - _rms_db(trimmed)))
    processed = trimmed * np.float32(10.0 ** (gain_db / 20.0))
    peak = float(np.max(np.abs(processed))) if processed.size else 0.0
    if peak > 0.891:
        processed = processed * np.float32(0.891 / peak)
    return _fade(processed, rate), gain_db


def _join_chunks(chunks: list[np.ndarray], rate: int) -> np.ndarray:
    pieces: list[np.ndarray] = []
    gap = np.zeros(int(CHUNK_GAP_SECONDS * rate), dtype=np.float32)
    for chunk in chunks:
        if chunk.size == 0:
            continue
        if pieces:
            pieces.append(gap)
        pieces.append(chunk)
    if not pieces:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(pieces)


def _match_head(chunk: np.ndarray, previous_tail: np.ndarray, rate: int) -> tuple[np.ndarray, float]:
    """Smooth a chunk start towards the previous chunk tail over one second."""
    if previous_tail.size == 0 or chunk.size == 0:
        return chunk, 0.0
    head_count = min(int(0.40 * rate), chunk.size)
    head = chunk[:head_count]
    previous_db = _rms_db(previous_tail)
    head_db = _rms_db(head)
    # Allow a small natural rise, but remove the abrupt chunk-start step.
    delta = previous_db + 3.0 - head_db
    delta = max(-MAX_GAIN_DB, min(MAX_GAIN_DB, delta))
    if abs(delta) < 1.0:
        return chunk, 0.0

    # Hold the matched level through the first word, then glide back to the
    # original chunk level. This avoids both a step and a hard fade-in.
    hold_count = min(int(0.45 * rate), chunk.size)
    ramp_count = min(int(0.90 * rate), max(0, chunk.size - hold_count))
    matched = chunk.copy()
    matched[:hold_count] *= np.float32(10.0 ** (delta / 20.0))
    if ramp_count:
        curve = np.linspace(delta, 0.0, ramp_count, dtype=np.float32)
        matched[hold_count : hold_count + ramp_count] *= np.power(
            np.float32(10.0),
            curve / np.float32(20.0),
        )
    return matched, delta


def _stream_play(
    function,
    kwargs: dict[str, Any],
    model,
    texts: list[str],
    postprocess: bool,
) -> dict[str, Any]:
    """Generate with stream=True and write chunks to the default audio device."""
    import sounddevice as sd

    start = time.monotonic()
    output_stream = None
    total_samples = 0
    chunks = 0
    sample_rate = int(getattr(model, "sample_rate", None) or 24000)
    first_chunk_seconds: float | None = None
    gap = np.zeros(0, dtype=np.float32)
    previous_tail = np.zeros(0, dtype=np.float32)

    try:
        for index, text in enumerate(texts):
            chunk_kwargs = {**kwargs, "text": text}
            chunk_parts: list[np.ndarray] = []
            for result in supported_call(function, chunk_kwargs):
                data = np.asarray(result.audio, dtype=np.float32).reshape(-1)
                if data.size:
                    sample_rate = int(getattr(result, "sample_rate", None) or sample_rate)
                    chunk_parts.append(np.clip(data, -1.0, 1.0))
            if not chunk_parts:
                continue
            data = np.concatenate(chunk_parts).reshape(-1)
            if postprocess and len(texts) > 1:
                data, gain_db = _postprocess_chunk(data, sample_rate)
                log(f"chunk {index + 1}/{len(texts)} gain {gain_db:+.1f} dB")
                if previous_tail.size:
                    data, match_db = _match_head(data, previous_tail, sample_rate)
                    log(
                        f"chunk {index + 1}/{len(texts)} boundary match "
                        f"{match_db:+.1f} dB"
                    )
            if data.size == 0:
                continue
            if output_stream is None:
                output_stream = sd.OutputStream(
                    samplerate=sample_rate,
                    channels=1,
                    dtype="float32",
                )
                output_stream.start()
                first_chunk_seconds = time.monotonic() - start
                gap = np.zeros(int(CHUNK_GAP_SECONDS * sample_rate), dtype=np.float32)
                log(f"first audio after {first_chunk_seconds:.2f}s")
            output_stream.write(data.reshape(-1, 1))
            total_samples += data.size
            chunks += 1
            tail_count = min(int(0.40 * sample_rate), data.size)
            previous_tail = data[-tail_count:] if tail_count else np.zeros(0, dtype=np.float32)
            if index < len(texts) - 1 and gap.size:
                output_stream.write(gap.reshape(-1, 1))
                total_samples += gap.size
    except sd.PortAudioError as exc:
        raise RuntimeError(
            "Live audio output failed. Use `--no-play -o out.wav` to write a file instead. "
            f"PortAudio: {exc}"
        ) from exc
    finally:
        if output_stream is not None:
            output_stream.stop()
            output_stream.close()

    if chunks == 0:
        raise RuntimeError("The model returned only empty audio chunks.")

    duration = total_samples / sample_rate if sample_rate else 0.0
    log(f"streamed {duration:.2f}s at {sample_rate} Hz")
    return {
        "ok": True,
        "output": None,
        "duration": duration,
        "sample_rate": sample_rate,
        "chunks": chunks,
        "streamed": True,
        "first_chunk_seconds": first_chunk_seconds,
    }


def synthesize(request: dict[str, Any]) -> dict[str, Any]:
    from mlx_audio.tts.utils import load_model

    model_path = Path(request["model_path"])
    method = request["method"]
    text = request["text"]
    output_value = request.get("output")
    stream = bool(request.get("stream")) and not output_value
    output = Path(output_value) if output_value else None
    if not stream and output is None:
        raise ValueError("Non-streaming synthesis requires an output file.")

    log(f"loading {model_path.name} ...")
    model = load_model(model_path)
    log("model loaded")

    if method == "custom_voice":
        if not request.get("speaker"):
            raise ValueError("custom_voice requires a speaker")
        function = getattr(model, "generate_custom_voice", None)
        kwargs = {
            "text": text,
            "speaker": request.get("speaker"),
            "language": request.get("language"),
            "instruct": request.get("instruct"),
            "speed": request.get("speed"),
        }
    elif method == "preset_voice":
        if not request.get("speaker"):
            raise ValueError("preset_voice requires a voice")
        function = getattr(model, "generate", None)
        kwargs = {
            "text": text,
            "voice": request.get("speaker"),
            "speed": request.get("speed"),
        }
    elif method == "voice_design":
        if not request.get("instruct"):
            raise ValueError("voice_design requires an instruction/description")
        function = getattr(model, "generate_voice_design", None)
        kwargs = {
            "text": text,
            "language": request.get("language"),
            "instruct": request.get("instruct"),
            "speed": request.get("speed"),
        }
    elif method == "clone":
        if not request.get("ref_audio"):
            raise ValueError("voice cloning requires a reference audio file")
        if not Path(request["ref_audio"]).is_file():
            raise FileNotFoundError(f"Reference audio not found: {request['ref_audio']}")
        function = getattr(model, "generate", None)
        kwargs = {
            "text": text,
            "ref_audio": request.get("ref_audio"),
            "ref_text": request.get("ref_text"),
            "speed": request.get("speed"),
        }
    else:
        raise ValueError(f"Unknown method: {method}")

    if function is None:
        raise AttributeError(f"Model {type(model).__name__} has no method for '{method}'")

    chunk_chars = int(request.get("chunk_chars") or 0)
    texts = split_text(text, max_chars=chunk_chars) if chunk_chars > 0 else [text]
    if not texts:
        texts = [text]
    postprocess = bool(request.get("postprocess", True))

    log(f"generating {len(text)} characters in {len(texts)} chunk(s) ...")
    if stream:
        kwargs["stream"] = True
        kwargs["streaming_interval"] = 0.32
        return _stream_play(function, kwargs, model, texts, postprocess)

    output.parent.mkdir(parents=True, exist_ok=True)
    raw_chunks: list[np.ndarray] = []
    results = []
    sample_rate = int(getattr(model, "sample_rate", None) or 24000)
    for index, chunk in enumerate(texts):
        log(f"chunk {index + 1}/{len(texts)} ({len(chunk)} characters) ...")
        chunk_kwargs = {**kwargs, "text": chunk}
        chunk_results = list(supported_call(function, chunk_kwargs))
        if not chunk_results:
            raise RuntimeError("The model returned no audio.")
        results.extend(chunk_results)
        chunk_parts: list[np.ndarray] = []
        for result in chunk_results:
            audio = np.asarray(result.audio, dtype=np.float32).reshape(-1)
            if audio.size:
                sample_rate = int(getattr(result, "sample_rate", None) or sample_rate)
                chunk_parts.append(np.clip(audio, -1.0, 1.0))
        if chunk_parts:
            raw_chunks.append(np.concatenate(chunk_parts).reshape(-1))

    if not raw_chunks:
        raise RuntimeError("The model returned only empty audio chunks.")

    prepared_chunks = raw_chunks
    if postprocess and len(raw_chunks) > 1:
        prepared_chunks = []
        previous_tail = np.zeros(0, dtype=np.float32)
        for index, chunk in enumerate(raw_chunks):
            processed, gain_db = _postprocess_chunk(chunk, sample_rate)
            if index:
                processed, match_db = _match_head(processed, previous_tail, sample_rate)
                log(f"chunk {index + 1}/{len(raw_chunks)} boundary match {match_db:+.1f} dB")
            log(f"chunk {index + 1}/{len(raw_chunks)} gain {gain_db:+.1f} dB")
            prepared_chunks.append(processed)
            tail_count = min(int(0.40 * sample_rate), processed.size)
            previous_tail = processed[-tail_count:] if tail_count else np.zeros(0, dtype=np.float32)

    samples = _join_chunks(prepared_chunks, sample_rate)
    if samples.size == 0:
        raise RuntimeError("The model returned only silence.")
    pcm = (samples * 32767.0).astype(np.int16)

    with wave.open(str(output), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())

    duration = len(samples) / sample_rate if sample_rate else 0.0
    rtf = getattr(results[0], "real_time_factor", None)
    processing = getattr(results[0], "processing_time_seconds", None)
    if processing is not None:
        log(f"processed in {float(processing):.2f}s (RTF {rtf})")
    log(f"wrote {output} ({duration:.2f}s at {sample_rate} Hz)")

    return {
        "ok": True,
        "output": str(output),
        "duration": duration,
        "sample_rate": sample_rate,
        "chunks": len(results),
        "streamed": False,
        "real_time_factor": float(rtf) if rtf is not None else None,
        "processing_time_seconds": float(processing) if processing is not None else None,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: worker_mlx.py REQUEST.json", file=sys.stderr)
        return 2
    request_path = Path(argv[1])
    request: dict[str, Any] = {}
    result_path: Path | None = None
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        result_path = Path(request["result_path"])
        payload = synthesize(request)
        write_result(result_path, payload)
        return 0
    except Exception as exc:  # noqa: BLE001 - boundary process
        traceback.print_exc()
        if result_path is None and "result_path" in request:
            result_path = Path(request["result_path"])
        if result_path is not None:
            write_result(
                result_path,
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
