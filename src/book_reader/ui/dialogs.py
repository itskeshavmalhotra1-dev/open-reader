"""Accessible dialogs for search, bookmarks, settings, and keyboard shortcuts."""

from __future__ import annotations

import wx

from book_reader.backend.engine import SearchHit, search_text
from book_reader.backend.models import Bookmark, PageBreak
from book_reader.tts.speech import VoiceInfo


class SearchDialog(wx.Dialog):
    """Keyboard-friendly search dialog returning the selected SearchHit."""

    def __init__(self, parent: wx.Window, chapter_text: str) -> None:
        super().__init__(parent, title="Find in Chapter", size=(560, 420))
        self._text = chapter_text
        self._hits: list[SearchHit] = []
        self.selected_hit: SearchHit | None = None

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        query_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(panel, label="&Search query:")
        self.query_ctrl = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.query_ctrl.SetName("Search query")
        self.find_btn = wx.Button(panel, label="&Find")
        query_row.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        query_row.Add(self.query_ctrl, 1, wx.EXPAND | wx.RIGHT, 8)
        query_row.Add(self.find_btn, 0)
        vbox.Add(query_row, 0, wx.EXPAND | wx.ALL, 10)

        self.status_lbl = wx.StaticText(panel, label="Type a word or phrase and press Enter.")
        vbox.Add(self.status_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        results_lbl = wx.StaticText(panel, label="&Results:")
        vbox.Add(results_lbl, 0, wx.LEFT | wx.RIGHT, 10)
        self.results_list = wx.ListBox(panel)
        self.results_list.SetName("Search results")
        vbox.Add(self.results_list, 1, wx.EXPAND | wx.ALL, 10)

        btn_sizer = wx.StdDialogButtonSizer()
        self.jump_btn = wx.Button(panel, wx.ID_OK, "&Jump to Match")
        self.jump_btn.Enable(False)
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, "&Cancel")
        btn_sizer.AddButton(self.jump_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        vbox.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        panel.SetSizer(vbox)

        self.query_ctrl.Bind(wx.EVT_TEXT_ENTER, self._on_find)
        self.find_btn.Bind(wx.EVT_BUTTON, self._on_find)
        self.results_list.Bind(wx.EVT_LISTBOX, self._on_select)
        self.results_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_activate)
        self.jump_btn.Bind(wx.EVT_BUTTON, self._on_activate)
        self.query_ctrl.SetFocus()

    def _on_find(self, _event: wx.Event) -> None:
        query = self.query_ctrl.GetValue()
        self._hits = search_text(self._text, query, 200)
        self.results_list.Clear()
        for hit in self._hits:
            snippet = hit.snippet[:120]
            self.results_list.Append(f"Line {hit.line_number}: {snippet}")

        if self._hits:
            self.status_lbl.SetLabel(f"Found {len(self._hits)} matches.")
            self.results_list.SetSelection(0)
            self.jump_btn.Enable(True)
            self.results_list.SetFocus()
        else:
            self.status_lbl.SetLabel("No matches found.")
            self.jump_btn.Enable(False)

    def _on_select(self, _event: wx.Event) -> None:
        self.jump_btn.Enable(self.results_list.GetSelection() != wx.NOT_FOUND)

    def _on_activate(self, _event: wx.Event) -> None:
        idx = self.results_list.GetSelection()
        if 0 <= idx < len(self._hits):
            self.selected_hit = self._hits[idx]
            self.EndModal(wx.ID_OK)


class BookmarksDialog(wx.Dialog):
    """Accessible list of bookmarks for the active book."""

    def __init__(self, parent: wx.Window, bookmarks: list[Bookmark]) -> None:
        super().__init__(parent, title="Bookmarks", size=(500, 360))
        self._bookmarks = bookmarks
        self.selected_bookmark: Bookmark | None = None

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(panel, label="&Saved bookmarks (press Enter to jump):")
        vbox.Add(lbl, 0, wx.ALL, 10)

        self.list_box = wx.ListBox(panel)
        self.list_box.SetName("Bookmarks list")
        for bm in bookmarks:
            self.list_box.Append(f"Chapter {bm.chapter_index + 1} - {bm.label}")
        vbox.Add(self.list_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(panel, wx.ID_OK, "&Go to Bookmark")
        ok_btn.SetDefault()
        ok_btn.Enable(bool(bookmarks))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, "&Close")
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        vbox.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        panel.SetSizer(vbox)

        if bookmarks:
            self.list_box.SetSelection(0)
        self.list_box.Bind(wx.EVT_LISTBOX_DCLICK, self._on_open)
        ok_btn.Bind(wx.EVT_BUTTON, self._on_open)
        self.list_box.SetFocus()

    def _on_open(self, _event: wx.Event) -> None:
        idx = self.list_box.GetSelection()
        if 0 <= idx < len(self._bookmarks):
            self.selected_bookmark = self._bookmarks[idx]
            self.EndModal(wx.ID_OK)


class GoToPageDialog(wx.Dialog):
    """Accessible Go to Page dialog for EPUB page-list, DAISY, and PDF pages."""

    def __init__(self, parent: wx.Window, page_breaks: list[PageBreak]) -> None:
        super().__init__(parent, title="Go to Page", size=(420, 340))
        self._pages = page_breaks
        self.selected_query: str = ""

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        row = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(panel, label="&Page number or label:")
        self.page_ctrl = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.page_ctrl.SetName("Page number or label")
        row.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(self.page_ctrl, 1, wx.EXPAND)
        vbox.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        list_lbl = wx.StaticText(panel, label=f"Available &pages ({len(page_breaks)}):")
        vbox.Add(list_lbl, 0, wx.LEFT | wx.RIGHT, 10)
        self.page_list = wx.ListBox(panel)
        self.page_list.SetName("Available pages")
        for pb in page_breaks[:500]:
            self.page_list.Append(f"Page {pb.label} (Section {pb.chapter_index + 1})")
        vbox.Add(self.page_list, 1, wx.EXPAND | wx.ALL, 10)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(panel, wx.ID_OK, "&Go")
        ok_btn.SetDefault()
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, "&Cancel")
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        vbox.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        panel.SetSizer(vbox)
        self.page_ctrl.Bind(wx.EVT_TEXT_ENTER, self._on_go)
        self.page_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_list_pick)
        ok_btn.Bind(wx.EVT_BUTTON, self._on_go)
        self.page_ctrl.SetFocus()

    def _on_list_pick(self, _event: wx.Event) -> None:
        idx = self.page_list.GetSelection()
        if 0 <= idx < len(self._pages):
            self.selected_query = self._pages[idx].label
            self.EndModal(wx.ID_OK)

    def _on_go(self, _event: wx.Event) -> None:
        typed = self.page_ctrl.GetValue().strip()
        if typed:
            self.selected_query = typed
            self.EndModal(wx.ID_OK)
            return
        idx = self.page_list.GetSelection()
        if 0 <= idx < len(self._pages):
            self.selected_query = self._pages[idx].label
            self.EndModal(wx.ID_OK)


class SettingsDialog(wx.Dialog):
    """Accessible dialog for Font Size, High Contrast, Speech Rate, and Voice."""

    def __init__(
        self,
        parent: wx.Window,
        prefs: dict,
        voices: list[VoiceInfo],
    ) -> None:
        super().__init__(parent, title="Reader Settings", size=(460, 320))
        self._voices = voices

        panel = wx.Panel(self)
        grid = wx.FlexGridSizer(rows=4, cols=2, vgap=12, hgap=12)
        grid.AddGrowableCol(1, 1)

        grid.Add(wx.StaticText(panel, label="&Font size (pt):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.font_spin = wx.SpinCtrl(panel, min=10, max=40, initial=int(prefs.get("font_size", 14)))
        self.font_spin.SetName("Font size in points")
        grid.Add(self.font_spin, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="&High contrast mode:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.contrast_cb = wx.CheckBox(panel, label="Yellow text on black background")
        self.contrast_cb.SetValue(bool(prefs.get("high_contrast", False)))
        grid.Add(self.contrast_cb, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Speech &rate (-10 to 10):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.rate_spin = wx.SpinCtrl(panel, min=-10, max=10, initial=int(prefs.get("speech_rate", 0)))
        self.rate_spin.SetName("Speech rate")
        grid.Add(self.rate_spin, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="TTS &Voice:"), 0, wx.ALIGN_CENTER_VERTICAL)
        voice_names = ["System Default"] + [v.name for v in voices]
        self.voice_choice = wx.Choice(panel, choices=voice_names)
        self.voice_choice.SetName("Text to Speech voice")
        current_id = prefs.get("voice_id", "")
        sel_idx = 0
        for idx, v in enumerate(voices, start=1):
            if v.voice_id == current_id:
                sel_idx = idx
                break
        self.voice_choice.SetSelection(sel_idx)
        grid.Add(self.voice_choice, 1, wx.EXPAND)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(grid, 1, wx.EXPAND | wx.ALL, 14)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(panel, wx.ID_OK, "&Save")
        ok_btn.SetDefault()
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, "&Cancel")
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        vbox.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 12)

        panel.SetSizer(vbox)
        self.font_spin.SetFocus()

    def get_updated_prefs(self) -> dict:
        sel = self.voice_choice.GetSelection()
        voice_id = self._voices[sel - 1].voice_id if sel > 0 and sel - 1 < len(self._voices) else ""
        return {
            "font_size": self.font_spin.GetValue(),
            "high_contrast": self.contrast_cb.GetValue(),
            "speech_rate": self.rate_spin.GetValue(),
            "voice_id": voice_id,
        }
