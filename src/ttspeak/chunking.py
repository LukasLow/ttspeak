"""Split long text into safe TTS chunks at paragraph and sentence boundaries."""

from __future__ import annotations

import re

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    if len(sentence) <= max_chars:
        return [sentence]
    words = sentence.split()
    parts: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            parts.append(current)
            current = word
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _paragraph_sentences(paragraph: str, max_chars: int) -> list[str]:
    result: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(paragraph.strip()):
        if sentence.strip():
            result.extend(_split_long_sentence(sentence.strip(), max_chars))
    return result


def split_text(text: str, max_chars: int = 1000) -> list[str]:
    """Return chunks no longer than ``max_chars`` where possible.

    Paragraph boundaries are preferred, then sentence boundaries, then word
    boundaries. The original words and punctuation are preserved.
    """
    if max_chars < 10:
        raise ValueError("max_chars must be at least 10")
    stripped = text.strip()
    if not stripped:
        return []
    if len(stripped) <= max_chars:
        return [stripped]

    paragraphs = [part.strip() for part in _PARAGRAPH_SPLIT_RE.split(stripped) if part.strip()]
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for paragraph in paragraphs:
        pieces = _paragraph_sentences(paragraph, max_chars)
        for piece in pieces:
            candidate = f"{current} {piece}".strip()
            if current and len(candidate) > max_chars:
                flush()
                current = piece
            else:
                current = candidate
            if len(current) >= max_chars:
                flush()
    flush()
    return chunks
