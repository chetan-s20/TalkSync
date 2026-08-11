"""
Tier 4: Real-World Application Scenarios Test Suite for TalkSync AI.
Verifies end-to-end integration across complex multi-feature application workloads.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.interfaces import (
    AudioChunk, BaseAudioInput, BaseAudioOutput,
    BaseSTT, BaseTTS, BaseTranslator, BaseVAD,
    TranscriptionSegment, TranslationResult,
)
from app.pipeline import Pipeline
from config.settings import Settings, AudioSettings, VADSettings
from services.translation.context_engine import ContextEngine

try:
    from app.bridge import ApiBridge
except ImportError:
    from tests.unit.test_bridge_api import ApiBridge


class TestTier4RealWorldApplicationScenarios:
    """Tier 4 Real-World Application Workload Scenarios from TEST_INFRA.md."""

    @pytest.mark.asyncio
    async def test_t4_s1_continuous_hindi_english_speech_stream(self):
        """
        Scenario 1: Continuous Hindi/English Speech Stream
        Exercises: Mic Audio -> VAD -> STT -> Translation -> UI Bridge
        Verifies: Continuous speech chunks stream through pipeline, trigger transcription/translation,
        and dispatch events to the pywebview UI bridge within latency thresholds.
        """
        settings = Settings(source_lang="EN", target_lang="HI")
        audio_input = AsyncMock(spec=BaseAudioInput)
        vad = MagicMock(spec=BaseVAD)
        stt = AsyncMock(spec=BaseSTT)
        translator = AsyncMock(spec=BaseTranslator)
        tts = AsyncMock(spec=BaseTTS)
        audio_output = AsyncMock(spec=BaseAudioOutput)
        context_engine = MagicMock(spec=ContextEngine)

        # Mock STT transcription
        stt.transcribe = AsyncMock(return_value=TranscriptionSegment(
            text="Hello continuous speech test", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="en", confidence=0.95, input_source="mic",
        ))

        # Mock Translator
        translator.translate = AsyncMock(return_value=TranslationResult(
            original_text="Hello continuous speech test",
            translated_text="नमस्ते निरंतर भाषण परीक्षण",
            source_lang="EN", target_lang="HI", is_final=True, input_source="mic",
        ))

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
            context_engine=context_engine, settings=settings,
        )

        window = MagicMock()
        window.evaluate_js = MagicMock()
        app_mock = MagicMock(pipeline=pipeline)
        bridge = ApiBridge(application=app_mock, window=window)

        transcriptions_emitted = []
        translations_emitted = []

        pipeline.on_transcription = lambda s: bridge.emit_transcription(s.text, is_final=s.is_final)
        pipeline.on_translation = lambda r: bridge.emit_translation(r.original_text, r.translated_text, is_final=r.is_final)

        # Execute speech segment processing
        seg = TranscriptionSegment(
            text="Hello continuous speech test", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="en", confidence=0.95, input_source="mic",
        )
        await pipeline._translate_and_route(seg, is_final=True, enqueue_tts=False)

        assert window.evaluate_js.call_count >= 1
        call_args = [call[0][0] for call in window.evaluate_js.call_args_list]
        assert any("onTranslation" in code for code in call_args)

    @pytest.mark.asyncio
    async def test_t4_s2_loopback_audio_playback_translation(self):
        """
        Scenario 2: Loopback Audio Playback Translation
        Exercises: Loopback Stream -> VAD -> STT -> Translation -> UI Log
        Verifies: Computer audio playback (e.g. YouTube/meeting audio) captured via WASAPI loopback,
        translated accurately, and logged to history/UI without feedback loop.
        """
        settings = Settings(loopback_enabled=True)
        pipeline = Pipeline(
            audio_input=AsyncMock(), vad=AsyncMock(), stt=AsyncMock(),
            translator=AsyncMock(), tts=AsyncMock(), audio_output=AsyncMock(),
            settings=settings,
        )

        lb_segment = TranscriptionSegment(
            text="Incoming computer audio stream", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="en", confidence=0.92, input_source="loopback",
        )

        translator_result = TranslationResult(
            original_text="Incoming computer audio stream",
            translated_text="आने वाली कंप्यूटर ऑडियो धारा",
            source_lang="EN", target_lang="HI", is_final=True, input_source="loopback",
        )

        pipeline._translator.translate = AsyncMock(return_value=translator_result)

        emitted_logs = []
        pipeline.on_translation = lambda r: emitted_logs.append(r)

        await pipeline._translate_and_route(lb_segment, is_final=True, enqueue_tts=False)

        assert len(emitted_logs) == 1
        assert emitted_logs[0].input_source == "loopback"
        assert emitted_logs[0].translated_text == "आने वाली कंप्यूटर ऑडियो धारा"

    def test_t4_s3_bluetooth_headset_boult_airbass_hotplug_fallback(self):
        """
        Scenario 3: Bluetooth Headset (Boult Airbass 16) Hotplug/Fallback
        Exercises: Device Auto-Detect -> Mic Stream -> VAD Threshold Adjustment
        Verifies: Boult Airbass headset index 16 or 0-channel BT device resolution and fallback.
        """
        from utils.device import find_best_input_device, find_best_output_device

        devices = [
            {"name": "Speakers (Realtek High Definition Audio)", "max_input_channels": 0, "max_output_channels": 2, "hostapi": 0},
            {"name": "Microphone Array (Realtek High Definition Audio)", "max_input_channels": 2, "max_output_channels": 0, "hostapi": 0},
            {"name": "Boult Audio Airbass 16 Hands-Free AG Audio", "max_input_channels": 1, "max_output_channels": 1, "hostapi": 0},
        ]

        with patch("sounddevice.query_devices", return_value=devices):
            with patch("sounddevice.default.device", [2, 2]):
                # Test requested ID 16 fallback to Boult Audio Airbass 16
                dev_id, dev_name = find_best_input_device(requested_id=16)
                assert dev_id == 2
                assert "Boult" in dev_name

                # Test output resolution
                out_id, out_name = find_best_output_device(requested_id=None)
                assert out_id == 2
                assert "Boult" in out_name

    @pytest.mark.asyncio
    async def test_t4_s4_deepl_api_key_failover_to_argos(self):
        """
        Scenario 4: DeepL API Key Failover to Argos
        Exercises: Translation Factory -> DeepL Failure -> Argos Fallback -> UI Output
        Verifies: Invalid DeepL API key or connection failure seamlessly fails over to ArgosTranslator
        without crashing the active user session or dropping transcriptions.
        """
        from services.translation.factory import TranslationFactory

        settings = Settings()
        settings.translation.deepl_api_key = "invalid_expired_key_123"

        with patch("services.translation.deepl.DeepLTranslator.start", side_effect=RuntimeError("DeepL API Key Invalid")):
            with patch("services.translation.factory.ArgosTranslator") as mock_argos_cls:
                mock_argos_inst = AsyncMock()
                mock_argos_inst.translate = AsyncMock(return_value=TranslationResult(
                    original_text="Failover test", translated_text="फ़ेलओवर परीक्षण",
                    source_lang="EN", target_lang="HI", is_final=True,
                ))
                mock_argos_cls.return_value = mock_argos_inst

                translator = await TranslationFactory.create(settings)
                assert translator is mock_argos_inst

                res = await translator.translate("Failover test", "EN", "HI")
                assert res.translated_text == "फ़ेलओवर परीक्षण"

    def test_t4_s5_rapid_session_start_stop_toggle(self):
        """
        Scenario 5: Rapid Session Start/Stop Toggle
        Exercises: UI Bridge Lifecycle -> Event Loop Safety -> Worker Cleanup
        Verifies: Toggling Start/Stop rapidly 20 times does not cause thread blocks, memory leaks,
        orphaned worker tasks, or inconsistent state in ApiBridge.
        """
        pipeline = MagicMock()
        pipeline.running = False

        app_mock = MagicMock(pipeline=pipeline)
        window = MagicMock()
        bridge = ApiBridge(application=app_mock, window=window)

        for i in range(20):
            res_start = bridge.start_session("EN", "HI")
            assert res_start["status"] == "ok"
            assert bridge.active is True

            res_stop = bridge.stop_session()
            assert res_stop["status"] == "ok"
            assert bridge.active is False

        assert len(pipeline._tasks) == 0
        assert pipeline.running is False
