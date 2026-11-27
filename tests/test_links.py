"""Tests for hyperlink extraction, navigation, and activation."""

from pathlib import Path
import zipfile

import wx

from book_reader.backend.parsers import load_book
from book_reader.ui.main_frame import BookReaderFrame


def test_html_and_markdown_link_extraction(tmp_path: Path) -> None:
    html_file = tmp_path / "sample.html"
    html_file.write_text(
        '<html><body><p id="top">Top</p>'
        '<p>Visit <a href="https://example.com/docs">Open Docs</a> or '
        '<a href="#top">Back to top</a>.</p></body></html>',
        encoding="utf-8",
    )
    html_doc = load_book(html_file)
    links = html_doc.chapters[0].links
    assert len(links) == 2
    assert links[0].text == "Open Docs"
    assert links[0].href == "https://example.com/docs"
    assert links[0].target_chapter is None
    assert links[1].text == "Back to top"
    assert links[1].href == "#top"
    assert links[1].target_chapter == 0

    md_file = tmp_path / "notes.md"
    md_file.write_text(
        "# Notes\n\nSee [Project](https://github.com/itskeshavmalhotra1-dev/open-reader) "
        "or https://example.org/info.\n",
        encoding="utf-8",
    )
    md_doc = load_book(md_file)
    assert len(md_doc.chapters[0].links) == 2
    assert md_doc.chapters[0].links[0].href == "https://github.com/itskeshavmalhotra1-dev/open-reader"
    assert md_doc.chapters[0].links[1].href == "https://example.org/info"


def test_epub_internal_and_external_links_and_frame_navigation(tmp_path: Path) -> None:
    epub_path = tmp_path / "links.epub"
    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>'
            "</container>",
        )
        zf.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Links Book</dc:title></metadata>'
            '<manifest><item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>',
        )
        zf.writestr(
            "OEBPS/ch1.xhtml",
            '<html><body><h1>One</h1><p>Go to <a href="ch2.xhtml#sec2">Section Two</a> or '
            '<a href="https://example.com">Example Site</a>.</p></body></html>',
        )
        zf.writestr(
            "OEBPS/ch2.xhtml",
            '<html><body><h1 id="sec2">Two</h1><p>Target reached.</p></body></html>',
        )

    app = wx.App(False)
    frame = BookReaderFrame(data_dir=tmp_path / "data")
    try:
        frame.open_book_path(epub_path)
        chap0 = frame.book.chapters[0]
        assert len(chap0.links) == 2
        assert chap0.links[0].target_chapter == 1
        frame.step_link(1)
        pos = frame.reader_ctrl.GetInsertionPoint()
        found = frame._find_link_at_pos(pos)
        assert found is not None
        assert found.text == "Section Two"
        frame._activate_link(found)
        assert frame.current_chapter_idx == 1
    finally:
        frame.Destroy()
        app.Destroy()
