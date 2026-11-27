"""Unit tests for online libraries pagination integration (Project Gutenberg, Standard Ebooks, Open Library)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from book_reader.backend.gutenberg import (
    CatalogBook,
    CatalogPage,
    download_catalog_book,
    fetch_gutenberg_page,
    fetch_online_catalog_page,
    fetch_open_library_page,
    fetch_standard_ebooks_page,
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


def test_fetch_gutenberg_page_mock() -> None:
    sample_response = {
        "count": 75000,
        "next": "https://gutendex.com/books/?page=2",
        "previous": None,
        "results": [
            {
                "id": 84,
                "title": "Frankenstein",
                "authors": [{"name": "Shelley, Mary"}],
                "languages": ["en"],
                "formats": {"application/epub+zip": "https://example.com/84.epub"},
                "download_count": 65000,
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(sample_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        page = fetch_gutenberg_page("Frankenstein", page=1)
        assert isinstance(page, CatalogPage)
        assert len(page.books) == 1
        assert page.total_count == 75000
        assert page.current_page == 1
        assert page.has_next is True
        assert page.has_previous is False
        assert page.books[0].title == "Frankenstein"

        # Test backward-compatible wrapper
        books = search_gutenberg("Frankenstein")
        assert len(books) == 1


def test_search_and_page_standard_ebooks_mock() -> None:
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
        page = fetch_standard_ebooks_page("Gatsby", page=1)
        assert len(page.books) == 1
        assert page.total_count == 1
        assert page.books[0].title == "The Great Gatsby"
        assert page.books[0].source == "Standard Ebooks"
        assert page.books[0].epub_url == "https://standardebooks.org/ebooks/f-scott-fitzgerald/the-great-gatsby/dist/epub"

        # Check backward compatibility
        books = search_standard_ebooks("Gatsby")
        assert len(books) == 1


def test_fetch_open_library_page_mock() -> None:
    sample_json = {
        "numFound": 150,
        "docs": [
            {
                "key": "/works/OL123W",
                "title": "Moby Dick",
                "author_name": ["Herman Melville"],
                "language": ["eng"],
                "ia": ["mobydick00melv"],
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(sample_json).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        page = fetch_open_library_page("Moby Dick", page=1, limit=20)
        assert len(page.books) == 1
        assert page.total_count == 150
        assert page.has_next is True
        assert page.has_previous is False
        assert page.books[0].title == "Moby Dick"
        assert "archive.org" in (page.books[0].epub_url or "")

        # Check unified dispatcher
        dispatched_page = fetch_online_catalog_page("Open Library / Internet Archive", query="Moby Dick", page=1)
        assert len(dispatched_page.books) == 1


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


def test_download_gutenberg_pglaf_mirror_used(tmp_path: Path) -> None:
    book = CatalogBook(
        id=84,
        title="Frankenstein",
        authors=["Mary Shelley"],
        languages=["en"],
        formats={"application/epub+zip": "https://www.gutenberg.org/ebooks/84.epub3.images"},
        download_count=1000,
        source="Project Gutenberg",
    )
    mock_resp = MagicMock()
    mock_resp.read.side_effect = [b"frankenstein-epub-bytes", b""]
    mock_resp.headers = {"Content-Length": "23"}
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp) as mock_url:
        out_file = download_catalog_book(book, tmp_path)
        assert out_file.exists()
        assert out_file.suffix == ".epub"
        called_req = mock_url.call_args[0][0]
        assert "gutenberg.pglaf.org" in called_req.full_url


def test_download_fallback_when_first_url_returns_503(tmp_path: Path) -> None:
    from urllib.error import HTTPError

    book = CatalogBook(
        id=84,
        title="Frankenstein",
        authors=["Mary Shelley"],
        languages=["en"],
        formats={"application/epub+zip": "https://www.gutenberg.org/ebooks/84.epub3.images"},
        download_count=1000,
        source="Project Gutenberg",
    )
    mock_resp = MagicMock()
    mock_resp.read.side_effect = [b"epub-content", b""]
    mock_resp.headers = {"Content-Length": "12"}
    mock_resp.__enter__.return_value = mock_resp

    def side_effect(req, *args, **kwargs):
        if "pg84.epub" in req.full_url:
            raise HTTPError(req.full_url, 503, "Service Unavailable", {}, None)
        return mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", side_effect=side_effect):
        out_file = download_catalog_book(book, tmp_path)
        assert out_file.exists()
        assert out_file.read_bytes() == b"epub-content"


def test_online_libraries_dialog_status_and_info(tmp_path: Path) -> None:
    import wx
    from book_reader.ui.dialogs import OnlineLibrariesDialog

    app = wx.App.Get() or wx.App(False)
    dlg = OnlineLibrariesDialog(None, tmp_path)
    try:
        # Initial library Gutenberg info
        info_val = dlg.lib_info_ctrl.GetValue()
        assert "Project Gutenberg" in info_val
        assert "75,000+" in info_val
        assert dlg.cat_choice.IsEnabled()

        # Switch to Standard Ebooks
        idx_se = dlg.lib_choice.FindString("Standard Ebooks")
        if idx_se != wx.NOT_FOUND:
            dlg.lib_choice.SetSelection(idx_se)
            dlg._on_lib_changed(None)
            info_se = dlg.lib_info_ctrl.GetValue()
            assert "Standard Ebooks" in info_se
            assert "Clean EPUB" in info_se
            assert not dlg.cat_choice.IsEnabled()

        # Switch to Open Library
        idx_ol = dlg.lib_choice.FindString("Open Library / Internet Archive")
        if idx_ol != wx.NOT_FOUND:
            dlg.lib_choice.SetSelection(idx_ol)
            dlg._on_lib_changed(None)
            info_ol = dlg.lib_info_ctrl.GetValue()
            assert "Open Library" in info_ol
            assert "Internet Archive" in info_ol

        # Switch to Wikisource
        idx_ws = dlg.lib_choice.FindString("Wikisource (Hindi, Urdu, English)")
        if idx_ws != wx.NOT_FOUND:
            dlg.lib_choice.SetSelection(idx_ws)
            dlg._on_lib_changed(None)
            info_ws = dlg.lib_info_ctrl.GetValue()
            assert "Wikisource" in info_ws
            assert dlg.cat_choice.IsEnabled()

        # Switch to OpenStax
        idx_ox = dlg.lib_choice.FindString("OpenStax (Academic Textbooks)")
        if idx_ox != wx.NOT_FOUND:
            dlg.lib_choice.SetSelection(idx_ox)
            dlg._on_lib_changed(None)
            info_ox = dlg.lib_info_ctrl.GetValue()
            assert "OpenStax" in info_ox
            assert dlg.cat_choice.IsEnabled()
    finally:
        dlg.Destroy()
        app.ProcessPendingEvents()


def test_fetch_wikisource_page_mock() -> None:
    from book_reader.backend.gutenberg import fetch_wikisource_page

    sample_search = {
        "query": {
            "searchinfo": {"totalhits": 45},
            "search": [
                {"title": "Godan", "pageid": 1234},
                {"title": "Gaban", "pageid": 5678},
            ],
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(sample_search).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        page = fetch_wikisource_page(query="Godan", category="Hindi Wikisource (हिन्दी)", page=1)
        assert len(page.books) == 2
        assert page.total_count == 45
        assert page.books[0].title == "Godan"
        assert page.books[0].source == "Wikisource (Hindi)"
        assert page.books[0].html_url is not None


def test_fetch_openstax_page_mock() -> None:
    from book_reader.backend.gutenberg import fetch_openstax_page

    sample_cms = {
        "items": [
            {
                "id": 873,
                "title": "Calculus Volume 1",
                "pdf_url": "https://assets.openstax.org/calc1.pdf",
                "high_resolution_pdf_url": "https://assets.openstax.org/calc1.pdf",
            },
            {
                "id": 874,
                "title": "University Physics",
                "pdf_url": "https://assets.openstax.org/physics.pdf",
                "high_resolution_pdf_url": "https://assets.openstax.org/physics.pdf",
            },
        ]
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(sample_cms).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        page = fetch_openstax_page(query="calculus", category="Math & Statistics", page=1)
        assert len(page.books) == 1
        assert page.books[0].title == "Calculus Volume 1"
        assert page.books[0].pdf_url == "https://assets.openstax.org/calc1.pdf"


def test_download_wikisource_html_mock(tmp_path: Path) -> None:
    from book_reader.backend.gutenberg import CatalogBook, download_catalog_book

    book = CatalogBook(
        id="ws_1",
        title="Godan",
        authors=["Premchand"],
        languages=["hi"],
        formats={"text/html": "https://hi.wikisource.org/w/api.php?action=parse&page=Godan&prop=text&format=json"},
        download_count=0,
        source="Wikisource (Hindi)",
    )
    parse_json = {
        "parse": {
            "title": "Godan",
            "text": {"*": "<p>Chapter one text of Godan in Hindi</p>"},
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(parse_json).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        out_file = download_catalog_book(book, tmp_path)
        assert out_file.exists()
        assert out_file.suffix == ".html"
        content = out_file.read_text(encoding="utf-8")
        assert "Chapter one text of Godan" in content

