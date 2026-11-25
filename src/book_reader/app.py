"""Application entrypoint for Accessible Book Reader Prototype."""

from __future__ import annotations

import sys
import wx

from book_reader.ui.main_frame import BookReaderFrame


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    initial_book = args[0] if args else None
    app = wx.App(False)
    frame = BookReaderFrame(initial_book=initial_book)
    frame.Show()
    app.MainLoop()
    return 0
