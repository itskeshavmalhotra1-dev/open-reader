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
        # Switch to Indian Literature
        idx_in = dlg.lib_choice.FindString("Indian Literature Archive (भारतीय साहित्य)")
        if idx_in != wx.NOT_FOUND:
            dlg.lib_choice.SetSelection(idx_in)
            dlg._on_lib_changed(None)
            info_in = dlg.lib_info_ctrl.GetValue()
            assert "Indian Literature" in info_in
            assert dlg.cat_choice.IsEnabled()

        # Switch to Open Tech
        idx_tech = dlg.lib_choice.FindString("Open Tech & CS Books (Programming)")
        if idx_tech != wx.NOT_FOUND:
            dlg.lib_choice.SetSelection(idx_tech)
            dlg._on_lib_changed(None)
            info_tech = dlg.lib_info_ctrl.GetValue()
            assert "Tech" in info_tech
            assert dlg.cat_choice.IsEnabled()

        # Switch to NCBI Bookshelf
        idx_ncbi = dlg.lib_choice.FindString("NCBI Bookshelf (Medical & Health)")
        if idx_ncbi != wx.NOT_FOUND:
            dlg.lib_choice.SetSelection(idx_ncbi)
            dlg._on_lib_changed(None)
            info_ncbi = dlg.lib_info_ctrl.GetValue()
            assert "NCBI" in info_ncbi
            assert dlg.cat_choice.IsEnabled()

        # Switch to 20th Century Classics
        idx_20 = dlg.lib_choice.FindString("20th Century Classics (Orwell, Woolf)")
        if idx_20 != wx.NOT_FOUND:
            dlg.lib_choice.SetSelection(idx_20)
            dlg._on_lib_changed(None)
            info_20 = dlg.lib_info_ctrl.GetValue()
            assert "20th Century" in info_20
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


def test_fetch_indian_archive_page_mock() -> None:
    from book_reader.backend.gutenberg import fetch_indian_archive_page

    sample_search = {
        "response": {
            "numFound": 100,
            "docs": [
                {
                    "identifier": "godan_hindi_01",
                    "title": "Godan",
                    "creator": ["Munshi Premchand"],
                    "language": ["hin"],
                }
            ],
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(sample_search).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        page = fetch_indian_archive_page(query="godan", category="Hindi (हिन्दी)", page=1)
        assert len(page.books) == 1
        assert page.total_count == 100
        assert page.books[0].title == "Godan"
        assert "Indian Literature" in page.books[0].source
        assert "godan_hindi_01.epub" in (page.books[0].epub_url or "")


def test_fetch_open_tech_page_mock() -> None:
    from book_reader.backend.gutenberg import fetch_open_tech_page

    sample_search = {
        "response": {
            "numFound": 50,
            "docs": [
                {
                    "identifier": "python_algorithms_01",
                    "title": "Python Algorithms and Data Structures",
                    "creator": ["Tech Expert"],
                }
            ],
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(sample_search).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        page = fetch_open_tech_page(query="python", category="Python & Data Science", page=1)
        assert len(page.books) == 1
        assert page.total_count == 50
        assert page.books[0].title == "Python Algorithms and Data Structures"
        assert "python_algorithms_01.pdf" in (page.books[0].pdf_url or "")


def test_fetch_ncbi_page_mock() -> None:
    from book_reader.backend.gutenberg import fetch_ncbi_page

    search_json = {
        "esearchresult": {
            "count": "10",
            "idlist": ["12345"],
        }
    }
    summary_json = {
        "result": {
            "12345": {
                "title": "Clinical Pharmacology Principles",
                "authors": [{"name": "Dr. Smith"}],
            }
        }
    }

    mock_search = MagicMock()
    mock_search.read.return_value = json.dumps(search_json).encode("utf-8")
    mock_search.__enter__.return_value = mock_search

    mock_sum = MagicMock()
    mock_sum.read.return_value = json.dumps(summary_json).encode("utf-8")
    mock_sum.__enter__.return_value = mock_sum

    with patch("book_reader.backend.gutenberg.urlopen", side_effect=[mock_search, mock_sum]):
        page = fetch_ncbi_page(query="pharmacology", category="Clinical Medicine & Pharmacology", page=1)
        assert len(page.books) == 1
        assert page.total_count == 10
        assert page.books[0].title == "Clinical Pharmacology Principles"
        assert "ncbi.nlm.nih.gov" in (page.books[0].html_url or "")


def test_fetch_classics_20th_page_mock() -> None:
    from book_reader.backend.gutenberg import fetch_classics_20th_page

    sample_search = {
        "response": {
            "numFound": 12,
            "docs": [
                {
                    "identifier": "nineteen_eighty_four_orwell",
                    "title": "Nineteen Eighty-Four",
                    "creator": ["George Orwell"],
                }
            ],
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(sample_search).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        page = fetch_classics_20th_page(query="1984", category="George Orwell (1984, Animal Farm)", page=1)
        assert len(page.books) == 1
        assert page.total_count == 12
        assert page.books[0].title == "Nineteen Eighty-Four"
        assert page.books[0].source == "20th Century Classics"


def test_download_ncbi_printable_html_mock(tmp_path: Path) -> None:
    from book_reader.backend.gutenberg import CatalogBook, download_catalog_book

    book = CatalogBook(
        id="ncbi_12345",
        title="Clinical Pharmacology",
        authors=["Dr. Smith"],
        languages=["en"],
        formats={"text/html": "https://www.ncbi.nlm.nih.gov/books/NBK12345/?report=printable"},
        download_count=100,
        source="NCBI Bookshelf",
    )
    printable_html = b"<html><head><title>Printable</title></head><body>Medical text content</body></html>"
    mock_resp = MagicMock()
    mock_resp.read.return_value = printable_html
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        out_file = download_catalog_book(book, tmp_path)
        assert out_file.exists()
        assert out_file.suffix == ".html"
        assert "Medical text content" in out_file.read_text(encoding="utf-8")


def test_catalog_book_available_formats() -> None:
    from book_reader.backend.gutenberg import CatalogBook

    # Multi-format book (e.g. Internet Archive or Gutenberg)
    book_multi = CatalogBook(
        id="book_1",
        title="Sample Book",
        authors=["Author One"],
        languages=["en"],
        formats={
            "application/epub+zip": "https://example.com/book.epub",
            "application/pdf": "https://example.com/book.pdf",
            "text/plain": "https://example.com/book.txt",
        },
        source="Open Library / Internet Archive",
    )
    fmts = book_multi.available_formats
    assert "EPUB" in fmts
    assert "PDF" in fmts
    assert "Plain Text" in fmts

    # PDF only (e.g. OpenStax)
    book_pdf = CatalogBook(
        id="openstax_1",
        title="College Physics",
        authors=["OpenStax"],
        languages=["en"],
        formats={"application/pdf": "https://openstax.org/physics.pdf"},
        source="OpenStax (Academic Textbooks)",
    )
    assert book_pdf.available_formats == ["PDF"]

    # HTML only (e.g. Wikisource)
    book_html = CatalogBook(
        id="wiki_1",
        title="Godan",
        authors=["Premchand"],
        languages=["hi"],
        formats={"text/html": "https://hi.wikisource.org/w/api.php?action=parse"},
        source="Wikisource (Hindi, Urdu, English)",
    )
    assert book_html.available_formats == ["HTML"]


def test_download_catalog_book_honors_preferred_format(tmp_path: Path) -> None:
    from book_reader.backend.gutenberg import CatalogBook, download_catalog_book

    book = CatalogBook(
        id=1234,
        title="Multi Format Book",
        authors=["Author"],
        languages=["en"],
        formats={
            "application/epub+zip": "https://www.gutenberg.org/ebooks/1234.epub3.images",
            "text/plain": "https://www.gutenberg.org/ebooks/1234.txt.utf-8",
            "application/pdf": "https://example.com/1234.pdf",
        },
        source="Project Gutenberg",
    )

    mock_resp = MagicMock()
    mock_resp.read.side_effect = [b"txt content", b""]
    mock_resp.headers = {"Content-Length": "11"}
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp) as mock_url:
        out_file = download_catalog_book(book, tmp_path, preferred_format="Plain Text")
        assert out_file.exists()
        assert out_file.suffix == ".txt"
        called_req = mock_url.call_args[0][0]
        assert "pg1234.txt" in called_req.full_url or "1234.txt" in called_req.full_url


def test_online_libraries_dialog_format_selector(tmp_path: Path) -> None:
    import wx
    from book_reader.backend.gutenberg import CatalogBook, CatalogPage
    from book_reader.ui.dialogs import OnlineLibrariesDialog

    app = wx.App.Get() or wx.App(False)
    dlg = OnlineLibrariesDialog(None, tmp_path)
    try:
        assert hasattr(dlg, "format_choice")
        assert not dlg.format_choice.IsEnabled()

        # Mock results population
        book = CatalogBook(
            id="test_book",
            title="Accessible Reading",
            authors=["A. Tester"],
            languages=["en"],
            formats={
                "application/epub+zip": "https://example.com/test.epub",
                "application/pdf": "https://example.com/test.pdf",
            },
            source="Open Library / Internet Archive",
        )
        fake_page = CatalogPage(
            books=[book],
            total_count=1,
            current_page=1,
            has_next=False,
            has_previous=False,
        )
        dlg._populate_results(fake_page, dlg._search_seq)

        # Format choice should now have EPUB and PDF
        assert dlg.format_choice.IsEnabled()
        choices = [dlg.format_choice.GetString(i) for i in range(dlg.format_choice.GetCount())]
        assert "EPUB" in choices
        assert "PDF" in choices
        assert dlg.format_choice.GetStringSelection() == "EPUB"

        # Change format choice to PDF
        dlg.format_choice.SetStringSelection("PDF")
        dlg._on_format_changed(None)
        assert "Format: PDF" in dlg.details_ctrl.GetValue()
    finally:
        dlg.Destroy()


def test_fetch_open_library_filters_borrowable_without_public_scan() -> None:
    from book_reader.backend.gutenberg import fetch_open_library_page

    sample_json = {
        "numFound": 3,
        "docs": [
            {
                "key": "/works/OL1",
                "title": "Public Scan Book",
                "author_name": ["Author"],
                "ia": ["public_scan_01"],
                "ebook_access": "public",
                "public_scan_b": True,
            },
            {
                "key": "/works/OL2",
                "title": "Borrow Only Book",
                "author_name": ["Author"],
                "ia": ["borrow_only_02"],
                "ebook_access": "borrowable",
                "public_scan_b": False,
            },
            {
                "key": "/works/OL3",
                "title": "Print Disabled Book",
                "author_name": ["Author"],
                "ia": ["print_disabled_03"],
                "ebook_access": "printdisabled",
                "public_scan_b": False,
            },
        ],
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(sample_json).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        page = fetch_open_library_page("Test Query")
        # Only the public scan book should be included
        assert len(page.books) == 1
        assert page.books[0].title == "Public Scan Book"


def test_resolve_archive_org_candidates_mock() -> None:
    from book_reader.backend.gutenberg import resolve_archive_org_candidates

    metadata_json = {
        "result": [
            {"name": "1984.epub"},
            {"name": "1984.pdf"},
            {"name": "1984_djvu.txt"},
            {"name": "1984_meta.xml"},
        ]
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(metadata_json).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        cands = resolve_archive_org_candidates("nineteen_eighty-four", preferred_format="EPUB")
        assert len(cands) == 3
        assert "1984.epub" in cands[0]
        assert not any("_meta.xml" in c for c in cands)


def test_download_catalog_book_handles_401_gracefully(tmp_path: Path) -> None:
    from urllib.error import HTTPError
    from book_reader.backend.gutenberg import CatalogBook, download_catalog_book

    book = CatalogBook(
        id="restricted_book",
        title="Restricted Title",
        authors=["Author"],
        languages=["en"],
        formats={"application/epub+zip": "https://archive.org/download/restricted/restricted.epub"},
        source="Open Library / Internet Archive",
    )

    def side_effect(req, *args, **kwargs):
        raise HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    with patch("book_reader.backend.gutenberg.urlopen", side_effect=side_effect):
        import pytest
        with pytest.raises(PermissionError) as exc_info:
            download_catalog_book(book, tmp_path)
        assert "401" in str(exc_info.value)
        assert "restricted lending-library" in str(exc_info.value)


def test_fetch_urdu_libraries_mock(tmp_path: Path) -> None:
    from book_reader.backend.gutenberg import (
        fetch_iqbal_library_page,
        fetch_online_catalog_page,
        fetch_rekhta_library_page,
        fetch_urdu_library_page,
    )

    sample_search = {
        "response": {
            "numFound": 50,
            "docs": [
                {
                    "identifier": "bang_e_dra_01",
                    "title": "Bang-e-Dra",
                    "creator": ["Allama Muhammad Iqbal"],
                }
            ],
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(sample_search).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("book_reader.backend.gutenberg.urlopen", return_value=mock_resp):
        # 1. Urdu Digital Library
        page_urdu = fetch_urdu_library_page("Iqbal", category="Shayari & Ghazal (اردو شاعری و غزل)")
        assert len(page_urdu.books) == 1
        assert page_urdu.books[0].title == "Bang-e-Dra"
        assert "Urdu Digital Library" in page_urdu.books[0].source

        # 2. Iqbal Cyber Library
        page_iqbal = fetch_iqbal_library_page(category="Bang-e-Dra (بانگِ درا)")
        assert len(page_iqbal.books) == 1
        assert "Iqbal Cyber Library" in page_iqbal.books[0].source

        # 3. Rekhta Open Urdu Archive
        page_rekhta = fetch_rekhta_library_page(category="Mirza Ghalib (دیوانِ غالب)")
        assert len(page_rekhta.books) == 1
        assert "Rekhta" in page_rekhta.books[0].source

        # 4. Unified dispatcher routing
        p1 = fetch_online_catalog_page("Urdu Digital Library (اردو ڈیجیٹل کتب خانہ - 1.8 Lakh+ Books)", query="Ghalib")
        assert len(p1.books) == 1
        p2 = fetch_online_catalog_page("Iqbal Cyber Library (اقبال سائبر لائبریری - Allama Iqbal)")
        assert len(p2.books) == 1
        p3 = fetch_online_catalog_page("Rekhta Open Urdu Archive (ریختہ اردو کلاسک)")
        assert len(p3.books) == 1


def test_online_libraries_dialog_urdu_switching(tmp_path: Path) -> None:
    import wx
    from book_reader.ui.dialogs import OnlineLibrariesDialog

    app = wx.App.Get() or wx.App(False)
    dlg = OnlineLibrariesDialog(None, tmp_path)
    try:
        # Check Urdu Digital Library
        idx_urdu = dlg.lib_choice.FindString("Urdu Digital Library (اردو ڈیجیٹل کتب خانہ - 1.8 Lakh+ Books)")
        assert idx_urdu != wx.NOT_FOUND
        dlg.lib_choice.SetSelection(idx_urdu)
        dlg._on_lib_changed(None)
        assert "182,000+" in dlg.lib_info_ctrl.GetValue()
        assert dlg.cat_choice.IsEnabled()

        # Check Iqbal Cyber Library
        idx_iqbal = dlg.lib_choice.FindString("Iqbal Cyber Library (اقبال سائبر لائبریری - Allama Iqbal)")
        assert idx_iqbal != wx.NOT_FOUND
        dlg.lib_choice.SetSelection(idx_iqbal)
        dlg._on_lib_changed(None)
        assert "Bang-e-Dra" in dlg.lib_info_ctrl.GetValue()
        assert dlg.cat_choice.IsEnabled()

        # Check Rekhta Open Urdu Archive
        idx_rekhta = dlg.lib_choice.FindString("Rekhta Open Urdu Archive (ریختہ اردو کلاسک)")
        assert idx_rekhta != wx.NOT_FOUND
        dlg.lib_choice.SetSelection(idx_rekhta)
        dlg._on_lib_changed(None)
        assert "Mirza Ghalib" in dlg.lib_info_ctrl.GetValue()
        assert dlg.cat_choice.IsEnabled()
    finally:
        dlg.Destroy()




