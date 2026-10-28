from ttspeak.chunking import split_text


def test_short_text_is_one_chunk():
    assert split_text("Hallo Welt.", max_chars=1000) == ["Hallo Welt."]


def test_long_text_is_split_at_paragraphs_and_sentences():
    paragraphs = [
        "Der erste Absatz ist kurz.",
        (
            "Der zweite Absatz enthält mehrere Sätze. Er soll an einer Satzgrenze "
            "geteilt werden, damit die Chunks nicht zu lang werden."
        ),
        "Der dritte Absatz beendet den Text.",
    ]
    chunks = split_text("\n\n".join(paragraphs), max_chars=80)
    assert len(chunks) > 1
    assert all(len(chunk) <= 80 for chunk in chunks)
    assert "erste Absatz" in chunks[0]
    assert any("dritte Absatz" in chunk for chunk in chunks)


def test_words_are_preserved():
    text = "eins zwei drei vier fünf sechs sieben acht neun zehn"
    chunks = split_text(text, max_chars=20)
    assert " ".join(chunks).split() == text.split()


def test_empty_text():
    assert split_text("   ") == []
