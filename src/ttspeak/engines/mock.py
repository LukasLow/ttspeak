"""Dependency-free mock engine used by tests and for development."""

from __future__ import annotations

import math
import struct
import wave

from .base import SynthesisRequest, SynthesisResult

SAMPLE_RATE = 24000


def _tone(duration: float) -> bytes:
    frames = max(1, int(duration * SAMPLE_RATE))
    fade = min(int(0.02 * SAMPLE_RATE), frames // 4)
    data = bytearray()
    for index in range(frames):
        t = index / SAMPLE_RATE
        envelope = 1.0
        if index < fade:
            envelope = index / fade
        elif index > frames - fade:
            envelope = max(0.0, (frames - index) / fade)
        value = 0.18 * envelope * math.sin(2 * math.pi * 220 * t)
        data.extend(struct.pack("<h", int(value * 32767)))
    return bytes(data)


class MockEngine:
    name = "mock"

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        duration = min(5.0, max(0.3, 0.055 * len(request.text)))
        request.output.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(request.output), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(_tone(duration))
        return SynthesisResult(
            output=request.output,
            duration=duration,
            sample_rate=SAMPLE_RATE,
            chunks=1,
        )
