"""Text-to-Speech (SAPI5 and Microsoft Edge Neural TTS) and Screen Reader bridge."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import io
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
from typing import Callable

from book_reader.backend.engine import SentenceSpan

try:
    import book_reader_core as _rust_audio  # type: ignore[import-not-found]
except ImportError:
    _rust_audio = None


@dataclass(slots=True)
class VoiceInfo:
    voice_id: str
    name: str
    language: str = "All"


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

    def say(self, text: str, interrupt: bool = False) -> bool:
        if not self._outputs or not text:
            return False
        for out in self._outputs:
            try:
                if out.is_active():
                    out.output(text, interrupt=interrupt)
                    return True
            except Exception:
                continue
        return False

    def silence(self) -> None:
        for out in self._outputs:
            try:
                if out.is_active() and hasattr(out, "silence"):
                    out.silence()
                    return
            except Exception:
                continue


class ReadAloudController:
    """Non-blocking sentence-by-sentence Read Aloud engine supporting SAPI5, OneCore, Piper, eSpeak-NG, and Microsoft Edge Neural TTS."""

    _cached_edge_voices: list[VoiceInfo] = []
    _cached_sapi_voices: list[VoiceInfo] = []
    _cached_onecore_voices: list[VoiceInfo] = []
    _cached_piper_voices: list[VoiceInfo] = []
    _cached_piper_catalog: list[dict] = []
    _cached_kokoro_voices: list[VoiceInfo] = []
    _piper_voice_cache: dict[str, object] = {}
    _kokoro_instance: object | None = None
    _kokoro_lock = threading.Lock()
    _piper_dl_lock = threading.Lock()
    _mixer_lock = threading.Lock()

    def __init__(
        self,
        on_sentence: Callable[[int, SentenceSpan], None] | None = None,
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        self.on_sentence = on_sentence
        self.on_finished = on_finished
        self._sentences: list[SentenceSpan] = []
        self._source_text: str = ""
        self._index = 0
        self._rate = 0  # -10..10 for SAPI5 or percentage for Edge
        self._voice_id = ""
        self._engine = "sapi"  # "sapi" or "edge"
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._announcer = ScreenReaderAnnouncer()
        self.is_playing = False

    @staticmethod
    def list_voices(engine: str = "sapi") -> list[VoiceInfo]:
        eng = engine.lower()
        if eng == "edge":
            return ReadAloudController.list_edge_voices()
        elif eng == "onecore":
            return ReadAloudController.list_onecore_voices()
        elif eng == "piper":
            return ReadAloudController.list_piper_voices()
        elif eng == "kokoro":
            return ReadAloudController.list_kokoro_voices()
        elif eng == "nvda":
            return ReadAloudController.list_nvda_voices()
        elif eng == "espeak":
            return ReadAloudController.list_espeak_voices()
        return ReadAloudController.list_sapi_voices()

    @staticmethod
    def list_onecore_voices() -> list[VoiceInfo]:
        """List Windows 10/11 OneCore voices (Local & Offline)."""
        if ReadAloudController._cached_onecore_voices:
            return ReadAloudController._cached_onecore_voices
        res: list[VoiceInfo] = []
        try:
            import win32com.client
            import pythoncom

            pythoncom.CoInitialize()
            cat = win32com.client.Dispatch("SAPI.SpObjectTokenCategory")
            cat.SetId(r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices")
            tokens = cat.EnumerateTokens()
            for i in range(tokens.Count):
                tok = tokens.Item(i)
                desc = tok.GetDescription()
                lang = "English" if "English" in desc else "Hindi" if "Hindi" in desc else "General"
                res.append(VoiceInfo(voice_id=tok.Id, name=f"[OneCore] {desc}", language=lang))
            pythoncom.CoUninitialize()
        except Exception:
            pass
        result = res or [
            VoiceInfo("MSTTS_V110_enUS_DavidM", "[OneCore] Microsoft David - English (US)", language="English"),
            VoiceInfo("MSTTS_V110_enUS_MarkM", "[OneCore] Microsoft Mark - English (US)", language="English"),
            VoiceInfo("MSTTS_V110_enUS_ZiraM", "[OneCore] Microsoft Zira - English (US)", language="English"),
        ]
        ReadAloudController._cached_onecore_voices = result
        return result

    @staticmethod
    def list_piper_voices() -> list[VoiceInfo]:
        """List local offline neural Piper voices plus full downloadable catalog."""
        if ReadAloudController._cached_piper_voices:
            return ReadAloudController._cached_piper_voices

        model_dir = Path.home() / ".accessible_book_reader" / "piper_models"
        res: list[VoiceInfo] = []
        seen_stems: set[str] = set()
        lang_map = {
            "hi": "Hindi",
            "en": "English",
            "ur": "Urdu",
            "ar": "Arabic",
            "bn": "Bengali",
            "ml": "Malayalam",
            "mr": "Marathi",
            "ne": "Nepali",
            "te": "Telugu",
        }
        if model_dir.is_dir():
            for onnx_file in sorted(model_dir.glob("*.onnx")):
                if not onnx_file.with_suffix(".onnx.json").is_file():
                    continue
                stem = onnx_file.stem
                seen_stems.add(stem)
                prefix = stem.split("_", 1)[0].lower()
                lang = lang_map.get(prefix, "General")
                res.append(VoiceInfo(voice_id=str(onnx_file), name=f"[Piper Offline] {stem}", language=lang))

        try:
            import json
            from urllib.request import urlopen
            import piper.download_voices as dv

            raw = json.loads(urlopen(dv.VOICES_JSON, timeout=5).read().decode("utf-8"))
            for key, info in sorted(raw.items()):
                if key in seen_stems:
                    continue
                lang_name = info.get("language", {}).get("name_english", "General")
                country = info.get("language", {}).get("country_english", "")
                name = info.get("name", key)
                quality = info.get("quality", "")
                label = f"[Piper Neural] {name} ({lang_name} - {country}, {quality})".strip()
                res.append(VoiceInfo(key, label, language=lang_name))
        except Exception:
            fallback = [
                ("en_US-lessac-medium", "[Piper Neural] en_US-lessac (English US)", "English"),
                ("en_US-amy-medium", "[Piper Neural] en_US-amy (English US)", "English"),
                ("en_US-ryan-medium", "[Piper Neural] en_US-ryan (English US)", "English"),
                ("en_US-kristin-medium", "[Piper Neural] en_US-kristin (English US)", "English"),
                ("en_GB-alan-medium", "[Piper Neural] en_GB-alan (English UK)", "English"),
                ("en_GB-cori-medium", "[Piper Neural] en_GB-cori (English UK)", "English"),
                ("hi_IN-pratham-medium", "[Piper Neural] hi_IN-pratham (Hindi Male)", "Hindi"),
                ("hi_IN-priyamvada-medium", "[Piper Neural] hi_IN-priyamvada (Hindi Female)", "Hindi"),
                ("hi_IN-rohan-medium", "[Piper Neural] hi_IN-rohan (Hindi Male)", "Hindi"),
                ("ur_PK-aegis_female-medium", "[Piper Neural] ur_PK-aegis_female (Urdu)", "Urdu"),
                ("ur_PK-fasih-medium", "[Piper Neural] ur_PK-fasih (Urdu)", "Urdu"),
            ]
            for voice_id, label, lang in fallback:
                if voice_id not in seen_stems:
                    res.append(VoiceInfo(voice_id, label, language=lang))

        ReadAloudController._cached_piper_voices = res
        return res

    @staticmethod
    def list_espeak_voices() -> list[VoiceInfo]:
        """List eSpeak-NG multi-lingual synthetic voices."""
        return [
            VoiceInfo("en-us", "[eSpeak-NG] English (US)", language="English"),
            VoiceInfo("en-gb", "[eSpeak-NG] English (UK)", language="English"),
            VoiceInfo("hi", "[eSpeak-NG] Hindi", language="Hindi"),
            VoiceInfo("ur", "[eSpeak-NG] Urdu", language="Urdu"),
            VoiceInfo("bn", "[eSpeak-NG] Bengali", language="Bengali"),
            VoiceInfo("ta", "[eSpeak-NG] Tamil", language="Tamil"),
            VoiceInfo("te", "[eSpeak-NG] Telugu", language="Telugu"),
            VoiceInfo("mr", "[eSpeak-NG] Marathi", language="Marathi"),
            VoiceInfo("pa", "[eSpeak-NG] Punjabi", language="Punjabi"),
            VoiceInfo("es", "[eSpeak-NG] Spanish", language="Spanish"),
            VoiceInfo("fr", "[eSpeak-NG] French", language="French"),
            VoiceInfo("de", "[eSpeak-NG] German", language="German"),
            VoiceInfo("ar", "[eSpeak-NG] Arabic", language="Arabic"),
        ]

    @staticmethod
    def list_sapi_voices() -> list[VoiceInfo]:
        if ReadAloudController._cached_sapi_voices:
            return ReadAloudController._cached_sapi_voices
        try:
            import win32com.client  # type: ignore[import-not-found]

            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            voices = speaker.GetVoices()
            res: list[VoiceInfo] = []
            for i in range(voices.Count):
                v = voices.Item(i)
                desc = v.GetDescription()
                lang = "English" if "English" in desc else "Hindi" if "Hindi" in desc else "General"
                res.append(VoiceInfo(voice_id=v.Id, name=desc, language=lang))
            ReadAloudController._cached_sapi_voices = res
            return res
        except Exception:
            try:
                import pyttsx3  # type: ignore[import-not-found]

                eng = pyttsx3.init()
                res = [
                    VoiceInfo(v.id, v.name, language="English" if "English" in v.name else "General")
                    for v in eng.getProperty("voices")
                ]
                ReadAloudController._cached_sapi_voices = res
                return res
            except Exception:
                return []

    @staticmethod
    def list_edge_voices() -> list[VoiceInfo]:
        """Fetch list of Microsoft Edge Neural voices with language tagging (cached)."""
        if ReadAloudController._cached_edge_voices:
            return ReadAloudController._cached_edge_voices
        lang_names = {
            "hi": "Hindi",
            "en": "English",
            "ur": "Urdu",
            "bn": "Bengali",
            "ta": "Tamil",
            "te": "Telugu",
            "mr": "Marathi",
            "gu": "Gujarati",
            "kn": "Kannada",
            "ml": "Malayalam",
            "pa": "Punjabi",
            "es": "Spanish",
            "fr": "French",
            "de": "German",
            "ar": "Arabic",
            "zh": "Chinese",
            "ja": "Japanese",
            "ru": "Russian",
            "pt": "Portuguese",
            "it": "Italian",
        }
        try:
            import edge_tts

            raw_voices = asyncio.run(edge_tts.list_voices())
            res: list[VoiceInfo] = []
            for v in raw_voices:
                short_name = v.get("ShortName", "")
                friendly = v.get("FriendlyName", short_name)
                gender = v.get("Gender", "")
                locale = v.get("Locale", "")
                lang_code = locale.split("-")[0].lower() if locale else ""
                lang_label = lang_names.get(lang_code, locale or "Other")
                label = f"{friendly} ({gender})" if gender else friendly
                res.append(VoiceInfo(voice_id=short_name, name=label, language=lang_label))
            res.sort(key=lambda x: (x.language, x.name))
            ReadAloudController._cached_edge_voices = res
            return res
        except Exception:
            # Fallback popular Microsoft voices if offline/error
            return [
                VoiceInfo("hi-IN-SwaraNeural", "Microsoft Swara Neural - Hindi (India)", language="Hindi"),
                VoiceInfo("hi-IN-MadhurNeural", "Microsoft Madhur Neural - Hindi (India)", language="Hindi"),
                VoiceInfo("en-IN-NeerjaNeural", "Microsoft Neerja Neural - English (India)", language="English"),
                VoiceInfo("en-IN-PrabhatNeural", "Microsoft Prabhat Neural - English (India)", language="English"),
                VoiceInfo("en-US-AriaNeural", "Microsoft Aria Neural - English (United States)", language="English"),
                VoiceInfo("en-US-GuyNeural", "Microsoft Guy Neural - English (United States)", language="English"),
                VoiceInfo("ur-PK-UzmaNeural", "Microsoft Uzma Neural - Urdu (Pakistan)", language="Urdu"),
            ]

    def configure(
        self,
        rate: int | None = None,
        voice_id: str | None = None,
        engine: str | None = None,
    ) -> None:
        if rate is not None:
            self._rate = max(-10, min(10, int(rate)))
        if voice_id is not None:
            self._voice_id = voice_id
        if engine is not None:
            self._engine = engine.lower()

    def start(self, sentences: list[SentenceSpan], start_index: int = 0, source_text: str = "") -> None:
        self.stop()
        if not sentences:
            return
        with self._lock:
            self._sentences = sentences
            self._source_text = source_text
            self._index = max(0, min(start_index, len(sentences) - 1))
            self._stop_event.clear()
            self.is_playing = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self.is_playing = False
        if _rust_audio is not None and hasattr(_rust_audio, "rust_stop_audio"):
            try:
                _rust_audio.rust_stop_audio()
            except Exception:
                pass
        if self._engine == "nvda":
            self._announcer.silence()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None

    def current_index(self) -> int:
        return self._index

    def preview_voice(self, text: str, voice_id: str, engine: str, rate: int = 0) -> None:
        """Speak a short preview text using the specified engine and voice without mutating active config."""
        self.stop()
        with self._lock:
            self._stop_event.clear()
            preview_ctrl = ReadAloudController()
            preview_ctrl.configure(rate=rate, voice_id=voice_id, engine=engine)
            preview_ctrl._stop_event = self._stop_event

            def _do_preview() -> None:
                try:
                    if engine.lower() == "nvda":
                        preview_ctrl._speak_with_nvda(text, interrupt=True)
                    else:
                        preview_ctrl._dispatch_speak(text, engine=engine)
                except Exception as exc:
                    print(f"[TTS Preview Error]: {exc}")

            self._thread = threading.Thread(target=_do_preview, daemon=True)
            self._thread.start()

    def _speak_with_sapi(self, text: str, is_onecore: bool = False) -> None:
        import pythoncom  # type: ignore[import-not-found]
        import win32com.client  # type: ignore[import-not-found]

        pythoncom.CoInitialize()
        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Rate = self._rate
            if is_onecore:
                try:
                    cat = win32com.client.Dispatch("SAPI.SpObjectTokenCategory")
                    cat.SetId(r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices")
                    tokens = cat.EnumerateTokens()
                    for i in range(tokens.Count):
                        tok = tokens.Item(i)
                        if tok.Id == self._voice_id or self._voice_id in tok.Id:
                            speaker.Voice = tok
                            break
                except Exception:
                    pass
            elif self._voice_id:
                voices = speaker.GetVoices()
                for i in range(voices.Count):
                    if voices.Item(i).Id == self._voice_id:
                        speaker.Voice = voices.Item(i)
                        break
            speaker.Speak(text, 1)
            while not self._stop_event.is_set():
                if speaker.WaitUntilDone(100):
                    break
            if self._stop_event.is_set():
                speaker.Speak("", 2)
        finally:
            pythoncom.CoUninitialize()

    def _speak_with_espeak(self, text: str) -> None:
        """Speak using eSpeak-NG via CLI subprocess or pyttsx3 fallback."""
        import shutil
        import subprocess

        voice = self._voice_id or "en-us"
        speed = max(80, min(450, 175 + (self._rate * 15)))
        exe = shutil.which("espeak-ng") or shutil.which("espeak")
        if exe:
            try:
                subprocess.run([exe, "-v", voice, "-s", str(speed), text], check=True, timeout=5)
                return
            except Exception:
                pass

        # If eSpeak-NG binary is not installed on PATH, speak cleanly with SAPI without hanging
        self._speak_with_sapi(text)

    @staticmethod
    def get_piper_storage_summary() -> tuple[int, int, Path]:
        """Return (downloaded_count, total_bytes, model_dir) for local Piper models."""
        model_dir = Path.home() / ".accessible_book_reader" / "piper_models"
        if not model_dir.is_dir():
            return 0, 0, model_dir
        count = 0
        total_bytes = 0
        for onnx_file in model_dir.glob("*.onnx"):
            json_file = onnx_file.with_suffix(".onnx.json")
            if json_file.is_file() and onnx_file.stat().st_size > 1_000_000:
                count += 1
                total_bytes += onnx_file.stat().st_size + json_file.stat().st_size
        return count, total_bytes, model_dir

    @staticmethod
    def get_piper_catalog_details() -> list[dict]:
        """Return detailed metadata for all Piper voices (cached)."""
        model_dir = Path.home() / ".accessible_book_reader" / "piper_models"
        local_sizes: dict[str, int] = {}
        if model_dir.is_dir():
            for onnx_file in model_dir.glob("*.onnx"):
                json_file = onnx_file.with_suffix(".onnx.json")
                if json_file.is_file() and onnx_file.stat().st_size > 1_000_000:
                    local_sizes[onnx_file.stem] = onnx_file.stat().st_size + json_file.stat().st_size

        if not ReadAloudController._cached_piper_catalog:
            entries: list[dict] = []
            try:
                import json
                from urllib.request import urlopen
                import piper.download_voices as dv

                raw = json.loads(urlopen(dv.VOICES_JSON, timeout=6).read().decode("utf-8"))
                for key, info in sorted(raw.items()):
                    files = info.get("files", {})
                    size_bytes = sum(
                        int(finfo.get("size_bytes", 0))
                        for fname, finfo in files.items()
                        if fname.endswith(".onnx") or fname.endswith(".onnx.json")
                    )
                    lang_info = info.get("language", {})
                    entries.append({
                        "voice_id": key,
                        "name": info.get("name", key),
                        "language": lang_info.get("name_english", "General"),
                        "country": lang_info.get("country_english", ""),
                        "quality": info.get("quality", "medium"),
                        "num_speakers": int(info.get("num_speakers", 1)),
                        "size_bytes": size_bytes,
                    })
                ReadAloudController._cached_piper_catalog = entries
            except Exception:
                # Offline fallback using local files + curated list
                for stem, sz in sorted(local_sizes.items()):
                    parts = stem.split("-")
                    prefix = stem.split("_", 1)[0].lower()
                    lang = "Hindi" if prefix == "hi" else "English" if prefix == "en" else "Urdu" if prefix == "ur" else "General"
                    entries.append({
                        "voice_id": stem,
                        "name": parts[1] if len(parts) > 1 else stem,
                        "language": lang,
                        "country": "",
                        "quality": parts[-1] if len(parts) > 2 else "medium",
                        "num_speakers": 1,
                        "size_bytes": sz,
                    })

        # Return fresh copies with up-to-date downloaded flag & size
        result: list[dict] = []
        source = ReadAloudController._cached_piper_catalog
        seen = set()
        for item in source:
            vid = item["voice_id"]
            seen.add(vid)
            copy = dict(item)
            copy["downloaded"] = vid in local_sizes
            if vid in local_sizes and copy["size_bytes"] == 0:
                copy["size_bytes"] = local_sizes[vid]
            result.append(copy)
        for stem, sz in sorted(local_sizes.items()):
            if stem not in seen:
                parts = stem.split("-")
                prefix = stem.split("_", 1)[0].lower()
                lang = "Hindi" if prefix == "hi" else "English" if prefix == "en" else "Urdu" if prefix == "ur" else "General"
                result.append({
                    "voice_id": stem,
                    "name": parts[1] if len(parts) > 1 else stem,
                    "language": lang,
                    "country": "",
                    "quality": parts[-1] if len(parts) > 2 else "medium",
                    "num_speakers": 1,
                    "size_bytes": sz,
                    "downloaded": True,
                })
        return result

    @staticmethod
    def delete_piper_model(voice_id: str) -> bool:
        """Delete a locally downloaded Piper voice model to free disk space."""
        stem = Path(voice_id).stem if voice_id.endswith(".onnx") else voice_id
        model_dir = Path.home() / ".accessible_book_reader" / "piper_models"
        onnx_p = model_dir / f"{stem}.onnx"
        json_p = model_dir / f"{stem}.onnx.json"
        deleted = False
        for p in (onnx_p, json_p):
            if p.exists():
                p.unlink(missing_ok=True)
                deleted = True
        ReadAloudController._piper_voice_cache.pop(str(onnx_p), None)
        ReadAloudController._cached_piper_voices = []
        return deleted

    @staticmethod
    def download_piper_model_with_progress(
        voice_id: str,
        on_progress: Callable[[int, int], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        """Download a Piper .onnx + .onnx.json model with byte progress and atomic move."""
        import shutil
        from urllib.request import urlopen
        import piper.download_voices as dv

        stem = Path(voice_id).stem if voice_id.endswith(".onnx") else voice_id
        match = dv.VOICE_PATTERN.match(stem)
        if not match:
            return ReadAloudController._ensure_piper_model(stem)

        lang_family = match.group("lang_family")
        lang_code = f"{lang_family}_{match.group('lang_region')}"
        voice_name = match.group("voice_name")
        voice_quality = match.group("voice_quality")
        fmt_args = {
            "lang_family": lang_family,
            "lang_code": lang_code,
            "voice_name": voice_name,
            "voice_quality": voice_quality,
        }

        model_dir = Path.home() / ".accessible_book_reader" / "piper_models"
        model_dir.mkdir(parents=True, exist_ok=True)
        model_path = model_dir / f"{stem}.onnx"
        config_path = model_dir / f"{stem}.onnx.json"

        with ReadAloudController._piper_dl_lock:
            if model_path.is_file() and config_path.is_file() and model_path.stat().st_size > 1_000_000:
                return model_path

            tmp_dir = model_dir / ".tmp_dl"
            shutil.rmtree(tmp_dir, ignore_errors=True)
            tmp_dir.mkdir(parents=True, exist_ok=True)
            try:
                tmp_onnx = tmp_dir / f"{stem}.onnx"
                tmp_json = tmp_dir / f"{stem}.onnx.json"

                # Download config first (tiny)
                json_url = dv.URL_FORMAT.format(extension=".onnx.json", **fmt_args)
                with urlopen(json_url, timeout=15) as resp, open(tmp_json, "wb") as out:
                    shutil.copyfileobj(resp, out)

                # Stream onnx model with progress
                onnx_url = dv.URL_FORMAT.format(extension=".onnx", **fmt_args)
                with urlopen(onnx_url, timeout=30) as resp, open(tmp_onnx, "wb") as out:
                    total = int(resp.headers.get("Content-Length") or 0)
                    downloaded = 0
                    while True:
                        if cancel_event and cancel_event.is_set():
                            raise InterruptedError("Download cancelled")
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        out.write(chunk)
                        downloaded += len(chunk)
                        if on_progress:
                            on_progress(downloaded, total)

                shutil.move(str(tmp_onnx), str(model_path))
                shutil.move(str(tmp_json), str(config_path))
                ReadAloudController._cached_piper_voices = []
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        return model_path

    @staticmethod
    def is_piper_model_downloaded(voice_id: str) -> bool:
        """Return True if the Piper .onnx and .onnx.json files exist locally."""
        if not voice_id:
            voice_id = "en_US-lessac-medium"
        candidate = Path(voice_id)
        if candidate.is_file() and candidate.with_suffix(".onnx.json").is_file():
            return True
        model_dir = Path.home() / ".accessible_book_reader" / "piper_models"
        onnx_p = model_dir / f"{voice_id}.onnx"
        json_p = model_dir / f"{voice_id}.onnx.json"
        return onnx_p.is_file() and json_p.is_file() and onnx_p.stat().st_size > 1_000_000

    @staticmethod
    def _ensure_piper_model(voice_id: str) -> Path:
        """Ensure a Piper model + config exist locally, using atomic download."""
        import shutil
        from piper.download_voices import download_voice

        candidate = Path(voice_id)
        if candidate.is_file() and candidate.with_suffix(".onnx.json").is_file():
            return candidate

        model_dir = Path.home() / ".accessible_book_reader" / "piper_models"
        model_dir.mkdir(parents=True, exist_ok=True)
        model_path = model_dir / f"{voice_id}.onnx"
        config_path = model_dir / f"{voice_id}.onnx.json"

        with ReadAloudController._piper_dl_lock:
            if model_path.is_file() and config_path.is_file() and model_path.stat().st_size > 1_000_000:
                return model_path

            # Remove any incomplete/corrupt partial files before downloading
            for p in (model_path, config_path):
                if p.exists():
                    p.unlink(missing_ok=True)

            tmp_dir = model_dir / ".tmp_dl"
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            tmp_dir.mkdir(parents=True, exist_ok=True)
            try:
                download_voice(voice_id, tmp_dir)
                tmp_onnx = tmp_dir / f"{voice_id}.onnx"
                tmp_json = tmp_dir / f"{voice_id}.onnx.json"
                if not tmp_onnx.is_file() or not tmp_json.is_file():
                    raise FileNotFoundError(f"Piper model download incomplete for {voice_id}")
                shutil.move(str(tmp_onnx), str(model_path))
                shutil.move(str(tmp_json), str(config_path))
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        return model_path

    def _play_audio_bytes(self, audio_bytes: bytes) -> None:
        """Play WAV/MP3 bytes directly from RAM using Rust rodio sink (or pygame fallback)."""
        if not audio_bytes:
            return
        with ReadAloudController._mixer_lock:
            if self._stop_event.is_set():
                return
            if _rust_audio is not None and hasattr(_rust_audio, "rust_play_audio_bytes"):
                try:
                    _rust_audio.rust_play_audio_bytes(audio_bytes)
                    return
                except Exception:
                    pass

            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(io.BytesIO(audio_bytes))
            pygame.mixer.music.play()
            while not self._stop_event.is_set() and pygame.mixer.music.get_busy():
                time.sleep(0.03)
            if self._stop_event.is_set():
                pygame.mixer.music.stop()
            pygame.mixer.music.unload()

    def _synthesize_piper_bytes(self, text: str, post_ms: int = 300) -> bytes:
        """Synthesize Piper offline neural TTS into in-memory WAV bytes."""
        import wave
        from piper import PiperVoice, SynthesisConfig

        voice_id = self._voice_id or "en_US-lessac-medium"
        model_path = self._ensure_piper_model(voice_id)

        cache_key = str(model_path)
        voice = ReadAloudController._piper_voice_cache.get(cache_key)
        if voice is None:
            try:
                voice = PiperVoice.load(cache_key)
            except Exception:
                # Corrupt model on disk: delete and re-download once
                model_path.unlink(missing_ok=True)
                model_path.with_suffix(".onnx.json").unlink(missing_ok=True)
                model_path = self._ensure_piper_model(voice_id)
                voice = PiperVoice.load(str(model_path))
            ReadAloudController._piper_voice_cache[cache_key] = voice

        length_scale = max(0.5, min(2.0, 1.0 - (self._rate * 0.04)))
        syn_config = SynthesisConfig(length_scale=length_scale)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            voice.synthesize_wav(text, wav_file, syn_config=syn_config)
        wav_bytes = buf.getvalue()
        if _rust_audio is not None and hasattr(_rust_audio, "trim_wav_silence"):
            try:
                return _rust_audio.trim_wav_silence(wav_bytes, 160, post_ms)
            except Exception:
                pass
        return wav_bytes

    def _speak_with_piper(self, text: str) -> None:
        """Speak using Piper offline neural TTS (in-memory)."""
        self._play_audio_bytes(self._synthesize_piper_bytes(text))

    @staticmethod
    def list_kokoro_voices() -> list[VoiceInfo]:
        """List Kokoro-82M v1.0 offline neural voices."""
        if ReadAloudController._cached_kokoro_voices:
            return ReadAloudController._cached_kokoro_voices

        lang_prefix = {
            "a": ("English", "US"),
            "b": ("English", "UK"),
            "h": ("Hindi", "India"),
            "e": ("Spanish", "ES"),
            "f": ("French", "FR"),
            "i": ("Italian", "IT"),
            "p": ("Portuguese", "BR"),
            "j": ("Japanese", "JP"),
            "z": ("Chinese", "CN"),
        }
        curated = [
            "af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky", "af_nova", "af_jessica", "af_river",
            "am_adam", "am_michael", "am_fenrir", "am_eric", "am_liam", "am_onyx", "am_puck",
            "bf_emma", "bf_isabella", "bf_alice", "bf_lily",
            "bm_george", "bm_lewis", "bm_daniel", "bm_fable",
            "hf_alpha", "hf_beta", "hm_omega", "hm_psi",
            "ef_dora", "em_alex", "ff_siwis", "if_sara", "im_nicola", "pf_dora", "pm_alex",
            "jf_alpha", "jm_kumo", "zf_xiaobei", "zm_yunjian",
        ]
        # If voices-v1.0.bin is already downloaded, read exact voice keys from it
        model_dir = Path.home() / ".accessible_book_reader" / "kokoro_models"
        voices_bin = model_dir / "voices-v1.0.bin"
        voice_ids = curated
        if voices_bin.is_file():
            try:
                import numpy as np

                with np.load(str(voices_bin)) as data:
                    keys = sorted(list(data.files))
                    if keys:
                        voice_ids = keys
            except Exception:
                pass

        res: list[VoiceInfo] = []
        for vid in voice_ids:
            p0 = vid[0].lower() if vid else "a"
            g = "Female" if len(vid) > 1 and vid[1].lower() == "f" else "Male"
            lang, region = lang_prefix.get(p0, ("English", "US"))
            speaker = vid.split("_", 1)[1].replace("_", " ").title() if "_" in vid else vid
            res.append(VoiceInfo(vid, f"[Kokoro-82M] {speaker} ({lang} {region}, {g})", language=lang))

        res.sort(key=lambda x: (x.language, x.name))
        ReadAloudController._cached_kokoro_voices = res
        return res

    @staticmethod
    def get_kokoro_storage_summary() -> tuple[bool, int, Path]:
        """Return (is_downloaded, total_bytes, model_dir) for Kokoro-82M."""
        model_dir = Path.home() / ".accessible_book_reader" / "kokoro_models"
        onnx_p = model_dir / "kokoro-v1.0.int8.onnx"
        voices_p = model_dir / "voices-v1.0.bin"
        if onnx_p.is_file() and voices_p.is_file() and onnx_p.stat().st_size > 10_000_000:
            return True, onnx_p.stat().st_size + voices_p.stat().st_size, model_dir
        return False, 0, model_dir

    @staticmethod
    def delete_kokoro_models() -> bool:
        """Delete locally downloaded Kokoro v1.0 model and voices pack."""
        model_dir = Path.home() / ".accessible_book_reader" / "kokoro_models"
        deleted = False
        for fname in ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin"):
            p = model_dir / fname
            if p.exists():
                p.unlink(missing_ok=True)
                deleted = True
        with ReadAloudController._kokoro_lock:
            ReadAloudController._kokoro_instance = None
        ReadAloudController._cached_kokoro_voices = []
        return deleted

    @staticmethod
    def _ensure_kokoro_models(
        on_progress: Callable[[str, int, int], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> tuple[Path, Path]:
        """Ensure Kokoro v1.0 int8 ONNX + voices.bin exist locally (atomic download)."""
        import shutil
        from urllib.request import urlopen

        model_dir = Path.home() / ".accessible_book_reader" / "kokoro_models"
        model_dir.mkdir(parents=True, exist_ok=True)
        onnx_p = model_dir / "kokoro-v1.0.int8.onnx"
        voices_p = model_dir / "voices-v1.0.bin"

        with ReadAloudController._kokoro_lock:
            if onnx_p.is_file() and voices_p.is_file() and onnx_p.stat().st_size > 10_000_000:
                return onnx_p, voices_p

            tmp_dir = model_dir / ".tmp_dl"
            shutil.rmtree(tmp_dir, ignore_errors=True)
            tmp_dir.mkdir(parents=True, exist_ok=True)
            try:
                base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
                for fname, dst in [("kokoro-v1.0.int8.onnx", onnx_p), ("voices-v1.0.bin", voices_p)]:
                    if dst.is_file() and dst.stat().st_size > 1_000_000:
                        continue
                    with urlopen(f"{base}/{fname}", timeout=60) as resp, open(tmp_dir / fname, "wb") as out:
                        total = int(resp.headers.get("Content-Length") or 0)
                        done = 0
                        while True:
                            if cancel_event and cancel_event.is_set():
                                raise InterruptedError("Download cancelled")
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            out.write(chunk)
                            done += len(chunk)
                            if on_progress:
                                on_progress(fname, done, total)
                    shutil.move(str(tmp_dir / fname), str(dst))
                ReadAloudController._cached_kokoro_voices = []
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        return onnx_p, voices_p

    def _synthesize_kokoro_bytes(self, text: str, post_ms: int = 300) -> bytes:
        """Synthesize Kokoro-82M offline neural TTS into in-memory WAV bytes."""
        import wave
        import numpy as np
        from kokoro_onnx import Kokoro

        onnx_p, voices_p = self._ensure_kokoro_models()
        with ReadAloudController._kokoro_lock:
            if ReadAloudController._kokoro_instance is None:
                ReadAloudController._kokoro_instance = Kokoro(str(onnx_p), str(voices_p))
            kokoro = ReadAloudController._kokoro_instance

        voice = self._voice_id or "af_heart"
        lang_map = {
            "a": "en-us",
            "b": "en-gb",
            "h": "hi",
            "e": "es",
            "f": "fr-fr",
            "i": "it",
            "p": "pt-br",
            "j": "ja",
            "z": "cmn",
        }
        lang = lang_map.get(voice[0].lower() if voice else "a", "en-us")
        speed = max(0.5, min(2.0, 0.94 + (self._rate * 0.05)))

        audio, sample_rate = kokoro.create(
            text,
            voice=voice,
            speed=speed,
            lang=lang,
            sentence_pause=0.40,
            clause_pause=0.18,
        )
        if _rust_audio is not None and hasattr(_rust_audio, "float32_to_trimmed_wav"):
            try:
                f32_bytes = np.asarray(audio, dtype=np.float32).tobytes()
                return _rust_audio.float32_to_trimmed_wav(f32_bytes, int(sample_rate), 0.0005, post_ms)
            except Exception:
                pass

        pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(int(sample_rate))
            wf.writeframes(pcm.tobytes())
        return buf.getvalue()

    def _speak_with_kokoro(self, text: str) -> None:
        """Speak using Kokoro-82M offline neural TTS (in-memory)."""
        self._play_audio_bytes(self._synthesize_kokoro_bytes(text))

    def _synthesize_edge_bytes(self, text: str) -> bytes:
        """Synthesize Microsoft Edge Neural TTS into in-memory MP3 bytes."""
        import edge_tts

        voice = self._voice_id or "en-US-AriaNeural"
        rate_pct = int(self._rate * 10)
        rate_str = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"

        async def _collect() -> bytes:
            buf = io.BytesIO()
            communicate = edge_tts.Communicate(text, voice, rate=rate_str)
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            return buf.getvalue()

        return asyncio.run(_collect())

    def _speak_with_edge(self, text: str) -> None:
        """Speak using Microsoft Edge Neural TTS (in-memory)."""
        self._play_audio_bytes(self._synthesize_edge_bytes(text))

    @staticmethod
    def _normalize_tts_text(text: str) -> str:
        """Normalize typographic punctuation so TTS narrators pause and pronounce naturally."""
        cleaned = (
            text.replace("\u2019", "'")
            .replace("\u2018", "'")
            .replace("\u201c", '"')
            .replace("\u201d", '"')
            .replace("\u2014", ", ")  # em-dash -> natural clause pause
            .replace("\u2013", ", ")  # en-dash -> natural clause pause
            .replace("\u2026", "...")
        )
        return " ".join(cleaned.split())

    def _synthesize_audio_bytes(self, text: str, engine: str | None = None, post_ms: int = 300) -> bytes:
        eng = (engine or self._engine).lower()
        norm_text = self._normalize_tts_text(text)
        if eng == "kokoro":
            return self._synthesize_kokoro_bytes(norm_text, post_ms=post_ms)
        if eng == "piper":
            return self._synthesize_piper_bytes(norm_text, post_ms=post_ms)
        if eng == "edge":
            return self._synthesize_edge_bytes(norm_text)
        raise ValueError(f"Engine '{eng}' does not support byte synthesis")

    @staticmethod
    def list_nvda_voices() -> list[VoiceInfo]:
        """Virtual voice entry for direct Screen Reader (NVDA / JAWS) playback."""
        return [VoiceInfo("screen_reader", "Active Screen Reader Voice (NVDA / JAWS)", language="All")]

    def _speak_with_nvda(self, text: str, interrupt: bool = False) -> None:
        """Speak directly via active screen reader (NVDA / JAWS / Dolphin)."""
        clean = self._normalize_tts_text(text)
        if not self._announcer.say(clean, interrupt=interrupt):
            # If no active screen reader controller responded, fall back to SAPI5
            self._speak_with_sapi(clean)
            return
        # Estimate speech duration (~15 chars/sec adjusted by rate) so sentences don't flood the queue
        cps = max(8.0, min(40.0, 15.0 + (self._rate * 1.5)))
        wait_secs = max(0.45, len(clean) / cps)
        elapsed = 0.0
        while elapsed < wait_secs:
            if self._stop_event.is_set():
                self._announcer.silence()
                return
            time.sleep(0.05)
            elapsed += 0.05

    def _dispatch_speak(self, text: str, engine: str | None = None) -> None:
        eng = (engine or self._engine).lower()
        if eng == "edge":
            self._speak_with_edge(text)
        elif eng == "onecore":
            self._speak_with_sapi(text, is_onecore=True)
        elif eng == "piper":
            self._speak_with_piper(text)
        elif eng == "kokoro":
            self._speak_with_kokoro(text)
        elif eng == "nvda":
            self._speak_with_nvda(text)
        elif eng == "espeak":
            self._speak_with_espeak(text)
        else:
            self._speak_with_sapi(text)

    def _run_prefetch_loop(self) -> None:
        """Producer-consumer look-ahead prefetch loop for zero-gap AI narrator playback."""
        audio_queue: queue.Queue[tuple[int, SentenceSpan, bytes | None] | None] = queue.Queue(maxsize=2)
        start_idx = self._index
        sentences = self._sentences
        source_text = self._source_text

        def _calc_post_ms(idx: int, span: SentenceSpan) -> int:
            if source_text and idx + 1 < len(sentences):
                gap = source_text[span.end : sentences[idx + 1].start]
                if "\n" in gap:
                    return 650  # Paragraph / line break: calm reflective beat
            stripped = span.text.rstrip("\"'”’)] ")
            if stripped.endswith(("?", "!")):
                return 420
            return 300

        def producer() -> None:
            try:
                for idx in range(start_idx, len(sentences)):
                    if self._stop_event.is_set():
                        break
                    span = sentences[idx]
                    post_ms = _calc_post_ms(idx, span)
                    audio_bytes: bytes | None = None
                    try:
                        if post_ms != 300:
                            audio_bytes = self._synthesize_audio_bytes(span.text, post_ms=post_ms)
                        else:
                            audio_bytes = self._synthesize_audio_bytes(span.text)
                    except Exception:
                        audio_bytes = None
                    while not self._stop_event.is_set():
                        try:
                            audio_queue.put((idx, span, audio_bytes), timeout=0.1)
                            break
                        except queue.Full:
                            continue
            finally:
                while not self._stop_event.is_set():
                    try:
                        audio_queue.put(None, timeout=0.1)
                        break
                    except queue.Full:
                        continue

        prod_thread = threading.Thread(target=producer, daemon=True)
        prod_thread.start()

        while not self._stop_event.is_set():
            try:
                item = audio_queue.get(timeout=0.1)
            except queue.Empty:
                if not prod_thread.is_alive():
                    break
                continue
            if item is None:
                break
            idx, span, audio_bytes = item
            self._index = idx
            if self.on_sentence:
                self.on_sentence(idx, span)
            if audio_bytes:
                self._play_audio_bytes(audio_bytes)
            else:
                try:
                    self._speak_with_sapi(span.text)
                except Exception:
                    break
            if self._stop_event.is_set():
                return

        self.is_playing = False
        if not self._stop_event.is_set() and self.on_finished:
            self.on_finished()

    def _run_loop(self) -> None:
        if self._engine.lower() in ("kokoro", "piper", "edge"):
            self._run_prefetch_loop()
            return

        while not self._stop_event.is_set() and self._index < len(self._sentences):
            span = self._sentences[self._index]
            if self.on_sentence:
                self.on_sentence(self._index, span)
            try:
                self._dispatch_speak(span.text)
            except Exception:
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
