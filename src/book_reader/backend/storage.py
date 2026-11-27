"""Persistent user state: reading positions, bookmarks, and preferences."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from book_reader.backend.models import Bookmark


def default_data_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "AccessibleBookReader"
    return Path.home() / ".accessible_book_reader"


class StateStore:
    """Stores reading progress, bookmarks, and UI/TTS preferences in JSON."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.state_file = self.data_dir / "state.json"
        self.data: dict[str, Any] = {
            "preferences": {
                "font_size": 14,
                "high_contrast": False,
                "speech_rate": 0,
                "voice_id": "",
                "library_folder": "",
                "auto_save_library": False,
            },
            "positions": {},
            "bookmarks": [],
            "recent_books": [],
            "library": [],
        }
        self.load()

    def load(self) -> None:
        if not self.state_file.is_file():
            return
        try:
            loaded = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                if isinstance(loaded.get("preferences"), dict):
                    self.data["preferences"].update(loaded["preferences"])
                for key in ("positions", "bookmarks", "recent_books", "library"):
                    if key in loaded:
                        self.data[key] = loaded[key]
        except (OSError, json.JSONDecodeError):
            pass

    def save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def save_position(self, book_path: str, chapter_index: int, char_offset: int) -> None:
        norm = str(Path(book_path))
        self.data["positions"][norm] = {
            "chapter_index": chapter_index,
            "char_offset": char_offset,
        }
        recents: list[str] = [p for p in self.data.get("recent_books", []) if p != norm]
        recents.insert(0, norm)
        self.data["recent_books"] = recents[:15]
        self.save()

    def get_position(self, book_path: str) -> tuple[int, int]:
        norm = str(Path(book_path))
        pos = self.data["positions"].get(norm, {})
        return int(pos.get("chapter_index", 0)), int(pos.get("char_offset", 0))

    def add_bookmark(self, book_path: str, chapter_index: int, char_offset: int, label: str) -> Bookmark:
        bm = Bookmark(
            book_path=str(Path(book_path)),
            chapter_index=chapter_index,
            char_offset=char_offset,
            label=label.strip() or f"Chapter {chapter_index + 1} @ {char_offset}",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self.data["bookmarks"].append(asdict(bm))
        self.save()
        return bm

    def get_bookmarks(self, book_path: str) -> list[Bookmark]:
        norm = str(Path(book_path))
        return [
            Bookmark(**item)
            for item in self.data.get("bookmarks", [])
            if item.get("book_path") == norm
        ]

    # --- Library Management ---

    def is_in_library(self, book_path: str) -> bool:
        norm = str(Path(book_path))
        return any(str(Path(b.get("path", ""))) == norm for b in self.data.get("library", []))

    def add_to_library(self, book_path: str, title: str | None = None, format_name: str | None = None) -> bool:
        norm = str(Path(book_path))
        if self.is_in_library(norm):
            return False
        p = Path(norm)
        entry = {
            "path": norm,
            "title": title or p.stem,
            "format": format_name or p.suffix.lstrip(".").upper(),
            "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.data.setdefault("library", []).append(entry)
        self.save()
        return True

    def remove_from_library(self, book_path: str) -> bool:
        norm = str(Path(book_path))
        before = len(self.data.get("library", []))
        self.data["library"] = [b for b in self.data.get("library", []) if str(Path(b.get("path", ""))) != norm]
        if len(self.data["library"]) < before:
            self.save()
            return True
        return False

    def get_library(self) -> list[dict[str, Any]]:
        return list(self.data.get("library", []))

    def scan_folder_into_library(self, folder_path: str) -> int:
        folder = Path(folder_path)
        if not folder.is_dir():
            return 0
        extensions = {".epub", ".pdf", ".docx", ".opf", ".html", ".htm", ".xhtml", ".md", ".txt"}
        added_count = 0
        try:
            for item in folder.rglob("*"):
                if item.is_file() and item.suffix.lower() in extensions:
                    if self.add_to_library(str(item), title=item.stem, format_name=item.suffix.lstrip(".").upper()):
                        added_count += 1
        except OSError:
            pass
        return added_count
