"""Tests for the Rust/Python-fallback core engine functions."""

from book_reader.backend.engine import (
    BACKEND_MODE,
    extract_html_text_and_headings,
    search_text,
    split_sentences,
)


def test_backend_mode_is_valid() -> None:
    assert BACKEND_MODE in ("rust", "python-fallback")


def test_extract_html_text_and_headings_skips_scripts_and_tracks_offsets() -> None:
    html = (
        "<html><head><title>Ignored</title><style>body{color:red;}</style></head>"
        "<body><h1>Chapter One</h1><p>First paragraph.</p>"
        "<script>alert('hidden');</script>"
        "<h2>Section A</h2><p>Second&nbsp;paragraph.</p></body></html>"
    )
    text, headings = extract_html_text_and_headings(html)
    assert "Ignored" not in text
    assert "hidden" not in text
    assert "color:red" not in text
    assert "Chapter One" in text
    assert "Second paragraph." in text
    assert len(headings) == 2
    assert headings[0].level == 1
    assert headings[0].text == "Chapter One"
    assert text[headings[0].char_offset :].startswith("Chapter One")
    assert headings[1].level == 2
    assert headings[1].text == "Section A"
    assert text[headings[1].char_offset :].startswith("Section A")


def test_split_sentences_preserves_python_unicode_offsets() -> None:
    sample = 'Hello world! "Is this working?" नमस्ते। Next line\nFinal sentence.'
    spans = split_sentences(sample)
    assert [s.text for s in spans] == [
        "Hello world!",
        '"Is this working?"',
        "नमस्ते।",
        "Next line",
        "Final sentence.",
    ]
    for span in spans:
        assert sample[span.start : span.end] == span.text


def test_search_text_returns_accurate_unicode_offsets() -> None:
    text = "Line one: नमस्ते Reader\nLine two: accessible reader"
    hits = search_text(text, "reader", max_hits=10)
    assert len(hits) == 2
    assert hits[0].line_number == 1
    assert text[hits[0].start : hits[0].end].lower() == "reader"
    assert hits[1].line_number == 2
    assert text[hits[1].start : hits[1].end].lower() == "reader"
    assert search_text(text, "   ") == []
