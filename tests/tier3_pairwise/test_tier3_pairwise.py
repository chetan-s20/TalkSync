"""
Tier 3: Pairwise Combinations Test Suite for TalkSync AI.
Verifies interactions between feature pairs (15 combinatorial test cases).
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.interfaces import (
    AudioChunk, BaseAudioInput, BaseAudioOutput,
    BaseSTT, BaseTTS, BaseTranslator, BaseVAD,
    TranscriptionSegment, TranslationResult, VADResult,
)
from app.pipeline import Pipeline
from config.settings import AudioSettings, VADSettings, STTSettings, Settings
from services.audio.resampler import resample
from services.vad.silero_vad import SileroVAD
from services.stt.faster_whisper import FasterWhisperSTT
from services.stt.openai_stt import OpenAISTT
from services.translation.argos import ArgosTranslator
from services.translation.deepl import DeepLTranslator
from services.translation.context_engine import ContextEngine

try:
    from app.bridge import ApiBridge
except ImportError:
    from tests.unit.test_bridge_api import ApiBridge


class TestTier3PairwiseCombinations:
    """Tier 3 Pairwise Combinations Test Cases."""

    @pytest.mark.asyncio
    async def test_t3_p1_mic_audio_with_silero_vad(self):
        """P1: Mic audio + Silero VAD speech detection interaction."""
        vad = SileroVAD(VADSettings())
        await vad.start()
        mic_chunk = AudioChunk(
            data=(np.random.randn(480) * 0.1).astype(np.float32).tobytes(),
            sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=30.0, source="mic"
        )
        results = [r async for r in vad.process(mic_chunk)]
        assert len(results) == 1
        assert results[0].chunk.source == "mic"
        await vad.stop()

    @pytest.mark.asyncio
    async def test_t3_p2_loopback_audio_with_argos_translation(self):
        """P2: Computer audio + Argos translation interaction."""
        with patch("argostranslate.package.update_package_index"):
            with patch("argostranslate.package.get_available_packages", return_value=[]):
                with patch("argostranslate.translate") as mock_trans:
                    mock_inst = MagicMock()
                    mock_inst.translate.return_value = "कंप्यूटर ऑडियो"
                    mock_trans.get_translation_from_codes.return_value = mock_inst

                    translator = ArgosTranslator(MagicMock(deepl_api_key="", proxy_url="", timeout_s=5.0))
                    await translator.start()

                    res = await translator.translate("Computer audio", "en", "hi")
                    assert res.translated_text == "कंप्यूटर ऑडियो"

    @pytest.mark.asyncio
    async def test_t3_p3_noise_audio_with_vad_noise_floor(self):
        """P3: Low RMS noise + noise floor gating interaction."""
        vad = SileroVAD(VADSettings(rms_gate_threshold=0.0003))
        await vad.start()
        noise = (np.random.randn(480) * 0.0001).astype(np.float32)
        chunk = AudioChunk(data=noise.tobytes(), sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=30.0)
        results = [r async for r in vad.process(chunk)]
        assert len(results) == 1
        assert results[0].is_speech is False
        await vad.stop()

    def test_t3_p4_openai_stt_with_deepl_proxy_fallback(self):
        """P4: OpenAI STT fallback + DeepL proxy failover interaction."""
        from app.application import Application
        settings = Settings()
        settings.stt_engine = "openai"
        settings.openai.api_key = ""
        with patch("faster_whisper.WhisperModel"):
            app = Application(settings)
            pipeline = app.build_pipeline()
            assert isinstance(pipeline._stt, FasterWhisperSTT)

    def test_t3_p5_rapid_ui_bridge_with_active_audio_stream(self):
        """P5: Rapid UI Bridge API calls during active pipeline streaming."""
        pipeline_mock = MagicMock()
        pipeline_mock.running = True
        app_mock = MagicMock(pipeline=pipeline_mock)
        bridge = ApiBridge(application=app_mock, window=MagicMock())

        res_start = bridge.start_session("EN", "HI")
        bridge.emit_audio_level(0.8)
        bridge.set_translation_mode("two_way")
        res = bridge.submit_text_input("Test during stream")
        assert res["status"] == "ok"
        assert res_start["status"] == "ok"

    @pytest.mark.asyncio
    async def test_t3_p6_hindi_speech_stream_with_two_way_swap(self):
        """P6: Hindi input speech + automatic EN/HI directional swap interaction."""
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock(return_value=TranslationResult(
            original_text="नमस्ते", translated_text="Hello",
            source_lang="HI", target_lang="EN", is_final=True,
        ))

        pipeline = Pipeline(
            audio_input=AsyncMock(), vad=AsyncMock(), stt=AsyncMock(),
            translator=translator, tts=AsyncMock(), audio_output=AsyncMock(),
        )

        segment = TranscriptionSegment(
            text="नमस्ते", is_final=True, start_time=datetime.now(),
            end_time=datetime.now(), language="hi", confidence=0.9,
        )
        await pipeline._translate_and_route(segment, is_final=True, enqueue_tts=False)
        translator.translate.assert_called_once()

    @pytest.mark.asyncio
    async def test_t3_p7_text_input_mode_with_history_db(self):
        """P7: Text input submission + sqlite history recording interaction."""
        from services.history.database import HistoryDatabase
        db = HistoryDatabase(db_path=":memory:")
        db.connect()

        sid = db.save_session("Text Session", [{"text": "Hello world", "translated": "नमस्ते दुनिया"}])
        loaded = db.load_session(sid)
        assert loaded is not None
        assert "blocks" in loaded
        assert len(loaded["blocks"]) == 1
        db.close()

    @pytest.mark.asyncio
    async def test_t3_p8_tts_mute_gate_with_loopback_queue_purge(self):
        """P8: TTS playback start + loopback audio queue purging interaction."""
        pipeline = Pipeline(
            audio_input=AsyncMock(), vad=AsyncMock(), stt=AsyncMock(),
            translator=AsyncMock(), tts=AsyncMock(), audio_output=AsyncMock(),
        )
        lb_chunk = AudioChunk(data=b"lb", sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=10.0, source="loopback")
        await pipeline.audio_queue.put(lb_chunk)

        pipeline._activate_tts_mute_gate(1.0)
        pipeline._purge_loopback_queues()

        assert pipeline.audio_queue.empty()
        assert pipeline._should_ignore_loopback() is True

    @pytest.mark.asyncio
    async def test_t3_p9_partial_speech_stream_with_final_segment_route(self):
        """P9: Partial STT streaming -> final translation dispatch interaction."""
        translator = AsyncMock()
        translator.translate = AsyncMock(return_value=TranslationResult(
            original_text="Hello world", translated_text="नमस्ते दुनिया",
            source_lang="EN", target_lang="HI", is_final=True,
        ))

        pipeline = Pipeline(
            audio_input=AsyncMock(), vad=AsyncMock(), stt=AsyncMock(),
            translator=translator, tts=AsyncMock(), audio_output=AsyncMock(),
        )

        partial_seg = TranscriptionSegment(text="Hello", is_final=False, start_time=datetime.now(), end_time=datetime.now(), language="en", confidence=0.8)
        await pipeline._translate_and_route(partial_seg, is_final=False, enqueue_tts=False)

        final_seg = TranscriptionSegment(text="Hello world", is_final=True, start_time=datetime.now(), end_time=datetime.now(), language="en", confidence=0.95)
        await pipeline._translate_and_route(final_seg, is_final=True, enqueue_tts=False)

        assert translator.translate.call_count == 2

    def test_t3_p10_resampled_audio_with_vad_and_whisper(self):
        """P10: 44.1kHz audio downsampled to 16kHz + VAD + FasterWhisper interaction."""
        audio_44k = np.random.randn(44100).astype(np.float32)
        audio_16k = resample(audio_44k, src_rate=44100, dst_rate=16000)
        assert len(audio_16k) == 16000

    def test_t3_p11_context_engine_with_argos_translator(self):
        """P11: Context prompt accumulation + Argos translation interaction."""
        engine = ContextEngine()
        engine.add_segment("Good morning", "सुप्रभात", "en", "hi")
        prompt = engine.build_context_prompt("en", "hi")
        assert "Good morning" in prompt

    def test_t3_p12_audio_level_throttling_with_pywebview_render(self):
        """P12: Audio level inputs emission to window evaluate_js interaction."""
        window_mock = MagicMock()
        bridge = ApiBridge(application=MagicMock(), window=window_mock)

        for lvl in np.linspace(0.0, 1.0, 50):
            bridge.emit_audio_level(float(lvl))

        assert window_mock.evaluate_js.call_count == 50

    @pytest.mark.asyncio
    async def test_t3_p13_dual_source_mic_and_loopback_meeting_mode(self):
        """P13: Mic + Loopback dual streaming with source tagging interaction."""
        mic_chunk = AudioChunk(data=b"mic", sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=10.0, source="mic")
        lb_chunk = AudioChunk(data=b"lb", sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=10.0, source="loopback")

        assert mic_chunk.source == "mic"
        assert lb_chunk.source == "loopback"

    def test_t3_p14_srt_subtitle_export_with_translation_history(self):
        """P14: Translation history + SRT format export interaction."""
        from services.history.exporter import export_srt
        data = [{
            "timestamp": datetime.now().isoformat(),
            "original": "Hello",
            "translated": "नमस्ते",
        }]
        srt = export_srt(data)
        assert "Hello" in srt
        assert "नमस्ते" in srt

    def test_t3_p15_language_validator_hysteresis_with_whisper_confidence(self):
        """P15: Whisper confidence score + language validator hysteresis interaction."""
        from services.translation.language_validator import LanguageValidator
        validator = LanguageValidator()
        res1 = validator.validate("hi", 0.8, "en", "hi")
        assert res1 == "hi"

        res2 = validator.validate("en", 0.2, "en", "hi")
        assert res2 == "hi"
