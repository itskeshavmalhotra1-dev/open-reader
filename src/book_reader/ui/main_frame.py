"""Main accessible wxPython frame for the Book Reader prototype."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import tempfile
import threading
import webbrowser
import wx

from book_reader import APP_NAME, __version__
from book_reader.backend.engine import BACKEND_MODE, SentenceSpan, split_sentences
from book_reader.backend.models import BookDocument, LinkSpan, TocNode
from book_reader.backend.navigation import NavLocation, NavigationController
from book_reader.backend.parsers import load_book
from book_reader.backend.storage import StateStore
from book_reader.backend.updater import (
    UpdateError,
    UpdateInfo,
    check_for_update,
    download_update,
)
from book_reader.tts.speech import ReadAloudController, ScreenReaderAnnouncer
from book_reader.ui.dialogs import (
    BookmarksDialog,
    GoToPageDialog,
    LibraryDialog,
    LinksDialog,
    OnlineLibrariesDialog,
    SearchDialog,
    SettingsDialog,
)

SHORTCUTS_TEXT = """Navigation & Reader Shortcuts:
- Ctrl+O: Open book (EPUB, PDF, DOCX, DAISY OPF, HTML, MD, TXT)
- Ctrl+L: Open My Library (Bookshelf)
- F6: Switch focus between Table of Contents and Reading View
- Ctrl+PageDown / Ctrl+PageUp: Next / Previous section
- Ctrl+Down / Ctrl+Up: Next / Previous heading (cross-chapter)
- Ctrl+1 to Ctrl+6: Next heading of level 1 to 6
- Ctrl+Alt+Down / Ctrl+Alt+Up: Next / Previous paragraph
- Ctrl+G: Go to Page (EPUB page-list, DAISY, PDF)
- Alt+Backspace / Alt+Shift+Backspace: Navigate Back / Forward
- Ctrl+I: Where Am I? (announce book, section, heading, page, progress)
- Ctrl+Shift+N: Toggle Single-Key Navigation Mode (H, 1-6, P, G, I, Backspace)
- Ctrl+F: Find in current section
- Ctrl+D / Ctrl+B: Add Bookmark / Open Bookmarks
- F5: Start or Stop Read Aloud
- Alt+Right / Alt+Left: Next / Previous sentence
- Ctrl+,: Open Settings (Display, Audio, Library Scanner)
- F1: Show this Keyboard Shortcuts help"""


class BookReaderFrame(wx.Frame):
    """Accessible main window modeled on EasyReader and Thorium Reader."""

    def __init__(
        self,
        initial_book: str | None = None,
        data_dir: Path | None = None,
    ) -> None:
        super().__init__(
            None,
            title=APP_NAME,
            size=(1024, 720),
        )
        self.store = StateStore(data_dir=data_dir)
        self.announcer = ScreenReaderAnnouncer()
        self.tts = ReadAloudController(
            on_sentence=self._on_tts_sentence_bg,
            on_finished=self._on_tts_finished_bg,
        )
        self.book: BookDocument | None = None
        self.nav = NavigationController()
        self.current_chapter_idx = 0
        self.sentences: list[SentenceSpan] = []
        self._tts_active_span: SentenceSpan | None = None
        self.single_key_nav = False
        self._toc_items: list[tuple[wx.TreeItemId, int, int]] = []

        self._build_menu()
        self._build_ui()
        self._apply_preferences()
        self._update_status("Ready. Press Ctrl+O to open a book.")

        # Warm up voice lists in background thread so opening Settings is instant
        import threading
        threading.Thread(target=lambda: (ReadAloudController.list_sapi_voices(), ReadAloudController.list_onecore_voices(), ReadAloudController.list_edge_voices(), ReadAloudController.list_piper_voices()), daemon=True).start()

        self.Bind(wx.EVT_CLOSE, self._on_close)

        if initial_book:
            wx.CallAfter(self.open_book_path, initial_book)

    def _build_menu(self) -> None:
        menubar = wx.MenuBar()

        file_menu = wx.Menu()
        m_open = file_menu.Append(wx.ID_OPEN, "&Open Book...\tCtrl+O", "Open an e-book file")
        m_lib = file_menu.Append(wx.ID_ANY, "My &Library...\tCtrl+L", "Open your books library")
        m_online_lib = file_menu.Append(wx.ID_ANY, "&Online Libraries...\tCtrl+Shift+O", "Search and download books from online catalogs (Gutenberg, Standard Ebooks, etc.)")
        file_menu.AppendSeparator()
        m_prefs = file_menu.Append(wx.ID_PREFERENCES, "&Settings...\tCtrl+,", "Open Settings")
        file_menu.AppendSeparator()
        m_exit = file_menu.Append(wx.ID_EXIT, "E&xit\tAlt+F4", "Close the application")
        menubar.Append(file_menu, "&File")

        nav_menu = wx.Menu()
        m_focus = nav_menu.Append(wx.ID_ANY, "Switch &Pane (TOC / Reader)\tF6")
        m_back = nav_menu.Append(wx.ID_ANY, "Go &Back\tAlt+Back")
        m_fwd = nav_menu.Append(wx.ID_ANY, "Go &Forward\tAlt+Shift+Back")
        nav_menu.AppendSeparator()
        m_next_ch = nav_menu.Append(wx.ID_ANY, "&Next Section\tCtrl+PgDn")
        m_prev_ch = nav_menu.Append(wx.ID_ANY, "&Previous Section\tCtrl+PgUp")
        nav_menu.AppendSeparator()
        m_next_hd = nav_menu.Append(wx.ID_ANY, "Next &Heading\tCtrl+Down")
        m_prev_hd = nav_menu.Append(wx.ID_ANY, "Previous Heading\tCtrl+Up")
        for lvl in range(1, 7):
            m_lvl = nav_menu.Append(wx.ID_ANY, f"Next Heading Level &{lvl}\tCtrl+{lvl}")
            self.Bind(wx.EVT_MENU, lambda _e, level=lvl: self.step_heading(1, level=level), m_lvl)
        nav_menu.AppendSeparator()
        m_next_para = nav_menu.Append(wx.ID_ANY, "Next Para&graph\tCtrl+Alt+Down")
        m_prev_para = nav_menu.Append(wx.ID_ANY, "Previous Paragraph\tCtrl+Alt+Up")
        nav_menu.AppendSeparator()
        m_next_link = nav_menu.Append(wx.ID_ANY, "Next Lin&k\tCtrl+K")
        m_prev_link = nav_menu.Append(wx.ID_ANY, "Previous Link\tCtrl+Shift+K")
        m_list_links = nav_menu.Append(wx.ID_ANY, "Lin&ks List...\tAlt+K")
        nav_menu.AppendSeparator()
        m_goto_page = nav_menu.Append(wx.ID_ANY, "&Go to Page...\tCtrl+G")
        m_where = nav_menu.Append(wx.ID_ANY, "&Where Am I?\tCtrl+I")
        self.m_single_key = nav_menu.AppendCheckItem(
            wx.ID_ANY,
            "Single-&Key Navigation Mode\tCtrl+Shift+N",
            "Use H, 1-6, P, G, I, Backspace directly in Reading View",
        )
        nav_menu.AppendSeparator()
        m_find = nav_menu.Append(wx.ID_FIND, "&Find in Section...\tCtrl+F")
        menubar.Append(nav_menu, "&Navigate")

        audio_menu = wx.Menu()
        m_play = audio_menu.Append(wx.ID_ANY, "&Play / Stop Read Aloud\tF5")
        m_next_sent = audio_menu.Append(wx.ID_ANY, "Next &Sentence\tAlt+Right")
        m_prev_sent = audio_menu.Append(wx.ID_ANY, "Previous Sentence\tAlt+Left")
        menubar.Append(audio_menu, "&Audio")

        bm_menu = wx.Menu()
        m_add_bm = bm_menu.Append(wx.ID_ANY, "&Add Bookmark\tCtrl+D")
        m_list_bm = bm_menu.Append(wx.ID_ANY, "&Bookmarks...\tCtrl+B")
        menubar.Append(bm_menu, "&Bookmarks")

        help_menu = wx.Menu()
        m_keys = help_menu.Append(wx.ID_HELP, "&Keyboard Shortcuts\tF1")
        m_updates = help_menu.Append(wx.ID_ANY, "Check for &Updates...")
        m_about = help_menu.Append(wx.ID_ABOUT, "&About Open Reader")
        menubar.Append(help_menu, "&Help")

        self.SetMenuBar(menubar)

        self.Bind(wx.EVT_MENU, self._on_settings, m_prefs)
        self.Bind(wx.EVT_MENU, self._on_open_dialog, m_open)
        self.Bind(wx.EVT_MENU, self._on_library_dialog, m_lib)
        self.Bind(wx.EVT_MENU, self._on_online_libraries_dialog, m_online_lib)
        self.Bind(wx.EVT_MENU, lambda _e: self.Close(), m_exit)
        self.Bind(wx.EVT_MENU, self._on_toggle_pane_focus, m_focus)
        self.Bind(wx.EVT_MENU, lambda _e: self.go_back(), m_back)
        self.Bind(wx.EVT_MENU, lambda _e: self.go_forward(), m_fwd)
        self.Bind(wx.EVT_MENU, lambda _e: self.step_chapter(1), m_next_ch)
        self.Bind(wx.EVT_MENU, lambda _e: self.step_chapter(-1), m_prev_ch)
        self.Bind(wx.EVT_MENU, lambda _e: self.step_heading(1), m_next_hd)
        self.Bind(wx.EVT_MENU, lambda _e: self.step_heading(-1), m_prev_hd)
        self.Bind(wx.EVT_MENU, lambda _e: self.step_paragraph(1), m_next_para)
        self.Bind(wx.EVT_MENU, lambda _e: self.step_paragraph(-1), m_prev_para)
        self.Bind(wx.EVT_MENU, lambda _e: self.step_link(1), m_next_link)
        self.Bind(wx.EVT_MENU, lambda _e: self.step_link(-1), m_prev_link)
        self.Bind(wx.EVT_MENU, self._on_links_list, m_list_links)
        self.Bind(wx.EVT_MENU, self._on_go_to_page, m_goto_page)
        self.Bind(wx.EVT_MENU, self._on_where_am_i, m_where)
        self.Bind(wx.EVT_MENU, self._on_toggle_single_key_nav, self.m_single_key)
        self.Bind(wx.EVT_MENU, self._on_find, m_find)
        self.Bind(wx.EVT_MENU, self._on_toggle_read_aloud, m_play)
        self.Bind(wx.EVT_MENU, lambda _e: self.step_sentence(1), m_next_sent)
        self.Bind(wx.EVT_MENU, lambda _e: self.step_sentence(-1), m_prev_sent)
        self.Bind(wx.EVT_MENU, self._on_add_bookmark, m_add_bm)
        self.Bind(wx.EVT_MENU, self._on_list_bookmarks, m_list_bm)
        self.Bind(wx.EVT_MENU, self._on_settings, m_prefs)
        self.Bind(wx.EVT_MENU, self._on_help_shortcuts, m_keys)
        self.Bind(wx.EVT_MENU, self._on_check_updates, m_updates)
        self.Bind(wx.EVT_MENU, self._on_about, m_about)

    def _build_ui(self) -> None:
        self.CreateStatusBar()
        self.splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)

        left_panel = wx.Panel(self.splitter)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        toc_lbl = wx.StaticText(left_panel, label="Table of Contents (F6):")
        left_sizer.Add(toc_lbl, 0, wx.ALL, 6)
        self.toc_tree = wx.TreeCtrl(
            left_panel,
            style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT,
        )
        self.toc_tree.SetName("Table of contents and headings")
        left_sizer.Add(self.toc_tree, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        left_panel.SetSizer(left_sizer)

        right_panel = wx.Panel(self.splitter)
        right_sizer = wx.BoxSizer(wx.VERTICAL)
        self.chapter_lbl = wx.StaticText(right_panel, label="No book loaded")
        right_sizer.Add(self.chapter_lbl, 0, wx.ALL, 6)

        self.reader_ctrl = wx.TextCtrl(
            right_panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_NOHIDESEL | wx.TE_AUTO_URL,
        )
        self.reader_ctrl.SetName("Book reading view")
        self.reader_ctrl.SetValue(
            f"Welcome to {APP_NAME} v{__version__}.\n\n"
            "Press Ctrl+O to open an EPUB, PDF, DOCX, DAISY OPF, HTML, Markdown, or TXT file.\n"
            "Press F1 at any time for navigation shortcuts."
        )
        right_sizer.Add(self.reader_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        right_panel.SetSizer(right_sizer)

        self.splitter.SplitVertically(left_panel, right_panel, 280)
        self.splitter.SetMinimumPaneSize(180)

        self.toc_tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self._on_toc_activated)
        self.reader_ctrl.Bind(wx.EVT_KEY_DOWN, self._on_reader_key_down)
        self.reader_ctrl.Bind(wx.EVT_TEXT_URL, self._on_text_url)
        self.reader_ctrl.SetFocus()

    def _apply_preferences(self) -> None:
        prefs = self.store.data["preferences"]
        font_size = int(prefs.get("font_size", 14))
        high_contrast = bool(prefs.get("high_contrast", False))
        self.tts.configure(
            rate=int(prefs.get("speech_rate", 0)),
            voice_id=str(prefs.get("voice_id", "")),
            engine=str(prefs.get("tts_engine", "edge")),
        )

        font = wx.Font(
            font_size,
            wx.FONTFAMILY_SWISS,
            wx.FONTSTYLE_NORMAL,
            wx.FONTWEIGHT_NORMAL,
        )
        self.reader_ctrl.SetFont(font)

        if high_contrast:
            bg, fg = wx.Colour(0, 0, 0), wx.Colour(255, 255, 0)
        else:
            bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
            fg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)

        self.reader_ctrl.SetBackgroundColour(bg)
        self.reader_ctrl.SetForegroundColour(fg)
        self.reader_ctrl.Refresh()

    def _update_status(self, message: str) -> None:
        nav_mode = " | Nav: Single-Key" if self.single_key_nav else ""
        self.SetStatusText(f"{message}  |  Engine: {BACKEND_MODE}{nav_mode}")

    @property
    def _prefix_len(self) -> int:
        """Length of the EasyReader navigation marker prefix (marker text + newline)."""
        if hasattr(self, 'prev_marker'):
            return len(self.prev_marker) + 1
        return 0

    def _to_display_pos(self, char_offset: int) -> int:
        """Convert a chapter character offset to a display position (accounting for the prefix)."""
        return char_offset + self._prefix_len

    def _to_chapter_pos(self, display_pos: int) -> int:
        """Convert a display position back to a chapter character offset."""
        return max(0, display_pos - self._prefix_len)

    def _current_location(self) -> NavLocation:
        return NavLocation(self.current_chapter_idx, self._to_chapter_pos(self.reader_ctrl.GetInsertionPoint()))

    def jump_to_location(
        self,
        loc: NavLocation,
        *,
        record_history: bool = True,
        announce_text: str | None = None,
    ) -> None:
        if not self.book or not (0 <= loc.chapter_index < self.book.chapter_count):
            return
        if record_history:
            self.nav.record_jump(self._current_location())

        if loc.chapter_index != self.current_chapter_idx:
            self.load_chapter(loc.chapter_index, loc.char_offset, announce=False)
        else:
            safe_pos = max(0, min(loc.char_offset, len(self.book.chapters[loc.chapter_index].text)))
            display_pos = self._to_display_pos(safe_pos)
            self.reader_ctrl.SetInsertionPoint(display_pos)
            self.reader_ctrl.ShowPosition(display_pos)
            self.store.save_position(self.book.source_path, loc.chapter_index, safe_pos)
            self._sync_toc_selection(loc.chapter_index, safe_pos)

        if announce_text:
            self.announcer.say(announce_text, interrupt=True)

    def _on_open_dialog(self, _event: wx.Event) -> None:
        wildcard = (
            "Supported Books (*.epub;*.pdf;*.docx;*.opf;*.html;*.htm;*.md;*.txt)|"
            "*.epub;*.pdf;*.docx;*.opf;*.html;*.htm;*.xhtml;*.md;*.txt|All files (*.*)|*.*"
        )
        with wx.FileDialog(
            self,
            "Open Book",
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.open_book_path(dlg.GetPath())

    def open_book_path(self, path: str) -> None:
        self.tts.stop()
        try:
            book = load_book(path)
        except Exception as exc:
            wx.MessageBox(f"Could not open book:\n{exc}", "Open Error", wx.OK | wx.ICON_ERROR, self)
            return

        self.book = book
        self.nav.set_book(book)
        self.SetTitle(f"{book.title} - {APP_NAME}")
        self._populate_toc()

        saved_chap, saved_offset = self.store.get_position(book.source_path)
        if saved_chap >= book.chapter_count:
            saved_chap, saved_offset = 0, 0
        self.load_chapter(saved_chap, saved_offset, announce=False)
        self.announcer.say(f"Opened {book.title}, {book.chapter_count} sections.", interrupt=True)
        self.reader_ctrl.SetFocus()

    def _populate_toc(self) -> None:
        self.toc_tree.DeleteAllItems()
        self._toc_items.clear()
        if not self.book:
            return
        root = self.toc_tree.AddRoot("Book")

        def add_nodes(parent_item: wx.TreeItemId, nodes: list[TocNode]) -> None:
            for node in nodes:
                item = self.toc_tree.AppendItem(parent_item, node.title)
                self.toc_tree.SetItemData(item, (node.chapter_index, node.char_offset))
                self._toc_items.append((item, node.chapter_index, node.char_offset))
                if node.children:
                    add_nodes(item, node.children)

        add_nodes(root, self.book.toc)

    def _sync_toc_selection(self, chapter_index: int, char_offset: int) -> None:
        best_item: wx.TreeItemId | None = None
        best_key = (-1, -1)
        for item, c_idx, c_off in self._toc_items:
            if (c_idx, c_off) <= (chapter_index, char_offset) and (c_idx, c_off) >= best_key:
                best_key = (c_idx, c_off)
                best_item = item
        if best_item is not None and best_item.IsOk():
            self.toc_tree.SelectItem(best_item)

    def load_chapter(self, chapter_index: int, char_offset: int = 0, announce: bool = True) -> None:
        """Load a chapter (or the whole book) into the reading view.
        Adds EasyReader‑style navigation markers at the top and bottom so the user can press **Enter** to move to the previous or next chapter.
        """
        if not self.book or not (0 <= chapter_index < self.book.chapter_count):
            return
        self.tts.stop()
        self.current_chapter_idx = chapter_index
        chap = self.book.chapters[chapter_index]
        self.sentences = split_sentences(chap.text)

        self.chapter_lbl.SetLabel(
            f"{self.book.title} ({self.book.format_name}) — Section {chapter_index + 1}/{self.book.chapter_count}: {chap.title}"
        )

        # EasyReader navigation markers
        self.prev_marker = "Load previous"
        self.next_marker = "Load next"
        display_text = f"{self.prev_marker}\n{chap.text}\n{self.next_marker}"
        self.reader_ctrl.SetValue(display_text)

        if chap.links:
            link_attr = wx.TextAttr(wx.Colour(0, 102, 204))
            font = self.reader_ctrl.GetFont()
            font.SetUnderlined(True)
            link_attr.SetFont(font)
            for lnk in chap.links:
                s_pos = self._to_display_pos(lnk.start_offset)
                e_pos = self._to_display_pos(lnk.end_offset)
                if e_pos > s_pos:
                    self.reader_ctrl.SetStyle(s_pos, e_pos, link_attr)

        # Adjust insertion point to account for the prefix line
        chap_pos = max(0, min(char_offset, len(chap.text)))
        display_pos = self._to_display_pos(chap_pos)
        self.reader_ctrl.SetInsertionPoint(display_pos)
        self.reader_ctrl.ShowPosition(display_pos)

        # Save position without navigation markers
        self.store.save_position(self.book.source_path, chapter_index, chap_pos)
        self._sync_toc_selection(chapter_index, chap_pos)
        self._update_status(f"Section {chapter_index + 1}/{self.book.chapter_count}: {chap.title}")
        if announce:
            self.announcer.say(f"Section {chapter_index + 1}: {chap.title}", interrupt=True)

    def _on_toc_activated(self, event: wx.TreeEvent) -> None:
        data = self.toc_tree.GetItemData(event.GetItem())
        if not data:
            return
        chap_idx, offset = data
        self.jump_to_location(NavLocation(chap_idx, offset), record_history=True)
        self.reader_ctrl.SetFocus()

    def _on_toggle_pane_focus(self, _event: wx.Event) -> None:
        if self.FindFocus() == self.toc_tree:
            self.reader_ctrl.SetFocus()
            self.announcer.say("Reading view", interrupt=True)
        else:
            self.toc_tree.SetFocus()
            self.announcer.say("Table of contents", interrupt=True)

    def _on_reader_key_down(self, event: wx.KeyEvent) -> None:
        """Combined key handler for the reading view.
        1. Enter/Return on navigation markers loads previous/next chapter.
        2. Single-key navigation mode (H, 1-6, P, G, I, Backspace).
        3. Otherwise, let the event propagate.
        """
        key = event.GetKeyCode()

        # --- EasyReader Enter-to-navigate on marker lines and links ---
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and self.book:
            pos = self.reader_ctrl.GetInsertionPoint()
            content = self.reader_ctrl.GetValue()
            lines = content.splitlines()
            line_no = content[:pos].count('\n')
            if 0 <= line_no < len(lines):
                line_text = lines[line_no]
                if hasattr(self, 'prev_marker') and self.prev_marker in line_text:
                    self.step_chapter(-1)
                    return
                if hasattr(self, 'next_marker') and self.next_marker in line_text:
                    self.step_chapter(1)
                    return
            link = self._find_link_at_pos(pos)
            if link is not None:
                self._activate_link(link)
                return

        # --- Single-key navigation mode ---
        if not self.single_key_nav or event.ControlDown() or event.AltDown():
            event.Skip()
            return
        shift = event.ShiftDown()
        delta = -1 if shift else 1

        if key == ord("H"):
            self.step_heading(delta)
        elif ord("1") <= key <= ord("6"):
            self.step_heading(delta, level=key - ord("0"))
        elif key == ord("P"):
            self.step_paragraph(delta)
        elif key == ord("K"):
            self.step_link(delta)
        elif key == ord("G"):
            self._on_go_to_page(event)
        elif key == ord("I"):
            self._on_where_am_i(event)
        elif key == wx.WXK_BACK:
            if shift:
                self.go_forward()
            else:
                self.go_back()
        else:
            event.Skip()

    def go_back(self) -> None:
        if not self.book:
            return
        target = self.nav.go_back(self._current_location())
        if target is None:
            self.announcer.say("No previous location in history", interrupt=True)
            return
        self.jump_to_location(target, record_history=False, announce_text="Returned to previous location")

    def go_forward(self) -> None:
        if not self.book:
            return
        target = self.nav.go_forward(self._current_location())
        if target is None:
            self.announcer.say("No forward location in history", interrupt=True)
            return
        self.jump_to_location(target, record_history=False, announce_text="Moved forward in history")

    def step_chapter(self, delta: int) -> None:
        if not self.book:
            return
        target = self.current_chapter_idx + delta
        if 0 <= target < self.book.chapter_count:
            self.nav.record_jump(self._current_location())
            self.load_chapter(target, 0, announce=True)
        else:
            self.announcer.say("End of book" if delta > 0 else "Start of book", interrupt=True)

    def step_heading(self, delta: int, level: int | None = None) -> None:
        if not self.book:
            return
        res = self.nav.step_heading(
            self.current_chapter_idx,
            self._current_location().char_offset,
            delta,
            level=level,
        )
        if res is None:
            msg = f"No more level {level} headings" if level else "No more headings"
            self.announcer.say(msg, interrupt=True)
            return
        chap_idx, heading = res
        self.jump_to_location(
            NavLocation(chap_idx, heading.char_offset),
            record_history=False,
            announce_text=f"Heading level {heading.level}: {heading.title}",
        )

    def _find_link_at_pos(self, display_pos: int) -> LinkSpan | None:
        if not self.book:
            return None
        chap = self.book.chapters[self.current_chapter_idx]
        chap_pos = self._to_chapter_pos(display_pos)
        for lnk in chap.links:
            if lnk.start_offset <= chap_pos <= lnk.end_offset:
                return lnk
        # Fallback: check raw URL on the current line around display_pos
        content = self.reader_ctrl.GetValue()
        line_start = content.rfind("\n", 0, display_pos) + 1
        line_end = content.find("\n", display_pos)
        if line_end < 0:
            line_end = len(content)
        line = content[line_start:line_end]
        rel = display_pos - line_start
        for m in re.finditer(r"(?:https?://|mailto:)[^\s<>\"'\)\]]+", line):
            url = m.group(0).rstrip(".,;:!?")
            if m.start() <= rel <= m.start() + len(url):
                return LinkSpan(
                    text=url,
                    href=url,
                    start_offset=max(0, self._to_chapter_pos(line_start + m.start())),
                    end_offset=max(0, self._to_chapter_pos(line_start + m.start() + len(url))),
                )
        return None

    def _activate_link(self, link: LinkSpan) -> None:
        if link.target_chapter is not None:
            self.jump_to_location(
                NavLocation(link.target_chapter, link.target_offset or 0),
                record_history=True,
                announce_text=f"Followed link to {link.text}",
            )
            return
        if link.href.lower().startswith(("http://", "https://", "mailto:")):
            webbrowser.open(link.href)
            self.SetStatusText(f"Opened link: {link.href}")
            self.announcer.say(f"Opening link {link.text}", interrupt=True)
        else:
            self.announcer.say(f"Unresolved internal link: {link.href}", interrupt=True)

    def _on_text_url(self, event: wx.TextUrlEvent) -> None:
        if event.GetMouseEvent().LeftUp():
            start = event.GetURLStart()
            end = event.GetURLEnd()
            url = self.reader_ctrl.GetRange(start, end).strip()
            if url.lower().startswith(("http://", "https://", "mailto:")):
                webbrowser.open(url)
                self.SetStatusText(f"Opened link: {url}")
                self.announcer.say("Opening link in browser", interrupt=True)
        event.Skip()

    def step_link(self, delta: int) -> None:
        if not self.book:
            return
        chap = self.book.chapters[self.current_chapter_idx]
        if not chap.links:
            self.announcer.say("No links in this section", interrupt=True)
            return
        chap_pos = self._to_chapter_pos(self.reader_ctrl.GetInsertionPoint())
        chosen: LinkSpan | None = None
        if delta > 0:
            for lnk in chap.links:
                if lnk.start_offset > chap_pos:
                    chosen = lnk
                    break
        else:
            for lnk in reversed(chap.links):
                if lnk.start_offset < chap_pos:
                    chosen = lnk
                    break
        if chosen is None:
            self.announcer.say("No more links in this section", interrupt=True)
            return
        disp = self._to_display_pos(chosen.start_offset)
        self.reader_ctrl.SetInsertionPoint(disp)
        self.reader_ctrl.ShowPosition(disp)
        self.reader_ctrl.SetFocus()
        kind = "internal link" if chosen.target_chapter is not None else "link"
        self.SetStatusText(f"Link: {chosen.text} ({chosen.href})")
        self.announcer.say(f"{kind}: {chosen.text}", interrupt=True)

    def _on_links_list(self, _event: wx.Event) -> None:
        if not self.book:
            return
        chap = self.book.chapters[self.current_chapter_idx]
        if not chap.links:
            wx.MessageBox("No links found in this section.", "Links", wx.OK | wx.ICON_INFORMATION, self)
            return
        dlg = LinksDialog(self, chap.links)
        try:
            if dlg.ShowModal() == wx.ID_OK and 0 <= dlg.selected_index < len(chap.links):
                chosen = chap.links[dlg.selected_index]
                if dlg.action == "jump":
                    disp = self._to_display_pos(chosen.start_offset)
                    self.reader_ctrl.SetInsertionPoint(disp)
                    self.reader_ctrl.ShowPosition(disp)
                    self.reader_ctrl.SetFocus()
                    self.announcer.say(f"Link: {chosen.text}", interrupt=True)
                else:
                    self._activate_link(chosen)
        finally:
            dlg.Destroy()

    def step_paragraph(self, delta: int) -> None:
        if not self.book:
            return
        loc = self.nav.step_paragraph(
            self.current_chapter_idx,
            self._current_location().char_offset,
            delta,
        )
        if loc is None:
            self.announcer.say("End of paragraphs" if delta > 0 else "Start of paragraphs", interrupt=True)
            return
        chap_text = self.book.chapters[loc.chapter_index].text
        line = chap_text[loc.char_offset :].split("\n", 1)[0].strip()
        self.jump_to_location(loc, record_history=False, announce_text=line[:180])

    def _on_go_to_page(self, _event: wx.Event) -> None:
        if not self.book:
            return
        if not self.book.page_breaks:
            self.announcer.say("No page numbers available in this book", interrupt=True)
            return
        with GoToPageDialog(self, self.book.page_breaks) as dlg:
            if dlg.ShowModal() == wx.ID_OK and dlg.selected_query:
                pb = self.nav.go_to_page(dlg.selected_query)
                if pb is None:
                    self.announcer.say(f"Page {dlg.selected_query} not found", interrupt=True)
                    return
                self.jump_to_location(
                    NavLocation(pb.chapter_index, pb.char_offset),
                    record_history=True,
                    announce_text=f"Page {pb.label}",
                )
                self.reader_ctrl.SetFocus()

    def _on_where_am_i(self, _event: wx.Event) -> None:
        summary = self.nav.where_am_i(
            self.current_chapter_idx,
            self._current_location().char_offset,
        )
        self._update_status(summary)
        self.announcer.say(summary, interrupt=True)

    def _on_toggle_single_key_nav(self, _event: wx.Event) -> None:
        self.single_key_nav = self.m_single_key.IsChecked()
        state = "Single-key navigation enabled" if self.single_key_nav else "Single-key navigation disabled"
        self._update_status(state)
        self.announcer.say(state, interrupt=True)


    def _sentence_index_at_cursor(self) -> int:
        pos = self._to_chapter_pos(self.reader_ctrl.GetInsertionPoint())
        for idx, span in enumerate(self.sentences):
            if span.end >= pos:
                return idx
        return 0

    def _on_toggle_read_aloud(self, _event: wx.Event) -> None:
        if not self.book or not self.sentences:
            return
        if self.tts.is_playing:
            self.tts.stop()
            if self._tts_active_span is not None:
                self._highlight_sentence(self._tts_active_span)
            self._update_status("Read aloud stopped")
            self.announcer.say("Read aloud stopped", interrupt=True)
        else:
            start_idx = self._sentence_index_at_cursor()
            self._tts_active_span = self.sentences[start_idx]
            # Silence any queued NVDA speech before starting narration
            self.announcer.say(" ", interrupt=True)
            self._update_status("Reading aloud...")
            chap_text = self.book.chapters[self.current_chapter_idx].text
            self.tts.start(self.sentences, start_idx, source_text=chap_text)

    def step_sentence(self, delta: int) -> None:
        if not self.book or not self.sentences:
            return
        was_playing = self.tts.is_playing
        base = self.tts.current_index() if was_playing else self._sentence_index_at_cursor()
        target = max(0, min(len(self.sentences) - 1, base + delta))
        span = self.sentences[target]
        self._tts_active_span = span
        if was_playing:
            chap_text = self.book.chapters[self.current_chapter_idx].text
            self.tts.start(self.sentences, target, source_text=chap_text)
        else:
            self._highlight_sentence(span)
            self.announcer.say(span.text, interrupt=True)

    def _highlight_sentence(self, span: SentenceSpan) -> None:
        start = self._to_display_pos(span.start)
        end = self._to_display_pos(span.end)
        self.reader_ctrl.SetInsertionPoint(start)
        self.reader_ctrl.SetSelection(start, end)
        self.reader_ctrl.ShowPosition(start)

    def _on_tts_sentence_bg(self, idx: int, span: SentenceSpan) -> None:
        def update_ui() -> None:
            if self and not self.IsBeingDeleted():
                # Do NOT move caret/selection while Read Aloud is playing,
                # otherwise NVDA speaks every caret/selection change over the audio!
                self._tts_active_span = span
                self._update_status(f"Reading sentence {idx + 1}/{len(self.sentences)}")

        wx.CallAfter(update_ui)

    def _on_tts_finished_bg(self) -> None:
        def update_ui() -> None:
            if self and not self.IsBeingDeleted():
                if self._tts_active_span is not None:
                    self._highlight_sentence(self._tts_active_span)
                self._update_status("Finished section")

        wx.CallAfter(update_ui)

    def _on_find(self, _event: wx.Event) -> None:
        if not self.book:
            return
        chap_text = self.book.chapters[self.current_chapter_idx].text
        with SearchDialog(self, chap_text) as dlg:
            if dlg.ShowModal() == wx.ID_OK and dlg.selected_hit is not None:
                hit = dlg.selected_hit
                self.nav.record_jump(self._current_location())
                start = self._to_display_pos(hit.start)
                end = self._to_display_pos(hit.end)
                self.reader_ctrl.SetInsertionPoint(start)
                self.reader_ctrl.SetSelection(start, end)
                self.reader_ctrl.ShowPosition(start)
                self.reader_ctrl.SetFocus()
                self.announcer.say(f"Line {hit.line_number}: {hit.snippet}", interrupt=True)

    def _on_add_bookmark(self, _event: wx.Event) -> None:
        if not self.book:
            return
        pos = self._to_chapter_pos(self.reader_ctrl.GetInsertionPoint())
        chap = self.book.chapters[self.current_chapter_idx]
        preview = chap.text[pos : pos + 45].replace("\n", " ").strip()
        default_label = preview or chap.title
        with wx.TextEntryDialog(self, "Bookmark label:", "Add Bookmark", default_label) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                bm = self.store.add_bookmark(
                    self.book.source_path,
                    self.current_chapter_idx,
                    pos,
                    dlg.GetValue(),
                )
                self._update_status(f"Bookmark added: {bm.label}")
                self.announcer.say(f"Bookmark saved: {bm.label}", interrupt=True)

    def _on_list_bookmarks(self, _event: wx.Event) -> None:
        if not self.book:
            return
        bms = self.store.get_bookmarks(self.book.source_path)
        with BookmarksDialog(self, bms) as dlg:
            if dlg.ShowModal() == wx.ID_OK and dlg.selected_bookmark is not None:
                bm = dlg.selected_bookmark
                self.jump_to_location(
                    NavLocation(bm.chapter_index, bm.char_offset),
                    record_history=True,
                    announce_text=f"Bookmark: {bm.label}",
                )
                self.reader_ctrl.SetFocus()

    def _on_library_dialog(self, _event: wx.Event) -> None:
        lib_books = self.store.get_library()
        with LibraryDialog(self, lib_books) as dlg:
            res = dlg.ShowModal()
            if dlg.book_to_delete:
                self.store.remove_from_library(dlg.book_to_delete)
            if res == wx.ID_OK and dlg.selected_path:
                self.open_book_path(dlg.selected_path)

    def _on_online_libraries_dialog(self, _event: wx.Event) -> None:
        download_dir = Path(self.store.data_dir) / "downloads"
        with OnlineLibrariesDialog(self, download_dir) as dlg:
            if dlg.ShowModal() == wx.ID_OK and dlg.downloaded_path:
                self.open_book_path(str(dlg.downloaded_path))

    def _on_settings(self, _event: wx.Event) -> None:
        voices = self.tts.list_sapi_voices()
        with SettingsDialog(
            self,
            self.store.data["preferences"],
            voices,
            on_scan_folder=self.store.scan_folder_into_library,
            tts_controller=self.tts,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.store.data["preferences"] = dlg.get_updated_prefs()
                self.store.save()
                self._apply_preferences()
                self.announcer.say("Settings saved", interrupt=True)

    def _on_help_shortcuts(self, _event: wx.Event) -> None:
        wx.MessageBox(SHORTCUTS_TEXT, "Keyboard Shortcuts", wx.OK | wx.ICON_INFORMATION, self)

    def _on_about(self, _event: wx.Event) -> None:
        wx.MessageBox(
            f"{APP_NAME} v{__version__}\n"
            "Open-source desktop book reader (EPUB, PDF, DOCX, DAISY, HTML, Markdown, TXT).",
            f"About {APP_NAME}",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def _on_check_updates(self, _event: wx.Event) -> None:
        self.SetStatusText("Checking for updates on GitHub...")
        self.announcer.say("Checking for updates", interrupt=True)

        def _worker() -> None:
            try:
                info = check_for_update(__version__)
                wx.CallAfter(self._handle_update_result, info)
            except UpdateError as exc:
                wx.CallAfter(self._handle_update_error, str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_update_error(self, message: str) -> None:
        self.SetStatusText("Update check failed.")
        wx.MessageBox(message, "Check for Updates", wx.OK | wx.ICON_INFORMATION, self)

    def _handle_update_result(self, info: UpdateInfo) -> None:
        if not info.update_available:
            self.SetStatusText(f"{APP_NAME} is up to date (v{__version__}).")
            wx.MessageBox(
                f"You are using the latest version of {APP_NAME} (v{__version__}).",
                "Check for Updates",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return

        self.SetStatusText(f"Update available: v{info.latest_version}")
        notes_preview = info.release_notes[:400] + ("..." if len(info.release_notes) > 400 else "")
        prompt = (
            f"A new version of {APP_NAME} is available!\n\n"
            f"Current version: v{info.current_version}\n"
            f"Latest version: v{info.latest_version}\n"
        )
        if notes_preview:
            prompt += f"\nRelease notes:\n{notes_preview}\n"

        if info.asset_url and info.asset_name and info.asset_name.lower().endswith(".exe"):
            prompt += f"\nDownload and install {info.asset_name} now?"
            choice = wx.MessageBox(prompt, "Update Available", wx.YES_NO | wx.ICON_QUESTION, self)
            if choice == wx.YES:
                self._download_and_install_update(info)
        else:
            prompt += "\nOpen the GitHub release page in your browser?"
            choice = wx.MessageBox(prompt, "Update Available", wx.YES_NO | wx.ICON_QUESTION, self)
            if choice == wx.YES:
                webbrowser.open(info.release_url)

    def _download_and_install_update(self, info: UpdateInfo) -> None:
        assert info.asset_url and info.asset_name
        progress = wx.ProgressDialog(
            "Downloading Update",
            f"Downloading {info.asset_name}...",
            maximum=100,
            parent=self,
            style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_AUTO_HIDE,
        )
        cancelled = False

        def _on_progress(downloaded: int, total: int) -> bool:
            nonlocal cancelled
            pct = min(99, int((downloaded * 100) / total)) if total > 0 else 0

            def _update_dlg() -> None:
                nonlocal cancelled
                if progress:
                    cont, _ = progress.Update(
                        pct,
                        f"Downloaded {downloaded // 1024} KB"
                        + (f" of {total // 1024} KB" if total > 0 else "..."),
                    )
                    if not cont:
                        cancelled = True

            wx.CallAfter(_update_dlg)
            return not cancelled

        def _worker() -> None:
            dest_dir = Path(tempfile.gettempdir()) / "OpenReaderUpdate"
            try:
                installer_path = download_update(
                    info.asset_url,
                    dest_dir,
                    info.asset_name,
                    expected_size=info.asset_size,
                    progress_cb=_on_progress,
                )
                wx.CallAfter(self._launch_downloaded_installer, progress, installer_path)
            except UpdateError as exc:
                wx.CallAfter(self._on_download_failed, progress, str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_download_failed(self, progress: wx.ProgressDialog, message: str) -> None:
        progress.Destroy()
        wx.MessageBox(message, "Update Download Failed", wx.OK | wx.ICON_ERROR, self)

    def _launch_downloaded_installer(self, progress: wx.ProgressDialog, installer_path: Path) -> None:
        progress.Update(100, "Launching installer...")
        progress.Destroy()
        try:
            subprocess.Popen([str(installer_path)], shell=False)
            self.Close()
        except Exception as exc:
            wx.MessageBox(
                f"Downloaded installer to:\n{installer_path}\n\nCould not launch automatically: {exc}",
                "Launch Installer",
                wx.OK | wx.ICON_ERROR,
                self,
            )

    def _on_close(self, event: wx.CloseEvent) -> None:
        self.tts.stop()
        if self.book:
            raw_pos = self.reader_ctrl.GetInsertionPoint()
            chap_pos = self._to_chapter_pos(raw_pos)
            self.store.save_position(
                self.book.source_path,
                self.current_chapter_idx,
                chap_pos,
            )

            # Check if book is already in library
            auto_save = bool(self.store.data.get("preferences", {}).get("auto_save_library", False))
            if not self.store.is_in_library(self.book.source_path):
                if auto_save:
                    self.store.add_to_library(self.book.source_path, self.book.title, self.book.format_name)
                elif event.CanVeto():
                    prompt = f"'{self.book.title}' is not in your Library.\nWould you like to add it to your Library?"
                    ans = wx.MessageBox(prompt, "Add to Library?", wx.YES_NO | wx.ICON_QUESTION, self)
                    if ans == wx.YES:
                        self.store.add_to_library(self.book.source_path, self.book.title, self.book.format_name)

        event.Skip()
