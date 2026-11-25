"""Comprehensive tests for navigation: EPUB nav.xhtml/NCX, anchors, pages, history, paragraphs, and Where-Am-I."""

from pathlib import Path
import zipfile

import fitz
import wx

from book_reader.backend.engine import extract_html_document, paragraph_offsets
from book_reader.backend.navigation import NavLocation, NavigationController
from book_reader.backend.parsers import load_book
from book_reader.ui.main_frame import BookReaderFrame


def test_html_anchors_and_pagebreaks_extracted() -> None:
    html = (
        '<html><body>'
        '<h1 id="ch1">Chapter 1</h1>'
        '<p id="p1">First paragraph.</p>'
        '<span id="pg12" epub:type="pagebreak" title="12"/>'
        '<p id="p2">Second paragraph on page twelve.</p>'
        '</body></html>'
    )
    res = extract_html_document(html)
    assert res.anchors["ch1"] >= 0
    assert res.text[res.anchors["p2"] :].startswith("Second paragraph")
    assert len(res.page_breaks) == 1
    assert res.page_breaks[0].label == "12"
    assert res.page_breaks[0].char_offset == res.anchors["pg12"]


def test_paragraph_offsets() -> None:
    text = "Para one.\n\nPara two line 1.\nPara two line 2.\n\nPara three."
    offsets = paragraph_offsets(text)
    assert [text[o:].split("\n", 1)[0] for o in offsets] == [
        "Para one.",
        "Para two line 1.",
        "Para three.",
    ]


def test_epub3_nav_xhtml_fragment_anchors_and_pagelist(tmp_path: Path) -> None:
    epub_path = tmp_path / "nav3.epub"
    container_xml = (
        '<?xml version="1.0"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/package.opf" media-type="application/oebps-package+xml"/></rootfiles>'
        "</container>"
    )
    opf_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>EPUB3 Nav Book</dc:title></metadata>'
        "<manifest>"
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>'
        "</manifest>"
        '<spine><itemref idref="c1"/><itemref idref="c2"/></spine>'
        "</package>"
    )
    nav_xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        "<body>"
        '<nav epub:type="toc"><ol>'
        '<li><a href="ch1.xhtml">Part One</a>'
        '<ol><li><a href="ch1.xhtml#deep">Deep Section</a></li></ol>'
        "</li>"
        '<li><a href="ch2.xhtml">Part Two</a></li>'
        "</ol></nav>"
        '<nav epub:type="page-list"><ol>'
        '<li><a href="ch1.xhtml#pg5">5</a></li>'
        '<li><a href="ch2.xhtml#pg10">10</a></li>'
        "</ol></nav>"
        "</body></html>"
    )
    ch1 = '<html><body><h1>Intro</h1><p>Lead text.</p><h2 id="deep">Deep Target</h2><p id="pg5">Page five text.</p></body></html>'
    ch2 = '<html><body><h1>Chapter Two</h1><p id="pg10">Page ten text.</p></body></html>'

    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/package.opf", opf_xml)
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml)
        zf.writestr("OEBPS/ch1.xhtml", ch1)
        zf.writestr("OEBPS/ch2.xhtml", ch2)

    book = load_book(epub_path)
    assert len(book.toc) == 2
    assert book.toc[0].title == "Part One"
    assert len(book.toc[0].children) == 1
    deep_node = book.toc[0].children[0]
    assert deep_node.title == "Deep Section"
    assert deep_node.chapter_index == 0
    assert book.chapters[0].text[deep_node.char_offset :].startswith("Deep Target")

    nav = NavigationController(book)
    pb10 = nav.go_to_page("10")
    assert pb10 is not None
    assert pb10.chapter_index == 1
    assert book.chapters[1].text[pb10.char_offset :].startswith("Page ten text.")


def test_navigation_controller_history_levels_paragraphs_and_where_am_i(tmp_path: Path) -> None:
    pdf_path = tmp_path / "multi.pdf"
    doc = fitz.open()
    for p in range(1, 4):
        page = doc.new_page()
        page.insert_text((72, 72), f"Body text on page {p}.")
    doc.set_toc([[1, "Main Title", 1], [2, "Sub Section", 3]])
    doc.save(pdf_path)
    doc.close()

    book = load_book(pdf_path)
    nav = NavigationController(book)

    # Go to page 3
    pb = nav.go_to_page("3")
    assert pb is not None
    nav.record_jump(NavLocation(0, 0))
    loc = NavLocation(pb.chapter_index, pb.char_offset)
    summary = nav.where_am_i(loc.chapter_index, loc.char_offset)
    assert "Page 3" in summary
    assert "Sub Section" in summary

    # Back / Forward history
    back = nav.go_back(loc)
    assert back == NavLocation(0, 0)
    fwd = nav.go_forward(back)
    assert fwd == loc

    # Heading level 2 jump from start
    h2 = nav.step_heading(0, 0, delta=1, level=2)
    assert h2 is not None
    assert h2[1].title == "Sub Section"


def test_wx_frame_navigation_history_and_paragraphs(tmp_path: Path) -> None:
    md = tmp_path / "nav_demo.md"
    md.write_text("# Heading 1\nFirst para.\n\nSecond para.\n\n## Heading 2\nThird para.", encoding="utf-8")

    app = wx.App.Get() or wx.App(False)
    frame = BookReaderFrame(data_dir=tmp_path)
    try:
        frame.open_book_path(str(md))
        frame.reader_ctrl.SetInsertionPoint(0)
        frame.step_paragraph(1)
        pos1 = frame.reader_ctrl.GetInsertionPoint()
        assert frame.reader_ctrl.GetValue()[pos1:].startswith("Second para.")

        frame.jump_to_location(NavLocation(0, len(frame.reader_ctrl.GetValue()) - 5), record_history=True)
        frame.go_back()
        assert frame.reader_ctrl.GetInsertionPoint() == pos1
        frame.go_forward()
        assert frame.reader_ctrl.GetInsertionPoint() > pos1
    finally:
        frame.Destroy()
        app.ProcessPendingEvents()
