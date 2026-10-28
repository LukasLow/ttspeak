"""Speech engine interface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class SynthesisRequest:
    text: str
    output: Path | None
    method: str
    model_path: Path | None = None
    speaker: str | None = None
    language: str = "German"
    instruct: str | None = None
    speed: float = 1.0
    ref_audio: Path | None = None
    ref_text: str | None = None
    stream: bool = False
    chunk_chars: int = 1000


@dataclass
class SynthesisResult:
    output: Path | None
    duration: float
    sample_rate: int
    chunks: int = 1
    streamed: bool = False


class Engine(Protocol):
    name: str

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult: ...
