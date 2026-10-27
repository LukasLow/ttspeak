"""Speech engine interface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class SynthesisRequest:
    text: str
    output: Path
    method: str
    model_path: Path | None = None
    speaker: str | None = None
    language: str = "German"
    instruct: str | None = None
    speed: float = 1.0
    ref_audio: Path | None = None
    ref_text: str | None = None


@dataclass
class SynthesisResult:
    output: Path
    duration: float
    sample_rate: int
    chunks: int = 1


class Engine(Protocol):
    name: str

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult: ...
