"""Unit tests for online libraries integration (Project Gutenberg, Standard Ebooks, Open Library)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from book_reader.backend.gutenberg import (
    CatalogBook,
    download_catalog_book,
    search_gutenberg,
    search_online_library,
    search_open_library,
    search_standard_ebooks,
)


def test_catalog_book_format_selection() -> None:
    b1 = CatalogBook(
        id=1342,
        title="Pride and Prejudice",
        authors=["Austen, Jane"],
        languages=["en"],
        formats={
            "application/epub+zip": "https://example.com/1342.epub3.images",
            "text/plain; charset=utf-8": "https://example.com/1342-0.txt",
        },
        download_count=50000,
        source="Project Gutenberg",
    )
    assert b1.author_display == "Austen, Jane"
    assert b1.epub_url == "https://example.com/1342.epub3.images"
    assert b1.text_url == "https://example.com/1342-0.txt"


def test_search_gutenberg_mock() -> None:
    sample_response = {
        "results": [
            {
                "id": 84,
                "title": "Frankenstein",
                "authors": [{"name": "Shelley, Mary"}],
                "languages": ["en"],
                "formats": {"application/epub+zip": "https://example.com/84.epub"},
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
        assert books[0].source == "Project Gutenberg"


def test_search_standard_ebooks_mock() -> None:
    atom_xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>The Great Gatsby</title>
        <author><name>F. Scott Fitzgerald</name></author>
        <link href="/ebooks/f-scott-fitzgerald/the-great-gatsby/dist/epub" type="application/epub+zip"/>
      </entry>
    </feed>"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = atom_xml
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        books = search_standard_ebooks("Gatsby")
        assert len(books) == 1
        assert books[0].title == "The Great Gatsby"
        assert books[0].source == "Standard Ebooks"
        assert books[0].epub_url == "https://standardebooks.org/ebooks/f-scott-fitzgerald/the-great-gatsby/dist/epub"


def test_search_open_library_mock() -> None:
    sample_json = {
        "docs": [
            {
                "key": "/works/OL123W",
                "title": "Moby Dick",
                "author_name": ["Herman Melville"],
                "language": ["eng"],
                "ia": ["mobydick00melv"],
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(sample_json).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        books = search_open_library("Moby Dick")
        assert len(books) == 1
        assert books[0].title == "Moby Dick"
        assert "archive.org" in (books[0].epub_url or "")


def test_download_catalog_book_mock(tmp_path: Path) -> None:
    book = CatalogBook(
        id="demo_1",
        title="Demo Book",
        authors=["Author"],
        languages=["en"],
        formats={"application/epub+zip": "https://example.com/demo.epub"},
        download_count=10,
        source="Test Source",
    )
    mock_resp = MagicMock()
    mock_resp.read.side_effect = [b"epub-data-content", b""]
    mock_resp.headers = {"Content-Length": "17"}
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        out_file = download_catalog_book(book, tmp_path)
        assert out_file.exists()
        assert out_file.suffix == ".epub"
        assert out_file.read_bytes() == b"epub-data-content"
