"""Online libraries catalog clients with real-time pagination (Project Gutenberg, Standard Ebooks, Open Library)."""

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
    def pdf_url(self) -> str | None:
        """Get PDF download URL."""
        for mime in ("application/pdf", "pdf"):
            if mime in self.formats:
                return self.formats[mime]
        for k, v in self.formats.items():
            if "pdf" in k.lower():
                return v
        return None

    @property
    def html_url(self) -> str | None:
        """Get HTML download URL."""
        for mime in ("text/html", "html"):
            if mime in self.formats:
                return self.formats[mime]
        for k, v in self.formats.items():
            if "html" in k.lower():
                return v
        return None

    @property
    def text_url(self) -> str | None:
        """Get plain text fallback URL."""
        for k, v in self.formats.items():
            if "text/plain" in k.lower() or "txt" in k.lower():
                return v
        return None


@dataclass(frozen=True)
class CatalogPage:
    """A paginated page of books from an online library."""

    books: list[CatalogBook]
    total_count: int
    current_page: int
    has_next: bool
    has_previous: bool


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

WIKISOURCE_CATEGORIES = [
    "Hindi Wikisource (हिन्दी)",
    "Urdu Wikisource (اردو)",
    "English Wikisource",
]

OPENSTAX_CATEGORIES = [
    "All Subjects",
    "Math & Statistics",
    "Science (Physics, Chemistry, Biology)",
    "Business & Economics",
    "Social Sciences & Humanities",
    "Computer Science & Engineering",
]


def fetch_gutenberg_page(
    query: str = "",
    topic: str = "",
    page: int = 1,
    timeout: float = 12.0,
) -> CatalogPage:
    """Fetch live paginated books directly from Project Gutenberg (Gutendex)."""
    params = [f"page={max(1, page)}"]
    if query.strip():
        params.append(f"search={urllib.parse.quote_plus(query.strip())}")
    if topic.strip() and topic != "Popular Classics (All)":
        params.append(f"topic={urllib.parse.quote_plus(topic.strip())}")

    url = f"https://gutendex.com/books/?{'&'.join(params)}"
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

    total = int(data.get("count", len(results)))
    has_next = bool(data.get("next"))
    has_prev = bool(data.get("previous"))

    return CatalogPage(
        books=results,
        total_count=total,
        current_page=page,
        has_next=has_next,
        has_previous=has_prev,
    )


def search_standard_ebooks(
    query: str = "",
    feed_url: str | None = None,
    timeout: float = 12.0,
) -> list[CatalogBook]:
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


def fetch_standard_ebooks_page(
    query: str = "",
    feed_url: str | None = None,
    page: int = 1,
    limit: int = 20,
    timeout: float = 12.0,
) -> CatalogPage:
    """Fetch paginated books from Standard Ebooks."""
    all_books = search_standard_ebooks(query=query, feed_url=feed_url, timeout=timeout)
    total = len(all_books)
    start = (max(1, page) - 1) * limit
    paged = all_books[start : start + limit]
    return CatalogPage(
        books=paged,
        total_count=total,
        current_page=page,
        has_next=(start + limit) < total,
        has_previous=page > 1,
    )


def fetch_open_library_page(
    query: str = "",
    subject: str = "",
    page: int = 1,
    limit: int = 20,
    timeout: float = 12.0,
) -> CatalogPage:
    """Fetch live paginated public books directly from Open Library / Internet Archive."""
    q_str = query.strip() or subject.strip() or "classics"
    encoded = urllib.parse.quote_plus(q_str)
    url = f"https://openlibrary.org/search.json?q={encoded}&has_fulltext=true&limit={limit}&page={max(1, page)}"

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

    total = int(data.get("numFound", len(results)))
    has_next = (page * limit) < total
    has_prev = page > 1

    return CatalogPage(
        books=results,
        total_count=total,
        current_page=page,
        has_next=has_next,
        has_previous=has_prev,
    )


def fetch_wikisource_page(
    query: str = "",
    category: str = "",
    page: int = 1,
    limit: int = 20,
    timeout: float = 12.0,
) -> CatalogPage:
    """Search and browse multilingual public domain works from Wikisource (Hindi, Urdu, English)."""
    cat_lower = category.lower()
    if "urdu" in cat_lower or "اردو" in category:
        lang = "ur"
        default_query = "دیوان"
    elif "hindi" in cat_lower or "हिन्दी" in category:
        lang = "hi"
        default_query = "प्रेमचंद"
    else:
        lang = "en"
        default_query = "classic"

    search_term = query.strip() or default_query
    encoded = urllib.parse.quote_plus(search_term)
    offset = max(0, (page - 1) * limit)

    url = (
        f"https://{lang}.wikisource.org/w/api.php?action=query&list=search"
        f"&srsearch={encoded}&sroffset={offset}&srlimit={limit}&format=json"
    )
    req = Request(
        url,
        headers={"User-Agent": "OpenReader/1.0 (https://github.com/itskeshavmalhotra1-dev/open-reader; dev@example.com)"},
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    search_info = data.get("query", {}).get("searchinfo", {})
    total = int(search_info.get("totalhits", 0))
    raw_results = data.get("query", {}).get("search", [])

    books: list[CatalogBook] = []
    for item in raw_results:
        title = item.get("title", "Untitled")
        page_id = item.get("pageid", 0)
        encoded_title = urllib.parse.quote_plus(title)
        fetch_url = f"https://{lang}.wikisource.org/w/api.php?action=parse&page={encoded_title}&prop=text&format=json"
        formats = {
            "text/html": fetch_url,
            "text/plain": f"https://{lang}.wikisource.org/w/index.php?title={encoded_title}&action=raw",
        }
        lang_name = "Hindi" if lang == "hi" else ("Urdu" if lang == "ur" else "English")
        books.append(
            CatalogBook(
                id=f"wikisource_{lang}_{page_id}",
                title=title,
                authors=[f"Wikisource ({lang_name})"],
                languages=[lang],
                formats=formats,
                download_count=0,
                source=f"Wikisource ({lang_name})",
            )
        )

    has_next = (offset + limit) < total
    has_prev = page > 1

    return CatalogPage(
        books=books,
        total_count=total,
        current_page=page,
        has_next=has_next,
        has_previous=has_prev,
    )


def fetch_openstax_page(
    query: str = "",
    category: str = "",
    page: int = 1,
    limit: int = 20,
    timeout: float = 12.0,
) -> CatalogPage:
    """Fetch free peer-reviewed college textbooks from OpenStax."""
    params = ["type=books.Book", "limit=150", "fields=title,slug,high_resolution_pdf_url,pdf_url"]
    if query.strip():
        params.append(f"search={urllib.parse.quote_plus(query.strip())}")

    url = f"https://openstax.org/apps/cms/api/v2/pages/?{'&'.join(params)}"
    req = Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Open-Reader/26.0"},
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    all_items = data.get("items", [])
    cat_lower = category.lower()

    filtered: list[CatalogBook] = []
    for it in all_items:
        t = it.get("title", "")
        t_low = t.lower()
        if category and category != "All Subjects":
            if "math" in cat_lower and not any(w in t_low for w in ["math", "algebra", "calculus", "statistic", "trigonometry", "precalculus"]):
                continue
            if "science" in cat_lower and not any(w in t_low for w in ["physics", "chemistry", "biology", "astronomy", "anatomy", "microbiology", "organic"]):
                continue
            if "business" in cat_lower and not any(w in t_low for w in ["business", "economics", "accounting", "finance", "management", "entrepreneurship"]):
                continue
            if "social" in cat_lower and not any(w in t_low for w in ["history", "psychology", "sociology", "government", "political", "anthropology"]):
                continue
            if "computer" in cat_lower and not any(w in t_low for w in ["computer", "programming", "python", "data", "engineering", "information"]):
                continue

        pdf_url = it.get("high_resolution_pdf_url") or it.get("pdf_url")
        if not pdf_url:
            continue

        filtered.append(
            CatalogBook(
                id=it.get("id", t),
                title=t,
                authors=["OpenStax"],
                languages=["en"],
                formats={"application/pdf": pdf_url},
                download_count=10000,
                source="OpenStax",
            )
        )

    total = len(filtered)
    start = max(0, (page - 1) * limit)
    paged = filtered[start : start + limit]

    return CatalogPage(
        books=paged,
        total_count=total,
        current_page=page,
        has_next=(start + limit) < total,
        has_previous=page > 1,
    )


def fetch_online_catalog_page(
    source_name: str,
    query: str = "",
    category: str = "",
    page: int = 1,
) -> CatalogPage:
    """Unified entrypoint fetching real-time paginated books without static disk cache."""
    if "Standard Ebooks" in source_name:
        return fetch_standard_ebooks_page(query=query, page=page)
    elif "Open Library" in source_name:
        return fetch_open_library_page(query=query, subject=category, page=page)
    elif "Wikisource" in source_name:
        return fetch_wikisource_page(query=query, category=category, page=page)
    elif "OpenStax" in source_name:
        return fetch_openstax_page(query=query, category=category, page=page)
    else:
        return fetch_gutenberg_page(query=query, topic=category, page=page)


def download_catalog_book(
    book: CatalogBook,
    dest_dir: Path,
    progress_cb=None,
    timeout: float = 30.0,
) -> Path:
    """Download the chosen catalog book with multi-mirror resilience (prefers EPUB, falls back to TXT/PDF/HTML)."""
    candidates: list[str] = []

    b_id = str(book.id).strip()
    is_gutenberg = (
        book.source == "Project Gutenberg"
        or "gutenberg" in str(book.source).lower()
        or any("gutenberg" in str(v).lower() for v in book.formats.values())
    )

    if is_gutenberg:
        # Extract numeric Gutenberg book ID
        match = re.search(r"/epub/(\d+)|/ebooks/(\d+)|pg(\d+)", f"{book.epub_url or ''} {book.text_url or ''} {b_id}")
        digit_id = (next((g for g in match.groups() if g is not None), None) if match else None) or (b_id if b_id.isdigit() else None)
        if digit_id:
            # Project Gutenberg Literary Archive Foundation (PGLAF) direct mirror.
            # Avoids Cloudflare rate-limiting / HTTP 503 Service Unavailable on www.gutenberg.org
            candidates.append(f"https://gutenberg.pglaf.org/cache/epub/{digit_id}/pg{digit_id}.epub")
            candidates.append(f"https://gutenberg.pglaf.org/cache/epub/{digit_id}/pg{digit_id}-images.epub")
            if book.epub_url and book.epub_url not in candidates:
                candidates.append(book.epub_url)
            candidates.append(f"https://gutenberg.pglaf.org/cache/epub/{digit_id}/pg{digit_id}.txt")
            if book.text_url and book.text_url not in candidates:
                candidates.append(book.text_url)

    if not candidates:
        if book.epub_url:
            candidates.append(book.epub_url)
        if book.pdf_url and book.pdf_url not in candidates:
            candidates.append(book.pdf_url)
        if book.html_url and book.html_url not in candidates:
            candidates.append(book.html_url)
        if book.text_url and book.text_url not in candidates:
            candidates.append(book.text_url)

    if not candidates:
        raise ValueError(f"No suitable download format found for '{book.title}'")

    safe_title = re.sub(r'[\\/*?:"<>|]', "_", book.title)[:60].strip() or "book"
    clean_id = re.sub(r'[\\/*?:"<>|]', "_", str(book.id))[:30].strip() or "item"
    dest_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Open-Reader/26.0",
        "Accept": "application/epub+zip, application/pdf, text/html, application/octet-stream, text/plain, */*",
    }

    last_error: Exception | None = None
    for candidate_url in candidates:
        # Handle Wikisource Parse API (extracts full rendered HTML document)
        if "wikisource.org" in candidate_url and "action=parse" in candidate_url:
            try:
                req = Request(candidate_url, headers=headers)
                with urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    raw_html = data.get("parse", {}).get("text", {}).get("*", "")
                    if not raw_html:
                        raise ValueError(f"No text content returned for {book.title}")
                    full_html = (
                        f"<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
                        f"<title>{book.title}</title>\n</head>\n<body>\n<h1>{book.title}</h1>\n"
                        f"{raw_html}\n</body>\n</html>"
                    )
                    ext = ".html"
                    filename = f"{safe_title}_{clean_id}{ext}"
                    target_path = dest_dir / filename
                    temp_path = dest_dir / f"{filename}.part"
                    temp_path.write_text(full_html, encoding="utf-8")
                    if progress_cb:
                        progress_cb(len(full_html), len(full_html))
                    temp_path.replace(target_path)
                    return target_path
            except Exception as exc:
                last_error = exc
                continue

        ext = (
            ".pdf" if "pdf" in candidate_url.lower()
            else (".epub" if "epub" in candidate_url.lower()
            else (".html" if "html" in candidate_url.lower()
            else (".txt" if "txt" in candidate_url.lower() else ".epub")))
        )
        filename = f"{safe_title}_{clean_id}{ext}"
        target_path = dest_dir / filename
        temp_path = dest_dir / f"{filename}.part"

        try:
            req = Request(candidate_url, headers=headers)
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

            if downloaded > 0 and temp_path.exists():
                temp_path.replace(target_path)
                return target_path
        except Exception as exc:
            last_error = exc
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            continue

    if last_error:
        raise last_error
    raise RuntimeError(f"Failed to download '{book.title}' from available catalog sources.")


# Backward compatibility aliases
GutenbergBook = CatalogBook
search_gutenberg = lambda q="", timeout=12.0: fetch_gutenberg_page(query=q, timeout=timeout).books
search_open_library = lambda q="", timeout=12.0: fetch_open_library_page(query=q, timeout=timeout).books
search_online_library = lambda src, q="", cat="": fetch_online_catalog_page(src, query=q, category=cat, page=1).books
download_gutenberg_book = download_catalog_book
