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
        self.query_ctrl.SetName("Search")
        self.find_btn = wx.Button(panel, label="&Find")
        query_row.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        query_row.Add(self.query_ctrl, 1, wx.EXPAND | wx.RIGHT, 8)
        query_row.Add(self.find_btn, 0)
        vbox.Add(query_row, 0, wx.EXPAND | wx.ALL, 10)

        self.status_lbl = wx.StaticText(panel, label="")
        vbox.Add(self.status_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        results_lbl = wx.StaticText(panel, label="&Results:")
        vbox.Add(results_lbl, 0, wx.LEFT | wx.RIGHT, 10)
        self.results_list = wx.ListBox(panel)
        self.results_list.SetName("Results")
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
        self.list_box.SetName("Bookmarks")
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
        self.page_ctrl.SetName("Page number")
        row.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(self.page_ctrl, 1, wx.EXPAND)
        vbox.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        list_lbl = wx.StaticText(panel, label=f"Available &pages ({len(page_breaks)}):")
        vbox.Add(list_lbl, 0, wx.LEFT | wx.RIGHT, 10)
        self.page_list = wx.ListBox(panel)
        self.page_list.SetName("Pages")
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
    """Accessible dialog for General, Audio, and Library Settings."""

    def __init__(
        self,
        parent: wx.Window,
        prefs: dict,
        voices: list[VoiceInfo],
        on_scan_folder: Any = None,
        tts_controller: Any = None,
        default_download_dir: Path | None = None,
    ) -> None:
        super().__init__(parent, title="Settings", size=(580, 520))
        from book_reader.backend.storage import default_data_dir

        self._voices = voices
        self._on_scan_folder = on_scan_folder
        self._tts_controller = tts_controller
        self._default_download_dir = str(default_download_dir or (default_data_dir() / "downloads"))

        main_panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.notebook = wx.Notebook(main_panel)

        # Tab 1: General & Display
        display_tab = wx.Panel(self.notebook)
        d_grid = wx.FlexGridSizer(rows=2, cols=2, vgap=12, hgap=12)
        d_grid.AddGrowableCol(1, 1)

        d_grid.Add(wx.StaticText(display_tab, label="&Font size (pt):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.font_spin = wx.SpinCtrl(display_tab, min=10, max=40, initial=int(prefs.get("font_size", 14)))
        self.font_spin.SetName("Font size")
        d_grid.Add(self.font_spin, 1, wx.EXPAND)

        d_grid.Add(wx.StaticText(display_tab, label="&High contrast mode:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.contrast_cb = wx.CheckBox(display_tab, label="Yellow text on black background")
        self.contrast_cb.SetValue(bool(prefs.get("high_contrast", False)))
        d_grid.Add(self.contrast_cb, 1, wx.EXPAND)

        d_vbox = wx.BoxSizer(wx.VERTICAL)
        d_vbox.Add(d_grid, 1, wx.EXPAND | wx.ALL, 14)
        display_tab.SetSizer(d_vbox)
        self.notebook.AddPage(display_tab, "Display")

        # Tab 2: Speech & Audio
        audio_tab = wx.Panel(self.notebook)
        a_grid = wx.FlexGridSizer(rows=6, cols=2, vgap=10, hgap=12)
        a_grid.AddGrowableCol(1, 1)

        a_grid.Add(wx.StaticText(audio_tab, label="TTS &Engine:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.engine_options = [
            ("edge", "Microsoft Edge (Natural Neural - Online)"),
            ("kokoro", "Kokoro-82M Neural (Ultra-Realistic AI - Offline)"),
            ("piper", "Piper Neural VITS (Fast AI - Offline)"),
            ("onecore", "Windows OneCore (Modern - Offline)"),
            ("sapi", "Windows SAPI5 (Built-in / Local - Offline)"),
            ("espeak", "eSpeak-NG (Synthetic - Offline)"),
            ("nvda", "Screen Reader Direct (NVDA / JAWS - No External TTS)"),
        ]
        engine_labels = [opt[1] for opt in self.engine_options]
        self.engine_choice = wx.Choice(audio_tab, choices=engine_labels)
        self.engine_choice.SetName("TTS engine")
        current_engine = str(prefs.get("tts_engine", "edge")).lower()
        sel_eng_idx = 0
        for idx, (code, _) in enumerate(self.engine_options):
            if code == current_engine:
                sel_eng_idx = idx
                break
        self.engine_choice.SetSelection(sel_eng_idx)
        a_grid.Add(self.engine_choice, 1, wx.EXPAND)

        a_grid.Add(wx.StaticText(audio_tab, label="Engine &Status:"), 0, wx.ALIGN_TOP)
        self.engine_status_ctrl = wx.TextCtrl(
            audio_tab,
            style=wx.TE_READONLY | wx.TE_MULTILINE,
            size=(-1, 56),
        )
        self.engine_status_ctrl.SetName("Engine status")
        a_grid.Add(self.engine_status_ctrl, 1, wx.EXPAND)

        a_grid.Add(wx.StaticText(audio_tab, label="&Filter by Language:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.lang_choice = wx.Choice(audio_tab)
        self.lang_choice.SetName("Language")
        a_grid.Add(self.lang_choice, 1, wx.EXPAND)

        a_grid.Add(wx.StaticText(audio_tab, label="Default TTS &Voice:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.voice_choice = wx.Choice(audio_tab)
        self.voice_choice.SetName("Voice")
        self._current_engine = current_engine
        self._sapi_voices = voices
        self._edge_voices: list[VoiceInfo] = []
        self._active_voices: list[VoiceInfo] = []
        self._all_engine_voices: list[VoiceInfo] = []
        a_grid.Add(self.voice_choice, 1, wx.EXPAND)

        a_grid.Add(wx.StaticText(audio_tab, label="Speech &rate (-10 to 10):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.rate_spin = wx.SpinCtrl(audio_tab, min=-10, max=10, initial=int(prefs.get("speech_rate", 0)))
        self.rate_spin.SetName("Speech rate")
        a_grid.Add(self.rate_spin, 1, wx.EXPAND)

        # Test Voice & Manage Piper Voices row
        a_grid.Add(wx.StaticText(audio_tab, label="Voice &Actions:"), 0, wx.ALIGN_CENTER_VERTICAL)
        action_row = wx.BoxSizer(wx.HORIZONTAL)
        test_btn = wx.Button(audio_tab, label="&Play Sample Voice")
        self.manage_piper_btn = wx.Button(audio_tab, label="&Download Voices...")
        action_row.Add(test_btn, 0, wx.RIGHT, 8)
        action_row.Add(self.manage_piper_btn, 0)
        a_grid.Add(action_row, 0)

        self._init_voices(current_id=prefs.get("voice_id", ""))

        self.engine_choice.Bind(wx.EVT_CHOICE, self._on_engine_change)
        self.lang_choice.Bind(wx.EVT_CHOICE, self._on_language_change)
        test_btn.Bind(wx.EVT_BUTTON, self._on_test_voice)
        self.manage_piper_btn.Bind(wx.EVT_BUTTON, self._on_manage_piper_voices)

        a_vbox = wx.BoxSizer(wx.VERTICAL)
        a_vbox.Add(a_grid, 1, wx.EXPAND | wx.ALL, 14)
        audio_tab.SetSizer(a_vbox)
        self.notebook.AddPage(audio_tab, "Audio")

        # Tab 3: Library Settings
        lib_tab = wx.Panel(self.notebook)
        lib_vbox = wx.BoxSizer(wx.VERTICAL)

        # Group 1: Local Library (Bookshelf)
        local_box = wx.StaticBoxSizer(wx.VERTICAL, lib_tab, "Local Library (Bookshelf)")
        local_parent = local_box.GetStaticBox()

        self.auto_save_cb = wx.CheckBox(local_parent, label="&Auto-save opened books to Library without asking")
        self.auto_save_cb.SetValue(bool(prefs.get("auto_save_library", False)))
        local_box.Add(self.auto_save_cb, 0, wx.ALL, 8)

        scan_lbl = wx.StaticText(local_parent, label="Local folder to scan for books:")
        local_box.Add(scan_lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)

        f_row = wx.BoxSizer(wx.HORIZONTAL)
        self.folder_text = wx.TextCtrl(local_parent, value=str(prefs.get("library_folder", "")))
        self.folder_text.SetName("Folder path")
        browse_btn = wx.Button(local_parent, label="&Browse Folder...")
        scan_btn = wx.Button(local_parent, label="Scan &Now")

        f_row.Add(self.folder_text, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        f_row.Add(browse_btn, 0, wx.RIGHT, 6)
        f_row.Add(scan_btn, 0)
        local_box.Add(f_row, 0, wx.EXPAND | wx.ALL, 8)

        self.scan_status_ctrl = wx.StaticText(local_parent, label="")
        local_box.Add(self.scan_status_ctrl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        lib_vbox.Add(local_box, 0, wx.EXPAND | wx.ALL, 10)

        # Group 2: Online Libraries Downloads
        dl_box = wx.StaticBoxSizer(wx.VERTICAL, lib_tab, "Online Libraries Downloads")
        dl_parent = dl_box.GetStaticBox()

        dl_lbl = wx.StaticText(dl_parent, label="Download destination folder:")
        dl_box.Add(dl_lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)

        dl_row = wx.BoxSizer(wx.HORIZONTAL)
        active_dl = str(prefs.get("online_download_dir", "")).strip() or self._default_download_dir
        self.dl_folder_text = wx.TextCtrl(dl_parent, value=active_dl)
        self.dl_folder_text.SetName("Download folder")
        self.dl_browse_btn = wx.Button(dl_parent, label="Change &Download Folder...")
        self.dl_reset_btn = wx.Button(dl_parent, label="&Reset to Default")

        dl_row.Add(self.dl_folder_text, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        dl_row.Add(self.dl_browse_btn, 0, wx.RIGHT, 6)
        dl_row.Add(self.dl_reset_btn, 0)
        dl_box.Add(dl_row, 0, wx.EXPAND | wx.ALL, 8)

        dl_hint = wx.StaticText(
            dl_parent,
            label="Books downloaded from online libraries will be saved in this folder.",
        )
        dl_box.Add(dl_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        lib_vbox.Add(dl_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        lib_tab.SetSizer(lib_vbox)
        self.notebook.AddPage(lib_tab, "Library")

        vbox.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 6)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(main_panel, wx.ID_OK, "&Save")
        ok_btn.SetDefault()
        cancel_btn = wx.Button(main_panel, wx.ID_CANCEL, "&Cancel")
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        vbox.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        main_panel.SetSizer(vbox)

        self.dl_browse_btn.Bind(wx.EVT_BUTTON, self._on_browse_download_folder)
        self.dl_reset_btn.Bind(wx.EVT_BUTTON, self._on_reset_download_folder)
        browse_btn.Bind(wx.EVT_BUTTON, self._on_browse_folder)
        scan_btn.Bind(wx.EVT_BUTTON, self._on_scan_now)
        self.font_spin.SetFocus()

    def _on_browse_download_folder(self, _event: wx.Event) -> None:
        with wx.DirDialog(self, "Choose Download Destination Folder for Online Books", style=wx.DD_DEFAULT_STYLE) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.dl_folder_text.SetValue(dlg.GetPath())

    def _on_reset_download_folder(self, _event: wx.Event) -> None:
        self.dl_folder_text.SetValue(self._default_download_dir)

    def _on_browse_folder(self, _event: wx.Event) -> None:
        with wx.DirDialog(self, "Choose Library Folder", style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.folder_text.SetValue(dlg.GetPath())

    def _on_scan_now(self, _event: wx.Event) -> None:
        folder = self.folder_text.GetValue().strip()
        if not folder:
            wx.MessageBox("Please select a folder first.", "Library Scanner", wx.OK | wx.ICON_WARNING, self)
            return
        if self._on_scan_folder:
            count = self._on_scan_folder(folder)
            self.scan_status_ctrl.SetLabel(f"Scan complete: {count} new books imported into library.")
            wx.MessageBox(f"Successfully added {count} books to your library!", "Scan Complete", wx.OK | wx.ICON_INFORMATION, self)

    def _on_test_voice(self, _event: wx.Event) -> None:
        if not self._tts_controller:
            return
        sel = self.voice_choice.GetSelection()
        selected_voice = self._active_voices[sel - 1] if sel > 0 and sel - 1 < len(self._active_voices) else None
        voice_id = selected_voice.voice_id if selected_voice else ""
        engine = self.engine_options[self.engine_choice.GetSelection()][0]
        rate = self.rate_spin.GetValue()

        voice_lang = selected_voice.language if selected_voice else self.lang_choice.GetStringSelection()
        if voice_lang == "Hindi":
            sample_text = "यह एक्सेसिबल बुक रीडर का वॉयस टेस्ट है।"
        elif voice_lang == "Urdu":
            sample_text = "یہ ایکسی ایبل بک ریڈر کے لیے وائس ٹیسٹ ہے۔"
        else:
            sample_text = "This is a sample voice test for Accessible Book Reader."

        self._tts_controller.preview_voice(sample_text, voice_id=voice_id, engine=engine, rate=rate)

    def _init_voices(self, current_id: str = "") -> None:
        self._on_engine_change(None, preserve_voice_id=current_id)

    def _on_engine_change(self, _event: wx.Event | None, preserve_voice_id: str = "") -> None:
        selected_code = self.engine_options[self.engine_choice.GetSelection()][0]
        self._current_engine = selected_code
        from book_reader.tts.speech import ReadAloudController

        self._all_engine_voices = ReadAloudController.list_voices(engine=self._current_engine)

        # Populate language filter
        langs = sorted(list(set(v.language for v in self._all_engine_voices if v.language)))
        lang_choices = ["All Languages"] + langs
        self.lang_choice.Set(lang_choices)

        # Detect current voice's language
        target_id = preserve_voice_id or (self._active_voices[self.voice_choice.GetSelection() - 1].voice_id if self.voice_choice.GetSelection() > 0 else "")
        matched_lang = "All Languages"
        for v in self._all_engine_voices:
            if v.voice_id == target_id:
                matched_lang = v.language
                break

        lang_idx = lang_choices.index(matched_lang) if matched_lang in lang_choices else 0
        self.lang_choice.SetSelection(lang_idx)
        self._apply_language_filter(current_id=target_id)
        self._update_engine_status()

    def _update_engine_status(self) -> None:
        from book_reader.tts.speech import ReadAloudController
        import shutil

        eng = self._current_engine
        if eng == "piper":
            cnt, total_bytes, model_dir = ReadAloudController.get_piper_storage_summary()
            mb = total_bytes / (1024 * 1024)
            avail = len(self._all_engine_voices)
            self.engine_status_ctrl.SetValue(
                f"Piper Offline Neural TTS: {cnt} models downloaded locally ({mb:.1f} MB). "
                f"{avail} total voices available (x_low, low, medium, high). "
                f"Folder: {model_dir}"
            )
            self.manage_piper_btn.Enable(True)
        elif eng == "kokoro":
            ready, total_bytes, model_dir = ReadAloudController.get_kokoro_storage_summary()
            mb = total_bytes / (1024 * 1024)
            avail = len(self._all_engine_voices)
            state = f"Downloaded locally ({mb:.1f} MB)" if ready else "Will auto-download (~115 MB) on first play"
            self.engine_status_ctrl.SetValue(
                f"Kokoro-82M Offline Neural TTS: {avail} voices available (English US/UK, Hindi, etc.). "
                f"Status: {state}. Folder: {model_dir}"
            )
            self.manage_piper_btn.Enable(True)
        elif eng == "edge":
            self.engine_status_ctrl.SetValue(
                f"Microsoft Edge Neural TTS: {len(self._all_engine_voices)} online AI voices available. "
                "Requires an active internet connection."
            )
            self.manage_piper_btn.Enable(False)
        elif eng == "onecore":
            self.engine_status_ctrl.SetValue(
                f"Windows OneCore: {len(self._all_engine_voices)} offline voices installed locally on Windows."
            )
            self.manage_piper_btn.Enable(False)
        elif eng == "sapi":
            self.engine_status_ctrl.SetValue(
                f"Windows SAPI5: {len(self._all_engine_voices)} local desktop voices installed."
            )
            self.manage_piper_btn.Enable(False)
        elif eng == "espeak":
            has_bin = bool(shutil.which("espeak-ng") or shutil.which("espeak"))
            note = "eSpeak-NG binary detected." if has_bin else "eSpeak-NG binary not found on PATH; falls back to SAPI5."
            self.engine_status_ctrl.SetValue(f"eSpeak-NG Offline Synthetic TTS: {note}")
            self.manage_piper_btn.Enable(False)
        elif eng == "nvda":
            self.engine_status_ctrl.SetValue(
                "Screen Reader Direct Mode: Reads directly through your active screen reader "
                "(NVDA / JAWS / Dolphin) using its own configured voice and speed."
            )
            self.manage_piper_btn.Enable(False)

    def _on_manage_piper_voices(self, _event: wx.Event) -> None:
        from book_reader.tts.speech import ReadAloudController

        if self._current_engine == "kokoro":
            with KokoroVoiceManagerDialog(self, tts_controller=self._tts_controller) as dlg:
                dlg.ShowModal()
            ReadAloudController._cached_kokoro_voices = []
        else:
            with PiperVoiceManagerDialog(self, tts_controller=self._tts_controller) as dlg:
                dlg.ShowModal()
            ReadAloudController._cached_piper_voices = []

        self._on_engine_change(None)
        self.manage_piper_btn.SetFocus()

    def _on_language_change(self, _event: wx.Event) -> None:
        self._apply_language_filter()

    def _apply_language_filter(self, current_id: str = "") -> None:
        selected_lang = self.lang_choice.GetStringSelection()
        if not selected_lang or selected_lang == "All Languages":
            self._active_voices = self._all_engine_voices
        else:
            self._active_voices = [v for v in self._all_engine_voices if v.language == selected_lang]

        voice_names = ["System Default"] + [v.name for v in self._active_voices]
        self.voice_choice.Set(voice_names)

        sel_idx = 0
        for idx, v in enumerate(self._active_voices, start=1):
            if v.voice_id == current_id:
                sel_idx = idx
                break
        self.voice_choice.SetSelection(sel_idx)

    def get_updated_prefs(self) -> dict:
        sel = self.voice_choice.GetSelection()
        voice_id = self._active_voices[sel - 1].voice_id if sel > 0 and sel - 1 < len(self._active_voices) else ""
        engine = self.engine_options[self.engine_choice.GetSelection()][0]
        dl_val = self.dl_folder_text.GetValue().strip()
        if dl_val == self._default_download_dir:
            dl_val = ""
        return {
            "font_size": self.font_spin.GetValue(),
            "high_contrast": self.contrast_cb.GetValue(),
            "speech_rate": self.rate_spin.GetValue(),
            "voice_id": voice_id,
            "tts_engine": engine,
            "library_folder": self.folder_text.GetValue().strip(),
            "auto_save_library": self.auto_save_cb.GetValue(),
            "online_download_dir": dl_val,
        }


class LibraryDialog(wx.Dialog):
    """Accessible Library Dialog showing all saved books with search and delete options."""

    def __init__(self, parent: wx.Window, library_books: list[dict[str, Any]]) -> None:
        super().__init__(parent, title="My Library (Bookshelf)", size=(640, 460))
        self._all_books = library_books
        self._filtered_books: list[dict[str, Any]] = list(library_books)
        self.selected_path: str | None = None
        self.book_to_delete: str | None = None

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Search row
        s_row = wx.BoxSizer(wx.HORIZONTAL)
        s_lbl = wx.StaticText(panel, label="&Search Library:")
        self.search_ctrl = wx.TextCtrl(panel)
        self.search_ctrl.SetName("Search")
        s_row.Add(s_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        s_row.Add(self.search_ctrl, 1, wx.EXPAND)
        vbox.Add(s_row, 0, wx.EXPAND | wx.ALL, 10)

        # Books list
        self.list_box = wx.ListBox(panel)
        self.list_box.SetName("Books")
        self._populate_list()
        vbox.Add(self.list_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Action buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.open_btn = wx.Button(panel, wx.ID_OK, "&Open Book")
        self.open_btn.SetDefault()
        self.remove_btn = wx.Button(panel, wx.ID_ANY, "&Remove from Library")
        close_btn = wx.Button(panel, wx.ID_CANCEL, "&Close")

        btn_sizer.Add(self.open_btn, 0, wx.RIGHT, 8)
        btn_sizer.Add(self.remove_btn, 0, wx.RIGHT, 8)
        btn_sizer.AddStretchSpacer(1)
        btn_sizer.Add(close_btn, 0)
        vbox.Add(btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        panel.SetSizer(vbox)

        self.search_ctrl.Bind(wx.EVT_TEXT, self._on_search)
        self.list_box.Bind(wx.EVT_LISTBOX_DCLICK, self._on_open)
        self.open_btn.Bind(wx.EVT_BUTTON, self._on_open)
        self.remove_btn.Bind(wx.EVT_BUTTON, self._on_remove)
        self.list_box.Bind(wx.EVT_KEY_DOWN, self._on_key_down)

        if self._filtered_books:
            self.list_box.SetSelection(0)
            self.list_box.SetFocus()
        else:
            self.search_ctrl.SetFocus()

    def _populate_list(self) -> None:
        self.list_box.Clear()
        for b in self._filtered_books:
            title = b.get("title", "Untitled")
            fmt = b.get("format", "BOOK")
            self.list_box.Append(f"{title} [{fmt}] - {b.get('path', '')}")

    def _on_search(self, _event: wx.Event) -> None:
        query = self.search_ctrl.GetValue().strip().lower()
        if not query:
            self._filtered_books = list(self._all_books)
        else:
            self._filtered_books = [
                b for b in self._all_books
                if query in b.get("title", "").lower() or query in b.get("path", "").lower()
            ]
        self._populate_list()
        if self._filtered_books:
            self.list_box.SetSelection(0)

    def _on_open(self, _event: wx.Event) -> None:
        idx = self.list_box.GetSelection()
        if 0 <= idx < len(self._filtered_books):
            self.selected_path = self._filtered_books[idx].get("path")
            self.EndModal(wx.ID_OK)

    def _on_remove(self, _event: wx.Event) -> None:
        idx = self.list_box.GetSelection()
        if 0 <= idx < len(self._filtered_books):
            book = self._filtered_books[idx]
            path = book.get("path")
            title = book.get("title", "this book")
            if wx.MessageBox(f"Remove '{title}' from your library?", "Remove Book", wx.YES_NO | wx.ICON_QUESTION, self) == wx.YES:
                self.book_to_delete = path
                self._all_books = [b for b in self._all_books if b.get("path") != path]
                self._filtered_books = [b for b in self._filtered_books if b.get("path") != path]
                self._populate_list()
                if self._filtered_books:
                    self.list_box.SetSelection(max(0, idx - 1))

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_DELETE:
            self._on_remove(event)
        elif event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._on_open(event)
        else:
            event.Skip()


class PiperVoiceManagerDialog(wx.Dialog):
    """Accessible dialog to browse, filter (language/quality), download, test, and remove Piper offline models."""

    def __init__(self, parent: wx.Window, tts_controller: Any = None) -> None:
        super().__init__(parent, title="Download and Manage Piper Offline Voices", size=(720, 540))
        from book_reader.tts.speech import ReadAloudController
        import threading

        self._tts_controller = tts_controller
        self._catalog: list[dict[str, Any]] = ReadAloudController.get_piper_catalog_details()
        self._filtered: list[dict[str, Any]] = []
        self._cancel_event: threading.Event | None = None
        self._downloading = False

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Summary status box (focusable by Tab for screen readers)
        self.summary_ctrl = wx.TextCtrl(
            panel,
            style=wx.TE_READONLY | wx.TE_MULTILINE,
            size=(-1, 46),
        )
        self.summary_ctrl.SetName("Piper offline storage summary")
        vbox.Add(self.summary_ctrl, 0, wx.EXPAND | wx.ALL, 10)

        # Filter row: Language, Quality, Search
        f_row = wx.BoxSizer(wx.HORIZONTAL)
        f_row.Add(wx.StaticText(panel, label="&Language:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        langs = sorted({item["language"] for item in self._catalog if item.get("language")})
        self.lang_choice = wx.Choice(panel, choices=["All Languages"] + langs)
        self.lang_choice.SetName("Language")
        self.lang_choice.SetSelection(0)
        f_row.Add(self.lang_choice, 1, wx.RIGHT, 10)

        f_row.Add(wx.StaticText(panel, label="&Quality:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        quals = ["All Qualities", "x_low", "low", "medium", "high"]
        self.qual_choice = wx.Choice(panel, choices=quals)
        self.qual_choice.SetName("Quality")
        self.qual_choice.SetSelection(0)
        f_row.Add(self.qual_choice, 1, wx.RIGHT, 10)

        f_row.Add(wx.StaticText(panel, label="&Search:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.search_ctrl = wx.TextCtrl(panel)
        self.search_ctrl.SetName("Search")
        f_row.Add(self.search_ctrl, 1)
        vbox.Add(f_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Voices list
        list_lbl = wx.StaticText(panel, label="Available &Voices:")
        vbox.Add(list_lbl, 0, wx.LEFT | wx.RIGHT, 10)
        self.voice_list = wx.ListBox(panel)
        self.voice_list.SetName("Voices")
        vbox.Add(self.voice_list, 1, wx.EXPAND | wx.ALL, 10)

        # Selected voice details (focusable by Tab)
        self.details_ctrl = wx.TextCtrl(
            panel,
            style=wx.TE_READONLY | wx.TE_MULTILINE,
            size=(-1, 56),
        )
        self.details_ctrl.SetName("Voice details")
        vbox.Add(self.details_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Progress bar + accessible status
        prog_row = wx.BoxSizer(wx.HORIZONTAL)
        self.gauge = wx.Gauge(panel, range=100, size=(-1, 18))
        self.gauge.SetName("Progress")
        self.prog_status_ctrl = wx.TextCtrl(panel, value="Ready.", style=wx.TE_READONLY)
        self.prog_status_ctrl.SetName("Status")
        prog_row.Add(self.gauge, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        prog_row.Add(self.prog_status_ctrl, 1, wx.EXPAND)
        vbox.Add(prog_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Action buttons
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.dl_btn = wx.Button(panel, label="&Download Selected")
        self.sample_btn = wx.Button(panel, label="&Play Sample")
        self.remove_btn = wx.Button(panel, label="&Remove Local Model")
        self.close_btn = wx.Button(panel, wx.ID_CANCEL, "&Close")

        btn_row.Add(self.dl_btn, 0, wx.RIGHT, 8)
        btn_row.Add(self.sample_btn, 0, wx.RIGHT, 8)
        btn_row.Add(self.remove_btn, 0, wx.RIGHT, 8)
        btn_row.AddStretchSpacer(1)
        btn_row.Add(self.close_btn, 0)
        vbox.Add(btn_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        panel.SetSizer(vbox)

        self.lang_choice.Bind(wx.EVT_CHOICE, self._on_filter)
        self.qual_choice.Bind(wx.EVT_CHOICE, self._on_filter)
        self.search_ctrl.Bind(wx.EVT_TEXT, self._on_filter)
        self.voice_list.Bind(wx.EVT_LISTBOX, self._on_select)
        self.dl_btn.Bind(wx.EVT_BUTTON, self._on_download)
        self.sample_btn.Bind(wx.EVT_BUTTON, self._on_play_sample)
        self.remove_btn.Bind(wx.EVT_BUTTON, self._on_remove)
        self.Bind(wx.EVT_CLOSE, self._on_dialog_close)

        self._refresh_summary()
        self._apply_filters()
        self.voice_list.SetFocus()

    @staticmethod
    def _fmt_size(size_bytes: int) -> str:
        if size_bytes <= 0:
            return "Unknown size"
        return f"{size_bytes / (1024 * 1024):.1f} MB"

    def _refresh_summary(self) -> None:
        from book_reader.tts.speech import ReadAloudController

        cnt, total_bytes, model_dir = ReadAloudController.get_piper_storage_summary()
        self.summary_ctrl.SetValue(
            f"Downloaded offline models: {cnt} ({self._fmt_size(total_bytes)}). "
            f"Catalog voices: {len(self._catalog)}. Folder: {model_dir}"
        )

    def _on_filter(self, _event: wx.Event) -> None:
        self._apply_filters()

    def _apply_filters(self, select_voice_id: str = "") -> None:
        lang_sel = self.lang_choice.GetStringSelection()
        qual_sel = self.qual_choice.GetStringSelection()
        q = self.search_ctrl.GetValue().strip().lower()

        self._filtered = []
        for item in self._catalog:
            if lang_sel and lang_sel != "All Languages" and item.get("language") != lang_sel:
                continue
            if qual_sel and qual_sel != "All Qualities" and item.get("quality") != qual_sel:
                continue
            if q and q not in item["voice_id"].lower() and q not in item.get("name", "").lower():
                continue
            self._filtered.append(item)

        self.voice_list.Clear()
        sel_idx = 0
        for idx, item in enumerate(self._filtered):
            status = "Downloaded" if item.get("downloaded") else "Not downloaded"
            country = f" ({item['country']})" if item.get("country") else ""
            sz = self._fmt_size(item.get("size_bytes", 0))
            line = (
                f"{item['voice_id']} | {item.get('language', 'General')}{country} | "
                f"Quality: {item.get('quality', 'medium')} | {sz} | {status}"
            )
            self.voice_list.Append(line)
            if select_voice_id and item["voice_id"] == select_voice_id:
                sel_idx = idx

        if self._filtered:
            self.voice_list.SetSelection(sel_idx)
        self._update_selection_details()

    def _selected_item(self) -> dict[str, Any] | None:
        idx = self.voice_list.GetSelection()
        if 0 <= idx < len(self._filtered):
            return self._filtered[idx]
        return None

    def _on_select(self, _event: wx.Event) -> None:
        self._update_selection_details()

    def _update_selection_details(self) -> None:
        item = self._selected_item()
        if not item:
            self.details_ctrl.SetValue("No voice selected.")
            self.dl_btn.Enable(False)
            self.sample_btn.Enable(False)
            self.remove_btn.Enable(False)
            return

        downloaded = bool(item.get("downloaded"))
        sz = self._fmt_size(item.get("size_bytes", 0))
        country = f" ({item['country']})" if item.get("country") else ""
        status_note = (
            "Downloaded locally (ready for offline playback and sample preview)."
            if downloaded
            else "Not downloaded yet. Download required before playback (Piper runs locally on CPU; server has no audio preview)."
        )
        self.details_ctrl.SetValue(
            f"Voice: {item['voice_id']} | Language: {item.get('language', 'General')}{country} | "
            f"Quality: {item.get('quality', 'medium')} | Size: {sz} | Speakers: {item.get('num_speakers', 1)}\n"
            f"Status: {status_note}"
        )
        self.dl_btn.Enable(not downloaded and not self._downloading)
        self.sample_btn.Enable(downloaded and self._tts_controller is not None)
        self.remove_btn.Enable(downloaded and not self._downloading)

    def _on_download(self, _event: wx.Event) -> None:
        import threading
        from book_reader.tts.speech import ReadAloudController, ScreenReaderAnnouncer

        item = self._selected_item()
        if not item or self._downloading:
            return
        voice_id = item["voice_id"]
        self._downloading = True
        self._cancel_event = threading.Event()
        self.dl_btn.Enable(False)
        self.remove_btn.Enable(False)
        self.gauge.SetValue(0)
        self.prog_status_ctrl.SetValue(f"Downloading {voice_id}...")
        ScreenReaderAnnouncer().say(f"Downloading {voice_id}", interrupt=True)

        def on_progress(done_bytes: int, total_bytes: int) -> None:
            def ui_update() -> None:
                if not self or self.IsBeingDeleted():
                    return
                if total_bytes > 0:
                    pct = min(100, int((done_bytes / total_bytes) * 100))
                    self.gauge.SetValue(pct)
                    self.prog_status_ctrl.SetValue(
                        f"Downloading {voice_id}: {pct}% ({self._fmt_size(done_bytes)} / {self._fmt_size(total_bytes)})"
                    )
                else:
                    self.prog_status_ctrl.SetValue(f"Downloading {voice_id}: {self._fmt_size(done_bytes)}")

            wx.CallAfter(ui_update)

        def worker() -> None:
            err: str | None = None
            try:
                ReadAloudController.download_piper_model_with_progress(
                    voice_id,
                    on_progress=on_progress,
                    cancel_event=self._cancel_event,
                )
            except Exception as exc:
                err = str(exc)

            def finish() -> None:
                if not self or self.IsBeingDeleted():
                    return
                self._downloading = False
                if err:
                    self.gauge.SetValue(0)
                    self.prog_status_ctrl.SetValue(f"Download failed: {err}")
                    ScreenReaderAnnouncer().say(f"Download failed: {err}", interrupt=True)
                else:
                    self.gauge.SetValue(100)
                    self.prog_status_ctrl.SetValue(f"Download complete: {voice_id}")
                    ScreenReaderAnnouncer().say(f"{voice_id} downloaded", interrupt=True)
                    self._catalog = ReadAloudController.get_piper_catalog_details()
                    self._refresh_summary()
                    self._apply_filters(select_voice_id=voice_id)
                self._update_selection_details()

            wx.CallAfter(finish)

        threading.Thread(target=worker, daemon=True).start()

    def _on_play_sample(self, _event: wx.Event) -> None:
        item = self._selected_item()
        if not item or not self._tts_controller:
            return
        if not item.get("downloaded"):
            wx.MessageBox(
                "Please download this voice model first. Piper voices run locally on your CPU.",
                "Not Downloaded",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return
        lang = item.get("language", "")
        if lang == "Hindi":
            sample = "यह एक्सेसिबल बुक रीडर का वॉयस टेस्ट है।"
        elif lang == "Urdu":
            sample = "یہ ایکسی ایبل بک ریڈر کے لیے وائس ٹیسٹ ہے۔"
        else:
            sample = "This is a sample voice test for Accessible Book Reader."
        self._tts_controller.preview_voice(sample, voice_id=item["voice_id"], engine="piper", rate=0)

    def _on_remove(self, _event: wx.Event) -> None:
        from book_reader.tts.speech import ReadAloudController, ScreenReaderAnnouncer

        item = self._selected_item()
        if not item or not item.get("downloaded"):
            return
        voice_id = item["voice_id"]
        if (
            wx.MessageBox(
                f"Delete local Piper model '{voice_id}' from disk?",
                "Remove Piper Model",
                wx.YES_NO | wx.ICON_QUESTION,
                self,
            )
            != wx.YES
        ):
            return
        ReadAloudController.delete_piper_model(voice_id)
        self._catalog = ReadAloudController.get_piper_catalog_details()
        self._refresh_summary()
        self._apply_filters(select_voice_id=voice_id)
        self.prog_status_ctrl.SetValue(f"Removed local model: {voice_id}")
        ScreenReaderAnnouncer().say(f"{voice_id} removed", interrupt=True)

    def _on_dialog_close(self, event: wx.CloseEvent) -> None:
        if self._cancel_event:
            self._cancel_event.set()
        event.Skip()


class KokoroVoiceManagerDialog(wx.Dialog):
    """Accessible dialog to manage Kokoro-82M offline model pack and preview all 54 voices."""

    def __init__(self, parent: wx.Window, tts_controller: Any = None) -> None:
        super().__init__(parent, title="Download and Manage Kokoro-82M Offline Voices", size=(700, 520))
        from book_reader.tts.speech import ReadAloudController
        import threading

        self._tts_controller = tts_controller
        self._voices = ReadAloudController.list_kokoro_voices()
        self._filtered: list[VoiceInfo] = []
        self._cancel_event: threading.Event | None = None
        self._downloading = False

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.summary_ctrl = wx.TextCtrl(
            panel,
            style=wx.TE_READONLY | wx.TE_MULTILINE,
            size=(-1, 48),
        )
        self.summary_ctrl.SetName("Storage summary")
        vbox.Add(self.summary_ctrl, 0, wx.EXPAND | wx.ALL, 10)

        f_row = wx.BoxSizer(wx.HORIZONTAL)
        f_row.Add(wx.StaticText(panel, label="&Language:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        langs = sorted({v.language for v in self._voices if v.language})
        self.lang_choice = wx.Choice(panel, choices=["All Languages"] + langs)
        self.lang_choice.SetName("Language")
        self.lang_choice.SetSelection(0)
        f_row.Add(self.lang_choice, 1, wx.RIGHT, 10)

        f_row.Add(wx.StaticText(panel, label="&Search:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.search_ctrl = wx.TextCtrl(panel)
        self.search_ctrl.SetName("Search")
        f_row.Add(self.search_ctrl, 1)
        vbox.Add(f_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        vbox.Add(wx.StaticText(panel, label="Kokoro &Voices (shared 115 MB model pack):"), 0, wx.LEFT | wx.RIGHT, 10)
        self.voice_list = wx.ListBox(panel)
        self.voice_list.SetName("Voices")
        vbox.Add(self.voice_list, 1, wx.EXPAND | wx.ALL, 10)

        self.details_ctrl = wx.TextCtrl(
            panel,
            style=wx.TE_READONLY | wx.TE_MULTILINE,
            size=(-1, 54),
        )
        self.details_ctrl.SetName("Details")
        vbox.Add(self.details_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        prog_row = wx.BoxSizer(wx.HORIZONTAL)
        self.gauge = wx.Gauge(panel, range=100, size=(-1, 18))
        self.gauge.SetName("Progress")
        self.prog_status_ctrl = wx.TextCtrl(panel, value="Ready.", style=wx.TE_READONLY)
        self.prog_status_ctrl.SetName("Status")
        prog_row.Add(self.gauge, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        prog_row.Add(self.prog_status_ctrl, 1, wx.EXPAND)
        vbox.Add(prog_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.dl_btn = wx.Button(panel, label="&Download Model Pack (115 MB)")
        self.sample_btn = wx.Button(panel, label="&Play Sample")
        self.remove_btn = wx.Button(panel, label="&Remove Local Model")
        close_btn = wx.Button(panel, wx.ID_CANCEL, "&Close")

        btn_row.Add(self.dl_btn, 0, wx.RIGHT, 8)
        btn_row.Add(self.sample_btn, 0, wx.RIGHT, 8)
        btn_row.Add(self.remove_btn, 0, wx.RIGHT, 8)
        btn_row.AddStretchSpacer(1)
        btn_row.Add(close_btn, 0)
        vbox.Add(btn_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        panel.SetSizer(vbox)

        self.lang_choice.Bind(wx.EVT_CHOICE, self._on_filter)
        self.search_ctrl.Bind(wx.EVT_TEXT, self._on_filter)
        self.voice_list.Bind(wx.EVT_LISTBOX, self._on_select)
        self.dl_btn.Bind(wx.EVT_BUTTON, self._on_download)
        self.sample_btn.Bind(wx.EVT_BUTTON, self._on_play_sample)
        self.remove_btn.Bind(wx.EVT_BUTTON, self._on_remove)
        self.Bind(wx.EVT_CLOSE, self._on_dialog_close)

        self._refresh_summary()
        self._apply_filters()
        self.voice_list.SetFocus()

    def _refresh_summary(self) -> None:
        from book_reader.tts.speech import ReadAloudController

        ready, total_bytes, model_dir = ReadAloudController.get_kokoro_storage_summary()
        if ready:
            mb = total_bytes / (1024 * 1024)
            self.summary_ctrl.SetValue(
                f"Kokoro-82M Model Pack: Downloaded ({mb:.1f} MB). "
                f"All {len(self._voices)} voices are ready offline. Folder: {model_dir}"
            )
        else:
            self.summary_ctrl.SetValue(
                f"Kokoro-82M Model Pack: Not downloaded (~115 MB total for all {len(self._voices)} voices). "
                f"Folder: {model_dir}"
            )

    def _on_filter(self, _event: wx.Event) -> None:
        self._apply_filters()

    def _apply_filters(self) -> None:
        from book_reader.tts.speech import ReadAloudController

        lang_sel = self.lang_choice.GetStringSelection()
        q = self.search_ctrl.GetValue().strip().lower()
        ready, _, _ = ReadAloudController.get_kokoro_storage_summary()
        state_lbl = "Ready offline" if ready else "Needs model pack"

        self._filtered = []
        self.voice_list.Clear()
        for v in self._voices:
            if lang_sel and lang_sel != "All Languages" and v.language != lang_sel:
                continue
            if q and q not in v.voice_id.lower() and q not in v.name.lower():
                continue
            self._filtered.append(v)
            self.voice_list.Append(f"{v.voice_id} | {v.name} | {state_lbl}")

        if self._filtered:
            self.voice_list.SetSelection(0)
        self._update_details()

    def _selected_voice(self) -> VoiceInfo | None:
        idx = self.voice_list.GetSelection()
        if 0 <= idx < len(self._filtered):
            return self._filtered[idx]
        return None

    def _on_select(self, _event: wx.Event) -> None:
        self._update_details()

    def _update_details(self) -> None:
        from book_reader.tts.speech import ReadAloudController

        ready, total_bytes, _ = ReadAloudController.get_kokoro_storage_summary()
        v = self._selected_voice()
        if not v:
            self.details_ctrl.SetValue("No voice selected.")
        else:
            sz = f"{total_bytes / (1024 * 1024):.1f} MB" if ready else "~115.0 MB (shared pack)"
            status = (
                "Downloaded locally (ready for offline playback and sample preview)."
                if ready
                else "Not downloaded yet. Download the shared Kokoro-82M model pack first."
            )
            self.details_ctrl.SetValue(
                f"Voice: {v.voice_id} | Language: {v.language} | Pack Size: {sz}\nStatus: {status}"
            )

        self.dl_btn.Enable(not ready and not self._downloading)
        self.sample_btn.Enable(ready and self._tts_controller is not None and v is not None)
        self.remove_btn.Enable(ready and not self._downloading)

    def _on_download(self, _event: wx.Event) -> None:
        import threading
        from book_reader.tts.speech import ReadAloudController, ScreenReaderAnnouncer

        if self._downloading:
            return
        self._downloading = True
        self._cancel_event = threading.Event()
        self.dl_btn.Enable(False)
        self.remove_btn.Enable(False)
        self.gauge.SetValue(0)
        self.prog_status_ctrl.SetValue("Downloading Kokoro-82M model pack...")
        ScreenReaderAnnouncer().say("Downloading Kokoro model pack", interrupt=True)

        def on_progress(fname: str, done_bytes: int, total_bytes: int) -> None:
            def ui_update() -> None:
                if not self or self.IsBeingDeleted():
                    return
                if total_bytes > 0:
                    pct = min(100, int((done_bytes / total_bytes) * 100))
                    self.gauge.SetValue(pct)
                    self.prog_status_ctrl.SetValue(
                        f"Downloading {fname}: {pct}% ({done_bytes / (1024 * 1024):.1f} / {total_bytes / (1024 * 1024):.1f} MB)"
                    )

            wx.CallAfter(ui_update)

        def worker() -> None:
            err: str | None = None
            try:
                ReadAloudController._ensure_kokoro_models(
                    on_progress=on_progress,
                    cancel_event=self._cancel_event,
                )
            except Exception as exc:
                err = str(exc)

            def finish() -> None:
                if not self or self.IsBeingDeleted():
                    return
                self._downloading = False
                if err:
                    self.gauge.SetValue(0)
                    self.prog_status_ctrl.SetValue(f"Download failed: {err}")
                    ScreenReaderAnnouncer().say(f"Download failed: {err}", interrupt=True)
                else:
                    self.gauge.SetValue(100)
                    self.prog_status_ctrl.SetValue("Kokoro-82M model pack download complete.")
                    ScreenReaderAnnouncer().say("Kokoro model pack downloaded", interrupt=True)
                    self._voices = ReadAloudController.list_kokoro_voices()
                    self._refresh_summary()
                    self._apply_filters()
                self._update_details()

            wx.CallAfter(finish)

        threading.Thread(target=worker, daemon=True).start()

    def _on_play_sample(self, _event: wx.Event) -> None:
        v = self._selected_voice()
        if not v or not self._tts_controller:
            return
        if v.language == "Hindi":
            sample = "यह एक्सेसिबल बुक रीडर का वॉयस टेस्ट है।"
        else:
            sample = "This is a sample voice test for Accessible Book Reader."
        self._tts_controller.preview_voice(sample, voice_id=v.voice_id, engine="kokoro", rate=0)

    def _on_remove(self, _event: wx.Event) -> None:
        from book_reader.tts.speech import ReadAloudController, ScreenReaderAnnouncer

        if (
            wx.MessageBox(
                "Delete local Kokoro-82M model pack (~115 MB) from disk?",
                "Remove Kokoro Model Pack",
                wx.YES_NO | wx.ICON_QUESTION,
                self,
            )
            != wx.YES
        ):
            return
        ReadAloudController.delete_kokoro_models()
        self._refresh_summary()
        self._apply_filters()
        self.prog_status_ctrl.SetValue("Removed local Kokoro-82M model pack.")
        ScreenReaderAnnouncer().say("Kokoro model pack removed", interrupt=True)

    def _on_dialog_close(self, event: wx.CloseEvent) -> None:
        if self._cancel_event:
            self._cancel_event.set()
        event.Skip()


class LinksDialog(wx.Dialog):
    """Accessible dialog listing links in the current chapter."""

    def __init__(self, parent: wx.Window, links: list) -> None:
        super().__init__(parent, title="Links in Section", size=(560, 380))
        self.links = links
        self.action: str | None = None
        self.selected_index: int = -1

        sizer = wx.BoxSizer(wx.VERTICAL)
        lbl = wx.StaticText(
            self,
            label=f"Links ({len(links)}):",
        )
        sizer.Add(lbl, 0, wx.ALL, 8)

        items = []
        for lnk in links:
            kind = "Internal" if getattr(lnk, "target_chapter", None) is not None else "External"
            items.append(f"{lnk.text} [{kind}] — {lnk.href}")

        self.listbox = wx.ListBox(self, choices=items)
        self.listbox.SetName("Links")
        if items:
            self.listbox.SetSelection(0)
        sizer.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        open_btn = wx.Button(self, wx.ID_OK, "&Open / Follow Link")
        jump_btn = wx.Button(self, wx.ID_ANY, "&Jump to Link in Text")
        close_btn = wx.Button(self, wx.ID_CANCEL, "&Close")
        open_btn.SetDefault()
        btn_row.Add(open_btn, 0, wx.RIGHT, 6)
        btn_row.Add(jump_btn, 0, wx.RIGHT, 6)
        btn_row.Add(close_btn, 0)
        sizer.Add(btn_row, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        self.SetSizer(sizer)
        self.listbox.SetFocus()

        open_btn.Bind(wx.EVT_BUTTON, lambda _e: self._finish("open"))
        jump_btn.Bind(wx.EVT_BUTTON, lambda _e: self._finish("jump"))
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, lambda _e: self._finish("open"))

    def _finish(self, action: str) -> None:
        sel = self.listbox.GetSelection()
        if sel == wx.NOT_FOUND:
            return
        self.action = action
        self.selected_index = sel
        self.EndModal(wx.ID_OK)


class OnlineLibrariesDialog(wx.Dialog):
    """Accessible online library catalog hub (Project Gutenberg, Standard Ebooks, Open Library)."""

    AVAILABLE_LIBRARIES = [
        "Project Gutenberg",
        "Standard Ebooks",
        "Open Library / Internet Archive",
        "Wikisource (Hindi, Urdu, English)",
        "OpenStax (Academic Textbooks)",
        "Indian Literature Archive (भारतीय साहित्य)",
        "Open Tech & CS Books (Programming)",
        "NCBI Bookshelf (Medical & Health)",
        "20th Century Classics (Orwell, Woolf)",
    ]

    LIBRARY_INFO = {
        "Project Gutenberg": {
            "status": "Online • 75,000+ Free Public Domain Books",
            "formats": "EPUB, Plain Text",
            "description": "Oldest digital library with classic literature. Supports browsing by 10+ genres (Fiction, History, Sci-Fi, Philosophy, etc.) and keyword search.",
            "access": "100% Free, no account or registration required, open public domain.",
        },
        "Standard Ebooks": {
            "status": "Online • Free High-Quality Modern Editions",
            "formats": "Clean EPUB",
            "description": "Volunteer-driven project formatting public domain books into beautiful, modern, typographically professional and proofread free ebooks.",
            "access": "Free open-source releases, no DRM, optimized for e-readers and screen readers.",
        },
        "Open Library / Internet Archive": {
            "status": "Online • Millions of Digitized Titles & Archive Editions",
            "formats": "EPUB, Text, DJVU",
            "description": "Open editable library catalog backed by the Internet Archive. Search across millions of historical titles and full-text digitized public books.",
            "access": "Free public domain & full-text archive reading, no account required for public editions.",
        },
        "Wikisource (Hindi, Urdu, English)": {
            "status": "Online • Multilingual Public Domain & Indian Classics",
            "formats": "HTML, Plain Text",
            "description": "Wikimedia free digital library. Search and read lakhs of classic works in Hindi (Premchand, Kabir, Tulsi), Urdu (Ghalib, Iqbal, Mir), English, and Sanskrit.",
            "access": "100% Free public domain, no account required.",
        },
        "OpenStax (Academic Textbooks)": {
            "status": "Online • 120+ Free Peer-Reviewed College Textbooks",
            "formats": "PDF",
            "description": "Rice University's open textbook library. College-level textbooks for Calculus, Physics, Biology, Chemistry, Anatomy, Economics, History, and Computing.",
            "access": "100% Free Open Educational Resources (OER), peer-reviewed.",
        },
        "Indian Literature Archive (भारतीय साहित्य)": {
            "status": "Online • 16+ Lakh Books in Indian Languages",
            "formats": "EPUB, PDF, Plain Text",
            "description": "Massive collection of Hindi, Urdu, Sanskrit, Bengali, Tamil, Marathi, and Punjabi classic literature, religious scriptures, history, and poetry.",
            "access": "100% Free public domain archive, no account required.",
        },
        "Open Tech & CS Books (Programming)": {
            "status": "Online • 40,000+ Free Computer Science & IT Textbooks",
            "formats": "PDF, EPUB, Plain Text",
            "description": "Free open-source textbooks on Python, C++, Data Science, Machine Learning, Algorithms, Linux, Cybersecurity, Web Development, and Databases.",
            "access": "100% Free open-access educational texts.",
        },
        "NCBI Bookshelf (Medical & Health)": {
            "status": "Online • National Library of Medicine Bookshelf",
            "formats": "HTML, PDF",
            "description": "Authoritative biomedical, clinical medicine, pharmacology, genetics, anatomy, epidemiology, and public health reference textbooks and clinical guides.",
            "access": "100% Free NIH / NLM open biomedical reference library.",
        },
        "20th Century Classics (Orwell, Woolf)": {
            "status": "Online • Modern Public Domain Classics",
            "formats": "EPUB, PDF, Plain Text",
            "description": "Celebrated 20th century classic works: George Orwell (1984, Animal Farm), Virginia Woolf, H. G. Wells, Jack London, F. Scott Fitzgerald, and Franz Kafka.",
            "access": "100% Free public domain literature.",
        },
    }

    def __init__(self, parent: wx.Window, download_dir: Path) -> None:
        super().__init__(parent, title="Online Book Catalogs", size=(750, 680))
        from book_reader.backend.gutenberg import (
            GUTENBERG_CATEGORIES,
            CatalogBook,
            download_catalog_book,
            fetch_online_catalog_page,
        )
        import threading

        self.download_dir = download_dir
        self.books: list[CatalogBook] = []
        self.downloaded_path: Path | None = None
        self._current_page: int = 1
        self._total_count: int = 0
        self._has_next: bool = False
        self._has_prev: bool = False
        self._search_seq: int = 0
        self._lock = threading.Lock()
        self._is_active = True

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Library selector row
        lib_box = wx.BoxSizer(wx.HORIZONTAL)
        lib_lbl = wx.StaticText(panel, label="&Select Library Catalog:")
        self.lib_choice = wx.Choice(panel, choices=self.AVAILABLE_LIBRARIES)
        self.lib_choice.SetName("Library")
        self.lib_choice.SetSelection(0)
        lib_box.Add(lib_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        lib_box.Add(self.lib_choice, 1, wx.EXPAND)
        vbox.Add(lib_box, 0, wx.EXPAND | wx.ALL, 8)

        # Library details and status text card
        self.lib_info_ctrl = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(-1, 62),
        )
        self.lib_info_ctrl.SetName("Library info")
        vbox.Add(self.lib_info_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Category / Topic row
        cat_box = wx.BoxSizer(wx.HORIZONTAL)
        cat_lbl = wx.StaticText(panel, label="&Category / Topic:")
        self.cat_choice = wx.Choice(panel, choices=GUTENBERG_CATEGORIES)
        self.cat_choice.SetName("Category")
        self.cat_choice.SetSelection(0)
        cat_box.Add(cat_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        cat_box.Add(self.cat_choice, 1, wx.EXPAND)
        vbox.Add(cat_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Search row
        search_box = wx.BoxSizer(wx.HORIZONTAL)
        search_lbl = wx.StaticText(panel, label="&Search (Optional):")
        self.query_ctrl = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.query_ctrl.SetName("Search")
        self.search_btn = wx.Button(panel, label="&Search")
        search_box.Add(search_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        search_box.Add(self.query_ctrl, 1, wx.EXPAND | wx.RIGHT, 8)
        search_box.Add(self.search_btn, 0)
        vbox.Add(search_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Status indicator
        self.status_lbl = wx.StaticText(
            panel,
            label="",
        )
        vbox.Add(self.status_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Results list
        results_lbl = wx.StaticText(panel, label="&Available Books:")
        vbox.Add(results_lbl, 0, wx.LEFT | wx.RIGHT, 8)
        self.results_list = wx.ListBox(panel)
        self.results_list.SetName("Books")
        vbox.Add(self.results_list, 1, wx.EXPAND | wx.ALL, 8)

        # Pagination controls row
        page_box = wx.BoxSizer(wx.HORIZONTAL)
        self.prev_page_btn = wx.Button(panel, label="&Previous Page")
        self.prev_page_btn.Enable(False)

        self.page_indicator = wx.StaticText(panel, label="Page 1")
        self.page_indicator.SetName("Page")

        self.next_page_btn = wx.Button(panel, label="&Next Page")
        self.next_page_btn.Enable(False)

        page_box.Add(self.prev_page_btn, 0, wx.RIGHT, 8)
        page_box.Add(self.page_indicator, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        page_box.Add(self.next_page_btn, 0)
        vbox.Add(page_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Details text
        self.details_ctrl = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(-1, 75),
        )
        self.details_ctrl.SetName("Details")
        vbox.Add(self.details_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Format selector row
        fmt_sizer = wx.BoxSizer(wx.HORIZONTAL)
        fmt_lbl = wx.StaticText(panel, label="&Format:")
        self.format_choice = wx.Choice(panel, choices=[])
        self.format_choice.SetName("Format")
        self.format_choice.Enable(False)
        fmt_sizer.Add(fmt_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        fmt_sizer.Add(self.format_choice, 1, wx.ALIGN_CENTER_VERTICAL)
        vbox.Add(fmt_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.download_btn = wx.Button(panel, wx.ID_OK, "&Download and Read")
        self.download_btn.Enable(False)
        self.search_btn.SetDefault()
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, "&Close")
        btn_sizer.Add(self.download_btn, 0, wx.RIGHT, 8)
        btn_sizer.Add(cancel_btn, 0)
        vbox.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        panel.SetSizer(vbox)

        # Event bindings
        self.lib_choice.Bind(wx.EVT_CHOICE, self._on_lib_changed)
        self.cat_choice.Bind(wx.EVT_CHOICE, self._on_category_changed)
        self.query_ctrl.Bind(wx.EVT_TEXT_ENTER, self._on_search)
        self.search_btn.Bind(wx.EVT_BUTTON, self._on_search)
        self.prev_page_btn.Bind(wx.EVT_BUTTON, self._on_prev_page)
        self.next_page_btn.Bind(wx.EVT_BUTTON, self._on_next_page)
        self.results_list.Bind(wx.EVT_LISTBOX, self._on_select)
        self.results_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_download)
        self.format_choice.Bind(wx.EVT_CHOICE, self._on_format_changed)
        self.download_btn.Bind(wx.EVT_BUTTON, self._on_download)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        # Initial library status display
        self._update_library_info()

    def _on_close(self, event: wx.CloseEvent) -> None:
        with self._lock:
            self._is_active = False
            self._search_seq += 1
        event.Skip()

    def _update_library_info(self) -> None:
        lib_name = self.lib_choice.GetStringSelection()
        info = self.LIBRARY_INFO.get(lib_name, {})
        status_text = info.get("status", "Online")
        formats = info.get("formats", "EPUB")
        desc = info.get("description", "")
        access = info.get("access", "Free")
        summary = (
            f"Catalog: {lib_name} ({status_text})\n"
            f"Formats: {formats} | Access: {access}\n"
            f"Features: {desc}"
        )
        self.lib_info_ctrl.SetValue(summary)

    def _on_lib_changed(self, _event: wx.Event) -> None:
        lib_name = self.lib_choice.GetStringSelection()
        from book_reader.backend.gutenberg import (
            CLASSICS_20TH_CATEGORIES,
            GUTENBERG_CATEGORIES,
            INDIAN_ARCHIVE_CATEGORIES,
            NCBI_CATEGORIES,
            OPEN_TECH_CATEGORIES,
            OPENSTAX_CATEGORIES,
            WIKISOURCE_CATEGORIES,
        )
        self.cat_choice.Clear()
        if "Gutenberg" in lib_name:
            self.cat_choice.Append(GUTENBERG_CATEGORIES)
            self.cat_choice.SetSelection(0)
            self.cat_choice.Enable(True)
        elif "Wikisource" in lib_name:
            self.cat_choice.Append(WIKISOURCE_CATEGORIES)
            self.cat_choice.SetSelection(0)
            self.cat_choice.Enable(True)
        elif "OpenStax" in lib_name:
            self.cat_choice.Append(OPENSTAX_CATEGORIES)
            self.cat_choice.SetSelection(0)
            self.cat_choice.Enable(True)
        elif "Indian Literature" in lib_name:
            self.cat_choice.Append(INDIAN_ARCHIVE_CATEGORIES)
            self.cat_choice.SetSelection(0)
            self.cat_choice.Enable(True)
        elif "Tech" in lib_name:
            self.cat_choice.Append(OPEN_TECH_CATEGORIES)
            self.cat_choice.SetSelection(0)
            self.cat_choice.Enable(True)
        elif "NCBI" in lib_name:
            self.cat_choice.Append(NCBI_CATEGORIES)
            self.cat_choice.SetSelection(0)
            self.cat_choice.Enable(True)
        elif "20th Century" in lib_name:
            self.cat_choice.Append(CLASSICS_20TH_CATEGORIES)
            self.cat_choice.SetSelection(0)
            self.cat_choice.Enable(True)
        else:
            self.cat_choice.Append(["All Topics"])
            self.cat_choice.SetSelection(0)
            self.cat_choice.Enable(False)

        self._update_library_info()
        self.status_lbl.SetLabel(f"Selected {lib_name}")

    def _on_category_changed(self, _event: wx.Event) -> None:
        cat_name = self.cat_choice.GetStringSelection()
        self.status_lbl.SetLabel(f"Selected {cat_name}")

    def _on_search(self, _event: wx.Event) -> None:
        self._trigger_load(reset_page=True)

    def _on_prev_page(self, _event: wx.Event) -> None:
        if self._current_page > 1:
            self._current_page -= 1
            self._trigger_load(reset_page=False)

    def _on_next_page(self, _event: wx.Event) -> None:
        self._current_page += 1
        self._trigger_load(reset_page=False)

    def _trigger_load(self, reset_page: bool = True) -> None:
        from book_reader.backend.gutenberg import fetch_online_catalog_page
        import threading

        with self._lock:
            if not self._is_active:
                return
            self._search_seq += 1
            current_seq = self._search_seq

        if reset_page:
            self._current_page = 1

        lib_name = self.lib_choice.GetStringSelection()
        cat_name = self.cat_choice.GetStringSelection() if self.cat_choice.IsEnabled() else ""
        query = self.query_ctrl.GetValue().strip()

        msg = f"Loading {lib_name}"
        if query:
            msg += f" for '{query}'"
        elif cat_name and cat_name != "Popular Classics (All)":
            msg += f" in '{cat_name}'"
        else:
            msg += " (Popular titles)"
        self.status_lbl.SetLabel(f"{msg} (Loading Page {self._current_page})...")

        self.results_list.Clear()
        self.format_choice.Clear()
        self.format_choice.Enable(False)
        self.download_btn.Enable(False)
        self.search_btn.Enable(False)
        self.prev_page_btn.Enable(False)
        self.next_page_btn.Enable(False)

        current_page = self._current_page

        def worker() -> None:
            try:
                page_data = fetch_online_catalog_page(
                    lib_name,
                    query=query,
                    category=cat_name,
                    page=current_page,
                )
                wx.CallAfter(self._populate_results, page_data, current_seq)
            except Exception as e:
                wx.CallAfter(self._search_failed, str(e), current_seq)

        threading.Thread(target=worker, daemon=True).start()

    def _populate_results(self, page_data, seq: int) -> None:
        with self._lock:
            if not self._is_active or seq != self._search_seq:
                return
        if not self:
            return

        self.search_btn.Enable(True)
        self.books = page_data.books
        self._total_count = page_data.total_count
        self._has_next = page_data.has_next
        self._has_prev = page_data.has_previous

        self.prev_page_btn.Enable(self._has_prev)
        self.next_page_btn.Enable(self._has_next)
        self.page_indicator.SetLabel(f"Page {page_data.current_page} (Total: {page_data.total_count:,} books)")

        self.results_list.Clear()
        if not page_data.books:
            self.format_choice.Clear()
            self.format_choice.Enable(False)
            self.status_lbl.SetLabel("No books found matching query in this library.")
            return

        for b in page_data.books:
            lang = f"[{','.join(b.languages)}]" if b.languages else ""
            self.results_list.Append(f"{b.title} — {b.author_display} {lang}")

        self.status_lbl.SetLabel(
            f"Loaded {len(page_data.books)} books."
        )
        self.results_list.SetSelection(0)
        self.download_btn.Enable(True)
        self._update_details()
        self.results_list.SetFocus()

    def _search_failed(self, error: str, seq: int) -> None:
        with self._lock:
            if not self._is_active or seq != self._search_seq:
                return
        if not self:
            return
        self.search_btn.Enable(True)
        self.prev_page_btn.Enable(self._current_page > 1)
        self.next_page_btn.Enable(self._has_next)
        self.status_lbl.SetLabel(f"Search failed: {error}")

    def _on_select(self, _event: wx.Event) -> None:
        self._update_details()
        self.download_btn.Enable(self.results_list.GetSelection() != wx.NOT_FOUND)

    def _update_details(self) -> None:
        idx = self.results_list.GetSelection()
        if 0 <= idx < len(self.books):
            b = self.books[idx]
            available = b.available_formats
            prev_sel = (
                self.format_choice.GetStringSelection()
                if self.format_choice.GetSelection() != wx.NOT_FOUND
                else ""
            )
            self.format_choice.Clear()
            if available:
                self.format_choice.Append(available)
                if prev_sel in available:
                    self.format_choice.SetStringSelection(prev_sel)
                else:
                    self.format_choice.SetSelection(0)
                self.format_choice.Enable(True)
            else:
                self.format_choice.Enable(False)

            current_fmt = (
                self.format_choice.GetStringSelection()
                or (available[0] if available else "Unknown")
            )
            details = (
                f"Title: {b.title}\n"
                f"Author: {b.author_display}\n"
                f"Library: {b.source} | Format: {current_fmt}"
            )
            self.details_ctrl.SetValue(details)
        else:
            self.format_choice.Clear()
            self.format_choice.Enable(False)
            self.details_ctrl.SetValue("")

    def _on_format_changed(self, _event: wx.Event) -> None:
        idx = self.results_list.GetSelection()
        if 0 <= idx < len(self.books):
            b = self.books[idx]
            current_fmt = (
                self.format_choice.GetStringSelection()
                if self.format_choice.GetSelection() != wx.NOT_FOUND
                else "Default"
            )
            details = (
                f"Title: {b.title}\n"
                f"Author: {b.author_display}\n"
                f"Library: {b.source} | Format: {current_fmt}"
            )
            self.details_ctrl.SetValue(details)

    def _on_download(self, _event: wx.Event) -> None:
        from book_reader.backend.gutenberg import download_catalog_book
        import threading

        idx = self.results_list.GetSelection()
        if not (0 <= idx < len(self.books)):
            return

        book = self.books[idx]
        chosen_fmt = (
            self.format_choice.GetStringSelection()
            if self.format_choice.IsEnabled()
            and self.format_choice.GetSelection() != wx.NOT_FOUND
            else None
        )
        progress = wx.ProgressDialog(
            "Downloading Book",
            f"Downloading '{book.title}' from {book.source} ({chosen_fmt or 'default'})...",
            maximum=100,
            parent=self,
            style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE,
        )

        def worker() -> None:
            try:
                def on_progress(dl: int, total: int) -> None:
                    if total > 0:
                        pct = min(99, int((dl * 100) / total))
                        wx.CallAfter(progress.Update, pct, f"Downloaded {dl // 1024} KB of {total // 1024} KB...")

                path = download_catalog_book(
                    book,
                    self.download_dir,
                    progress_cb=on_progress,
                    preferred_format=chosen_fmt,
                )
                wx.CallAfter(self._download_complete, progress, path)
            except Exception as e:
                wx.CallAfter(self._download_failed, progress, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _download_complete(self, progress: wx.ProgressDialog, path: Path) -> None:
        progress.Update(100, "Done!")
        progress.Destroy()
        self.downloaded_path = path
        self.EndModal(wx.ID_OK)

    def _download_failed(self, progress: wx.ProgressDialog, error: str) -> None:
        progress.Destroy()
        wx.MessageBox(f"Failed to download book:\n{error}", "Download Error", wx.OK | wx.ICON_ERROR, self)


# Backward compatibility alias
GutenbergCatalogDialog = OnlineLibrariesDialog
