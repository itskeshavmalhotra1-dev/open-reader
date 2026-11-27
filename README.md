# Open Reader

Desktop book reader for Windows supporting EPUB, PDF, DOCX, DAISY OPF, HTML, Markdown, and TXT.

## Features

- **Formats:** EPUB, PDF, DOCX, DAISY `.opf`, HTML, Markdown, and TXT
- **Navigation:** Table of Contents, chapter/heading/paragraph/sentence stepping, Go to Page, Jump History, Find, and Bookmarks
- **Read Aloud (TTS):** Edge TTS, Kokoro ONNX, Piper, Windows OneCore, SAPI5, eSpeak, and NVDA direct speech
- **Updates:** Built-in GitHub Releases updater (`Help -> Check for Updates...`)

## Run from Source

```powershell
pip install -e .
python run_reader.py
```

Run tests:

```powershell
python -m pytest -v
```

## Build Rust Core

```powershell
cd rust_core
maturin build --release -i python
cd ..
pip install --force-reinstall rust_core\target\wheels\book_reader_core-0.1.0-cp313-cp313-win_amd64.whl
```

## Keyboard Shortcuts

- `Ctrl+O`: Open book
- `Ctrl+L`: Library
- `F6`: Switch between Table of Contents and Reading View
- `Ctrl+PageDown` / `Ctrl+PageUp`: Next / Previous section
- `Ctrl+Down` / `Ctrl+Up`: Next / Previous heading
- `Ctrl+1` to `Ctrl+6`: Next heading level 1–6
- `Ctrl+Alt+Down` / `Ctrl+Alt+Up`: Next / Previous paragraph
- `Ctrl+G`: Go to Page
- `Alt+Backspace` / `Alt+Shift+Backspace`: Back / Forward
- `Ctrl+F`: Find in section
- `Ctrl+D` / `Ctrl+B`: Add Bookmark / Bookmarks list
- `F5`: Play / Stop Read Aloud
- `Alt+Right` / `Alt+Left`: Next / Previous sentence
- `Ctrl+,`: Settings
- `F1`: Keyboard shortcuts
