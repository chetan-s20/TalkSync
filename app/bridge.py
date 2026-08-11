"""TalkSync AI — PyWebView JavaScript-to-Python IPC API Bridge.

Exposes 11 JS-to-Python API methods for pywebview frontend and dispatches
Python-to-JS event callbacks via window.evaluate_js().
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
import time
from typing import Any, Optional

from utils.logger import get_logger

logger = get_logger("bridge")

VALID_LANGUAGES = {"EN", "HI", "ES", "FR", "DE", "ZH", "JA", "KO", "AUTO"}
VALID_MODES = ("1-way", "2-way", "one_way", "two_way")


class ApiBridge:
    """IPC API Bridge connecting PyWebView frontend to backend Application and Pipeline."""

    def __init__(self, application: Any = None, window: Any = None):
        self._application = application
        self._window = window
        self.active: bool = False
        self.source_lang: str = "EN"
        self.target_lang: str = "HI"
        self.translation_mode: str = "two_way"
        self.mic_muted: bool = False
        self.tts_enabled_a: bool = True
        self.tts_enabled_b: bool = True
        self.audio_settings: dict[str, Any] = {
            "vad_threshold": 0.5,
            "rms_gate": 0.0003,
            "input_device_id": None,
            "output_device_id": None,
            "loopback_enabled": False,
            "virtual_mic_enabled": False,
        }
        self.keywords: list[str] = []
        self._pipeline: Any = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[Any] = None
        self._last_audio_level_time: float = 0.0
        self._pending_events: list[tuple[str, dict]] = []

        if self._application and hasattr(self._application, "settings") and self._application.settings:
            s = self._application.settings
            self.source_lang = getattr(s, "source_lang", "EN")
            self.target_lang = getattr(s, "target_lang", "HI")
            self.translation_mode = getattr(s, "translation_mode", "two_way")
            
            # Load Audio & VAD settings
            if hasattr(s, "vad") and s.vad:
                self.audio_settings["vad_threshold"] = getattr(s.vad, "threshold", 0.5)
            if hasattr(s, "stt") and s.stt:
                self.audio_settings["rms_gate"] = getattr(s.stt, "rms_gate_threshold", 0.0003)
            if hasattr(s, "audio") and s.audio:
                self.audio_settings["input_device_id"] = getattr(s.audio, "input_device_id", None)
                self.audio_settings["output_device_id"] = getattr(s.audio, "output_device_id", None)
                self.audio_settings["virtual_mic_enabled"] = getattr(s.audio, "virtual_mic_enabled", False)
            self.audio_settings["loopback_enabled"] = getattr(s, "loopback_enabled", False)

        if self._application and hasattr(self._application, "pipeline"):
            self._pipeline = self._application.pipeline

    def set_window(self, window: Any) -> None:
        """Bind or update the pywebview window instance and flush any queued pending event callbacks."""
        self._window = window
        if self._window and hasattr(self._window, "evaluate_js") and self._pending_events:
            logger.info(f"Flushing {len(self._pending_events)} pending event callbacks to pywebview")
            for cb_name, payload in self._pending_events:
                self._evaluate_js(cb_name, payload)
            self._pending_events.clear()

    def _persist_settings(self) -> None:
        """Persist active application settings object to models_config.json file."""
        if self._application and hasattr(self._application, "settings") and self._application.settings:
            try:
                from config.settings import get_default_config_path
                path = get_default_config_path()
                self._application.settings.to_json(str(path))
                logger.info(f"Successfully persisted settings to disk at: {path}")
            except Exception as e:
                logger.warning(f"Error persisting settings: {e}")

    # ------------------------------------------------------------------
    # JS-to-Python API Methods (11 functions)
    # ------------------------------------------------------------------

    def start_session(
        self,
        source: str = "EN",
        target: str = "HI",
        loopback: bool = False,
        text_mode: bool = False,
    ) -> dict:
        """Start translation session and pipeline workers."""
        self.source_lang = source
        self.target_lang = target
        self.active = True

        # Default to True for loopback unless explicitly turned off
        use_loopback = loopback if loopback else self.audio_settings.get("loopback_enabled", True)

        pipeline = self._pipeline
        if not pipeline and self._application:
            if hasattr(self._application, "pipeline") and self._application.pipeline:
                pipeline = self._application.pipeline
            elif hasattr(self._application, "build_pipeline"):
                pipeline = self._application.build_pipeline()

        if pipeline:
            self._pipeline = pipeline
            # Bind event callbacks
            pipeline.on_transcription = self.on_transcription
            pipeline.on_translation = self.on_translation
            pipeline.on_status = self.on_status
            pipeline.on_latency = self.on_latency
            pipeline.on_audio_level = self.on_audio_level
            if hasattr(pipeline, "on_vad_state"):
                pipeline.on_vad_state = self.on_vad_state

            if hasattr(pipeline, "start") and callable(pipeline.start):
                self._run_async(pipeline.start(source, target, loopback=use_loopback, text_mode=text_mode), block=False)

        return {"status": "ok", "active": True, "source": source, "target": target}

    def stop_session(self) -> dict:
        """Stop active session and pipeline gracefully."""
        self.active = False
        if self._pipeline and hasattr(self._pipeline, "stop") and callable(self._pipeline.stop):
            self._run_async(self._pipeline.stop(), block=False)
        return {"status": "ok", "active": False}

    def close(self) -> None:
        """Gracefully stop session without destroying the persistent event loop while tasks are active."""
        if self.active:
            self.stop_session()

    def set_languages(self, source: str, target: str) -> dict:
        """Update active translation language pair."""
        if not source or not target or not isinstance(source, str) or not isinstance(target, str):
            return {"status": "error", "error": "Invalid language parameters"}

        src_upper = source.upper()
        tgt_upper = target.upper()

        if src_upper not in VALID_LANGUAGES or tgt_upper not in VALID_LANGUAGES:
            return {"status": "error", "error": f"Unsupported language pair: {source}->{target}"}

        self.source_lang = src_upper
        self.target_lang = tgt_upper

        if self._pipeline:
            if hasattr(self._pipeline, "_source_lang"):
                self._pipeline._source_lang = src_upper
            if hasattr(self._pipeline, "_target_lang"):
                self._pipeline._target_lang = tgt_upper

        if self._application and hasattr(self._application, "settings") and self._application.settings:
            self._application.settings.source_lang = src_upper
            self._application.settings.target_lang = tgt_upper
            self._persist_settings()

        return {"status": "ok", "source": self.source_lang, "target": self.target_lang}

    def set_translation_mode(self, mode: str) -> dict:
        """Set translation mode ('1-way' / '2-way' or 'one_way' / 'two_way')."""
        if not mode or not isinstance(mode, str) or mode not in VALID_MODES:
            return {"status": "error", "error": f"Invalid translation mode: {mode}"}

        self.translation_mode = mode
        if self._pipeline and hasattr(self._pipeline, "_translation_mode"):
            self._pipeline._translation_mode = mode

        if self._application and hasattr(self._application, "settings") and self._application.settings:
            self._application.settings.translation_mode = mode
            self._persist_settings()

        return {"status": "ok", "mode": mode}

    def toggle_mic_mute(self, muted: bool = True) -> dict:
        """Toggle microphone mute status."""
        self.mic_muted = bool(muted)
        if self._pipeline and hasattr(self._pipeline, "_mic_muted"):
            self._pipeline._mic_muted = self.mic_muted
        return {"status": "ok", "muted": self.mic_muted}

    def set_panel_tts(self, panel: str, enabled: bool) -> dict:
        """Enable or disable TTS playback for Panel A or Panel B."""
        if not panel or not isinstance(panel, str) or panel.upper() not in ("A", "B"):
            return {"status": "error", "error": f"Invalid panel: {panel}"}

        p = panel.upper()
        enabled_bool = bool(enabled)
        if p == "A":
            self.tts_enabled_a = enabled_bool
            if self._pipeline and hasattr(self._pipeline, "tts_enabled_a"):
                self._pipeline.tts_enabled_a = enabled_bool
        else:
            self.tts_enabled_b = enabled_bool
            if self._pipeline and hasattr(self._pipeline, "tts_enabled_b"):
                self._pipeline.tts_enabled_b = enabled_bool

        return {"status": "ok", "panel": p, "enabled": enabled_bool}

    def set_audio_settings(self, settings: dict) -> dict:
        """Update VAD threshold, noise gate, or audio device selection."""
        if not isinstance(settings, dict):
            return {"status": "error", "error": "Settings must be a dictionary"}

        self.audio_settings.update(settings)
        if self._application and hasattr(self._application, "settings") and self._application.settings:
            for k, v in settings.items():
                if hasattr(self._application.settings, k):
                    setattr(self._application.settings, k, v)
            audio_obj = getattr(self._application.settings, "audio", None)
            if audio_obj:
                for k, v in settings.items():
                    if hasattr(audio_obj, k):
                        setattr(audio_obj, k, v)
            self._persist_settings()

        if self._pipeline and getattr(self._pipeline, "running", False):
            if "loopback_enabled" in settings:
                loop_val = bool(settings["loopback_enabled"])
                if hasattr(self._pipeline, "_audio_input") and self._pipeline._audio_input:
                    if loop_val and self._pipeline._audio_input._loopback_stream is None:
                        try:
                            self._run_async(self._pipeline._audio_input._start_loopback(
                                getattr(self._pipeline._audio_input.settings, "input_device_id", None),
                                capture_mic=True
                            ), block=False)
                            logger.info("Dynamically started WASAPI loopback capture on running pipeline")
                        except Exception as e:
                            logger.warning(f"Failed dynamically starting loopback on running pipeline: {e}")

        return {"status": "ok", "settings": self.audio_settings}

    def fetch_history(self, limit: int = 50) -> list[dict]:
        """Fetch past session transcript & translation history from SQLite DB."""
        if not isinstance(limit, int) or limit <= 0:
            return []

        db = None
        if self._application:
            if hasattr(self._application, "get_service") and callable(self._application.get_service):
                db = self._application.get_service("db")
            elif hasattr(self._application, "db"):
                db = getattr(self._application, "db", None)

        if not db:
            return []

        raw_sessions = None
        if hasattr(db, "list_sessions") and callable(db.list_sessions):
            try:
                raw_sessions = db.list_sessions(limit=limit)
            except Exception as err:
                logger.warning(f"Error calling db.list_sessions: {err}")

        if raw_sessions is None and hasattr(db, "get_all_sessions") and callable(db.get_all_sessions):
            try:
                raw_sessions = db.get_all_sessions()
            except Exception as err:
                logger.warning(f"Error calling db.get_all_sessions: {err}")

        if not isinstance(raw_sessions, list) or not raw_sessions:
            return []

        results: list[dict] = []

        for item in raw_sessions:
            if not isinstance(item, dict):
                continue

            blocks = []
            if "blocks" in item and isinstance(item["blocks"], list) and len(item["blocks"]) > 0:
                blocks = item["blocks"]
            elif "id" in item and hasattr(db, "get_session_segments") and callable(db.get_session_segments):
                try:
                    fetched = db.get_session_segments(item["id"])
                    if isinstance(fetched, list) and len(fetched) > 0:
                        blocks = fetched
                except Exception as err:
                    logger.warning(f"Error fetching session segments for id {item.get('id')}: {err}")
            elif "id" in item and hasattr(db, "load_session") and callable(db.load_session):
                try:
                    loaded = db.load_session(item["id"])
                    if loaded and isinstance(loaded.get("blocks"), list) and len(loaded["blocks"]) > 0:
                        blocks = loaded["blocks"]
                except Exception as err:
                    logger.warning(f"Error loading session for id {item.get('id')}: {err}")

            if blocks:
                for b in blocks:
                    if not isinstance(b, dict):
                        continue
                    mapped = {
                        "timestamp": b.get("timestamp") or b.get("created_at") or item.get("created_at") or datetime.now().isoformat(),
                        "original": b.get("original") or b.get("original_text") or b.get("text") or "",
                        "translated": b.get("translated") or b.get("translated_text") or b.get("translation") or "",
                        "source_lang": b.get("source_lang") or b.get("src") or self.source_lang,
                        "target_lang": b.get("target_lang") or b.get("tgt") or self.target_lang,
                        "input_source": b.get("input_source") or b.get("source") or "VOICE",
                    }
                    results.append(mapped)
                    if len(results) >= limit:
                        break
            else:
                original = item.get("original") or item.get("original_text") or item.get("text") or ""
                translated = item.get("translated") or item.get("translated_text") or item.get("translation") or ""
                if original or translated or "id" not in item:
                    mapped = {
                        "timestamp": item.get("timestamp") or item.get("created_at") or datetime.now().isoformat(),
                        "original": original,
                        "translated": translated,
                        "source_lang": item.get("source_lang") or item.get("src") or self.source_lang,
                        "target_lang": item.get("target_lang") or item.get("tgt") or self.target_lang,
                        "input_source": item.get("input_source") or item.get("source") or "VOICE",
                    }
                    results.append(mapped)

            if len(results) >= limit:
                break

        return results[:limit]

    def submit_text_input(self, text: str, target_lang: str = "HI") -> dict:
        """Submit text string for translation."""
        if not text or not isinstance(text, str) or not text.strip():
            return {"status": "error", "error": "Empty text input"}

        translated_str = f"Translated[{text}]"
        if self._application and hasattr(self._application, "get_service"):
            translator = self._application.get_service("translator")
            if translator and hasattr(translator, "translate"):
                try:
                    res = self._run_async(translator.translate(text, self.source_lang, target_lang), block=True)
                    if res and hasattr(res, "translated_text"):
                        translated_str = res.translated_text
                except Exception as err:
                    logger.warning(f"Text translation error: {err}")

        # Construct TranslationResult
        from app.interfaces import TranslationResult
        result = TranslationResult(
            original_text=text,
            translated_text=translated_str,
            source_lang=self.source_lang,
            target_lang=target_lang,
            is_final=True,
            input_source="KEYBOARD",
        )

        # Emit to JS frontend immediately to show in transcript card list
        try:
            self.on_translation(result)
        except Exception as emit_err:
            logger.warning(f"Error emitting keyboard translation callback: {emit_err}")

        # Apply side-effects if pipeline is active
        pipeline = self._pipeline
        if not pipeline and self._application and hasattr(self._application, "pipeline"):
            pipeline = self._application.pipeline

        if pipeline and getattr(pipeline, "running", False):
            # 1. Persist to DB session block
            if hasattr(pipeline, "_db_blocks") and pipeline._db_blocks is not None:
                from datetime import datetime
                pipeline._db_blocks.append({
                    "original": text,
                    "translated": translated_str,
                    "source_lang": self.source_lang,
                    "target_lang": target_lang,
                    "input_source": "KEYBOARD",
                    "timestamp": datetime.now().isoformat(),
                })
            # 2. Queue for TTS playback if enabled
            if hasattr(pipeline, "tts_enabled_a") and hasattr(pipeline, "tts_enabled_b"):
                tts_enabled = pipeline.tts_enabled_a if self.source_lang.upper() == "EN" else pipeline.tts_enabled_b
                if tts_enabled and hasattr(pipeline, "tts_queue") and pipeline.tts_queue:
                    try:
                        pipeline.tts_queue.put_nowait(result)
                    except Exception as tts_err:
                        logger.warning(f"Error queuing keyboard input for TTS: {tts_err}")

        return {
            "status": "ok",
            "original": text,
            "translated": translated_str,
            "translated_text": translated_str,
            "target_lang": target_lang,
        }

    def get_settings(self) -> dict:
        """Return active application configuration dictionary."""
        theme_val = "light"
        if self._application and hasattr(self._application, "settings") and self._application.settings:
            theme_val = getattr(self._application.settings, "theme", "light")
        return {
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "translation_mode": self.translation_mode,
            "mic_muted": self.mic_muted,
            "tts_enabled_a": self.tts_enabled_a,
            "tts_enabled_b": self.tts_enabled_b,
            "audio_settings": self.audio_settings,
            "keywords": self.keywords,
            "theme": theme_val,
        }

    def update_keywords(self, keywords: list[str]) -> dict:
        """Update domain dictionary keywords list."""
        if not isinstance(keywords, list):
            return {"status": "error", "error": "Keywords must be a list of strings"}

        self.keywords = [str(k) for k in keywords if isinstance(k, str)]
        if self._application and hasattr(self._application, "settings") and self._application.settings:
            self._application.settings.keywords = ", ".join(self.keywords)
            self._persist_settings()
        return {"status": "ok", "keywords": self.keywords}

    def list_audio_devices(self) -> dict:
        """Query host system and return lists of active input and output audio devices."""
        import sounddevice as sd
        inputs = []
        outputs = []
        try:
            devices = sd.query_devices()
            for idx, dev in enumerate(devices):
                name = dev.get("name", f"Device {idx}")
                if isinstance(name, bytes):
                    name = name.decode("utf-8", errors="replace")
                
                max_in = dev.get("max_input_channels", 0)
                max_out = dev.get("max_output_channels", 0)
                
                if max_in > 0:
                    inputs.append({"id": idx, "name": name, "channels": max_in})
                if max_out > 0:
                    outputs.append({"id": idx, "name": name, "channels": max_out})
        except Exception as e:
            logger.warning(f"Error querying audio devices: {e}")
        return {"inputs": inputs, "outputs": outputs}

    # ------------------------------------------------------------------
    # Python-to-JS Event Callbacks Emission Helpers
    # ------------------------------------------------------------------

    def emit_transcription(
        self,
        text: str,
        is_final: bool,
        speaker: str = "user",
        lang: str = "en",
    ) -> dict:
        """Emit onTranscription event to pywebview frontend."""
        payload = {
            "text": text,
            "is_final": is_final,
            "speaker": speaker,
            "lang": lang,
        }
        self._evaluate_js("onTranscription", payload)
        return payload

    def emit_translation(
        self,
        original: str,
        translated: str,
        is_final: bool,
        speaker: str = "user",
        source_lang: str = "EN",
        target_lang: str = "HI",
    ) -> dict:
        """Emit onTranslation event to pywebview frontend."""
        payload = {
            "original": original,
            "translated": translated,
            "original_text": original,
            "translated_text": translated,
            "is_final": is_final,
            "speaker": speaker,
            "source_lang": source_lang,
            "target_lang": target_lang,
        }
        self._evaluate_js("onTranslation", payload)
        return payload

    def emit_status(self, status: str, active: bool = True) -> dict:
        """Emit onStatus event to pywebview frontend."""
        payload = {"status": status, "active": active}
        self._evaluate_js("onStatus", payload)
        return payload

    def emit_latency(
        self,
        stt_ms: float,
        translation_ms: float,
        tts_ms: float,
        total_ms: float,
    ) -> dict:
        """Emit onLatency event to pywebview frontend."""
        payload = {
            "stt_ms": round(stt_ms, 2),
            "translation_ms": round(translation_ms, 2),
            "tts_ms": round(tts_ms, 2),
            "total_ms": round(total_ms, 2),
        }
        self._evaluate_js("onLatency", payload)
        return payload

    def emit_audio_level(self, level: float, rms: float = 0.0, source: str = "mic", force: bool = False) -> dict:
        """Emit onAudioLevel event to pywebview frontend (throttled to max 25 Hz / 40ms interval)."""
        payload = {
            "level": round(level, 4),
            "rms": round(rms, 4),
            "source": source,
        }
        now = time.time()
        if force or (now - self._last_audio_level_time >= 0.04):
            self._last_audio_level_time = now
            self._evaluate_js("onAudioLevel", payload)
        return payload

    def emit_vad_state(self, is_speech: bool) -> dict:
        """Emit onVADState event to pywebview frontend."""
        payload = {"is_speech": bool(is_speech)}
        self._evaluate_js("onVADState", payload)
        return payload

    # ------------------------------------------------------------------
    # Pipeline Callback Bindings
    # ------------------------------------------------------------------

    def on_transcription(self, data: Any) -> dict:
        """Callback handler bound to Pipeline.on_transcription."""
        if isinstance(data, dict):
            text = data.get("text", "")
            is_final = data.get("is_final", True)
            speaker = data.get("speaker", "user")
            lang = data.get("lang", data.get("language", "en"))
        else:
            text = getattr(data, "text", str(data))
            is_final = getattr(data, "is_final", True)
            speaker = getattr(data, "speaker", getattr(data, "input_source", "user"))
            lang = getattr(data, "language", getattr(data, "lang", "en"))

        return self.emit_transcription(text=text, is_final=is_final, speaker=speaker, lang=lang)

    def on_translation(self, data: Any) -> dict:
        """Callback handler bound to Pipeline.on_translation."""
        if isinstance(data, dict):
            original = data.get("original", data.get("original_text", ""))
            translated = data.get("translated", data.get("translated_text", ""))
            is_final = data.get("is_final", True)
            speaker = data.get("speaker", "user")
            source_lang = data.get("source_lang", "EN")
            target_lang = data.get("target_lang", "HI")
        else:
            original = getattr(data, "original_text", getattr(data, "original", ""))
            translated = getattr(data, "translated_text", getattr(data, "translated", ""))
            is_final = getattr(data, "is_final", True)
            speaker = getattr(data, "speaker", getattr(data, "input_source", "user"))
            source_lang = getattr(data, "source_lang", "EN")
            target_lang = getattr(data, "target_lang", "HI")

        return self.emit_translation(
            original=original,
            translated=translated,
            is_final=is_final,
            speaker=speaker,
            source_lang=source_lang,
            target_lang=target_lang,
        )

    def on_status(self, status_or_data: Any, active: bool = True) -> dict:
        """Callback handler bound to Pipeline.on_status."""
        if isinstance(status_or_data, dict):
            status = status_or_data.get("status", status_or_data.get("message", ""))
            act = status_or_data.get("active", active)
        else:
            status = str(status_or_data)
            act = active

        return self.emit_status(status=status, active=act)

    def on_latency(self, data: Any) -> dict:
        """Callback handler bound to Pipeline.on_latency."""
        if isinstance(data, dict):
            stt_ms = data.get("stt_ms", 0.0)
            translation_ms = data.get("translation_ms", 0.0)
            tts_ms = data.get("tts_ms", 0.0)
            total_ms = data.get("total_ms", 0.0)
            stages = data.get("stages")
            if isinstance(stages, list):
                for s in stages:
                    name = (s.get("name") or "").lower()
                    if "stt" in name and not stt_ms:
                        stt_ms = s.get("avg_ms", 0.0)
                    elif "trans" in name and not translation_ms:
                        translation_ms = s.get("avg_ms", 0.0)
                    elif "tts" in name and not tts_ms:
                        tts_ms = s.get("avg_ms", 0.0)
            if not total_ms:
                total_ms = stt_ms + translation_ms + tts_ms
        else:
            stt_ms = getattr(data, "stt_ms", 0.0)
            translation_ms = getattr(data, "translation_ms", 0.0)
            tts_ms = getattr(data, "tts_ms", 0.0)
            total_ms = getattr(data, "total_ms", stt_ms + translation_ms + tts_ms)

        return self.emit_latency(
            stt_ms=stt_ms,
            translation_ms=translation_ms,
            tts_ms=tts_ms,
            total_ms=total_ms,
        )

    def on_audio_level(self, data: Any) -> dict:
        """Callback handler bound to Pipeline.on_audio_level."""
        if isinstance(data, (float, int)):
            level = float(data)
            rms = 0.0
            source = "mic"
        elif isinstance(data, dict):
            level = data.get("level", 0.0)
            rms = data.get("rms", 0.0)
            source = data.get("source", "mic")
        else:
            level = getattr(data, "level", 0.0)
            rms = getattr(data, "rms", 0.0)
            source = getattr(data, "source", "mic")

        return self.emit_audio_level(level=level, rms=rms, source=source)

    def on_vad_state(self, data: Any) -> dict:
        """Callback handler bound to Pipeline.on_vad_state."""
        if isinstance(data, bool):
            is_speech = data
        elif isinstance(data, dict):
            is_speech = data.get("is_speech", False)
        else:
            is_speech = getattr(data, "is_speech", False)

        return self.emit_vad_state(is_speech=is_speech)

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _evaluate_js(self, callback_name: str, payload: dict) -> None:
        """Thread-safe evaluation of JavaScript event handler in pywebview."""
        if self._window and hasattr(self._window, "evaluate_js"):
            js_val = json.dumps(payload)
            js_str = f"window.TalkSyncUI && window.TalkSyncUI.{callback_name}({js_val})"
            try:
                self._window.evaluate_js(js_str)
            except Exception as err:
                logger.warning(f"Error evaluating JS callback '{callback_name}': {err}")
        else:
            # Queue critical state events when window is unbound before set_window completes
            if callback_name in ("onStatus", "onTranscription", "onTranslation"):
                if len(self._pending_events) < 50:
                    self._pending_events.append((callback_name, payload))

    def _get_or_create_loop(self) -> asyncio.AbstractEventLoop:
        """Get or start the persistent background event loop thread."""
        if self._loop is None or not self._loop.is_running():
            loop = asyncio.new_event_loop()
            self._loop = loop

            def run_loop(l: asyncio.AbstractEventLoop) -> None:
                asyncio.set_event_loop(l)
                l.run_forever()

            import threading
            t = threading.Thread(target=run_loop, args=(loop,), name="ApiBridge-EventLoop", daemon=True)
            t.start()
            self._loop_thread = t
        return self._loop

    def _run_async(self, coro_or_func: Any, block: bool = False) -> Any:
        """Execute a coroutine safely on the persistent background event loop thread."""
        if not asyncio.iscoroutine(coro_or_func):
            return coro_or_func

        try:
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None

            loop = self._get_or_create_loop()

            if running_loop is not None and running_loop is loop:
                return asyncio.create_task(coro_or_func)

            fut = asyncio.run_coroutine_threadsafe(coro_or_func, loop)
            if block:
                return fut.result(timeout=15.0)
            return fut
        except Exception as err:
            logger.warning(f"Async execution error: {err}")
            return None
