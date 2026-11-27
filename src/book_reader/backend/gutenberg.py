"""Project Gutenberg API client and book downloader using Gutendex."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import urllib.parse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class GutenbergBook:
    """Representation of a book in Project Gutenberg."""

    id: int
    title: str
    authors: list[str]
    languages: list[str]
    formats: dict[str, str]
    download_count: int

    @property
    def author_display(self) -> str:
        return ", ".join(self.authors) if self.authors else "Unknown Author"

    @property
    def epub_url(self) -> str | None:
        """Get best EPUB download URL (prefers epub.images, then epub.noimages)."""
        for mime in (
            "application/epub+zip",
            "application/x-mobipocket-ebook",
        ):
            if mime in self.formats:
                return self.formats[mime]
        for k, v in self.formats.items():
            if "epub" in k.lower():
                return v
        return None

    @property
    def text_url(self) -> str | None:
        """Get plain text fallback URL."""
        for k, v in self.formats.items():
            if "text/plain" in k.lower():
                return v
        return None


def search_gutenberg(query: str, timeout: float = 12.0) -> list[GutenbergBook]:
    """Search Project Gutenberg books via Gutendex open API."""
    encoded = urllib.parse.quote_plus(query.strip())
    url = f"https://gutendex.com/books/?search={encoded}"
    req = Request(
        url,
        headers={"User-Agent": "Open-Reader/26.0 (Accessibility desktop reader)"},
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results: list[GutenbergBook] = []
    for item in data.get("results", []):
        authors = [a.get("name", "") for a in item.get("authors", []) if a.get("name")]
        languages = item.get("languages", [])
        formats = item.get("formats", {})
        book = GutenbergBook(
            id=item.get("id", 0),
            title=item.get("title", "Untitled"),
            authors=authors,
            languages=languages,
            formats=formats,
            download_count=item.get("download_count", 0),
        )
        results.append(book)
    return results


def download_gutenberg_book(
    book: GutenbergBook,
    dest_dir: Path,
    progress_cb=None,
    timeout: float = 30.0,
) -> Path:
    """Download the chosen Gutenberg book (prefers EPUB, falls back to TXT)."""
    download_url = book.epub_url or book.text_url
    if not download_url:
        raise ValueError(f"No suitable download format found for '{book.title}'")

    ext = ".epub" if book.epub_url else ".txt"
    safe_title = re.sub(r'[\\/*?:"<>|]', "_", book.title)[:60].strip()
    filename = f"{safe_title}_{book.id}{ext}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    target_path = dest_dir / filename
    temp_path = dest_dir / f"{filename}.part"

    req = Request(
        download_url,
        headers={"User-Agent": "Open-Reader/26.0 (Accessibility desktop reader)"},
    )
    with urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        downloaded = 0
        with open(temp_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    progress_cb(downloaded, total)

    if temp_path.exists():
        temp_path.replace(target_path)
    return target_path
