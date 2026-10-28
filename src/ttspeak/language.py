"""Small, dependency-free language detector for de/en/ru text.

The detector works per sentence and per script run. It is intentionally
conservative: Latin text is classified with a small set of high-signal words,
Cyrillic text is always Russian. Anything unknown falls back to the configured
default language.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .constants import LANGUAGE_NAMES

AUTO_LANGUAGE = "auto"

_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüß]+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

_GERMAN_WORDS = {
    "aber",
    "abend",
    "auch",
    "auf",
    "beim",
    "bitte",
    "das",
    "danke",
    "dein",
    "dem",
    "den",
    "der",
    "deutsch",
    "die",
    "du",
    "ein",
    "eine",
    "einem",
    "einen",
    "einer",
    "er",
    "es",
    "für",
    "guten",
    "hallo",
    "heute",
    "ich",
    "ihr",
    "im",
    "ist",
    "klingt",
    "mit",
    "morgen",
    "nicht",
    "oder",
    "sprache",
    "stimme",
    "teste",
    "und",
    "von",
    "warum",
    "was",
    "wie",
    "wir",
    "wo",
    "zu",
    "zum",
    "zur",
}

_ENGLISH_WORDS = {
    "and",
    "are",
    "evening",
    "for",
    "good",
    "hello",
    "how",
    "in",
    "is",
    "it",
    "language",
    "morning",
    "my",
    "not",
    "of",
    "on",
    "one",
    "please",
    "sounds",
    "thank",
    "that",
    "the",
    "test",
    "they",
    "this",
    "three",
    "to",
    "today",
    "voice",
    "we",
    "what",
    "why",
    "with",
    "you",
    "your",
}


@dataclass(frozen=True)
class LanguageSegment:
    text: str
    code: str

    @property
    def name(self) -> str:
        return LANGUAGE_NAMES[self.code]


def detect_language(text: str) -> str | None:
    """Return ``de``, ``en`` or ``ru`` for a short text, or ``None``."""
    raw = text.strip()
    if not raw:
        return None

    cyrillic = len(_CYRILLIC_RE.findall(raw))
    latin = len(_LATIN_RE.findall(raw))
    if cyrillic and not latin:
        return "ru"
    if cyrillic and latin and cyrillic >= latin:
        return "ru"

    words = [word.lower() for word in _WORD_RE.findall(raw)]
    if not words:
        return None

    german = sum(1 for word in words if word in _GERMAN_WORDS)
    english = sum(1 for word in words if word in _ENGLISH_WORDS)
    if any(char in raw for char in "äöüßÄÖÜ"):
        german += 2

    if german > english:
        return "de"
    if english > german:
        return "en"
    if german:
        return "de"
    return None


def _split_scripts(text: str) -> list[str]:
    """Split a sentence where Cyrillic and Latin script meet."""
    chunks: list[str] = []
    current: list[str] = []
    current_script: str | None = None

    for char in text:
        if _CYRILLIC_RE.match(char):
            script = "cyrillic"
        elif _LATIN_RE.match(char):
            script = "latin"
        else:
            current.append(char)
            continue

        if current_script is not None and script != current_script:
            before = "".join(current).strip()
            if before:
                chunks.append(before)
            current = [char]
        else:
            current.append(char)
        current_script = script

    tail = "".join(current).strip()
    if tail:
        chunks.append(tail)
    return chunks


def split_sentences(text: str) -> list[str]:
    """Split on sentence punctuation while keeping the punctuation."""
    stripped = text.strip()
    if not stripped:
        return []
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(stripped) if part.strip()]


def segment_text(text: str, *, default_language: str = "de") -> list[LanguageSegment]:
    """Split text into language runs, merging adjacent runs of the same language."""
    pieces: list[LanguageSegment] = []
    for sentence in split_sentences(text):
        for chunk in _split_scripts(sentence):
            code = detect_language(chunk) or default_language
            if pieces and pieces[-1].code == code:
                pieces[-1] = LanguageSegment(
                    text=f"{pieces[-1].text} {chunk}",
                    code=code,
                )
            else:
                pieces.append(LanguageSegment(text=chunk, code=code))
    return pieces


def canonical_language(code: str) -> str:
    """Return the canonical model language name for a detector code."""
    return LANGUAGE_NAMES[code]
