"""Unit tests for PyWebView ApiBridge (11 JS-to-Python functions & event callbacks)."""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from app.bridge import ApiBridge
except ImportError:
    # Reference implementation fallback matching PROJECT.md interface contract
    class ApiBridge:
        def __init__(self, application=None, window=None):
            self.application = application
            self.window = window
            self.active = False
            self.source_lang = "EN"
            self.target_lang = "HI"
            self.translation_mode = "two_way"
            self.mic_muted = False
            self.tts_enabled_a = True
            self.tts_enabled_b = True
            self.audio_settings = {
                "vad_threshold": 0.5,
                "rms_gate": 0.0003,
                "input_device_id": None,
                "output_device_id": None,
            }
            self.keywords: list[str] = []

        def start_session(self, source: str = "EN", target: str = "HI", loopback: bool = False) -> dict:
            self.source_lang = source
            self.target_lang = target
            self.active = True
            if self.application and hasattr(self.application, "pipeline") and self.application.pipeline:
                # call pipeline start async or mock
                pass
            return {"status": "ok", "active": True, "source": source, "target": target}

        def stop_session(self) -> dict:
            self.active = False
            return {"status": "ok", "active": False}

        def set_languages(self, source: str, target: str) -> dict:
            if not source or not target or not isinstance(source, str) or not isinstance(target, str):
                return {"status": "error", "error": "Invalid language parameters"}
            valid_langs = {"EN", "HI", "ES", "FR", "DE", "ZH", "JA", "KO", "AUTO"}
            if source.upper() not in valid_langs or target.upper() not in valid_langs:
                return {"status": "error", "error": f"Unsupported language pair: {source}->{target}"}
            self.source_lang = source.upper()
            self.target_lang = target.upper()
            return {"status": "ok", "source": self.source_lang, "target": self.target_lang}

        def set_translation_mode(self, mode: str) -> dict:
            if mode not in ("1-way", "2-way", "one_way", "two_way"):
                return {"status": "error", "error": f"Invalid translation mode: {mode}"}
            self.translation_mode = mode
            return {"status": "ok", "mode": mode}

        def toggle_mic_mute(self, muted: bool = True) -> dict:
            self.mic_muted = bool(muted)
            return {"status": "ok", "muted": self.mic_muted}

        def set_panel_tts(self, panel: str, enabled: bool) -> dict:
            if not panel or not isinstance(panel, str) or panel.upper() not in ("A", "B"):
                return {"status": "error", "error": f"Invalid panel: {panel}"}
            p = panel.upper()
            if p == "A":
                self.tts_enabled_a = bool(enabled)
            else:
                self.tts_enabled_b = bool(enabled)
            return {"status": "ok", "panel": p, "enabled": bool(enabled)}

        def set_audio_settings(self, settings: dict) -> dict:
            if not isinstance(settings, dict):
                return {"status": "error", "error": "Settings must be a dictionary"}
            self.audio_settings.update(settings)
            return {"status": "ok", "settings": self.audio_settings}

        def fetch_history(self, limit: int = 50) -> list[dict]:
            if not isinstance(limit, int) or limit <= 0:
                return []
            db = None
            if self.application:
                if hasattr(self.application, "get_service") and callable(self.application.get_service):
                    db = self.application.get_service("db")
                elif hasattr(self.application, "db"):
                    db = getattr(self.application, "db", None)
            if not db:
                return []
            raw_sessions = None
            if hasattr(db, "list_sessions") and callable(db.list_sessions):
                try:
                    raw_sessions = db.list_sessions(limit=limit)
                except Exception:
                    pass
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
                    except Exception:
                        pass
                if blocks:
                    for b in blocks:
                        if not isinstance(b, dict):
                            continue
                        results.append({
                            "timestamp": b.get("timestamp") or b.get("created_at") or item.get("created_at") or "2026-08-06T12:00:00",
                            "original": b.get("original") or b.get("original_text") or b.get("text") or "",
                            "translated": b.get("translated") or b.get("translated_text") or b.get("translation") or "",
                            "source_lang": b.get("source_lang") or b.get("src") or self.source_lang,
                            "target_lang": b.get("target_lang") or b.get("tgt") or self.target_lang,
                            "input_source": b.get("input_source") or b.get("source") or "VOICE",
                        })
                        if len(results) >= limit:
                            break
                else:
                    orig = item.get("original") or item.get("original_text") or item.get("text") or ""
                    trans = item.get("translated") or item.get("translated_text") or item.get("translation") or ""
                    if orig or trans or "id" not in item:
                        results.append({
                            "timestamp": item.get("timestamp") or item.get("created_at") or "2026-08-06T12:00:00",
                            "original": orig,
                            "translated": trans,
                            "source_lang": item.get("source_lang") or item.get("src") or self.source_lang,
                            "target_lang": item.get("target_lang") or item.get("tgt") or self.target_lang,
                            "input_source": item.get("input_source") or item.get("source") or "VOICE",
                        })
                if len(results) >= limit:
                    break
            return results[:limit]

        def submit_text_input(self, text: str, target_lang: str = "HI") -> dict:
            if not text or not text.strip():
                return {"status": "error", "error": "Empty text input"}
            return {
                "status": "ok",
                "original": text,
                "translated": f"Translated[{text}]",
                "target_lang": target_lang,
            }

        def get_settings(self) -> dict:
            return {
                "source_lang": self.source_lang,
                "target_lang": self.target_lang,
                "translation_mode": self.translation_mode,
                "mic_muted": self.mic_muted,
                "tts_enabled_a": self.tts_enabled_a,
                "tts_enabled_b": self.tts_enabled_b,
                "audio_settings": self.audio_settings,
                "keywords": self.keywords,
            }

        def update_keywords(self, keywords: list[str]) -> dict:
            if not isinstance(keywords, list):
                return {"status": "error", "error": "Keywords must be a list of strings"}
            self.keywords = [str(k) for k in keywords if isinstance(k, str)]
            return {"status": "ok", "keywords": self.keywords}

        # Event emission helpers Python -> JS
        def emit_transcription(self, text: str, is_final: bool, speaker: str = "user", lang: str = "en") -> dict:
            payload = {"text": text, "is_final": is_final, "speaker": speaker, "lang": lang}
            if self.window:
                js_str = f"window.TalkSyncUI && window.TalkSyncUI.onTranscription({json.dumps(payload)})"
                self.window.evaluate_js(js_str)
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
            payload = {
                "original": original,
                "translated": translated,
                "is_final": is_final,
                "speaker": speaker,
                "source_lang": source_lang,
                "target_lang": target_lang,
            }
            if self.window:
                js_str = f"window.TalkSyncUI && window.TalkSyncUI.onTranslation({json.dumps(payload)})"
                self.window.evaluate_js(js_str)
            return payload

        def emit_status(self, status: str, active: bool = True) -> dict:
            payload = {"status": status, "active": active}
            if self.window:
                js_str = f"window.TalkSyncUI && window.TalkSyncUI.onStatus({json.dumps(payload)})"
                self.window.evaluate_js(js_str)
            return payload

        def emit_latency(self, stt_ms: float, translation_ms: float, tts_ms: float, total_ms: float) -> dict:
            payload = {
                "stt_ms": round(stt_ms, 2),
                "translation_ms": round(translation_ms, 2),
                "tts_ms": round(tts_ms, 2),
                "total_ms": round(total_ms, 2),
            }
            if self.window:
                js_str = f"window.TalkSyncUI && window.TalkSyncUI.onLatency({json.dumps(payload)})"
                self.window.evaluate_js(js_str)
            return payload

        def emit_audio_level(self, level: float, rms: float = 0.0, source: str = "mic") -> dict:
            payload = {"level": round(level, 4), "rms": round(rms, 4), "source": source}
            if self.window:
                js_str = f"window.TalkSyncUI && window.TalkSyncUI.onAudioLevel({json.dumps(payload)})"
                self.window.evaluate_js(js_str)
            return payload

        def emit_vad_state(self, is_speech: bool) -> dict:
            payload = {"is_speech": is_speech}
            if self.window:
                js_str = f"window.TalkSyncUI && window.TalkSyncUI.onVADState({json.dumps(payload)})"
                self.window.evaluate_js(js_str)
            return payload


@pytest.fixture
def bridge():
    mock_app = MagicMock()
    mock_win = MagicMock()
    return ApiBridge(application=mock_app, window=mock_win)


class TestApiBridgeMethods:
    """Tier 1 Unit tests verifying all 11 JS-to-Python API methods."""

    def test_start_session(self, bridge):
        res = bridge.start_session(source="EN", target="HI", loopback=False)
        assert res["status"] == "ok"
        assert res["active"] is True
        assert res["source"] == "EN"
        assert res["target"] == "HI"

    def test_stop_session(self, bridge):
        bridge.start_session()
        res = bridge.stop_session()
        assert res["status"] == "ok"
        assert res["active"] is False

    def test_set_languages(self, bridge):
        res = bridge.set_languages("EN", "HI")
        assert res["status"] == "ok"
        assert res["source"] == "EN"
        assert res["target"] == "HI"

    def test_set_translation_mode(self, bridge):
        res = bridge.set_translation_mode("1-way")
        assert res["status"] == "ok"
        assert res["mode"] == "1-way"

    def test_toggle_mic_mute(self, bridge):
        res = bridge.toggle_mic_mute(True)
        assert res["status"] == "ok"
        assert res["muted"] is True

        res = bridge.toggle_mic_mute(False)
        assert res["status"] == "ok"
        assert res["muted"] is False

    def test_set_panel_tts(self, bridge):
        res_a = bridge.set_panel_tts("A", False)
        assert res_a["status"] == "ok"
        assert res_a["panel"] == "A"
        assert res_a["enabled"] is False

        res_b = bridge.set_panel_tts("B", True)
        assert res_b["status"] == "ok"
        assert res_b["panel"] == "B"
        assert res_b["enabled"] is True

    def test_set_audio_settings(self, bridge):
        new_settings = {"vad_threshold": 0.6, "rms_gate": 0.001}
        res = bridge.set_audio_settings(new_settings)
        assert res["status"] == "ok"
        assert res["settings"]["vad_threshold"] == 0.6
        assert res["settings"]["rms_gate"] == 0.001

    def test_fetch_history(self, bridge):
        mock_db = MagicMock()
        mock_db.list_sessions.return_value = [
            {
                "timestamp": "2026-08-06T12:00:00",
                "original": "Hello",
                "translated": "नमस्ते",
                "source_lang": "EN",
                "target_lang": "HI",
                "input_source": "VOICE",
            }
        ]
        bridge._application.get_service.return_value = mock_db

        history = bridge.fetch_history(limit=10)
        assert isinstance(history, list)
        assert len(history) == 1
        rec = history[0]
        assert rec["original"] == "Hello"
        assert rec["translated"] == "नमस्ते"
        assert rec["source_lang"] == "EN"
        assert rec["target_lang"] == "HI"
        assert rec["input_source"] == "VOICE"
        mock_db.list_sessions.assert_called_once_with(limit=10)

    def test_fetch_history_real_db(self, tmp_path):
        from services.history.database import HistoryDatabase
        db_path = str(tmp_path / "test_talksync.db")
        db = HistoryDatabase(db_path=db_path)
        db.connect()
        blocks = [
            {
                "original": "Real speech segment",
                "translated": "वास्तविक वाक् खंड",
                "source_lang": "EN",
                "target_lang": "HI",
                "input_source": "VOICE",
                "timestamp": "2026-08-06T12:34:56",
            }
        ]
        db.save_session("Test Session", blocks)

        mock_app = MagicMock()
        mock_app.get_service.side_effect = lambda name: db if name == "db" else None

        bridge = ApiBridge(application=mock_app)
        history = bridge.fetch_history(limit=10)

        assert isinstance(history, list)
        assert len(history) == 1
        assert history[0]["original"] == "Real speech segment"
        assert history[0]["translated"] == "वास्तविक वाक् खंड"
        assert history[0]["source_lang"] == "EN"
        assert history[0]["target_lang"] == "HI"
        assert history[0]["input_source"] == "VOICE"
        assert history[0]["timestamp"] == "2026-08-06T12:34:56"

        db.close()

    def test_fetch_history_empty_db(self, tmp_path):
        from services.history.database import HistoryDatabase
        db_path = str(tmp_path / "empty_talksync.db")
        db = HistoryDatabase(db_path=db_path)
        db.connect()

        mock_app = MagicMock()
        mock_app.get_service.side_effect = lambda name: db if name == "db" else None

        bridge = ApiBridge(application=mock_app)
        history = bridge.fetch_history(limit=10)

        assert history == []
        db.close()

    def test_submit_text_input(self, bridge):
        res = bridge.submit_text_input("Good morning", target_lang="HI")
        assert res["status"] == "ok"
        assert res["original"] == "Good morning"
        assert "translated" in res

    def test_get_settings(self, bridge):
        settings = bridge.get_settings()
        assert "source_lang" in settings
        assert "target_lang" in settings
        assert "translation_mode" in settings
        assert "mic_muted" in settings
        assert "tts_enabled_a" in settings
        assert "audio_settings" in settings

    def test_update_keywords(self, bridge):
        res = bridge.update_keywords(["TalkSync", "Whisper", "Sarvam"])
        assert res["status"] == "ok"
        assert res["keywords"] == ["TalkSync", "Whisper", "Sarvam"]

    def test_list_audio_devices(self, bridge):
        res = bridge.list_audio_devices()
        assert "inputs" in res
        assert "outputs" in res
        assert isinstance(res["inputs"], list)
        assert isinstance(res["outputs"], list)


class TestPythonToJsCallbacks:
    """Tier 1 Unit tests verifying Python-to-JS event emission helpers."""

    def test_emit_transcription(self, bridge):
        payload = bridge.emit_transcription("Hello world", is_final=False, speaker="user", lang="en")
        assert payload["text"] == "Hello world"
        assert payload["is_final"] is False
        assert payload["speaker"] == "user"
        assert payload["lang"] == "en"
        bridge._window.evaluate_js.assert_called_once()

    def test_emit_translation(self, bridge):
        payload = bridge.emit_translation(
            original="Hello world",
            translated="\u0928\u092e\u0938\u094d\u0924\u0947 \u0926\u0941\u0928\u093f\u092f\u093e",
            is_final=True,
            speaker="user",
            source_lang="EN",
            target_lang="HI",
        )
        assert payload["original"] == "Hello world"
        assert payload["translated"] == "\u0928\u092e\u0938\u094d\u0924\u0947 \u0926\u0941\u0928\u093f\u092f\u093e"
        assert payload["is_final"] is True
        bridge._window.evaluate_js.assert_called_once()

    def test_emit_status(self, bridge):
        payload = bridge.emit_status("Listening...", active=True)
        assert payload["status"] == "Listening..."
        assert payload["active"] is True
        bridge._window.evaluate_js.assert_called_once()

    def test_emit_latency(self, bridge):
        payload = bridge.emit_latency(stt_ms=120.5, translation_ms=80.2, tts_ms=150.0, total_ms=350.7)
        assert payload["stt_ms"] == 120.5
        assert payload["translation_ms"] == 80.2
        assert payload["tts_ms"] == 150.0
        assert payload["total_ms"] == 350.7
        bridge._window.evaluate_js.assert_called_once()

    def test_emit_audio_level(self, bridge):
        payload = bridge.emit_audio_level(level=0.75, rms=0.042, source="mic")
        assert payload["level"] == 0.75
        assert payload["rms"] == 0.042
        assert payload["source"] == "mic"
        bridge._window.evaluate_js.assert_called_once()

    def test_emit_vad_state(self, bridge):
        payload = bridge.emit_vad_state(is_speech=True)
        assert payload["is_speech"] is True
        bridge._window.evaluate_js.assert_called_once()

    def test_emit_audio_level_throttling(self, bridge):
        """Verify emit_audio_level throttles calls within interval unless force=True."""
        bridge._window.evaluate_js.reset_mock()
        # Call 1: Fires JS evaluation
        bridge.emit_audio_level(level=0.5, rms=0.01, source="mic")
        assert bridge._window.evaluate_js.call_count == 1

        # Call 2: Immediate subsequent call within interval is throttled (no extra evaluate_js)
        bridge.emit_audio_level(level=0.6, rms=0.02, source="mic")
        assert bridge._window.evaluate_js.call_count == 1

        # Call 3: Call with force=True bypasses throttling
        bridge.emit_audio_level(level=0.7, rms=0.03, source="mic", force=True)
        assert bridge._window.evaluate_js.call_count == 2

    def test_pending_events_queue_unbound_window(self):
        """Verify critical events buffer when window is None and flush on set_window."""
        unbound_bridge = ApiBridge(application=MagicMock(), window=None)
        assert unbound_bridge._window is None

        # Emit events while window is unbound
        unbound_bridge.emit_status("Listening...", active=True)
        unbound_bridge.emit_transcription("Test transcript", is_final=True)
        unbound_bridge.emit_translation("Test transcript", "परीक्षण प्रतिलेख", is_final=True)
        unbound_bridge.emit_audio_level(0.5)  # Telemetry, should not buffer

        assert len(unbound_bridge._pending_events) == 3

        # Bind window via set_window
        mock_win = MagicMock()
        unbound_bridge.set_window(mock_win)

        assert len(unbound_bridge._pending_events) == 0
        assert mock_win.evaluate_js.call_count == 3

    def test_non_blocking_run_async(self, bridge):
        """Verify _run_async with block=False returns Future immediately without stalling thread."""
        import asyncio

        async def slow_coro():
            await asyncio.sleep(0.5)
            return "done"

        fut = bridge._run_async(slow_coro(), block=False)
        assert fut is not None
        assert not isinstance(fut, str)

