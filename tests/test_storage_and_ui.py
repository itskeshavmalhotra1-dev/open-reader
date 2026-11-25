"""Tests for persistence, TTS controller, and wxPython UI smoke tests."""

from pathlib import Path
from unittest.mock import patch
import wx

from book_reader.backend.engine import split_sentences
from book_reader.backend.storage import StateStore
from book_reader.tts.speech import ReadAloudController
from book_reader.ui.main_frame import BookReaderFrame


def test_state_store_bookmarks_and_positions(tmp_path: Path) -> None:
    store = StateStore(data_dir=tmp_path)
    book_file = str(tmp_path / "demo.txt")
    store.save_position(book_file, chapter_index=2, char_offset=145)
    store.add_bookmark(book_file, chapter_index=2, char_offset=145, label="Important quote")

    reloaded = StateStore(data_dir=tmp_path)
    assert reloaded.get_position(book_file) == (2, 145)
    bms = reloaded.get_bookmarks(book_file)
    assert len(bms) == 1
    assert bms[0].label == "Important quote"


def test_read_aloud_controller_steps_through_sentences() -> None:
    spoken: list[str] = []
    done: list[bool] = []
    spans = split_sentences("First sentence. Second sentence.")

    ctrl = ReadAloudController(
        on_sentence=lambda _i, s: spoken.append(s.text),
        on_finished=lambda: done.append(True),
    )
    with patch.object(ctrl, "_speak_with_sapi", side_effect=lambda _t: None):
        ctrl.start(spans, start_index=0)
        if ctrl._thread:
            ctrl._thread.join(timeout=2.0)

    assert spoken == ["First sentence.", "Second sentence."]
    assert done == [True]


def test_wx_frame_loads_book_and_navigates_headings(tmp_path: Path) -> None:
    book_path = tmp_path / "test_book.md"
    book_path.write_text("# Chapter One\nHello there.\n## Subheading\nMore text.", encoding="utf-8")

    app = wx.App.Get() or wx.App(False)
    frame = BookReaderFrame(data_dir=tmp_path)
    try:
        frame.open_book_path(str(book_path))
        assert frame.book is not None
        assert frame.book.title == "test_book"
        assert "Hello there." in frame.reader_ctrl.GetValue()

        frame.reader_ctrl.SetInsertionPoint(0)
        frame.step_heading(1)
        pos_after_first = frame.reader_ctrl.GetInsertionPoint()
        assert frame.reader_ctrl.GetValue()[pos_after_first:].startswith("## Subheading")
    finally:
        frame.Destroy()
        app.ProcessPendingEvents()
