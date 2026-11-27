"""Rust PyO3 backend bridge with pure-Python fallback for identical API parity."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re


@dataclass(slots=True)
class HeadingOffset:
    level: int
    text: str
    char_offset: int


@dataclass(slots=True)
class PageBreakOffset:
    label: str
    char_offset: int


@dataclass(slots=True)
class HtmlExtractResult:
    text: str
    headings: list[HeadingOffset] = field(default_factory=list)
    anchors: dict[str, int] = field(default_factory=dict)
    page_breaks: list[PageBreakOffset] = field(default_factory=list)


@dataclass(slots=True)
class SentenceSpan:
    start: int
    end: int
    text: str


@dataclass(slots=True)
class SearchHit:
    start: int
    end: int
    line_number: int
    snippet: str


_BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "li", "tr", "blockquote", "pre",
    "h1", "h2", "h3", "h4", "h5", "h6",
})
_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_SKIP_TAGS = frozenset({"script", "style", "head"})


class _StructuredHTMLParser(HTMLParser):
    """Fallback HTML extractor matching the Rust quick-xml implementation."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._char_len = 0
        self._skip_depth = 0
        self._active_heading: tuple[int, int, list[str]] | None = None
        self._active_pagebreak: tuple[str, str, int, list[str]] | None = None
        self.headings: list[HeadingOffset] = []
        self.anchors: dict[str, int] = {}
        self.page_breaks: list[PageBreakOffset] = []

    def _ends_with_whitespace(self) -> bool:
        if not self._parts:
            return False
        last = self._parts[-1]
        return bool(last) and last[-1].isspace()

    def _ensure_newline(self, double: bool) -> None:
        while self._parts and self._parts[-1].endswith(" "):
            stripped = self._parts[-1].rstrip(" ")
            removed = len(self._parts[-1]) - len(stripped)
            self._char_len -= removed
            if stripped:
                self._parts[-1] = stripped
            else:
                self._parts.pop()
        if not self._parts:
            return
        tail = "".join(self._parts[-2:])
        if not tail.endswith("\n"):
            self._parts.append("\n")
            self._char_len += 1
            tail += "\n"
        if double and not tail.endswith("\n\n"):
            self._parts.append("\n")
            self._char_len += 1

    def _push_text(self, chunk: str) -> None:
        prev_space = self._ends_with_whitespace()
        buf: list[str] = []
        for ch in chunk:
            mapped = " " if ch == "\u00A0" else ch
            if mapped.isspace():
                if not prev_space and (self._char_len > 0 or buf):
                    buf.append(" ")
                    prev_space = True
            else:
                buf.append(mapped)
                prev_space = False
        if buf:
            text = "".join(buf)
            self._parts.append(text)
            self._char_len += len(text)

    def _inspect_attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> tuple[str, int] | None:
        attr_map = {k.lower(): (v or "").strip() for k, v in attrs}
        elem_id = attr_map.get("id", "")
        if elem_id and elem_id not in self.anchors:
            self.anchors[elem_id] = self._char_len
        type_val = f"{attr_map.get('epub:type', '')} {attr_map.get('type', '')} {attr_map.get('role', '')}"
        if "pagebreak" in type_val or "doc-pagebreak" in type_val:
            lbl = attr_map.get("title") or attr_map.get("aria-label") or ""
            return (lbl, self._char_len)
        return None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return
        if t in _BLOCK_TAGS:
            self._ensure_newline(double=True)
        elif t == "br":
            self._ensure_newline(double=False)
        pb = self._inspect_attrs(t, attrs)
        if pb is not None:
            self._active_pagebreak = (t, pb[0], pb[1], [])
        if t in _HEADING_TAGS:
            self._active_heading = (_HEADING_TAGS[t], self._char_len, [])

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if self._skip_depth > 0:
            return
        if t == "br":
            self._ensure_newline(double=False)
        pb = self._inspect_attrs(t, attrs)
        if pb is not None and pb[0]:
            self.page_breaks.append(PageBreakOffset(pb[0], pb[1]))

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth > 0:
            return
        if self._active_pagebreak is not None and self._active_pagebreak[0] == t:
            _, lbl, offset, chunks = self._active_pagebreak
            final_lbl = lbl or " ".join("".join(chunks).split())
            if final_lbl:
                self.page_breaks.append(PageBreakOffset(final_lbl, offset))
            self._active_pagebreak = None
        if t in _HEADING_TAGS and self._active_heading is not None:
            lvl, offset, chunks = self._active_heading
            if lvl == _HEADING_TAGS[t]:
                title = " ".join("".join(chunks).split())
                if title:
                    self.headings.append(HeadingOffset(lvl, title, offset))
                self._active_heading = None
        if t in _BLOCK_TAGS:
            self._ensure_newline(double=True)

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        self._push_text(data)
        if self._active_heading is not None:
            self._active_heading[2].append(data)
        if self._active_pagebreak is not None:
            self._active_pagebreak[3].append(data)

    def result(self) -> HtmlExtractResult:
        return HtmlExtractResult(
            text="".join(self._parts).rstrip(),
            headings=self.headings,
            anchors=self.anchors,
            page_breaks=self.page_breaks,
        )


def _py_extract_html_document(html: str) -> HtmlExtractResult:
    parser = _StructuredHTMLParser()
    parser.feed(html)
    parser.close()
    return parser.result()


def _py_extract_html_text_and_headings(html: str) -> tuple[str, list[HeadingOffset]]:
    res = _py_extract_html_document(html)
    return res.text, res.headings


def _py_split_sentences(text: str) -> list[SentenceSpan]:
    spans: list[SentenceSpan] = []
    n = len(text)
    start = 0
    i = 0
    closing = {'"', "'", ")", "]", "\u201d", "\u2019"}
    enders = {".", "!", "?", "\u0964", "\u06d4"}

    def emit(raw_start: int, raw_end: int) -> None:
        segment = text[raw_start:raw_end]
        trimmed = segment.strip()
        if not trimmed:
            return
        lead = len(segment) - len(segment.lstrip())
        trail = len(segment) - len(segment.rstrip())
        spans.append(SentenceSpan(raw_start + lead, raw_end - trail, trimmed))

    abbrevs = {
        "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc",
        "e.g", "i.e", "a.m", "p.m", "u.s", "u.k", "no", "vol", "ch", "fig",
    }

    def is_abbrev(dot_idx: int) -> bool:
        k = dot_idx
        while k > 0 and (text[k - 1].isalnum() or text[k - 1] == "."):
            k -= 1
        tok = text[k:dot_idx]
        if len(tok) == 1 and tok.isalpha():
            return True
        return tok.lower() in abbrevs

    def should_split_nl(nl_idx: int, cur_start: int) -> bool:
        j = nl_idx + 1
        while j < n and text[j] in (" ", "\t", "\r"):
            j += 1
        if j >= n or text[j] == "\n":
            return True
        trimmed = text[cur_start:nl_idx].strip()
        if not trimmed:
            return True
        if trimmed.startswith("--- Page ") or trimmed.startswith("#"):
            return True
        if text[j] in ("#", "-", "*"):
            return True
        if trimmed[-1] in (",", ";", ":", "-", "\u2014", "\u2013"):
            return False
        if text[j].islower():
            return False
        return len(trimmed) < 55 and (text[j].isupper() or text[j].isdigit())

    while i < n:
        ch = text[i]
        if ch in enders:
            if ch == "." and i + 1 < n and text[i + 1] == ".":
                while i + 1 < n and text[i + 1] == ".":
                    i += 1
                i += 1
                continue
            if ch == "." and is_abbrev(i):
                i += 1
                continue
            end = i + 1
            while end < n and text[end] in closing:
                end += 1
            if end == n or text[end].isspace():
                emit(start, end)
                start = end
                i = end
                continue
        elif ch == "\n" and should_split_nl(i, start):
            emit(start, i)
            start = i + 1
        i += 1

    if start < n:
        emit(start, n)
    return spans


def _py_paragraph_offsets(text: str) -> list[int]:
    offsets: list[int] = []
    char_pos = 0
    in_blank = True
    for line in text.split("\n"):
        if not line.strip():
            in_blank = True
        elif in_blank:
            leading_ws = len(line) - len(line.lstrip())
            offsets.append(char_pos + leading_ws)
            in_blank = False
        char_pos += len(line) + 1
    return offsets


def _py_search_text(text: str, query: str, max_hits: int | None = 200) -> list[SearchHit]:
    needle = query.strip().lower()
    if not needle:
        return []
    limit = 200 if max_hits is None else max_hits
    hits: list[SearchHit] = []
    char_offset = 0
    pattern = re.escape(needle)

    for line_idx, line in enumerate(text.split("\n"), start=1):
        line_lower = line.lower()
        for match in re.finditer(pattern, line_lower):
            start = char_offset + match.start()
            end = char_offset + match.end()
            hits.append(SearchHit(start, end, line_idx, line.strip()))
            if len(hits) >= limit:
                return hits
        char_offset += len(line) + 1
    return hits


try:
    import book_reader_core as _rust_core  # type: ignore[import-not-found]

    BACKEND_MODE = "rust"
    extract_html_document = _rust_core.extract_html_document
    extract_html_text_and_headings = _rust_core.extract_html_text_and_headings
    split_sentences = _rust_core.split_sentences
    paragraph_offsets = _rust_core.paragraph_offsets
    search_text = _rust_core.search_text
except ImportError:
    BACKEND_MODE = "python-fallback"
    extract_html_document = _py_extract_html_document
    extract_html_text_and_headings = _py_extract_html_text_and_headings
    split_sentences = _py_split_sentences
    paragraph_offsets = _py_paragraph_offsets
    search_text = _py_search_text
