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


def _stream_play(function, kwargs: dict[str, Any], model) -> dict[str, Any]:
    """Generate with stream=True and write chunks to the default audio device."""
    import numpy as np
    import sounddevice as sd

    start = time.monotonic()
    output_stream = None
    total_samples = 0
    chunks = 0
    sample_rate = int(getattr(model, "sample_rate", None) or 24000)
    first_chunk_seconds: float | None = None

    try:
        for result in supported_call(function, kwargs):
            data = np.asarray(result.audio, dtype=np.float32).reshape(-1)
            if data.size == 0:
                continue
            if output_stream is None:
                sample_rate = int(
                    getattr(result, "sample_rate", None)
                    or getattr(model, "sample_rate", None)
                    or 24000
                )
                output_stream = sd.OutputStream(
                    samplerate=sample_rate,
                    channels=1,
                    dtype="float32",
                )
                output_stream.start()
                first_chunk_seconds = time.monotonic() - start
                log(f"first audio after {first_chunk_seconds:.2f}s")
            output_stream.write(data.reshape(-1, 1))
            total_samples += data.size
            chunks += 1
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
    import mlx.core as mx
    import numpy as np
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

    log(f"generating {len(text)} characters ...")
    if stream:
        kwargs["stream"] = True
        kwargs["streaming_interval"] = 0.32
        return _stream_play(function, kwargs, model)

    output.parent.mkdir(parents=True, exist_ok=True)
    results = list(supported_call(function, kwargs))
    if not results:
        raise RuntimeError("The model returned no audio.")

    chunks = [result.audio for result in results if getattr(result.audio, "size", 0) > 0]
    if not chunks:
        raise RuntimeError("The model returned only empty audio chunks.")

    if len(chunks) > 1:
        audio = mx.concatenate(chunks, axis=0)
    else:
        audio = chunks[0]

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * 32767.0).astype(np.int16)

    sample_rate = int(
        getattr(results[0], "sample_rate", None)
        or getattr(model, "sample_rate", None)
        or 24000
    )
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
        "chunks": len(chunks),
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
