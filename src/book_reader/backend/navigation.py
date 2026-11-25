"""Book navigation engine: history stack, headings by level, paragraphs, sentences, pages, and Where-Am-I."""

from __future__ import annotations

from dataclasses import dataclass

from book_reader.backend.engine import SentenceSpan, paragraph_offsets, split_sentences
from book_reader.backend.models import BookDocument, Heading, PageBreak


@dataclass(frozen=True, slots=True)
class NavLocation:
    """Exact cursor position inside a BookDocument."""

    chapter_index: int
    char_offset: int


class NavigationController:
    """Manages structural navigation, jump history, page lookup, and location reporting."""

    def __init__(self, book: BookDocument | None = None) -> None:
        self.book = book
        self._back_stack: list[NavLocation] = []
        self._forward_stack: list[NavLocation] = []
        self._para_cache: dict[int, list[int]] = {}
        self._sent_cache: dict[int, list[SentenceSpan]] = {}

    def set_book(self, book: BookDocument | None) -> None:
        self.book = book
        self._back_stack.clear()
        self._forward_stack.clear()
        self._para_cache.clear()
        self._sent_cache.clear()

    def _paragraphs(self, chapter_index: int) -> list[int]:
        if not self.book or not (0 <= chapter_index < self.book.chapter_count):
            return []
        if chapter_index not in self._para_cache:
            self._para_cache[chapter_index] = paragraph_offsets(self.book.chapters[chapter_index].text)
        return self._para_cache[chapter_index]

    def _sentences(self, chapter_index: int) -> list[SentenceSpan]:
        if not self.book or not (0 <= chapter_index < self.book.chapter_count):
            return []
        if chapter_index not in self._sent_cache:
            self._sent_cache[chapter_index] = split_sentences(self.book.chapters[chapter_index].text)
        return self._sent_cache[chapter_index]

    # --- Jump History ---

    def record_jump(self, from_loc: NavLocation) -> None:
        if not self._back_stack or self._back_stack[-1] != from_loc:
            self._back_stack.append(from_loc)
            if len(self._back_stack) > 100:
                self._back_stack.pop(0)
        self._forward_stack.clear()

    def go_back(self, current_loc: NavLocation) -> NavLocation | None:
        if not self._back_stack:
            return None
        target = self._back_stack.pop()
        self._forward_stack.append(current_loc)
        return target

    def go_forward(self, current_loc: NavLocation) -> NavLocation | None:
        if not self._forward_stack:
            return None
        target = self._forward_stack.pop()
        self._back_stack.append(current_loc)
        return target

    # --- Page Navigation ---

    def go_to_page(self, query: str) -> PageBreak | None:
        if not self.book or not self.book.page_breaks:
            return None
        needle = query.strip().lower()
        if not needle:
            return None
        for pb in self.book.page_breaks:
            if pb.label.strip().lower() == needle:
                return pb
        for pb in self.book.page_breaks:
            if needle in pb.label.strip().lower():
                return pb
        return None

    # --- Heading Navigation (cross-chapter + optional level 1..6) ---

    def step_heading(
        self,
        chapter_index: int,
        char_offset: int,
        delta: int,
        level: int | None = None,
    ) -> tuple[int, Heading] | None:
        if not self.book or self.book.chapter_count == 0:
            return None

        def matches(h: Heading) -> bool:
            return level is None or h.level == level

        if delta >= 0:
            # Current chapter first
            cur_headings = [h for h in self.book.chapters[chapter_index].headings if matches(h) and h.char_offset > char_offset]
            if cur_headings:
                return chapter_index, cur_headings[0]
            # Subsequent chapters
            for c_idx in range(chapter_index + 1, self.book.chapter_count):
                ch_headings = [h for h in self.book.chapters[c_idx].headings if matches(h)]
                if ch_headings:
                    return c_idx, ch_headings[0]
            return None

        # delta < 0: Backward
        cur_headings = [h for h in self.book.chapters[chapter_index].headings if matches(h) and h.char_offset < char_offset]
        if cur_headings:
            return chapter_index, cur_headings[-1]
        for c_idx in range(chapter_index - 1, -1, -1):
            ch_headings = [h for h in self.book.chapters[c_idx].headings if matches(h)]
            if ch_headings:
                return c_idx, ch_headings[-1]
        return None

    # --- Paragraph Navigation ---

    def step_paragraph(
        self,
        chapter_index: int,
        char_offset: int,
        delta: int,
    ) -> NavLocation | None:
        if not self.book or self.book.chapter_count == 0:
            return None
        paras = self._paragraphs(chapter_index)
        if delta >= 0:
            nxt = [p for p in paras if p > char_offset]
            if nxt:
                return NavLocation(chapter_index, nxt[0])
            for c_idx in range(chapter_index + 1, self.book.chapter_count):
                c_paras = self._paragraphs(c_idx)
                if c_paras:
                    return NavLocation(c_idx, c_paras[0])
            return None

        prv = [p for p in paras if p < char_offset]
        if prv:
            return NavLocation(chapter_index, prv[-1])
        for c_idx in range(chapter_index - 1, -1, -1):
            c_paras = self._paragraphs(c_idx)
            if c_paras:
                return NavLocation(c_idx, c_paras[-1])
        return None

    # --- Sentence Navigation ---

    def step_sentence(
        self,
        chapter_index: int,
        char_offset: int,
        delta: int,
    ) -> tuple[NavLocation, SentenceSpan] | None:
        if not self.book or self.book.chapter_count == 0:
            return None
        spans = self._sentences(chapter_index)
        if spans:
            cur_idx = 0
            for idx, sp in enumerate(spans):
                if sp.end >= char_offset:
                    cur_idx = idx
                    break
            else:
                cur_idx = len(spans) - 1

            target_idx = cur_idx + delta
            if 0 <= target_idx < len(spans):
                sp = spans[target_idx]
                return NavLocation(chapter_index, sp.start), sp

        # Cross chapter boundary
        if delta > 0:
            for c_idx in range(chapter_index + 1, self.book.chapter_count):
                c_spans = self._sentences(c_idx)
                if c_spans:
                    sp = c_spans[0]
                    return NavLocation(c_idx, sp.start), sp
        elif delta < 0:
            for c_idx in range(chapter_index - 1, -1, -1):
                c_spans = self._sentences(c_idx)
                if c_spans:
                    sp = c_spans[-1]
                    return NavLocation(c_idx, sp.start), sp
        return None

    # --- Current Context / Where Am I ---

    def current_heading(self, chapter_index: int, char_offset: int) -> Heading | None:
        if not self.book or not (0 <= chapter_index < self.book.chapter_count):
            return None
        active = None
        for h in self.book.chapters[chapter_index].headings:
            if h.char_offset <= char_offset:
                active = h
            else:
                break
        return active

    def current_page(self, chapter_index: int, char_offset: int) -> PageBreak | None:
        if not self.book or not self.book.page_breaks:
            return None
        active = None
        for pb in self.book.page_breaks:
            if (pb.chapter_index, pb.char_offset) <= (chapter_index, char_offset):
                active = pb
        return active

    def progress_percent(self, chapter_index: int, char_offset: int) -> float:
        if not self.book or self.book.total_chars == 0:
            return 0.0
        before = sum(len(self.book.chapters[i].text) for i in range(chapter_index))
        pos = before + max(0, min(char_offset, len(self.book.chapters[chapter_index].text)))
        return round((pos / self.book.total_chars) * 100.0, 1)

    def where_am_i(self, chapter_index: int, char_offset: int) -> str:
        if not self.book:
            return "No book open."
        chap = self.book.chapters[chapter_index]
        parts = [
            f"{self.book.title}",
            f"Section {chapter_index + 1} of {self.book.chapter_count}: {chap.title}",
        ]
        hd = self.current_heading(chapter_index, char_offset)
        if hd:
            parts.append(f"Heading level {hd.level}: {hd.title}")
        pb = self.current_page(chapter_index, char_offset)
        if pb:
            parts.append(f"Page {pb.label}")
        pct = self.progress_percent(chapter_index, char_offset)
        parts.append(f"{pct}% complete")
        return ". ".join(parts) + "."
