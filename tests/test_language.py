from ttspeak.language import detect_language, segment_text


def test_detects_german_english_and_russian():
    assert detect_language("Guten Abend, wie geht es dir?") == "de"
    assert detect_language("Good evening, how are you?") == "en"
    assert detect_language("Добрый вечер, как дела?") == "ru"


def test_segments_mixed_sentences():
    segments = segment_text("Guten Abend. Good evening. Добрый вечер.")
    assert [segment.code for segment in segments] == ["de", "en", "ru"]
    assert segments[0].name == "German"
    assert segments[2].name == "Russian"


def test_merges_adjacent_same_language():
    segments = segment_text("Hallo. Wie geht es dir?")
    assert len(segments) == 1
    assert segments[0].code == "de"


def test_splits_cyrillic_and_latin_inside_one_sentence():
    segments = segment_text("Hello, как дела?")
    assert [segment.code for segment in segments] == ["en", "ru"]


def test_unknown_text_uses_default_language():
    segments = segment_text("12345 !!!", default_language="de")
    assert segments[0].code == "de"
