"""Launch Accessible Book Reader Prototype from the project root."""

from pathlib import Path
import sys

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from book_reader.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
