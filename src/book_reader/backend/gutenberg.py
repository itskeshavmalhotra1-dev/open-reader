"""Online libraries catalog clients with real-time pagination (Project Gutenberg, Standard Ebooks, Open Library)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import urllib.parse
from urllib.error import HTTPError
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

    @property
    def available_formats(self) -> list[str]:
        """Return human-readable format names available for this book (e.g. EPUB, PDF, HTML, Plain Text)."""
        fmts: list[str] = []
        is_gutenberg = (
            self.source == "Project Gutenberg"
            or "gutenberg" in str(self.source).lower()
            or any("gutenberg" in str(v).lower() for v in self.formats.values())
        )
        if self.epub_url or is_gutenberg:
            fmts.append("EPUB")
        if self.pdf_url:
            fmts.append("PDF")
        if self.html_url:
            fmts.append("HTML")
        if self.text_url or is_gutenberg:
            if "Plain Text" not in fmts:
                fmts.append("Plain Text")

        if not fmts:
            for k in self.formats:
                clean = k.split("/")[-1].replace("+zip", "").upper()
                if clean and clean not in fmts:
                    fmts.append(clean)
        return fmts or ["EPUB"]


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

INDIAN_ARCHIVE_CATEGORIES = [
    "Hindi (हिन्दी)",
    "Urdu (اردو)",
    "Sanskrit (संस्कृतम्)",
    "Bengali (বাংলা)",
    "Tamil (தமிழ்)",
    "Punjabi (ਪੰਜਾਬੀ)",
    "Marathi (मराठी)",
    "All Indian Languages",
]

OPEN_TECH_CATEGORIES = [
    "All Tech & Programming",
    "Python & Data Science",
    "Algorithms & Computer Science",
    "Artificial Intelligence & Machine Learning",
    "Linux & Systems Programming",
    "Cybersecurity & Networking",
    "Web Development & Databases",
]

NCBI_CATEGORIES = [
    "All Health & Medicine",
    "Clinical Medicine & Pharmacology",
    "Biology & Genetics",
    "Anatomy & Physiology",
    "Public Health & Epidemiology",
    "Neuroscience & Mental Health",
]

CLASSICS_20TH_CATEGORIES = [
    "All 20th Century Classics",
    "George Orwell (1984, Animal Farm)",
    "Virginia Woolf (Mrs Dalloway)",
    "H. G. Wells (Sci-Fi Classics)",
    "Jack London (Adventure)",
    "F. Scott Fitzgerald (Great Gatsby)",
    "Franz Kafka (Metamorphosis)",
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
        ebook_access = doc.get("ebook_access", "")
        # Filter out borrow-only or print-disabled items that require login checkout
        if ebook_access in ("borrowable", "printdisabled", "no_ebook"):
            if not doc.get("public_scan_b"):
                continue

        title = doc.get("title", "Untitled")
        authors = doc.get("author_name", [])
        languages = doc.get("language", ["en"])
        ia_ids = doc.get("ia", [])
        formats = {}
        if ia_ids:
            primary_ia = ia_ids[0]
            formats["application/epub+zip"] = f"https://archive.org/download/{primary_ia}/{primary_ia}.epub"
            formats["application/pdf"] = f"https://archive.org/download/{primary_ia}/{primary_ia}.pdf"
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


def fetch_indian_archive_page(
    query: str = "",
    category: str = "",
    page: int = 1,
    limit: int = 20,
    timeout: float = 12.0,
) -> CatalogPage:
    """Fetch books from Internet Archive's massive 16+ Lakh Indian & Regional Languages collection."""
    cat_low = category.lower()
    if "urdu" in cat_low or "اردو" in category:
        lang_filter = "(language:urdu OR language:urd)"
        lang_code = "ur"
        lang_name = "Urdu"
    elif "sanskrit" in cat_low or "संस्कृत" in category:
        lang_filter = "(language:sanskrit OR language:san)"
        lang_code = "sa"
        lang_name = "Sanskrit"
    elif "bengali" in cat_low or "বাংলা" in category:
        lang_filter = "(language:bengali OR language:ben)"
        lang_code = "bn"
        lang_name = "Bengali"
    elif "tamil" in cat_low or "தமிழ்" in category:
        lang_filter = "(language:tamil OR language:tam)"
        lang_code = "ta"
        lang_name = "Tamil"
    elif "punjabi" in cat_low or "ਪੰਜਾਬੀ" in category:
        lang_filter = "(language:punjabi OR language:pan)"
        lang_code = "pa"
        lang_name = "Punjabi"
    elif "marathi" in cat_low or "मराठी" in category:
        lang_filter = "(language:marathi OR language:mar)"
        lang_code = "mr"
        lang_name = "Marathi"
    elif "all" in cat_low:
        lang_filter = "(language:hindi OR language:hin OR language:urdu OR language:urd OR language:sanskrit OR language:san)"
        lang_code = "hi"
        lang_name = "Indian"
    else:
        lang_filter = "(language:hindi OR language:hin)"
        lang_code = "hi"
        lang_name = "Hindi"

    q_parts = [lang_filter, "mediatype:texts", "-collection:inlibrary", "-access-restricted-item:true"]
    if query.strip():
        q_parts.append(f"({query.strip()})")

    encoded_q = urllib.parse.quote_plus(" AND ".join(q_parts))
    url = (
        f"https://archive.org/advancedsearch.php?q={encoded_q}"
        f"&fl[]=identifier,title,creator,language,year"
        f"&rows={limit}&page={max(1, page)}&output=json"
    )
    req = Request(
        url,
        headers={"User-Agent": "OpenReader/1.0 (https://github.com/itskeshavmalhotra1-dev/open-reader; dev@example.com)"},
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    total = int(data.get("response", {}).get("numFound", 0))
    docs = data.get("response", {}).get("docs", [])

    books: list[CatalogBook] = []
    for doc in docs:
        ia_id = doc.get("identifier", "")
        if not ia_id:
            continue
        title = doc.get("title", "Untitled")
        authors = doc.get("creator", [])
        if isinstance(authors, str):
            authors = [authors]
        formats = {
            "application/epub+zip": f"https://archive.org/download/{ia_id}/{ia_id}.epub",
            "application/pdf": f"https://archive.org/download/{ia_id}/{ia_id}.pdf",
            "text/plain": f"https://archive.org/download/{ia_id}/{ia_id}_djvu.txt",
        }
        books.append(
            CatalogBook(
                id=ia_id,
                title=title,
                authors=authors,
                languages=[lang_code],
                formats=formats,
                download_count=0,
                source=f"Indian Literature ({lang_name})",
            )
        )

    return CatalogPage(
        books=books,
        total_count=total,
        current_page=page,
        has_next=(page * limit) < total,
        has_previous=page > 1,
    )


def fetch_open_tech_page(
    query: str = "",
    category: str = "",
    page: int = 1,
    limit: int = 20,
    timeout: float = 12.0,
) -> CatalogPage:
    """Fetch free open-source Computer Science, IT, and Programming textbooks."""
    cat_low = category.lower()
    if "python" in cat_low:
        subj = '(subject:"python" OR subject:"data science")'
    elif "algorithm" in cat_low:
        subj = '(subject:"algorithms" OR subject:"computer science")'
    elif "artificial" in cat_low or "machine" in cat_low:
        subj = '(subject:"artificial intelligence" OR subject:"machine learning")'
    elif "linux" in cat_low:
        subj = '(subject:"linux" OR subject:"operating systems")'
    elif "cyber" in cat_low or "network" in cat_low:
        subj = '(subject:"computer security" OR subject:"networking")'
    elif "web" in cat_low or "database" in cat_low:
        subj = '(subject:"web development" OR subject:"database")'
    else:
        subj = '(subject:"computer science" OR subject:"programming" OR subject:"software")'

    q_parts = [subj, "mediatype:texts"]
    if query.strip():
        q_parts.append(f"({query.strip()})")

    encoded_q = urllib.parse.quote_plus(" AND ".join(q_parts))
    url = (
        f"https://archive.org/advancedsearch.php?q={encoded_q}"
        f"&fl[]=identifier,title,creator,year"
        f"&rows={limit}&page={max(1, page)}&output=json"
    )
    req = Request(
        url,
        headers={"User-Agent": "OpenReader/1.0 (https://github.com/itskeshavmalhotra1-dev/open-reader; dev@example.com)"},
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    total = int(data.get("response", {}).get("numFound", 0))
    docs = data.get("response", {}).get("docs", [])

    books: list[CatalogBook] = []
    for doc in docs:
        ia_id = doc.get("identifier", "")
        if not ia_id:
            continue
        title = doc.get("title", "Untitled")
        authors = doc.get("creator", ["Tech Authors"])
        if isinstance(authors, str):
            authors = [authors]
        formats = {
            "application/pdf": f"https://archive.org/download/{ia_id}/{ia_id}.pdf",
            "application/epub+zip": f"https://archive.org/download/{ia_id}/{ia_id}.epub",
            "text/plain": f"https://archive.org/download/{ia_id}/{ia_id}_djvu.txt",
        }
        books.append(
            CatalogBook(
                id=ia_id,
                title=title,
                authors=authors,
                languages=["en"],
                formats=formats,
                download_count=1000,
                source="Open Tech Books",
            )
        )

    return CatalogPage(
        books=books,
        total_count=total,
        current_page=page,
        has_next=(page * limit) < total,
        has_previous=page > 1,
    )


def fetch_ncbi_page(
    query: str = "",
    category: str = "",
    page: int = 1,
    limit: int = 20,
    timeout: float = 12.0,
) -> CatalogPage:
    """Fetch free medical, health, and life sciences reference books from NCBI Bookshelf."""
    cat_low = category.lower()
    if "clinical" in cat_low or "pharmacol" in cat_low:
        default_term = "pharmacology OR therapeutics"
    elif "genetics" in cat_low:
        default_term = "genetics OR molecular biology"
    elif "anatomy" in cat_low:
        default_term = "anatomy OR physiology"
    elif "epidemiolog" in cat_low or "public" in cat_low:
        default_term = "public health OR epidemiology"
    elif "neuro" in cat_low or "mental" in cat_low:
        default_term = "neuroscience OR psychiatry"
    else:
        default_term = "medicine OR health"

    search_term = query.strip() or default_term
    encoded_term = urllib.parse.quote_plus(search_term)
    retstart = max(0, (page - 1) * limit)

    url_search = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?"
        f"db=books&term={encoded_term}&retstart={retstart}&retmax={limit}&retmode=json"
    )
    req = Request(
        url_search,
        headers={"User-Agent": "OpenReader/1.0 (https://github.com/itskeshavmalhotra1-dev/open-reader; dev@example.com)"},
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    esearch = data.get("esearchresult", {})
    total = int(esearch.get("count", 0))
    id_list = esearch.get("idlist", [])

    books: list[CatalogBook] = []
    if id_list:
        joined_ids = ",".join(id_list)
        url_sum = (
            f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?"
            f"db=books&id={joined_ids}&retmode=json"
        )
        req_sum = Request(
            url_sum,
            headers={"User-Agent": "OpenReader/1.0 (https://github.com/itskeshavmalhotra1-dev/open-reader; dev@example.com)"},
        )
        with urlopen(req_sum, timeout=timeout) as resp_sum:
            sum_data = json.loads(resp_sum.read().decode("utf-8")).get("result", {})

        for bid in id_list:
            b_info = sum_data.get(bid, {})
            title = b_info.get("title", f"NCBI Book {bid}")
            authors = [a.get("name", "") for a in b_info.get("authors", []) if a.get("name")] or ["NCBI Bookshelf"]
            formats = {
                "text/html": f"https://www.ncbi.nlm.nih.gov/books/NBK{bid}/?report=printable",
                "application/pdf": f"https://www.ncbi.nlm.nih.gov/books/NBK{bid}/pdf/Bookshelf_NBK{bid}.pdf",
            }
            books.append(
                CatalogBook(
                    id=f"ncbi_{bid}",
                    title=title,
                    authors=authors,
                    languages=["en"],
                    formats=formats,
                    download_count=5000,
                    source="NCBI Bookshelf",
                )
            )

    return CatalogPage(
        books=books,
        total_count=total,
        current_page=page,
        has_next=(retstart + limit) < total,
        has_previous=page > 1,
    )


def fetch_classics_20th_page(
    query: str = "",
    category: str = "",
    page: int = 1,
    limit: int = 20,
    timeout: float = 12.0,
) -> CatalogPage:
    """Fetch modern 20th century classic public domain books (Orwell, Woolf, Wells, Kafka, etc.)."""
    cat_low = category.lower()
    if "orwell" in cat_low:
        author_filter = 'creator:"George Orwell"'
    elif "woolf" in cat_low:
        author_filter = 'creator:"Virginia Woolf"'
    elif "wells" in cat_low:
        author_filter = 'creator:"H. G. Wells"'
    elif "london" in cat_low:
        author_filter = 'creator:"Jack London"'
    elif "fitzgerald" in cat_low:
        author_filter = 'creator:"F. Scott Fitzgerald"'
    elif "kafka" in cat_low:
        author_filter = 'creator:"Franz Kafka"'
    else:
        author_filter = '(creator:"George Orwell" OR creator:"Virginia Woolf" OR creator:"H. G. Wells" OR creator:"Jack London" OR creator:"Franz Kafka")'

    q_parts = [author_filter, "mediatype:texts", "-collection:inlibrary", "-access-restricted-item:true"]
    if query.strip():
        q_parts.append(f"({query.strip()})")

    encoded_q = urllib.parse.quote_plus(" AND ".join(q_parts))
    url = (
        f"https://archive.org/advancedsearch.php?q={encoded_q}"
        f"&fl[]=identifier,title,creator,year"
        f"&rows={limit}&page={max(1, page)}&output=json"
    )
    req = Request(
        url,
        headers={"User-Agent": "OpenReader/1.0 (https://github.com/itskeshavmalhotra1-dev/open-reader; dev@example.com)"},
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    total = int(data.get("response", {}).get("numFound", 0))
    docs = data.get("response", {}).get("docs", [])

    books: list[CatalogBook] = []
    for doc in docs:
        ia_id = doc.get("identifier", "")
        if not ia_id:
            continue
        title = doc.get("title", "Untitled")
        authors = doc.get("creator", ["Classic Author"])
        if isinstance(authors, str):
            authors = [authors]
        formats = {
            "application/epub+zip": f"https://archive.org/download/{ia_id}/{ia_id}.epub",
            "application/pdf": f"https://archive.org/download/{ia_id}/{ia_id}.pdf",
            "text/plain": f"https://archive.org/download/{ia_id}/{ia_id}_djvu.txt",
        }
        books.append(
            CatalogBook(
                id=ia_id,
                title=title,
                authors=authors,
                languages=["en"],
                formats=formats,
                download_count=10000,
                source="20th Century Classics",
            )
        )

    return CatalogPage(
        books=books,
        total_count=total,
        current_page=page,
        has_next=(page * limit) < total,
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
    elif "Indian" in source_name:
        return fetch_indian_archive_page(query=query, category=category, page=page)
    elif "Tech" in source_name or "Computer" in source_name:
        return fetch_open_tech_page(query=query, category=category, page=page)
    elif "NCBI" in source_name or "Medical" in source_name:
        return fetch_ncbi_page(query=query, category=category, page=page)
    elif "20th Century" in source_name or "Classics" in source_name:
        return fetch_classics_20th_page(query=query, category=category, page=page)
    else:
        return fetch_gutenberg_page(query=query, topic=category, page=page)


def resolve_archive_org_candidates(ia_id: str, preferred_format: str = "", timeout: float = 6.0) -> list[str]:
    """Query Internet Archive metadata API to discover exact available downloadable files for an item."""
    meta_url = f"https://archive.org/metadata/{urllib.parse.quote(ia_id)}/files"
    req = Request(
        meta_url,
        headers={"User-Agent": "OpenReader/26.0 (Accessibility desktop reader)"},
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            files = data.get("result", [])
    except Exception:
        return []

    epubs: list[str] = []
    pdfs: list[str] = []
    txts: list[str] = []
    htmls: list[str] = []

    for f in files:
        name = f.get("name", "")
        if not name or name.endswith(("_meta.xml", "_files.xml", "_archive.torrent", "_thumb.jpg")):
            continue
        low = name.lower()
        full_url = f"https://archive.org/download/{ia_id}/{name}"
        if low.endswith(".epub"):
            epubs.append(full_url)
        elif low.endswith(".pdf"):
            pdfs.append(full_url)
        elif low.endswith(("_djvu.txt", ".txt")):
            txts.append(full_url)
        elif low.endswith((".html", ".htm")) and not low.endswith(("_hocr.html", "_chocr.html")):
            htmls.append(full_url)

    pref = preferred_format.upper().strip()
    if "PDF" in pref:
        return pdfs + epubs + txts + htmls
    elif "TXT" in pref or "TEXT" in pref or "PLAIN" in pref:
        return txts + epubs + pdfs + htmls
    elif "HTML" in pref:
        return htmls + epubs + pdfs + txts
    else:
        return epubs + pdfs + txts + htmls


def download_catalog_book(
    book: CatalogBook,
    dest_dir: Path,
    progress_cb=None,
    timeout: float = 30.0,
    preferred_format: str | None = None,
) -> Path:
    """Download the chosen catalog book with multi-mirror resilience (honors preferred_format if available)."""
    candidates: list[str] = []

    b_id = str(book.id).strip()
    is_gutenberg = (
        book.source == "Project Gutenberg"
        or "gutenberg" in str(book.source).lower()
        or any("gutenberg" in str(v).lower() for v in book.formats.values())
    )

    pref = (preferred_format or "").strip().upper()
    wants_pdf = "PDF" in pref
    wants_html = "HTML" in pref
    wants_txt = "TXT" in pref or "TEXT" in pref or "PLAIN" in pref
    wants_epub = "EPUB" in pref

    if is_gutenberg:
        # Extract numeric Gutenberg book ID
        match = re.search(r"/epub/(\d+)|/ebooks/(\d+)|pg(\d+)", f"{book.epub_url or ''} {book.text_url or ''} {b_id}")
        digit_id = (next((g for g in match.groups() if g is not None), None) if match else None) or (b_id if b_id.isdigit() else None)

        epub_cands: list[str] = []
        txt_cands: list[str] = []
        pdf_cands: list[str] = []

        if digit_id:
            # Project Gutenberg Literary Archive Foundation (PGLAF) direct mirror.
            # Avoids Cloudflare rate-limiting / HTTP 503 Service Unavailable on www.gutenberg.org
            epub_cands.append(f"https://gutenberg.pglaf.org/cache/epub/{digit_id}/pg{digit_id}.epub")
            epub_cands.append(f"https://gutenberg.pglaf.org/cache/epub/{digit_id}/pg{digit_id}-images.epub")
            txt_cands.append(f"https://gutenberg.pglaf.org/cache/epub/{digit_id}/pg{digit_id}.txt")

        if book.epub_url and book.epub_url not in epub_cands:
            epub_cands.append(book.epub_url)
        if book.text_url and book.text_url not in txt_cands:
            txt_cands.append(book.text_url)
        if book.pdf_url and book.pdf_url not in pdf_cands:
            pdf_cands.append(book.pdf_url)

        if wants_txt:
            candidates.extend(txt_cands + epub_cands + pdf_cands)
        elif wants_pdf:
            candidates.extend(pdf_cands + epub_cands + txt_cands)
        else:
            candidates.extend(epub_cands + txt_cands + pdf_cands)

    if not candidates:
        ordered_sources: list[str | None] = []
        if wants_pdf:
            ordered_sources = [book.pdf_url, book.epub_url, book.html_url, book.text_url]
        elif wants_html:
            ordered_sources = [book.html_url, book.epub_url, book.pdf_url, book.text_url]
        elif wants_txt:
            ordered_sources = [book.text_url, book.epub_url, book.pdf_url, book.html_url]
        else:
            ordered_sources = [book.epub_url, book.pdf_url, book.html_url, book.text_url]

        for u in ordered_sources:
            if u and u not in candidates:
                candidates.append(u)

    if not candidates:
        raise ValueError(f"No suitable download format found for '{book.title}'")

    # For Internet Archive items, resolve exact available filenames via metadata API
    ia_match = None
    for cand in list(candidates):
        m = re.search(r"archive\.org/download/([^/]+)", cand)
        if m:
            ia_match = m.group(1)
            break

    if ia_match:
        resolved = resolve_archive_org_candidates(ia_match, preferred_format=pref, timeout=min(6.0, timeout))
        if resolved:
            candidates = resolved + [c for c in candidates if c not in resolved]

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

        # Handle NCBI Bookshelf printable HTML
        if "ncbi.nlm.nih.gov" in candidate_url and "report=printable" in candidate_url:
            try:
                req = Request(candidate_url, headers=headers)
                with urlopen(req, timeout=timeout) as resp:
                    raw_html = resp.read().decode("utf-8", errors="replace")
                    ext = ".html"
                    filename = f"{safe_title}_{clean_id}{ext}"
                    target_path = dest_dir / filename
                    temp_path = dest_dir / f"{filename}.part"
                    temp_path.write_text(raw_html, encoding="utf-8")
                    if progress_cb:
                        progress_cb(len(raw_html), len(raw_html))
                    temp_path.replace(target_path)
                    return target_path
            except Exception as exc:
                last_error = exc
                continue

        parsed_path = urllib.parse.urlparse(candidate_url).path.lower()
        last_seg = parsed_path.split("/")[-1]
        if last_seg.endswith(".pdf") or "pdf" in last_seg:
            ext = ".pdf"
        elif last_seg.endswith(".txt") or "txt" in last_seg:
            ext = ".txt"
        elif last_seg.endswith((".html", ".htm")) or "html" in last_seg:
            ext = ".html"
        elif last_seg.endswith(".epub") or "epub" in last_seg:
            ext = ".epub"
        elif ".pdf" in parsed_path:
            ext = ".pdf"
        elif ".txt" in parsed_path:
            ext = ".txt"
        elif ".html" in parsed_path or ".htm" in parsed_path:
            ext = ".html"
        elif ".epub" in parsed_path:
            ext = ".epub"
        elif wants_txt:
            ext = ".txt"
        elif wants_pdf:
            ext = ".pdf"
        elif wants_html:
            ext = ".html"
        else:
            ext = ".epub"
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
        except HTTPError as exc:
            if exc.code == 401:
                last_error = PermissionError(
                    f"HTTP Error 401: Unauthorized — '{book.title}' is a restricted lending-library item on Internet Archive requiring account checkout."
                )
            elif exc.code == 403:
                last_error = PermissionError(
                    f"HTTP Error 403: Forbidden — '{book.title}' access is restricted on the server."
                )
            else:
                last_error = exc
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            continue
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
