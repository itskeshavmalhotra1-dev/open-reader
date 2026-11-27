"""Book format parsers normalizing EPUB, DAISY, PDF, DOCX, HTML, and TXT."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import posixpath
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

from bs4 import BeautifulSoup
import fitz  # PyMuPDF

from book_reader.backend.engine import extract_html_document
from book_reader.backend.models import BookDocument, Chapter, Heading, LinkSpan, PageBreak, TocNode

_RAW_URL_RE = re.compile(r"(?:https?://|mailto:)[^\s<>\"'\)\]]+")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")

SUPPORTED_EXTENSIONS = (
    ".epub",
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".html",
    ".htm",
    ".xhtml",
    ".opf",
)


def _safe_zip_path(base_dir: str, rel_href: str) -> str:
    """Resolve a ZIP-internal relative href safely without allowing traversal."""
    clean_href = urllib.parse.unquote(rel_href.split("#", 1)[0]).replace("\\", "/")
    joined = posixpath.normpath(posixpath.join(base_dir, clean_href)) if base_dir else posixpath.normpath(clean_href)
    parts = PurePosixPath(joined).parts
    if joined.startswith("/") or ".." in parts:
        raise ValueError(f"Unsafe archive path detected: {rel_href}")
    return joined


def _split_href(base_dir: str, raw_href: str) -> tuple[str, str]:
    """Return (normalized_archive_path, fragment_id) from a relative href."""
    path_part, _, frag = raw_href.partition("#")
    return _safe_zip_path(base_dir, path_part), urllib.parse.unquote(frag)


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1].lower()


def _read_text_with_fallback(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _fallback_toc_from_chapters(chapters: list[Chapter]) -> list[TocNode]:
    nodes: list[TocNode] = []
    for chap in chapters:
        children = [
            TocNode(title=h.title, chapter_index=chap.index, char_offset=h.char_offset)
            for h in chap.headings
        ]
        nodes.append(
            TocNode(
                title=f"{chap.index + 1}. {chap.title}",
                chapter_index=chap.index,
                char_offset=0,
                children=children,
            )
        )
    return nodes


def _extract_raw_urls(
    text: str,
    existing_links: list[LinkSpan] | None = None,
) -> list[LinkSpan]:
    """Extract raw http(s)/mailto URLs not already covered by existing_links."""
    occupied = [(lnk.start_offset, lnk.end_offset) for lnk in (existing_links or ())]
    found: list[LinkSpan] = []
    for m in _RAW_URL_RE.finditer(text):
        start, end = m.span()
        raw = m.group(0).rstrip(".,;:!?")
        end = start + len(raw)
        if end <= start:
            continue
        if any(not (end <= s or start >= e) for s, e in occupied):
            continue
        found.append(LinkSpan(text=raw, href=raw, start_offset=start, end_offset=end))
    return found


def _extract_markdown_links(text: str) -> list[LinkSpan]:
    """Extract Markdown [label](url) links and any standalone raw URLs."""
    links: list[LinkSpan] = []
    for m in _MD_LINK_RE.finditer(text):
        label = m.group(1).strip() or m.group(2)
        href = m.group(2).strip()
        start, end = m.span()
        links.append(LinkSpan(text=label, href=href, start_offset=start, end_offset=end))
    links.extend(_extract_raw_urls(text, links))
    links.sort(key=lambda lnk: lnk.start_offset)
    return links


def _extract_html_links(raw_html: str, chapter_text: str) -> list[LinkSpan]:
    """Extract <a href> links from HTML and map them onto chapter_text offsets."""
    soup = BeautifulSoup(raw_html, "html.parser")
    links: list[LinkSpan] = []
    cursor = 0
    for a_tag in soup.find_all("a", href=True):
        href = str(a_tag.get("href", "")).strip()
        label = " ".join(a_tag.get_text(" ", strip=True).split())
        if not href or not label:
            continue
        idx = chapter_text.find(label, cursor)
        if idx < 0:
            idx = chapter_text.find(label)
        if idx < 0:
            continue
        end = idx + len(label)
        cursor = end
        links.append(LinkSpan(text=label, href=href, start_offset=idx, end_offset=end))
    links.extend(_extract_raw_urls(chapter_text, links))
    links.sort(key=lambda lnk: lnk.start_offset)
    return links


def _parse_txt(path: Path) -> BookDocument:
    content = _read_text_with_fallback(path.read_bytes()).replace("\r\n", "\n")
    headings: list[Heading] = []
    if path.suffix.lower() == ".md":
        offset = 0
        for line in content.split("\n"):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                hashes = len(stripped) - len(stripped.lstrip("#"))
                if 1 <= hashes <= 6 and (len(stripped) == hashes or stripped[hashes] == " "):
                    title = stripped[hashes:].strip()
                    if title:
                        headings.append(Heading(hashes, title, offset))
            offset += len(line) + 1
        links = _extract_markdown_links(content)
    else:
        links = _extract_raw_urls(content)

    chapter = Chapter(index=0, title=path.stem, text=content, headings=headings, links=links)
    return BookDocument(
        title=path.stem,
        author="Unknown",
        source_path=str(path),
        format_name=path.suffix.lstrip(".").upper() or "TXT",
        chapters=[chapter],
        toc=_fallback_toc_from_chapters([chapter]),
    )


def _parse_html_file(path: Path) -> BookDocument:
    raw_html = _read_text_with_fallback(path.read_bytes())
    res = extract_html_document(raw_html)
    headings = [Heading(h.level, h.text, h.char_offset) for h in res.headings]
    page_breaks = [PageBreak(pb.label, 0, pb.char_offset) for pb in res.page_breaks]
    links = _extract_html_links(raw_html, res.text)
    for lnk in links:
        if lnk.href.startswith("#"):
            frag = lnk.href[1:]
            if frag in res.anchors:
                lnk.target_chapter = 0
                lnk.target_offset = res.anchors[frag]
    title = headings[0].title if headings else path.stem
    chapter = Chapter(index=0, title=title, text=res.text, headings=headings, links=links)
    return BookDocument(
        title=title,
        author="Unknown",
        source_path=str(path),
        format_name="HTML",
        chapters=[chapter],
        toc=_fallback_toc_from_chapters([chapter]),
        page_breaks=page_breaks,
    )


def _parse_docx(path: Path) -> BookDocument:
    ns_w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs: list[str] = []
    headings: list[Heading] = []
    char_len = 0

    with zipfile.ZipFile(path, "r") as zf:
        if "word/document.xml" not in zf.namelist():
            raise ValueError("Invalid DOCX file: missing word/document.xml")
        xml_bytes = zf.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    for p_elem in root.iter(f"{ns_w}p"):
        text_runs = [t.text for t in p_elem.iter(f"{ns_w}t") if t.text]
        para_text = "".join(text_runs).strip()
        if not para_text:
            continue

        heading_level = None
        p_style = p_elem.find(f"{ns_w}pPr/{ns_w}pStyle")
        if p_style is not None:
            style_val = p_style.attrib.get(f"{ns_w}val", "")
            if style_val.lower().startswith("heading") and style_val[7:].isdigit():
                heading_level = max(1, min(6, int(style_val[7:])))
            elif style_val.lower() == "title":
                heading_level = 1

        if heading_level is not None:
            headings.append(Heading(heading_level, para_text, char_len))

        paragraphs.append(para_text)
        char_len += len(para_text) + 2

    full_text = "\n\n".join(paragraphs)
    title = headings[0].title if headings else path.stem
    chapter = Chapter(
        index=0,
        title=title,
        text=full_text,
        headings=headings,
        links=_extract_raw_urls(full_text),
    )
    return BookDocument(
        title=title,
        author="Unknown",
        source_path=str(path),
        format_name="DOCX",
        chapters=[chapter],
        toc=_fallback_toc_from_chapters([chapter]),
    )


def _parse_pdf(path: Path) -> BookDocument:
    chapters: list[Chapter] = []
    page_breaks: list[PageBreak] = []
    page_locations: dict[int, tuple[int, int]] = {}

    with fitz.open(path) as doc:
        meta = doc.metadata or {}
        title = (meta.get("title") or "").strip() or path.stem
        author = (meta.get("author") or "").strip() or "Unknown"
        raw_toc = doc.get_toc(simple=True) or []

        if doc.page_count == 0:
            chapters.append(Chapter(index=0, title=title, text=""))
        else:
            toc_by_page: dict[int, list[tuple[int, str]]] = {}
            for lvl, heading_title, page_num in raw_toc:
                toc_by_page.setdefault(page_num, []).append((max(1, min(6, lvl)), heading_title))

            chunk_size = 25
            for chunk_idx, start_page in enumerate(range(0, doc.page_count, chunk_size)):
                end_page = min(doc.page_count, start_page + chunk_size)
                parts: list[str] = []
                headings: list[Heading] = []
                char_len = 0

                for page_zero in range(start_page, end_page):
                    page_num = page_zero + 1
                    page_locations[page_num] = (chunk_idx, char_len)
                    page_breaks.append(PageBreak(str(page_num), chunk_idx, char_len))
                    page_marker = f"--- Page {page_num} ---\n"
                    for lvl, h_title in toc_by_page.get(page_num, []):
                        headings.append(Heading(lvl, h_title, char_len))
                    page_text = doc.load_page(page_zero).get_text("text").strip()
                    block = page_marker + (page_text or "[No extractable text on this page]")
                    parts.append(block)
                    char_len += len(block) + 2

                chap_title = (
                    f"Pages {start_page + 1}-{end_page}"
                    if doc.page_count > chunk_size
                    else title
                )
                chap_text = "\n\n".join(parts)
                chapters.append(
                    Chapter(
                        index=chunk_idx,
                        title=chap_title,
                        text=chap_text,
                        headings=headings,
                        links=_extract_raw_urls(chap_text),
                    )
                )

        toc_nodes: list[TocNode] = []
        if raw_toc:
            for _lvl, h_title, page_num in raw_toc:
                c_idx, c_off = page_locations.get(page_num, (0, 0))
                toc_nodes.append(TocNode(title=h_title, chapter_index=c_idx, char_offset=c_off))
        else:
            toc_nodes = _fallback_toc_from_chapters(chapters)

    return BookDocument(
        title=title,
        author=author,
        source_path=str(path),
        format_name="PDF",
        chapters=chapters,
        toc=toc_nodes,
        page_breaks=page_breaks,
    )


def _resolve_target(
    base_dir: str,
    raw_href: str,
    href_map: dict[str, tuple[int, dict[str, int]]],
) -> tuple[int, int] | None:
    try:
        file_path, frag = _split_href(base_dir, raw_href)
    except ValueError:
        return None
    target = href_map.get(file_path)
    if target is None:
        return None
    chap_idx, anchors = target
    offset = anchors.get(frag, 0) if frag else 0
    return chap_idx, offset


def _parse_nav_xhtml(
    nav_bytes: bytes,
    nav_path: str,
    href_map: dict[str, tuple[int, dict[str, int]]],
) -> tuple[list[TocNode], list[PageBreak]]:
    nav_dir = posixpath.dirname(nav_path)
    try:
        root = ET.fromstring(nav_bytes)
    except ET.ParseError:
        return [], []

    def elem_text(el: ET.Element) -> str:
        return " ".join("".join(el.itertext()).split())

    def parse_ol(ol_elem: ET.Element) -> list[TocNode]:
        nodes: list[TocNode] = []
        for li in ol_elem:
            if _local_tag(li.tag) != "li":
                continue
            link = None
            sub_ol = None
            for child in li:
                tag = _local_tag(child.tag)
                if tag == "a" and link is None:
                    link = child
                elif tag == "ol" and sub_ol is None:
                    sub_ol = child
            children = parse_ol(sub_ol) if sub_ol is not None else []
            if link is not None:
                title = elem_text(link)
                href = link.attrib.get("href", "")
                resolved = _resolve_target(nav_dir, href, href_map)
                if resolved is not None and title:
                    nodes.append(
                        TocNode(
                            title=title,
                            chapter_index=resolved[0],
                            char_offset=resolved[1],
                            children=children,
                        )
                    )
                elif children:
                    nodes.extend(children)
            elif children:
                nodes.extend(children)
        return nodes

    toc_nodes: list[TocNode] = []
    page_breaks: list[PageBreak] = []

    for nav in root.iter():
        if _local_tag(nav.tag) != "nav":
            continue
        nav_type = ""
        for k, v in nav.attrib.items():
            if k.endswith("type") or k == "role":
                nav_type += f" {v.lower()}"
        ol = next((c for c in nav if _local_tag(c.tag) == "ol"), None)
        if ol is None:
            continue
        if "page-list" in nav_type or "doc-pagelist" in nav_type:
            for a_el in ol.iter():
                if _local_tag(a_el.tag) == "a":
                    lbl = elem_text(a_el)
                    href = a_el.attrib.get("href", "")
                    resolved = _resolve_target(nav_dir, href, href_map)
                    if resolved is not None and lbl:
                        page_breaks.append(PageBreak(lbl, resolved[0], resolved[1]))
        elif "toc" in nav_type or not toc_nodes:
            parsed = parse_ol(ol)
            if parsed:
                toc_nodes = parsed

    return toc_nodes, page_breaks


def _parse_ncx(
    ncx_bytes: bytes,
    ncx_path: str,
    href_map: dict[str, tuple[int, dict[str, int]]],
) -> tuple[list[TocNode], list[PageBreak]]:
    ncx_dir = posixpath.dirname(ncx_path)
    try:
        root = ET.fromstring(ncx_bytes)
    except ET.ParseError:
        return [], []

    def parse_navpoints(parent: ET.Element) -> list[TocNode]:
        nodes: list[TocNode] = []
        for child in parent:
            if _local_tag(child.tag) != "navpoint":
                continue
            label_text = ""
            src = ""
            for sub in child:
                st = _local_tag(sub.tag)
                if st == "navlabel":
                    label_text = " ".join("".join(sub.itertext()).split())
                elif st == "content":
                    src = sub.attrib.get("src", "")
            sub_nodes = parse_navpoints(child)
            resolved = _resolve_target(ncx_dir, src, href_map) if src else None
            if resolved is not None and label_text:
                nodes.append(
                    TocNode(
                        title=label_text,
                        chapter_index=resolved[0],
                        char_offset=resolved[1],
                        children=sub_nodes,
                    )
                )
            elif sub_nodes:
                nodes.extend(sub_nodes)
        return nodes

    toc_nodes: list[TocNode] = []
    page_breaks: list[PageBreak] = []
    for elem in root.iter():
        tag = _local_tag(elem.tag)
        if tag == "navmap" and not toc_nodes:
            toc_nodes = parse_navpoints(elem)
        elif tag == "pagelist":
            for pt in elem:
                if _local_tag(pt.tag) != "pagetarget":
                    continue
                lbl = ""
                src = ""
                for sub in pt:
                    st = _local_tag(sub.tag)
                    if st == "navlabel":
                        lbl = " ".join("".join(sub.itertext()).split())
                    elif st == "content":
                        src = sub.attrib.get("src", "")
                resolved = _resolve_target(ncx_dir, src, href_map) if src else None
                if resolved is not None and lbl:
                    page_breaks.append(PageBreak(lbl, resolved[0], resolved[1]))

    return toc_nodes, page_breaks


def _parse_opf_from_reader(
    read_entry,
    opf_path: str,
    source_path: Path,
    format_name: str,
) -> BookDocument:
    opf_dir = posixpath.dirname(opf_path)
    opf_root = ET.fromstring(read_entry(opf_path))

    title = source_path.stem
    author = "Unknown"
    manifest: dict[str, tuple[str, str, str]] = {}
    spine_ids: list[str] = []
    spine_toc_id = ""

    for elem in opf_root.iter():
        tag = _local_tag(elem.tag)
        if tag == "title" and elem.text and elem.text.strip():
            title = elem.text.strip()
        elif tag == "creator" and elem.text and elem.text.strip():
            author = elem.text.strip()
        elif tag == "item":
            item_id = elem.attrib.get("id", "")
            href = elem.attrib.get("href", "")
            media_type = elem.attrib.get("media-type", "")
            props = elem.attrib.get("properties", "")
            if item_id and href:
                manifest[item_id] = (_safe_zip_path(opf_dir, href), media_type, props)
        elif tag == "spine":
            spine_toc_id = elem.attrib.get("toc", "")
        elif tag == "itemref":
            idref = elem.attrib.get("idref", "")
            if idref:
                spine_ids.append(idref)

    chapters: list[Chapter] = []
    href_map: dict[str, tuple[int, dict[str, int]]] = {}
    inline_page_breaks: list[PageBreak] = []

    for idref in spine_ids:
        entry = manifest.get(idref)
        if not entry:
            continue
        href_path, media_type, _props = entry
        if "html" not in media_type and not href_path.lower().endswith((".html", ".xhtml", ".htm", ".xml")):
            continue
        try:
            raw_bytes = read_entry(href_path)
        except KeyError:
            continue

        raw_html = _read_text_with_fallback(raw_bytes)
        res = extract_html_document(raw_html)
        if not res.text.strip():
            continue
        chap_idx = len(chapters)
        headings = [Heading(h.level, h.text, h.char_offset) for h in res.headings]
        chap_title = headings[0].title if headings else f"Section {chap_idx + 1}"
        links = _extract_html_links(raw_html, res.text)
        chapters.append(
            Chapter(
                index=chap_idx,
                title=chap_title,
                text=res.text,
                headings=headings,
                links=links,
            )
        )
        href_map[href_path] = (chap_idx, dict(res.anchors))
        for pb in res.page_breaks:
            inline_page_breaks.append(PageBreak(pb.label, chap_idx, pb.char_offset))

    # Resolve internal EPUB/DAISY links once href_map is complete
    chapter_dirs = [posixpath.dirname(hp) for hp in href_map]
    for chap, base_dir in zip(chapters, chapter_dirs):
        for lnk in chap.links:
            if not lnk.href.lower().startswith(("http://", "https://", "mailto:")):
                resolved = _resolve_target(base_dir, lnk.href, href_map)
                if resolved is not None:
                    lnk.target_chapter, lnk.target_offset = resolved

    if not chapters:
        chapters.append(Chapter(index=0, title=title, text="[No readable text chapters found]"))

    toc_nodes: list[TocNode] = []
    nav_page_breaks: list[PageBreak] = []

    # 1. Prefer EPUB 3 nav document (properties="nav")
    nav_entry = next(
        (v for v in manifest.values() if "nav" in v[2].split()),
        None,
    )
    if nav_entry is not None:
        try:
            toc_nodes, nav_page_breaks = _parse_nav_xhtml(read_entry(nav_entry[0]), nav_entry[0], href_map)
        except KeyError:
            pass

    # 2. Fallback to EPUB 2 / DAISY NCX
    if not toc_nodes:
        ncx_entry = manifest.get(spine_toc_id) if spine_toc_id else None
        if ncx_entry is None:
            ncx_entry = next(
                (v for v in manifest.values() if "ncx" in v[1].lower() or v[0].lower().endswith(".ncx")),
                None,
            )
        if ncx_entry is not None:
            try:
                toc_nodes, ncx_pbs = _parse_ncx(read_entry(ncx_entry[0]), ncx_entry[0], href_map)
                if not nav_page_breaks:
                    nav_page_breaks = ncx_pbs
            except KeyError:
                pass

    if not toc_nodes:
        toc_nodes = _fallback_toc_from_chapters(chapters)

    page_breaks = nav_page_breaks or inline_page_breaks

    return BookDocument(
        title=title,
        author=author,
        source_path=str(source_path),
        format_name=format_name,
        chapters=chapters,
        toc=toc_nodes,
        page_breaks=page_breaks,
    )


def _parse_epub(path: Path) -> BookDocument:
    with zipfile.ZipFile(path, "r") as zf:
        def read_entry(entry_path: str) -> bytes:
            return zf.read(entry_path)

        names = set(zf.namelist())
        if "META-INF/container.xml" in names:
            container_root = ET.fromstring(read_entry("META-INF/container.xml"))
            opf_path = None
            for elem in container_root.iter():
                if _local_tag(elem.tag) == "rootfile":
                    opf_path = elem.attrib.get("full-path")
                    if opf_path:
                        break
            if not opf_path:
                raise ValueError("Invalid EPUB: missing rootfile in container.xml")
            opf_path = _safe_zip_path("", opf_path)
            return _parse_opf_from_reader(read_entry, opf_path, path, "EPUB")

        opf_candidates = [n for n in names if n.lower().endswith(".opf")]
        if opf_candidates:
            return _parse_opf_from_reader(read_entry, opf_candidates[0], path, "DAISY 3")
        raise ValueError("Unsupported ZIP/EPUB archive: missing container.xml or OPF package")


def _parse_daisy_opf(path: Path) -> BookDocument:
    base_dir = path.parent.resolve()

    def read_local(rel_path: str) -> bytes:
        target = (base_dir / rel_path).resolve()
        if not target.is_relative_to(base_dir):
            raise ValueError(f"Unsafe path traversal outside book directory: {rel_path}")
        return target.read_bytes()

    return _parse_opf_from_reader(read_local, path.name, path, "DAISY")


def load_book(file_path: str | Path) -> BookDocument:
    """Load any supported book format into a normalized BookDocument."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Book file not found: {path}")

    ext = path.suffix.lower()
    if ext in (".txt", ".md"):
        return _parse_txt(path)
    if ext in (".html", ".htm", ".xhtml"):
        return _parse_html_file(path)
    if ext == ".docx":
        return _parse_docx(path)
    if ext == ".pdf":
        return _parse_pdf(path)
    if ext == ".epub":
        return _parse_epub(path)
    if ext == ".opf":
        return _parse_daisy_opf(path)
    raise ValueError(f"Unsupported file format: {ext}")
