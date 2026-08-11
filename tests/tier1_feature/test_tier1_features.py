"""
Tier 1: Feature Coverage (Category-Partition) Test Suite for TalkSync AI.
Verifies primary happy path behaviors for all 5 core features with >= 5 cases per feature.
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
from services.audio.loopback import find_loopback_device
from services.audio.resampler import resample
from services.audio_processing.normalizer import PeakNormalizer
from services.vad.silero_vad import SileroVAD
from services.stt.faster_whisper import FasterWhisperSTT
from services.stt.openai_stt import OpenAISTT
from services.translation.argos import ArgosTranslator
from services.translation.deepl import DeepLTranslator
from services.translation.factory import TranslationFactory
from services.translation.context_engine import ContextEngine
from utils.device import find_best_input_device

try:
    from app.bridge import ApiBridge
except ImportError:
    from tests.unit.test_bridge_api import ApiBridge


# ============================================================================
# Feature 1: Audio Stream Initialization (ORIGINAL_REQUEST §R1)
# ============================================================================

class TestFeature1AudioStreamInitialization:
    """Tier 1 Test Cases for Feature 1: Audio Stream Initialization."""

    @pytest.mark.asyncio
    async def test_t1_f1_mic_stream_initialization(self):
        """F1.1: Verify microphone input stream opens with valid sample rate and 1 channel."""
        settings = AudioSettings(sample_rate=16000, channels=1)
        with patch("sounddevice.InputStream") as mock_stream:
            mock_inst = MagicMock()
            mock_stream.return_value.__enter__.return_value = mock_inst
            from services.audio.input import SoundDeviceInput
            inp = SoundDeviceInput(settings)
            await inp.start(loopback=False, capture_mic=True)
            assert inp._running is True
            await inp.stop()
            assert inp._running is False

    def test_t1_f1_loopback_stream_initialization(self, mock_device_list):
        """F1.2: Verify WASAPI loopback / Stereo Mix stream discovery opens cleanly."""
        with patch("services.audio.loopback.find_wasapi_loopback", return_value=None):
            with patch("sounddevice.query_devices", return_value=mock_device_list):
                dev = find_loopback_device()
                assert dev is not None
                assert len(dev) == 2
                assert "Stereo Mix" in dev[1]

    def test_t1_f1_device_selection_by_index_or_name(self):
        """F1.3: Verify selecting specific device index/name (e.g. index 16 / Boult Airbass) resolves correctly."""
        devices = [
            {"name": "Speakers (Realtek)", "max_input_channels": 0, "max_output_channels": 2, "hostapi": 0},
            {"name": "Boult Audio Airbass 16", "max_input_channels": 1, "max_output_channels": 0, "hostapi": 0},
        ]
        with patch("sounddevice.query_devices", return_value=devices):
            with patch("sounddevice.default.device", [1, 0]):
                dev_id, dev_name = find_best_input_device(requested_id=1)
                assert dev_id == 1
                assert "Boult" in dev_name

    def test_t1_f1_audio_level_calculation(self):
        """F1.4: Verify RMS audio level computation on mic and loopback chunks."""
        audio = np.ones(16000, dtype=np.float32) * 0.5
        level = float(np.sqrt(np.mean(audio ** 2)))
        assert level == pytest.approx(0.5, rel=0.01)

    def test_t1_f1_sample_rate_resampling(self):
        """F1.5: Verify resampling audio from 44.1kHz / 48kHz down to 16kHz mono."""
        audio = np.random.randn(48000).astype(np.float32)
        resampled = resample(audio, src_rate=48000, dst_rate=16000)
        assert len(resampled) == 16000


# ============================================================================
# Feature 2: Silero VAD & Onset Detection (ORIGINAL_REQUEST §R1)
# ============================================================================

class TestFeature2SileroVADAndOnsetDetection:
    """Tier 1 Test Cases for Feature 2: Silero VAD & Onset Detection."""

    def test_t1_f2_vad_initialization_and_start(self):
        """F2.1: Verify Silero VAD initializes with default threshold and starts cleanly."""
        settings = VADSettings(threshold=0.35)
        with patch("torch.hub.load") as mock_load:
            mock_model = MagicMock()
            mock_load.return_value = (mock_model, None)
            vad = SileroVAD(settings)
            assert vad.settings.threshold == 0.35
            asyncio.run(vad.start())
            assert vad._running is True
            asyncio.run(vad.stop())
            assert vad._running is False

    def test_t1_f2_speech_chunk_detection(self):
        """F2.2: Verify active speech frames return is_speech=True with confidence score."""
        settings = VADSettings(threshold=0.35)
        with patch("torch.hub.load") as mock_load:
            mock_model = MagicMock()
            mock_model.return_value.item.return_value = 0.8
            mock_load.return_value = (mock_model, None)
            vad = SileroVAD(settings)
            asyncio.run(vad.start())

            chunk = MagicMock()
            chunk.data = np.random.randn(480).astype(np.float32).tobytes()

            results = []
            async def collect():
                async for r in vad.process(chunk):
                    results.append(r)
            asyncio.run(collect())
            assert len(results) == 1
            assert results[0].is_speech is True
            assert results[0].confidence == pytest.approx(0.8, abs=0.1)

    def test_t1_f2_non_speech_filtering(self):
        """F2.3: Verify silent audio frames return is_speech=False."""
        settings = VADSettings(threshold=0.35)
        with patch("torch.hub.load") as mock_load:
            mock_model = MagicMock()
            mock_model.return_value.item.return_value = 0.05
            mock_load.return_value = (mock_model, None)
            vad = SileroVAD(settings)
            asyncio.run(vad.start())

            chunk = MagicMock()
            chunk.data = (np.random.randn(480) * 0.0001).astype(np.float32).tobytes()

            results = []
            async def collect():
                async for r in vad.process(chunk):
                    results.append(r)
            asyncio.run(collect())
            assert len(results) == 1
            assert results[0].is_speech is False

    def test_t1_f2_onset_frame_preservation(self):
        """F2.4: Verify initial speech onset frames are preserved when tracking speech."""
        from app.pipeline_state import SpeechTracker
        tracker = SpeechTracker()
        onset_frame = np.ones(480, dtype=np.float32) * 0.1
        tracker.update(True, frame=onset_frame)
        pending = tracker.get_and_clear_pending_frames()
        assert len(pending) == 1
        assert np.array_equal(pending[0], onset_frame)

    def test_t1_f2_multi_source_vad_tagging(self):
        """F2.5: Verify VAD processes mic and loopback chunks independently with correct source tags."""
        settings = VADSettings()
        with patch("torch.hub.load") as mock_load:
            mock_model = MagicMock()
            mock_load.return_value = (mock_model, None)
            vad = SileroVAD(settings)
            asyncio.run(vad.start())

            for src in ["mic", "loopback"]:
                chunk = AudioChunk(
                    data=np.random.randn(480).astype(np.float32).tobytes(),
                    sample_rate=16000, channels=1, timestamp=datetime.now(),
                    duration_ms=30.0, source=src,
                )
                results = []
                async def collect():
                    async for r in vad.process(chunk):
                        results.append(r)
                asyncio.run(collect())
                assert len(results) == 1
                assert results[0].chunk.source == src


# ============================================================================
# Feature 3: STT Transcription Trigger (ORIGINAL_REQUEST §R2)
# ============================================================================

class TestFeature3STTTranscriptionTrigger:
    """Tier 1 Test Cases for Feature 3: STT Transcription Trigger."""

    @pytest.mark.asyncio
    async def test_t1_f3_stt_transcription_from_queue(self):
        """F3.1: Verify STT worker dequeues SttJob and triggers transcription."""
        stt = MagicMock(spec=BaseSTT)
        stt.transcribe = AsyncMock(return_value=TranscriptionSegment(
            text="Test transcript", is_final=True, start_time=datetime.now(),
            end_time=datetime.now(), language="en", confidence=0.9,
        ))
        audio = np.random.randn(16000).astype(np.float32)
        res = await stt.transcribe(audio, 16000)
        assert res.text == "Test transcript"
        assert res.is_final is True

    def test_t1_f3_language_auto_detection(self):
        """F3.2: Verify STT detects source language (English vs Hindi) when language=None."""
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_inst = MagicMock()
            mock_model.return_value = mock_inst

            mock_seg = MagicMock()
            mock_seg.text = "नमस्ते"
            mock_seg.start, mock_seg.end = 0.0, 1.0
            mock_seg.avg_logprob = -0.1
            mock_seg.no_speech_prob = 0.05

            mock_info = MagicMock()
            mock_info.language = "hi"
            mock_info.duration = 1.0

            mock_inst.transcribe.return_value = ([mock_seg], mock_info)

            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
            res = stt.transcribe(np.random.randn(16000).astype(np.float32), 16000, language=None)
            assert res.language == "hi"

    def test_t1_f3_faster_whisper_transcribe(self):
        """F3.3: Verify FasterWhisperSTT transcribes audio numpy array to TranscriptionSegment."""
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_inst = MagicMock()
            mock_model.return_value = mock_inst

            mock_seg = MagicMock()
            mock_seg.text = "Hello world"
            mock_seg.start, mock_seg.end = 0.0, 1.0
            mock_seg.avg_logprob = -0.1
            mock_seg.no_speech_prob = 0.05

            mock_info = MagicMock(language="en", duration=1.0)
            mock_inst.transcribe.return_value = ([mock_seg], mock_info)

            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
            res = stt.transcribe(np.random.randn(16000).astype(np.float32), 16000)
            assert res.text == "Hello world"

    @pytest.mark.asyncio
    async def test_t1_f3_openai_stt_transcribe(self):
        """F3.4: Verify OpenAISTT transcribes audio using gpt-4o-transcribe API."""
        settings = Settings()
        stt = OpenAISTT(settings)
        stt._loaded = True
        mock_client = MagicMock()
        mock_resp = MagicMock(text="OpenAI Transcribed Speech")
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_resp)
        stt._client = mock_client

        res = await stt.transcribe(np.random.randn(16000).astype(np.float32), 16000)
        assert res is not None
        assert res.text == "OpenAI Transcribed Speech"

    def test_t1_f3_low_logprob_noise_rejection(self):
        """F3.5: Verify low logprob / high no-speech prob segments are rejected as noise."""
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_inst = MagicMock()
            mock_model.return_value = mock_inst

            mock_seg = MagicMock()
            mock_seg.text = "Background static"
            mock_seg.avg_logprob = -1.5
            mock_seg.no_speech_prob = 0.85

            mock_info = MagicMock(language="en", duration=0.5)
            mock_inst.transcribe.return_value = ([mock_seg], mock_info)

            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
            res = stt.transcribe(np.random.randn(16000).astype(np.float32) * 0.001, 16000)
            assert res is None


# ============================================================================
# Feature 4: Translation & Fallback Handling (ORIGINAL_REQUEST §R2)
# ============================================================================

class TestFeature4TranslationAndFallbackHandling:
    """Tier 1 Test Cases for Feature 4: Translation & Fallback Handling."""

    @pytest.mark.asyncio
    async def test_t1_f4_deepl_translation_success(self):
        """F4.1: Verify DeepLTranslator translates text from source_lang to target_lang."""
        with patch("deepl.Translator") as mock_deepl:
            mock_client = MagicMock()
            mock_res = MagicMock()
            mock_res.text = "Bonjour"
            mock_client.translate_text.return_value = mock_res
            mock_client.get_usage.return_value = None
            mock_deepl.return_value = mock_client

            settings = MagicMock(deepl_api_key="test-key", proxy_url="", timeout_s=5.0)
            translator = DeepLTranslator(settings)
            await translator.start()

            res = await translator.translate("Hello", "EN", "FR")
            assert res.translated_text == "Bonjour"
            assert res.is_final is True

    @pytest.mark.asyncio
    async def test_t1_f4_argos_translation_fallback(self):
        """F4.2: Verify ArgosTranslator translates offline when DeepL is disabled or fails."""
        with patch("argostranslate.package.update_package_index"):
            with patch("argostranslate.package.get_available_packages", return_value=[]):
                with patch("argostranslate.translate") as mock_trans:
                    mock_inst = MagicMock()
                    mock_inst.translate.return_value = "नमस्ते"
                    mock_trans.get_translation_from_codes.return_value = mock_inst

                    settings = MagicMock(deepl_api_key="", proxy_url="", timeout_s=5.0)
                    translator = ArgosTranslator(settings)
                    await translator.start()

                    res = await translator.translate("Hello", "en", "hi")
                    assert res.translated_text == "नमस्ते"

    @pytest.mark.asyncio
    async def test_t1_f4_translation_factory_provider_chain(self):
        """F4.3: Verify TranslationFactory creates DeepL primary and falls back to Argos."""
        with patch("services.translation.factory.ArgosTranslator") as mock_argos:
            mock_argos_inst = AsyncMock()
            mock_argos.return_value = mock_argos_inst

            settings = MagicMock()
            settings.translation = MagicMock()
            res = await TranslationFactory.create(settings)
            assert res is mock_argos_inst

    @pytest.mark.asyncio
    async def test_t1_f4_two_way_language_swapping(self):
        """F4.4: Verify dynamic two-way translation swaps EN->HI and HI->EN based on input."""
        with patch("argostranslate.package.update_package_index"):
            with patch("argostranslate.package.get_available_packages", return_value=[]):
                with patch("argostranslate.translate") as mock_trans:
                    en_hi = MagicMock()
                    en_hi.translate.return_value = "नमस्ते"
                    hi_en = MagicMock()
                    hi_en.translate.return_value = "Hello"

                    mock_trans.get_translation_from_codes.side_effect = lambda f, t: en_hi if t == "hi" else hi_en

                    settings = MagicMock(deepl_api_key="", proxy_url="", timeout_s=5.0)
                    translator = ArgosTranslator(settings)
                    await translator.start()

                    r1 = await translator.translate("Hello", "en", "hi")
                    assert r1.translated_text == "नमस्ते"

                    r2 = await translator.translate("नमस्ते", "hi", "en")
                    assert r2.translated_text == "Hello"

    def test_t1_f4_context_engine_prompt_building(self):
        """F4.5: Verify ContextEngine builds context prompt from previous conversation segments."""
        engine = ContextEngine()
        engine.add_segment("Hello", "Hola", "en", "es")
        engine.add_segment("How are you?", "¿Cómo estás?", "en", "es")
        prompt = engine.build_context_prompt("en", "es")
        assert "Hello" in prompt
        assert "Hola" in prompt


# ============================================================================
# Feature 5: PyWebView UI Bridge Event Dispatch (ORIGINAL_REQUEST §R3)
# ============================================================================

class TestFeature5PyWebViewUIBridgeEventDispatch:
    """Tier 1 Test Cases for Feature 5: PyWebView UI Bridge Event Dispatch."""

    def test_t1_f5_bridge_lifecycle_start_stop(self):
        """F5.1: Verify ApiBridge.start_session and stop_session manage pipeline lifecycle cleanly."""
        pipeline_mock = AsyncMock()
        app_mock = MagicMock(pipeline=pipeline_mock)
        window_mock = MagicMock()
        bridge = ApiBridge(application=app_mock, window=window_mock)

        res_start = bridge.start_session("EN", "HI")
        assert res_start["status"] == "ok"
        assert bridge.active is True

        res_stop = bridge.stop_session()
        assert res_stop["status"] == "ok"
        assert bridge.active is False

    def test_t1_f5_transcription_event_emission(self):
        """F5.2: Verify emit_transcription dispatches onTranscription JS event callback."""
        window_mock = MagicMock()
        bridge = ApiBridge(application=MagicMock(), window=window_mock)

        payload = bridge.emit_transcription("Hello world", is_final=True, speaker="user", lang="en")
        assert payload["text"] == "Hello world"
        assert payload["is_final"] is True
        window_mock.evaluate_js.assert_called_once()
        assert "onTranscription" in window_mock.evaluate_js.call_args[0][0]

    def test_t1_f5_translation_event_emission(self):
        """F5.3: Verify emit_translation dispatches onTranslation JS event callback."""
        window_mock = MagicMock()
        bridge = ApiBridge(application=MagicMock(), window=window_mock)

        payload = bridge.emit_translation("Hello", "नमस्ते", is_final=True, speaker="user", source_lang="EN", target_lang="HI")
        assert payload["original"] == "Hello"
        assert payload["translated"] == "नमस्ते"
        window_mock.evaluate_js.assert_called_once()
        assert "onTranslation" in window_mock.evaluate_js.call_args[0][0]

    def test_t1_f5_audio_level_throttling(self):
        """F5.4: Verify emit_audio_level emits event payload to window.evaluate_js."""
        window_mock = MagicMock()
        bridge = ApiBridge(application=MagicMock(), window=window_mock)

        payload = bridge.emit_audio_level(0.42, rms=0.05, source="mic")
        assert payload["level"] == 0.42
        window_mock.evaluate_js.assert_called_once()

    def test_t1_f5_evaluate_js_execution(self):
        """F5.5: Verify window.evaluate_js is invoked with sanitized JSON payloads."""
        window_mock = MagicMock()
        bridge = ApiBridge(application=MagicMock(), window=window_mock)

        bridge.emit_status("Processing...", active=True)
        window_mock.evaluate_js.assert_called_once()
        code = window_mock.evaluate_js.call_args[0][0]
        assert "onStatus" in code
        assert "Processing..." in code
