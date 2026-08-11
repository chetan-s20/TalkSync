"""Integration tests for PyWebView ApiBridge and Pipeline bidirectional flow."""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import pytest_asyncio

from app.interfaces import AudioChunk, TranscriptionSegment, TranslationResult
from app.pipeline import Pipeline
from config.settings import Settings

try:
    from app.bridge import ApiBridge
except ImportError:
    from tests.unit.test_bridge_api import ApiBridge


@pytest.fixture
def mock_app_and_pipeline():
    settings = Settings(
        source_lang="EN",
        target_lang="HI",
        translation_mode="two_way",
    )
    mock_app = MagicMock()
    mock_app.settings = settings

    pipeline = MagicMock(spec=Pipeline)
    pipeline.running = False
    pipeline.start = AsyncMock()
    pipeline.stop = AsyncMock()
    pipeline.on_transcription = None
    pipeline.on_translation = None
    pipeline.on_status = None
    pipeline.on_latency = None
    pipeline.on_audio_level = None

    mock_app.pipeline = pipeline
    mock_app.build_pipeline.return_value = pipeline

    window = MagicMock()
    window.evaluate_js = MagicMock()

    bridge = ApiBridge(application=mock_app, window=window)
    return {"app": mock_app, "pipeline": pipeline, "window": window, "bridge": bridge}


class TestWebviewPipelineBridgeIntegration:
    """Tier 3 Integration tests verifying end-to-end PyWebView bridge and Pipeline orchestration."""

    def test_session_lifecycle_integration(self, mock_app_and_pipeline):
        env = mock_app_and_pipeline
        bridge = env["bridge"]
        pipeline = env["pipeline"]

        # 1. Start session
        res_start = bridge.start_session("EN", "HI", loopback=True)
        assert res_start["status"] == "ok"
        assert res_start["active"] is True

        # 2. Wire callbacks
        pipeline.on_transcription = lambda seg: bridge.emit_transcription(seg.text, seg.is_final)
        pipeline.on_translation = lambda res: bridge.emit_translation(
            res.original_text, res.translated_text, res.is_final, source_lang=res.source_lang, target_lang=res.target_lang
        )
        pipeline.on_status = lambda msg, active: bridge.emit_status(msg, active)
        pipeline.on_audio_level = lambda lvl: bridge.emit_audio_level(lvl)

        # 3. Simulate Pipeline firing status callback
        pipeline.on_status("Listening...", True)
        env["window"].evaluate_js.assert_called()

        # 4. Simulate Pipeline firing partial translation callback
        trans_res = TranslationResult(
            original_text="Hello friend",
            translated_text="\u0928\u092e\u0938\u094d\u0924\u0947 \u092e\u093f\u0924\u094d\u0930",
            source_lang="EN",
            target_lang="HI",
            is_final=False,
            input_source="VOICE",
        )
        pipeline.on_translation(trans_res)

        # Verify JavaScript invocation
        call_args = env["window"].evaluate_js.call_args_list
        js_calls = [arg[0][0] for arg in call_args]
        assert any("onTranslation" in js for js in js_calls)

        # 5. Stop session
        res_stop = bridge.stop_session()
        assert res_stop["status"] == "ok"
        assert res_stop["active"] is False

    def test_language_and_mode_switching_integration(self, mock_app_and_pipeline):
        env = mock_app_and_pipeline
        bridge = env["bridge"]

        # Change language
        res_lang = bridge.set_languages("HI", "EN")
        assert res_lang["status"] == "ok"
        assert bridge.source_lang == "HI"
        assert bridge.target_lang == "EN"

        # Change mode
        res_mode = bridge.set_translation_mode("1-way")
        assert res_mode["status"] == "ok"
        assert bridge.translation_mode == "1-way"

    def test_mute_toggle_integration(self, mock_app_and_pipeline):
        env = mock_app_and_pipeline
        bridge = env["bridge"]

        res_mute = bridge.toggle_mic_mute(True)
        assert res_mute["status"] == "ok"
        assert bridge.mic_muted is True

        res_unmute = bridge.toggle_mic_mute(False)
        assert res_unmute["status"] == "ok"
        assert bridge.mic_muted is False
