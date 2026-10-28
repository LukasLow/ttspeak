"""Split long text into safe TTS chunks at paragraph and sentence boundaries."""

from __future__ import annotations

import re

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
MIN_PARAGRAPH_CHARS = 200


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
    """Split at paragraph boundaries, then sentences for oversized paragraphs.

    Paragraphs are kept as separate chunks whenever possible. Very short
    paragraphs (for example a title) are merged with the following paragraph so
    they do not create a tiny one-word chunk.
    """
    if max_chars < 10:
        raise ValueError("max_chars must be at least 10")
    stripped = text.strip()
    if not stripped:
        return []
    if len(stripped) <= max_chars:
        return [stripped]

    raw_paragraphs = [
        part.strip() for part in _PARAGRAPH_SPLIT_RE.split(stripped) if part.strip()
    ]
    paragraphs: list[str] = []
    buffer = ""
    for paragraph in raw_paragraphs:
        if buffer:
            buffer = f"{buffer}\n\n{paragraph}"
            if len(buffer) >= MIN_PARAGRAPH_CHARS:
                paragraphs.append(buffer)
                buffer = ""
        elif len(paragraph) < MIN_PARAGRAPH_CHARS:
            buffer = paragraph
        else:
            paragraphs.append(paragraph)
    if buffer:
        if paragraphs:
            paragraphs[-1] = f"{paragraphs[-1]}\n\n{buffer}"
        else:
            paragraphs.append(buffer)

    chunks: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            chunks.append(paragraph)
            continue
        current = ""
        for piece in _paragraph_sentences(paragraph, max_chars):
            candidate = f"{current} {piece}".strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = candidate
            if len(current) >= max_chars:
                chunks.append(current)
                current = ""
        if current:
            chunks.append(current)
    return chunks
