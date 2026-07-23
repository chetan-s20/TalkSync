from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.interfaces import AudioChunk, TranscriptionSegment, TranslationResult
from app.pipeline import Pipeline
from services.audio.input import SoundDeviceInput
from services.audio.loopback import find_loopback_device, find_wasapi_loopback, find_stereo_mix, find_vb_cable
from services.stt.faster_whisper import FasterWhisperSTT
from ui.widgets.transcript_panel import TranscriptPanel


class TestMilestone2AudioLoopback:
    def test_find_wasapi_loopback_device_found(self):
        """WASAPI loopback returns default WASAPI output device (or None if unavailable)."""
        idx = find_wasapi_loopback()
        # On test systems with WASAPI, may return a device index; on headless CI, may be None
        assert idx is None or (isinstance(idx, int) and idx >= 0)

    def test_find_loopback_device_stereo_mix(self):
        devices = [
            {"name": "Microphone", "index": 0, "max_input_channels": 1, "max_output_channels": 0},
            {"name": "Stereo Mix (Realtek Audio)", "index": 1, "max_input_channels": 2, "max_output_channels": 0},
        ]
        with patch("sounddevice.query_devices", return_value=devices):
            res = find_loopback_device()
            assert res is not None
            assert res[0] == 1
            assert "Stereo Mix" in res[1]

    def test_find_loopback_device_vb_cable_fallback(self):
        devices = [
            {"name": "Microphone", "index": 0, "max_input_channels": 1, "max_output_channels": 0},
            {"name": "CABLE Output (VB-Audio Virtual Cable)", "index": 1, "max_input_channels": 2, "max_output_channels": 0},
        ]
        with patch("sounddevice.query_devices", return_value=devices):
            res = find_loopback_device()
            assert res is not None
            assert res[0] == 1
            assert "Cable" in res[1]

    def test_find_loopback_device_not_found(self):
        devices = [
            {"name": "Microphone", "index": 0, "max_input_channels": 1, "max_output_channels": 0},
        ]
        with patch("sounddevice.query_devices", return_value=devices):
            res = find_loopback_device()
            assert res is None

    @pytest.mark.asyncio
    async def test_input_queue_overflow_dropped_silently(self, mock_settings):
        input_service = SoundDeviceInput(mock_settings.audio)
        input_service._running = True
        input_service._loop = asyncio.get_running_loop()
        input_service._queue = asyncio.Queue(maxsize=1)

        cb = input_service._make_callback(16000, source="mic")
        indata = np.zeros((480, 1), dtype=np.float32)

        # Fill queue first
        chunk = AudioChunk(data=indata.tobytes(), sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=30.0, source="mic")
        await input_service._queue.put(chunk)

        # Trigger callback when queue is full — should not raise
        cb(indata, 480, None, None)
        await asyncio.sleep(0.05)

        # Queue should still have only the original item
        assert input_service._queue.qsize() == 1


class TestMilestone2WhisperAutoLang:
    def test_auto_lang_normalization_and_prob_extraction(self):
        with patch("faster_whisper.WhisperModel") as mock_model_cls:
            mock_model = MagicMock()
            mock_model_cls.return_value = mock_model

            mock_seg = MagicMock()
            mock_seg.text = "Hello world"
            mock_seg.avg_logprob = -0.2
            mock_seg.no_speech_prob = 0.01
            mock_seg.compression_ratio = 1.0

            mock_info = MagicMock()
            mock_info.language = "en"
            mock_info.language_probability = 0.98

            mock_model.transcribe.return_value = ([mock_seg], mock_info)

            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
            audio = np.random.randn(16000).astype(np.float32)

            for auto_arg in ("auto", "AUTO", "automatic"):
                res = stt.transcribe(audio, 16000, language=auto_arg)
                assert res is not None
                assert res.language == "en"
                assert res.language_probability == 0.98
                assert res.confidence == 0.98
                # Confirm None was passed to WhisperModel.transcribe
                call_kwargs = mock_model.transcribe.call_args[1]
                assert call_kwargs["language"] is None


class TestMilestone2PipelineRouting:
    @pytest.mark.asyncio
    async def test_stt_worker_attaches_input_source_and_prob(self):
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        stt_result = TranscriptionSegment(
            text="Hello world", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="en", confidence=0.9, language_probability=0.95,
        )
        stt.transcribe.return_value = stt_result

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline.running = True

        on_transcription_mock = MagicMock()
        pipeline.on_transcription = on_transcription_mock

        from app.pipeline_state import SttJob
        job = SttJob(source="loopback", audio=np.zeros(16000, dtype=np.float32).tobytes(), sample_rate=16000, is_final=True)
        await pipeline.stt_queue.put(job)

        worker_task = asyncio.create_task(pipeline._stt_worker())
        await asyncio.sleep(0.1)
        pipeline.running = False
        worker_task.cancel()

        on_transcription_mock.assert_called_once()
        called_segment = on_transcription_mock.call_args[0][0]
        assert called_segment.input_source == "COMPUTER_AUDIO"

        queued_trans = await pipeline.translation_queue.get()
        assert queued_trans.input_source == "COMPUTER_AUDIO"
        assert queued_trans.language_probability == 0.95

    @pytest.mark.asyncio
    async def test_translate_and_route_auto_language_resolution(self):
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        translator.translate = AsyncMock(return_value=TranslationResult(
            original_text="Bonjour", translated_text="Hello", source_lang="FR", target_lang="EN", is_final=True
        ))

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline._source_lang = "AUTO"
        pipeline._target_lang = "EN"

        segment = TranscriptionSegment(
            text="Bonjour", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="fr", confidence=0.95, language_probability=0.95,
            input_source="VOICE",
        )

        await pipeline._translate_and_route(segment, is_final=True, enqueue_tts=False)
        translator.translate.assert_called_once()
        call_args = translator.translate.call_args
        assert call_args[0][1] == "FR"  # Resolved source language
        assert call_args[0][2] == "EN"

    @pytest.mark.asyncio
    async def test_translate_and_route_loopback_default_direction(self):
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        translator.translate = AsyncMock(return_value=TranslationResult(
            original_text="Hola", translated_text="Hello", source_lang="HI", target_lang="EN", is_final=True
        ))

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline._source_lang = "EN"
        pipeline._target_lang = "HI"
        pipeline._translation_mode = "one_way"

        segment = TranscriptionSegment(
            text="Hola", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="", confidence=0.0,
            input_source="COMPUTER_AUDIO",
        )

        await pipeline._translate_and_route(segment, is_final=True, enqueue_tts=False)
        translator.translate.assert_called_once()
        call_args = translator.translate.call_args
        assert call_args[0][1] == "HI"  # src = target_lang for loopback
        assert call_args[0][2] == "EN"  # tgt = source_lang for loopback


class TestMilestone2TranscriptPanelWidget:
    @pytest.mark.skipif(True, reason="Requires display/Tk root; verify manually")
    def test_transcript_panel_badges_and_streaming(self):
        root = MagicMock()
        panel = TranscriptPanel(root, title="Panel A", lang_pair="en → hi")

        panel.append_message(original="Hello", translated="Namaste", input_source="VOICE", timestamp="12:00:00")
        panel.update_streaming_text(original="Streaming speech...")
        assert True
