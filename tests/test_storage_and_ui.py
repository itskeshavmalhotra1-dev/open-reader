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

    # Test library operations
    assert not store.is_in_library(book_file)
    assert store.add_to_library(book_file, title="Demo Book", format_name="TXT")
    assert store.is_in_library(book_file)
    assert not store.add_to_library(book_file)  # Duplicate add returns False

    lib_items = store.get_library()
    assert len(lib_items) == 1
    assert lib_items[0]["title"] == "Demo Book"

    # Folder scanning test
    sub_dir = tmp_path / "my_books"
    sub_dir.mkdir()
    (sub_dir / "book1.epub").write_text("dummy", encoding="utf-8")
    (sub_dir / "book2.pdf").write_text("dummy", encoding="utf-8")
    (sub_dir / "ignore.exe").write_text("binary", encoding="utf-8")
    added = store.scan_folder_into_library(str(sub_dir))
    assert added == 2
    assert len(store.get_library()) == 3

    assert store.remove_from_library(book_file)
    assert not store.is_in_library(book_file)


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


def test_read_aloud_prefetch_pipeline_for_neural_engines() -> None:
    spoken: list[str] = []
    played: list[bytes] = []
    done: list[bool] = []
    spans = split_sentences("One. Two. Three.")

    ctrl = ReadAloudController(
        on_sentence=lambda _i, s: spoken.append(s.text),
        on_finished=lambda: done.append(True),
    )
    ctrl.configure(engine="kokoro", voice_id="af_heart")
    with (
        patch.object(ctrl, "_synthesize_audio_bytes", side_effect=lambda t: t.encode("utf-8")),
        patch.object(ctrl, "_play_audio_bytes", side_effect=lambda b: played.append(b)),
    ):
        ctrl.start(spans, start_index=0)
        if ctrl._thread:
            ctrl._thread.join(timeout=3.0)

    assert spoken == ["One.", "Two.", "Three."]
    assert played == [b"One.", b"Two.", b"Three."]
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


def test_settings_engine_status_and_piper_manager_dialog() -> None:
    from book_reader.ui.dialogs import PiperVoiceManagerDialog, SettingsDialog

    app = wx.App.Get() or wx.App(False)
    ctrl = ReadAloudController()
    dlg = SettingsDialog(None, {"tts_engine": "piper", "voice_id": ""}, [], tts_controller=ctrl)
    try:
        status = dlg.engine_status_ctrl.GetValue()
        assert "Piper Offline Neural TTS" in status
        assert dlg.manage_piper_btn.IsEnabled()
    finally:
        dlg.Destroy()
        app.ProcessPendingEvents()

    mgr = PiperVoiceManagerDialog(None, tts_controller=ctrl)
    try:
        assert "Downloaded offline models:" in mgr.summary_ctrl.GetValue()
        assert len(mgr._catalog) > 0
        # Test quality filter
        idx = mgr.qual_choice.FindString("medium")
        if idx != wx.NOT_FOUND:
            mgr.qual_choice.SetSelection(idx)
            mgr._apply_filters()
            assert all(item.get("quality") == "medium" for item in mgr._filtered)
    finally:
        mgr.Destroy()
        app.ProcessPendingEvents()

    kokoro_dlg = SettingsDialog(None, {"tts_engine": "kokoro", "voice_id": "af_heart"}, [], tts_controller=ctrl)
    try:
        assert "Kokoro-82M Offline Neural TTS" in kokoro_dlg.engine_status_ctrl.GetValue()
        assert len(kokoro_dlg._all_engine_voices) > 0
        assert kokoro_dlg.manage_piper_btn.IsEnabled()
    finally:
        kokoro_dlg.Destroy()
        app.ProcessPendingEvents()

    from book_reader.ui.dialogs import KokoroVoiceManagerDialog

    kmgr = KokoroVoiceManagerDialog(None, tts_controller=ctrl)
    try:
        assert "Kokoro-82M Model Pack:" in kmgr.summary_ctrl.GetValue()
        assert len(kmgr._voices) > 0
    finally:
        kmgr.Destroy()
        app.ProcessPendingEvents()

    nvda_dlg = SettingsDialog(None, {"tts_engine": "nvda", "voice_id": "screen_reader"}, [], tts_controller=ctrl)
    try:
        assert "Screen Reader Direct Mode" in nvda_dlg.engine_status_ctrl.GetValue()
        assert len(nvda_dlg._all_engine_voices) == 1
    finally:
        nvda_dlg.Destroy()
        app.ProcessPendingEvents()
