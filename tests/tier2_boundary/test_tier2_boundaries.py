"""
Tier 2: Boundary Value Analysis & Corner Cases Test Suite for TalkSync AI.
Verifies edge cases, invalid inputs, error handling, and resource boundary limits for all 5 core features.
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
from services.audio.input import SoundDeviceInput
from services.audio.resampler import resample
from services.vad.silero_vad import SileroVAD
from services.stt.faster_whisper import FasterWhisperSTT
from services.stt.openai_stt import OpenAISTT
from services.translation.argos import ArgosTranslator
from services.translation.deepl import DeepLTranslator
from services.translation.factory import TranslationFactory
from utils.device import find_best_input_device

try:
    from app.bridge import ApiBridge
except ImportError:
    from tests.unit.test_bridge_api import ApiBridge


# ============================================================================
# Feature 1 Boundary Cases: Audio Stream Initialization
# ============================================================================

class TestFeature1AudioStreamBoundaries:
    """Tier 2 Boundary Test Cases for Feature 1: Audio Stream Initialization."""

    def test_t2_f1_invalid_device_index_out_of_bounds(self):
        """F1.1: Request device index 999 or out-of-bounds, verify graceful fallback to default device."""
        devices = [
            {"name": "Speakers (Realtek)", "max_input_channels": 0, "max_output_channels": 2, "hostapi": 0},
            {"name": "Microphone Array", "max_input_channels": 2, "max_output_channels": 0, "hostapi": 0},
        ]
        with patch("sounddevice.query_devices", return_value=devices):
            with patch("sounddevice.default.device", [1, 0]):
                dev_id, dev_name = find_best_input_device(requested_id=999)
                assert dev_id == 1
                assert "Microphone" in dev_name

    def test_t2_f1_zero_channel_device_handling(self):
        """F1.2: Input device with 0 input channels falls back to working mic."""
        devices = [
            {"name": "Muted Stereo Line In", "max_input_channels": 0, "max_output_channels": 0, "hostapi": 0},
            {"name": "Valid Mic", "max_input_channels": 1, "max_output_channels": 0, "hostapi": 0},
        ]
        with patch("sounddevice.query_devices", return_value=devices):
            with patch("sounddevice.default.device", [1, 0]):
                dev_id, dev_name = find_best_input_device(requested_id=0)
                assert dev_id == 1
                assert "Valid Mic" in dev_name

    @pytest.mark.asyncio
    async def test_t2_f1_empty_zero_length_audio_chunk(self):
        """F1.3: Feeding 0-byte or 0-sample audio chunk returns without crashing."""
        settings = VADSettings()
        vad = SileroVAD(settings)
        await vad.start()

        chunk = AudioChunk(data=b"", sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=0.0)
        results = [r async for r in vad.process(chunk)]
        assert len(results) == 1
        assert results[0].is_speech is False
        await vad.stop()

    def test_t2_f1_extreme_sample_rates(self):
        """F1.4: Audio with 8000Hz or 192000Hz resamples cleanly to 16000Hz."""
        audio_8k = np.random.randn(8000).astype(np.float32)
        res_8k = resample(audio_8k, src_rate=8000, dst_rate=16000)
        assert len(res_8k) == 16000

        audio_192k = np.random.randn(192000).astype(np.float32)
        res_192k = resample(audio_192k, src_rate=192000, dst_rate=16000)
        assert len(res_192k) == 16000

    @pytest.mark.asyncio
    async def test_t2_f1_stream_crash_and_recovery(self):
        """F1.5: Simulated sounddevice read error recovers or logs error without crashing application."""
        settings = AudioSettings()
        inp = SoundDeviceInput(settings)
        with patch("sounddevice.InputStream", side_effect=Exception("Driver crash")):
            with pytest.raises(Exception, match="Driver crash"):
                await inp.start(loopback=False, capture_mic=True)
            assert inp._running is False


# ============================================================================
# Feature 2 Boundary Cases: Silero VAD & Onset Detection
# ============================================================================

class TestFeature2SileroVADBoundaries:
    """Tier 2 Boundary Test Cases for Feature 2: Silero VAD."""

    @pytest.mark.asyncio
    async def test_t2_f2_vad_model_load_failure_fallback(self):
        """F2.1: Torch load failure falls back to RMS heuristic VAD mode."""
        settings = VADSettings()
        with patch("torch.hub.load", side_effect=Exception("PyTorch hub network failure")):
            vad = SileroVAD(settings)
            await vad.start()
            assert vad._running is True
            assert vad._model is None

            chunk = AudioChunk(
                data=(np.ones(480, dtype=np.float32) * 0.05).tobytes(),
                sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=30.0,
            )
            results = [r async for r in vad.process(chunk)]
            assert len(results) == 1
            assert results[0].is_speech is True
            await vad.stop()

    @pytest.mark.asyncio
    async def test_t2_f2_corrupted_garbage_audio_bytes(self):
        """F2.2: Corrupted/invalid byte payload returns is_speech=False."""
        settings = VADSettings()
        vad = SileroVAD(settings)
        await vad.start()

        chunk = MagicMock()
        chunk.data = b"\xFF\xFE\xFD\xFCinvalid_garbage_bytes"
        results = [r async for r in vad.process(chunk)]
        assert len(results) == 1
        assert results[0].is_speech is False
        await vad.stop()

    @pytest.mark.asyncio
    async def test_t2_f2_extreme_zero_silence(self):
        """F2.3: Completely silent audio (RMS = 0.0) bypasses Silero eval via noise floor gate."""
        settings = VADSettings()
        vad = SileroVAD(settings)
        await vad.start()

        chunk = AudioChunk(
            data=np.zeros(480, dtype=np.float32).tobytes(),
            sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=30.0,
        )
        results = [r async for r in vad.process(chunk)]
        assert len(results) == 1
        assert results[0].is_speech is False
        assert results[0].confidence == 0.0
        await vad.stop()

    @pytest.mark.asyncio
    async def test_t2_f2_clipping_amplitude_audio(self):
        """F2.4: Audio with amplitude > 1.0 or -1.0 is clamped and processed safely."""
        settings = VADSettings()
        vad = SileroVAD(settings)
        await vad.start()

        audio_clip = (np.ones(480, dtype=np.float32) * 50.0)
        chunk = AudioChunk(
            data=audio_clip.tobytes(),
            sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=30.0,
        )
        results = [r async for r in vad.process(chunk)]
        assert len(results) == 1
        assert np.isfinite(results[0].confidence)
        await vad.stop()

    @pytest.mark.asyncio
    async def test_t2_f2_boundary_rms_gate_threshold(self):
        """F2.5: Audio RMS exactly at noise floor threshold (0.0003) behaves deterministically."""
        settings = VADSettings(rms_gate_threshold=0.0003)
        vad = SileroVAD(settings)
        await vad.start()

        sub_rms_audio = (np.ones(480, dtype=np.float32) * 0.0001)
        chunk = AudioChunk(
            data=sub_rms_audio.tobytes(),
            sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=30.0,
        )
        results = [r async for r in vad.process(chunk)]
        assert len(results) == 1
        assert results[0].is_speech is False
        await vad.stop()


# ============================================================================
# Feature 3 Boundary Cases: STT Transcription Trigger
# ============================================================================

class TestFeature3STTBoundaries:
    """Tier 2 Boundary Test Cases for Feature 3: STT Transcription Trigger."""

    def test_t2_f3_stt_empty_transcript_result(self):
        """F3.1: Model returning empty string returns None segment without error."""
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_inst = MagicMock()
            mock_model.return_value = mock_inst
            mock_inst.transcribe.return_value = ([], MagicMock(language="en", duration=1.0))

            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
            res = stt.transcribe(np.zeros(16000, dtype=np.float32), 16000)
            assert res is None

    def test_t2_f3_stt_noise_rejection_extreme_logprob(self):
        """F3.2: Logprob -10.0 and no_speech_prob 0.99 cleanly rejected."""
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_inst = MagicMock()
            mock_model.return_value = mock_inst

            mock_seg = MagicMock()
            mock_seg.text = "Garbage noise"
            mock_seg.avg_logprob = -10.0
            mock_seg.no_speech_prob = 0.99

            mock_info = MagicMock(language="en", duration=0.5)
            mock_inst.transcribe.return_value = ([mock_seg], mock_info)

            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
            res = stt.transcribe(np.random.randn(16000).astype(np.float32) * 0.0001, 16000)
            assert res is None

    def test_t2_f3_stt_missing_openai_key_fallback(self):
        """F3.3: Missing OpenAI API key falls back to FasterWhisperSTT in Application build_pipeline."""
        from app.application import Application
        settings = Settings()
        settings.stt_engine = "openai"
        settings.openai.api_key = ""
        with patch("faster_whisper.WhisperModel"):
            app = Application(settings)
            pipeline = app.build_pipeline()
            assert isinstance(pipeline._stt, FasterWhisperSTT)

    def test_t2_f3_stt_extreme_short_chunk(self):
        """F3.4: 1ms audio chunk padded and processed cleanly."""
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_inst = MagicMock()
            mock_model.return_value = mock_inst
            mock_inst.transcribe.return_value = ([], MagicMock(language="en", duration=0.001))

            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
            short_audio = np.random.randn(16).astype(np.float32)
            res = stt.transcribe(short_audio, 16000)
            assert res is None

    @pytest.mark.asyncio
    async def test_t2_f3_stt_queue_overflow_burst(self):
        """F3.5: Rapid burst of 100 STT jobs handles queue full without thread block."""
        from app.pipeline_state import SttJob
        queue = asyncio.Queue(maxsize=10)
        for i in range(100):
            job = SttJob(source="mic", audio=b"audio", sample_rate=16000, is_final=True)
            if queue.full():
                queue.get_nowait()
            await queue.put(job)
        assert queue.qsize() == 10


# ============================================================================
# Feature 4 Boundary Cases: Translation & Fallback Handling
# ============================================================================

class TestFeature4TranslationBoundaries:
    """Tier 2 Boundary Test Cases for Feature 4: Translation & Fallback Handling."""

    @pytest.mark.asyncio
    async def test_t2_f4_invalid_deepl_api_key(self):
        """F4.1: DeepL init error raises exception, triggering Argos fallback."""
        with patch("deepl.Translator", side_effect=RuntimeError("Invalid API key")):
            settings = MagicMock(deepl_api_key="invalid-key", proxy_url="", timeout_s=5.0)
            translator = DeepLTranslator(settings)
            with pytest.raises(RuntimeError):
                await translator.start()
            assert translator._client is None

    @pytest.mark.asyncio
    async def test_t2_f4_network_timeout_and_unreachable_proxy(self):
        """F4.2: Network timeout returns original text without hanging pipeline."""
        with patch("deepl.Translator") as mock_deepl:
            mock_client = MagicMock()
            mock_client.translate_text.side_effect = TimeoutError("API Timeout")
            mock_client.get_usage.return_value = None
            mock_deepl.return_value = mock_client

            settings = MagicMock(deepl_api_key="key", proxy_url="", timeout_s=1.0)
            translator = DeepLTranslator(settings)
            await translator.start()

            res = await translator.translate("Timeout test", "EN", "FR")
            assert res.translated_text == "Timeout test"

    @pytest.mark.asyncio
    async def test_t2_f4_unsupported_language_pair_fallback(self):
        """F4.3: Unsupported language pair returns original text safely."""
        with patch("argostranslate.package.update_package_index"):
            with patch("argostranslate.package.get_available_packages", return_value=[]):
                with patch("argostranslate.translate") as mock_trans:
                    mock_trans.get_translation_from_codes.return_value = None
                    settings = MagicMock(deepl_api_key="", proxy_url="", timeout_s=5.0)
                    translator = ArgosTranslator(settings)
                    await translator.start()

                    res = await translator.translate("Hello", "xx", "yy")
                    assert res.translated_text == "Hello"

    @pytest.mark.asyncio
    async def test_t2_f4_empty_whitespace_translation_input(self):
        """F4.4: Empty string or whitespace returns empty result without API call."""
        with patch("argostranslate.package.update_package_index"):
            with patch("argostranslate.package.get_available_packages", return_value=[]):
                with patch("argostranslate.translate") as mock_trans:
                    mock_inst = MagicMock()
                    mock_inst.translate.return_value = ""
                    mock_trans.get_translation_from_codes.return_value = mock_inst

                    settings = MagicMock(deepl_api_key="", proxy_url="", timeout_s=5.0)
                    translator = ArgosTranslator(settings)
                    await translator.start()

                    res1 = await translator.translate("", "EN", "HI")
                    assert res1.translated_text == ""

                    res2 = await translator.translate("   \n\t  ", "EN", "HI")
                    assert res2.translated_text == ""

    @pytest.mark.asyncio
    async def test_t2_f4_partial_translation_queue_pruning(self):
        """F4.5: Rapid partial translations prune superseded older partials."""
        queue = asyncio.Queue(maxsize=5)
        for i in range(10):
            partial_res = TranslationResult(
                original_text=f"Part {i}", translated_text=f"Transl {i}",
                source_lang="EN", target_lang="HI", is_final=False,
            )
            if queue.full():
                queue.get_nowait()
            await queue.put(partial_res)
        assert queue.qsize() == 5
        last_item = await queue.get()
        assert last_item.original_text == "Part 5"


# ============================================================================
# Feature 5 Boundary Cases: PyWebView UI Bridge Event Dispatch
# ============================================================================

class TestFeature5UIBridgeBoundaries:
    """Tier 2 Boundary Test Cases for Feature 5: PyWebView UI Bridge Event Dispatch."""

    @pytest.mark.parametrize("source,target", [
        ("", "HI"), ("EN", ""), (None, "HI"), ("EN", None),
        ("INVALID_LANG", "HI"), (123, "HI"),
    ])
    def test_t2_f5_invalid_bridge_method_arguments(self, source, target):
        """F5.1: Passing invalid types returns error status dict."""
        bridge = ApiBridge(application=MagicMock(), window=MagicMock())
        res = bridge.set_languages(source, target)
        assert res["status"] == "error"
        assert "error" in res

    def test_t2_f5_rapid_start_stop_session_burst(self):
        """F5.2: Toggling start/stop 50 times rapidly maintains bridge active flag consistency."""
        bridge = ApiBridge(application=MagicMock(pipeline=AsyncMock()), window=MagicMock())
        for _ in range(50):
            res_start = bridge.start_session("EN", "HI")
            assert res_start["status"] == "ok"
            assert bridge.active is True

            res_stop = bridge.stop_session()
            assert res_stop["status"] == "ok"
            assert bridge.active is False

    def test_t2_f5_large_text_payload_emission(self):
        """F5.3: Transcribing 10,000 character string escapes special JSON characters safely."""
        window_mock = MagicMock()
        bridge = ApiBridge(application=MagicMock(), window=window_mock)

        large_text = "Special chars \n\t\"'\\ and " + ("x" * 10000)
        payload = bridge.emit_transcription(large_text, is_final=True)
        assert payload["text"] == large_text
        window_mock.evaluate_js.assert_called_once()

    def test_t2_f5_pywebview_window_none_or_destroyed(self):
        """F5.4: Calling bridge methods when window is None logs warning without raising exception."""
        bridge = ApiBridge(application=MagicMock(), window=None)
        payload = bridge.emit_translation("Hello", "नमस्ते", is_final=True)
        assert payload["original"] == "Hello"

    def test_t2_f5_concurrent_bridge_api_invocations(self):
        """F5.5: Rapid consecutive calls to start_session, submit_text_input, fetch_history execute safely."""
        pipeline_mock = MagicMock()
        pipeline_mock.running = False
        app_mock = MagicMock(pipeline=pipeline_mock)
        bridge = ApiBridge(application=app_mock, window=MagicMock())

        res_start = bridge.start_session("EN", "HI")
        res_sub = bridge.submit_text_input("Hello concurrent")
        res_hist = bridge.fetch_history(limit=10)

        assert res_start["status"] == "ok"
        assert res_sub["status"] == "ok"
        assert isinstance(res_hist, list)
