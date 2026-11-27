"""Unit tests for Project Gutenberg integration."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from book_reader.backend.gutenberg import GutenbergBook, download_gutenberg_book, search_gutenberg


def test_gutenberg_book_format_selection() -> None:
    b1 = GutenbergBook(
        id=1342,
        title="Pride and Prejudice",
        authors=["Austen, Jane"],
        languages=["en"],
        formats={
            "application/epub+zip": "https://example.com/1342.epub3.images",
            "text/plain; charset=utf-8": "https://example.com/1342-0.txt",
        },
        download_count=50000,
    )
    assert b1.author_display == "Austen, Jane"
    assert b1.epub_url == "https://example.com/1342.epub3.images"
    assert b1.text_url == "https://example.com/1342-0.txt"


def test_search_gutenberg_mock() -> None:
    sample_response = {
        "results": [
            {
                "id": 84,
                "title": "Frankenstein; Or, The Modern Prometheus",
                "authors": [{"name": "Shelley, Mary Wollstonecraft"}],
                "languages": ["en"],
                "formats": {
                    "application/epub+zip": "https://example.com/84.epub",
                },
                "download_count": 65000,
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(sample_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        books = search_gutenberg("Frankenstein")
        assert len(books) == 1
        assert books[0].id == 84
        assert books[0].author_display == "Shelley, Mary Wollstonecraft"
        assert books[0].epub_url == "https://example.com/84.epub"


def test_download_gutenberg_book_mock(tmp_path: Path) -> None:
    book = GutenbergBook(
        id=42,
        title="Test Book",
        authors=["Author"],
        languages=["en"],
        formats={"application/epub+zip": "https://example.com/42.epub"},
        download_count=10,
    )
    mock_resp = MagicMock()
    mock_resp.read.side_effect = [b"fake-epub-data-chunk", b""]
    mock_resp.headers = {"Content-Length": "20"}
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        out_file = download_gutenberg_book(book, tmp_path)
        assert out_file.exists()
        assert out_file.suffix == ".epub"
        assert out_file.read_bytes() == b"fake-epub-data-chunk"
