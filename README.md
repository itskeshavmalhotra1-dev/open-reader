# Accessible Book Reader (Rust Backend + wxPython Frontend)

An accessible EasyReader- and Thorium-inspired PC book reader designed for Windows screen readers (**NVDA**, **JAWS**, **Narrator**).

## Architecture

- **Rust Backend (`rust_core/`, PyO3 + `maturin`):**
  - `html_parser.rs`: High-speed HTML/XHTML text, heading, `#id` anchor, and `pagebreak` extraction (`quick-xml`)
  - `text_nav.rs`: Unicode-safe sentence segmentation, paragraph offset indexing, and full-text search
  - Loaded automatically via `book_reader_core` when compiled, with an API-identical Python fallback in `src/book_reader/backend/engine.py`.
- **Python Backend & Navigation (`src/book_reader/backend/`):**
  - `parsers.py`: EPUB (with `nav.xhtml`, `toc.ncx`, `page-list`, `#fragment` anchors), DAISY `.opf`, PDF (`PyMuPDF` + per-page index), DOCX, HTML, Markdown, and TXT.
  - `navigation.py`: `NavigationController` with Back/Forward jump history, Go to Page, cross-chapter Heading (levels 1–6), Paragraph & Sentence stepping, and "Where Am I?".
  - `storage.py`: Persistent reading positions, bookmarks, and preferences in `%APPDATA%\AccessibleBookReader\state.json`.
- **Python (`wxPython`) Frontend (`src/book_reader/ui/`):**
  - Native Windows controls (`wx.TreeCtrl`, `wx.TextCtrl`, accessible dialogs) for full NVDA/JAWS compatibility.

## Running & Testing

```powershell
python run_reader.py
python -m pytest -v
```

## Compiling the Rust Backend

```powershell
cd rust_core
maturin build --release -i python
cd ..
pip install --force-reinstall rust_core\target\wheels\book_reader_core-0.1.0-cp313-cp313-win_amd64.whl
```

## Navigation Shortcuts

- `Ctrl+O`: Open book
- `F6`: Switch focus between Table of Contents and Reading View
- `Ctrl+PageDown` / `Ctrl+PageUp`: Next / Previous section
- `Ctrl+Down` / `Ctrl+Up`: Next / Previous heading (cross-chapter)
- `Ctrl+1` to `Ctrl+6`: Next heading of level 1 to 6
- `Ctrl+Alt+Down` / `Ctrl+Alt+Up`: Next / Previous paragraph
- `Ctrl+G`: Go to Page (EPUB `page-list`, DAISY, PDF)
- `Alt+Backspace` / `Alt+Shift+Backspace`: Navigate Back / Forward in jump history
- `Ctrl+I`: Where Am I? (Book, Section, Heading, Page, `%` progress)
- `Ctrl+Shift+N`: Toggle Single-Key Navigation Mode (`H`, `1`–`6`, `P`, `G`, `I`, `Backspace`)
- `Ctrl+F`: Find in section
- `Ctrl+D` / `Ctrl+B`: Add Bookmark / Bookmarks list
- `F5`: Play / Stop Read Aloud
- `Alt+Right` / `Alt+Left`: Next / Previous sentence
- `Ctrl+,`: Reader Settings
- `F1`: Keyboard shortcuts help
