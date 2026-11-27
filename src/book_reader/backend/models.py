"""Core data models for normalized book representations and navigation."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class Heading:
    """Represents a structural heading inside a chapter."""

    level: int
    title: str
    char_offset: int


@dataclass(slots=True)
class PageBreak:
    """Represents a print/PDF page target within the book."""

    label: str
    chapter_index: int
    char_offset: int


@dataclass(slots=True)
class TocNode:
    """Hierarchical Table of Contents entry resolved to chapter + char offset."""

    title: str
    chapter_index: int
    char_offset: int
    children: list["TocNode"] = field(default_factory=list)


@dataclass(slots=True)
class LinkSpan:
    """Represents a clickable/navigable hyperlink inside a chapter."""

    text: str
    href: str
    start_offset: int
    end_offset: int
    target_chapter: int | None = None
    target_offset: int | None = None


@dataclass(slots=True)
class Chapter:
    """Normalized chapter content ready for reading and navigation."""

    index: int
    title: str
    text: str
    headings: list[Heading] = field(default_factory=list)
    links: list[LinkSpan] = field(default_factory=list)


@dataclass(slots=True)
class BookDocument:
    """Unified internal publication model across EPUB, DAISY, PDF, DOCX, HTML, and TXT."""

    title: str
    author: str
    source_path: str
    format_name: str
    chapters: list[Chapter] = field(default_factory=list)
    toc: list[TocNode] = field(default_factory=list)
    page_breaks: list[PageBreak] = field(default_factory=list)

    @property
    def chapter_count(self) -> int:
        return len(self.chapters)

    @property
    def total_chars(self) -> int:
        return sum(len(c.text) for c in self.chapters)


@dataclass(slots=True)
class Bookmark:
    """User bookmark tied to a specific book, chapter, and character offset."""

    book_path: str
    chapter_index: int
    char_offset: int
    label: str
    created_at: str
