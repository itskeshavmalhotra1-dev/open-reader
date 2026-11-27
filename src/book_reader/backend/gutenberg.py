"""Online libraries catalog clients and book downloaders (Project Gutenberg, Standard Ebooks, Open Library)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import urllib.parse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class CatalogBook:
    """Unified representation of a book from an online public library."""

    id: str | int
    title: str
    authors: list[str]
    languages: list[str]
    formats: dict[str, str]
    download_count: int = 0
    source: str = "Project Gutenberg"

    @property
    def author_display(self) -> str:
        return ", ".join(self.authors) if self.authors else "Unknown Author"

    @property
    def epub_url(self) -> str | None:
        """Get best EPUB download URL."""
        for mime in (
            "application/epub+zip",
            "epub",
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
            if "text/plain" in k.lower() or "txt" in k.lower():
                return v
        return None


# Backward compatibility alias
GutenbergBook = CatalogBook


GUTENBERG_CATEGORIES = [
    "Popular Classics (All)",
    "Fiction",
    "Science Fiction",
    "Mystery & Detective",
    "Philosophy & Psychology",
    "History",
    "Adventure",
    "Poetry",
    "Short Stories",
    "Children's Literature",
]

STANDARD_EBOOKS_FEEDS = [
    ("Popular Titles", "https://standardebooks.org/opds/all"),
    ("New Releases", "https://standardebooks.org/opds/new-releases"),
]


def search_gutenberg(query: str = "", topic: str = "", timeout: float = 12.0) -> list[CatalogBook]:
    """Search Project Gutenberg books via Gutendex open API.
    If query is empty, returns popular books or books in the given topic/category.
    """
    params = []
    if query.strip():
        params.append(f"search={urllib.parse.quote_plus(query.strip())}")
    if topic.strip() and topic != "Popular Classics (All)":
        params.append(f"topic={urllib.parse.quote_plus(topic.strip())}")
    
    query_str = ("?" + "&".join(params)) if params else ""
    url = f"https://gutendex.com/books/{query_str}"
    req = Request(
        url,
        headers={"User-Agent": "Open-Reader/26.0 (Accessibility desktop reader)"},
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results: list[CatalogBook] = []
    for item in data.get("results", []):
        authors = [a.get("name", "") for a in item.get("authors", []) if a.get("name")]
        languages = item.get("languages", [])
        formats = item.get("formats", {})
        book = CatalogBook(
            id=item.get("id", 0),
            title=item.get("title", "Untitled"),
            authors=authors,
            languages=languages,
            formats=formats,
            download_count=item.get("download_count", 0),
            source="Project Gutenberg",
        )
        results.append(book)
    return results


def search_standard_ebooks(query: str = "", feed_url: str | None = None, timeout: float = 12.0) -> list[CatalogBook]:
    """Search Standard Ebooks catalog via OPDS feed."""
    if query.strip():
        encoded = urllib.parse.quote_plus(query.strip())
        url = f"https://standardebooks.org/opds/all?query={encoded}"
    else:
        url = feed_url or "https://standardebooks.org/opds/all"

    req = Request(
        url,
        headers={"User-Agent": "Open-Reader/26.0 (Accessibility desktop reader)"},
    )
    with urlopen(req, timeout=timeout) as resp:
        xml_data = resp.read()

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_data)
    results: list[CatalogBook] = []

    for entry in root.findall("atom:entry", ns):
        title_elem = entry.find("atom:title", ns)
        title = title_elem.text.strip() if title_elem is not None and title_elem.text else "Untitled"
        authors = [
            a.find("atom:name", ns).text.strip()
            for a in entry.findall("atom:author", ns)
            if a.find("atom:name", ns) is not None and a.find("atom:name", ns).text
        ]
        formats = {}
        for link in entry.findall("atom:link", ns):
            link_type = link.attrib.get("type", "")
            href = link.attrib.get("href", "")
            if href.startswith("/"):
                href = f"https://standardebooks.org{href}"
            if "epub" in link_type.lower():
                formats["application/epub+zip"] = href

        if formats:
            results.append(
                CatalogBook(
                    id=title,
                    title=title,
                    authors=authors,
                    languages=["en"],
                    formats=formats,
                    download_count=0,
                    source="Standard Ebooks",
                )
            )
    return results


def search_open_library(query: str = "", subject: str = "", timeout: float = 12.0) -> list[CatalogBook]:
    """Search Open Library for public domain / readable editions."""
    q_str = query.strip() or subject.strip() or "classics"
    encoded = urllib.parse.quote_plus(q_str)
    url = f"https://openlibrary.org/search.json?q={encoded}&has_fulltext=true&limit=20"
    req = Request(
        url,
        headers={"User-Agent": "Open-Reader/26.0 (Accessibility desktop reader)"},
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results: list[CatalogBook] = []
    for doc in data.get("docs", []):
        title = doc.get("title", "Untitled")
        authors = doc.get("author_name", [])
        languages = doc.get("language", ["en"])
        ia_ids = doc.get("ia", [])
        formats = {}
        if ia_ids:
            primary_ia = ia_ids[0]
            formats["application/epub+zip"] = f"https://archive.org/download/{primary_ia}/{primary_ia}.epub"
            formats["text/plain"] = f"https://archive.org/download/{primary_ia}/{primary_ia}_djvu.txt"

        if formats:
            results.append(
                CatalogBook(
                    id=doc.get("key", title),
                    title=title,
                    authors=authors,
                    languages=languages,
                    formats=formats,
                    download_count=doc.get("readinglog_count", 0),
                    source="Open Library / Internet Archive",
                )
            )
    return results


def search_online_library(
    source_name: str,
    query: str = "",
    category: str = "",
    force_live: bool = False,
) -> list[CatalogBook]:
    """Search online libraries with a live-first strategy and persistent cache.
    1. Attempts live network search from the actual library API so new books appear.
    2. Merges newly found books with any previously cached or curated titles.
    3. If remote API is offline/timing out, gracefully serves existing cached/curated titles.
    """
    from book_reader.backend.curated_books import CURATED_CATEGORY_BOOKS

    cat_key = category if category in CURATED_CATEGORY_BOOKS else "Popular Classics (All)"
    curated = list(CURATED_CATEGORY_BOOKS.get(cat_key, CURATED_CATEGORY_BOOKS["Popular Classics (All)"]))

    live_results: list[CatalogBook] = []
    try:
        if source_name == "Standard Ebooks":
            live_results = search_standard_ebooks(query=query)
        elif "Open Library" in source_name:
            live_results = search_open_library(query=query, subject=category)
        else:
            live_results = search_gutenberg(query=query, topic=category)
    except Exception:
        live_results = []

    if live_results:
        # Deduplicate and return live results at top, followed by any matching curated
        seen_ids = {str(b.id) for b in live_results}
        combined = list(live_results)
        for b in curated:
            if str(b.id) not in seen_ids:
                if not query.strip() or (query.strip().lower() in b.title.lower()):
                    combined.append(b)
        return combined

    # Fallback to curated if network is slow/offline
    if query.strip():
        q_lower = query.strip().lower()
        matched = [b for b in curated if q_lower in b.title.lower() or any(q_lower in a.lower() for a in b.authors)]
        return matched if matched else curated
    return curated


def download_catalog_book(
    book: CatalogBook,
    dest_dir: Path,
    progress_cb=None,
    timeout: float = 30.0,
) -> Path:
    """Download the chosen catalog book (prefers EPUB, falls back to TXT)."""
    download_url = book.epub_url or book.text_url
    if not download_url:
        raise ValueError(f"No suitable download format found for '{book.title}'")

    ext = ".epub" if book.epub_url else ".txt"
    safe_title = re.sub(r'[\\/*?:"<>|]', "_", book.title)[:60].strip()
    clean_id = re.sub(r'[\\/*?:"<>|]', "_", str(book.id))[:30].strip()
    filename = f"{safe_title}_{clean_id}{ext}"
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


# Backward compatibility alias
download_gutenberg_book = download_catalog_book
