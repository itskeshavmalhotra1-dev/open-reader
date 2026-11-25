"""Text-to-Speech (SAPI5) and Screen Reader (NVDA/JAWS via accessible_output2) bridge."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Callable

from book_reader.backend.engine import SentenceSpan


@dataclass(slots=True)
class VoiceInfo:
    voice_id: str
    name: str


class ScreenReaderAnnouncer:
    """Sends polite status announcements to NVDA/JAWS/SuperNova via accessible_output2."""

    def __init__(self) -> None:
        self._outputs: list = []
        try:
            from accessible_output2.outputs import dolphin, jaws, nvda  # type: ignore[import-not-found]

            for cls in (nvda.NVDA, jaws.JAWS, dolphin.Dolphin):
                try:
                    self._outputs.append(cls())
                except Exception:
                    continue
        except Exception:
            self._outputs = []

    def say(self, text: str, interrupt: bool = False) -> None:
        if not self._outputs or not text:
            return
        for out in self._outputs:
            try:
                if out.is_active():
                    out.output(text, interrupt=interrupt)
                    return
            except Exception:
                continue


class ReadAloudController:
    """Non-blocking sentence-by-sentence Read Aloud engine using Windows SAPI5."""

    def __init__(
        self,
        on_sentence: Callable[[int, SentenceSpan], None] | None = None,
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        self.on_sentence = on_sentence
        self.on_finished = on_finished
        self._sentences: list[SentenceSpan] = []
        self._index = 0
        self._rate = 0  # -10..10 for SAPI5
        self._voice_id = ""
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.is_playing = False

    @staticmethod
    def list_voices() -> list[VoiceInfo]:
        try:
            import win32com.client  # type: ignore[import-not-found]

            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            voices = speaker.GetVoices()
            return [
                VoiceInfo(voice_id=voices.Item(i).Id, name=voices.Item(i).GetDescription())
                for i in range(voices.Count)
            ]
        except Exception:
            try:
                import pyttsx3  # type: ignore[import-not-found]

                eng = pyttsx3.init()
                return [VoiceInfo(v.id, v.name) for v in eng.getProperty("voices")]
            except Exception:
                return []

    def configure(self, rate: int | None = None, voice_id: str | None = None) -> None:
        if rate is not None:
            self._rate = max(-10, min(10, int(rate)))
        if voice_id is not None:
            self._voice_id = voice_id

    def start(self, sentences: list[SentenceSpan], start_index: int = 0) -> None:
        self.stop()
        if not sentences:
            return
        with self._lock:
            self._sentences = sentences
            self._index = max(0, min(start_index, len(sentences) - 1))
            self._stop_event.clear()
            self.is_playing = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self.is_playing = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None

    def current_index(self) -> int:
        return self._index

    def _speak_with_sapi(self, text: str) -> None:
        import pythoncom  # type: ignore[import-not-found]
        import win32com.client  # type: ignore[import-not-found]

        pythoncom.CoInitialize()
        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Rate = self._rate
            if self._voice_id:
                voices = speaker.GetVoices()
                for i in range(voices.Count):
                    if voices.Item(i).Id == self._voice_id:
                        speaker.Voice = voices.Item(i)
                        break
            # SVSFlagsAsync = 1
            speaker.Speak(text, 1)
            while not self._stop_event.is_set():
                if speaker.WaitUntilDone(100):
                    break
            if self._stop_event.is_set():
                # SVSFPurgeBeforeSpeak = 2
                speaker.Speak("", 2)
        finally:
            pythoncom.CoUninitialize()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set() and self._index < len(self._sentences):
            span = self._sentences[self._index]
            if self.on_sentence:
                self.on_sentence(self._index, span)
            try:
                self._speak_with_sapi(span.text)
            except Exception:
                break
            if self._stop_event.is_set():
                return
            self._index += 1

        self.is_playing = False
        if not self._stop_event.is_set() and self.on_finished:
            self.on_finished()
