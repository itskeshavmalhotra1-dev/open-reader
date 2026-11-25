"""Tests for EPUB, DAISY OPF, DOCX, PDF, HTML, Markdown, and TXT parsers."""

from pathlib import Path
import zipfile

import fitz
import pytest

from book_reader.backend.parsers import load_book


def _build_minimal_epub(epub_path: Path, chapter_href: str = "chap1.xhtml") -> None:
    container_xml = (
        '<?xml version="1.0"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        "<rootfiles>"
        '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
        "</rootfiles></container>"
    )
    opf_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:title>Test EPUB Book</dc:title>"
        "<dc:creator>Test Author</dc:creator>"
        "</metadata>"
        "<manifest>"
        f'<item id="c1" href="{chapter_href}" media-type="application/xhtml+xml"/>'
        "</manifest>"
        "<spine><itemref idref=\"c1\"/></spine>"
        "</package>"
    )
    chap_html = "<html><body><h1>Opening Chapter</h1><p>EPUB body content.</p></body></html>"

    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        if not chapter_href.startswith(".."):
            zf.writestr(f"OEBPS/{chapter_href}", chap_html)


def test_load_markdown_with_headings(tmp_path: Path) -> None:
    md_file = tmp_path / "notes.md"
    md_file.write_text("# Intro\nHello\n## Deep Dive\nDetails here.", encoding="utf-8")
    book = load_book(md_file)
    assert book.format_name == "MD"
    assert len(book.chapters) == 1
    assert [h.title for h in book.chapters[0].headings] == ["Intro", "Deep Dive"]


def test_load_epub_and_blocks_zip_traversal(tmp_path: Path) -> None:
    epub_ok = tmp_path / "sample.epub"
    _build_minimal_epub(epub_ok)
    book = load_book(epub_ok)
    assert book.title == "Test EPUB Book"
    assert book.author == "Test Author"
    assert book.format_name == "EPUB"
    assert len(book.chapters) == 1
    assert "EPUB body content." in book.chapters[0].text
    assert book.chapters[0].headings[0].title == "Opening Chapter"

    epub_bad = tmp_path / "evil.epub"
    _build_minimal_epub(epub_bad, chapter_href="../../etc/passwd")
    with pytest.raises(ValueError, match="Unsafe archive path"):
        load_book(epub_bad)


def test_load_docx(tmp_path: Path) -> None:
    docx_path = tmp_path / "sample.docx"
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Doc Title</w:t></w:r></w:p>'
        "<w:p><w:r><w:t>Paragraph one text.</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    with zipfile.ZipFile(docx_path, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)

    book = load_book(docx_path)
    assert book.format_name == "DOCX"
    assert book.title == "Doc Title"
    assert "Paragraph one text." in book.chapters[0].text
    assert book.chapters[0].headings[0].level == 1


def test_load_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello Accessible PDF")
    doc.set_toc([[1, "PDF Heading", 1]])
    doc.save(pdf_path)
    doc.close()

    book = load_book(pdf_path)
    assert book.format_name == "PDF"
    assert "Hello Accessible PDF" in book.chapters[0].text
    assert book.chapters[0].headings[0].title == "PDF Heading"


def test_load_daisy_opf(tmp_path: Path) -> None:
    opf = tmp_path / "book.opf"
    sec = tmp_path / "sec1.html"
    sec.write_text("<html><body><h1>DAISY Section</h1><p>Spoken content.</p></body></html>", encoding="utf-8")
    opf.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>DAISY Book</dc:title></metadata>'
        '<manifest><item id="s1" href="sec1.html" media-type="application/xhtml+xml"/></manifest>'
        '<spine><itemref idref="s1"/></spine>'
        "</package>",
        encoding="utf-8",
    )
    book = load_book(opf)
    assert book.format_name == "DAISY"
    assert book.title == "DAISY Book"
    assert "Spoken content." in book.chapters[0].text
