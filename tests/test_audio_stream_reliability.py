from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.interfaces import AudioChunk
from config.settings import AudioSettings, VADSettings
from services.audio.input import SoundDeviceInput
from services.diagnostics.stream_diagnostics import StreamDiagnostics
from services.vad.silero_vad import SileroVAD, VADSpeechOutcome


class TestSileroVADFramingAndNoiseFloor:
    def test_silero_vad_sliding_window_chunks_gt_512(self):
        """Verify chunks > 512 samples are processed with 512-sample frame iterator (sliding window)."""
        settings = VADSettings(threshold=0.5)
        vad = SileroVAD(settings)
        vad._model = MagicMock()
        vad._model.return_value.item.return_value = 0.8
        vad._running = True

        # Create audio chunk of 960 samples (> 512)
        sr = 16000
        t = np.linspace(0, 0.06, 960, endpoint=False)
        audio = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

        with patch.object(vad, "_eval_512_frame", wraps=vad._eval_512_frame) as mock_eval:
            mock_eval.return_value = 0.85
            outcome = vad.is_speech(audio)
            
            # For 960 samples with step 512, frames are [0:512] and [512:960] (padded to 512) -> 2 calls
            assert mock_eval.call_count == 2
            assert outcome.is_speech is True
            assert outcome.confidence == pytest.approx(0.85)

    def test_silero_vad_short_chunk_padding(self):
        """Verify short chunks (< 512 samples) are padded to 512 samples."""
        settings = VADSettings(threshold=0.5)
        vad = SileroVAD(settings)
        vad._model = MagicMock()
        vad._model.return_value.item.return_value = 0.75
        vad._running = True

        # 300 samples (< 512) with RMS > 0.005
        sr = 16000
        t = np.linspace(0, 0.01875, 300, endpoint=False)
        audio = (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

        with patch.object(vad, "_eval_512_frame", wraps=vad._eval_512_frame) as mock_eval:
            mock_eval.return_value = 0.75
            outcome = vad.is_speech(audio)

            assert mock_eval.call_count == 1
            evaluated_frame = mock_eval.call_args[0][0]
            assert len(evaluated_frame) == 512
            assert np.array_equal(evaluated_frame[:300], audio)
            assert np.array_equal(evaluated_frame[300:], np.zeros(212, dtype=np.float32))
            assert outcome.is_speech is True

    def test_silero_vad_noise_floor_gate(self):
        """Verify static noise with RMS < 0.005 is gated to is_speech=False, confidence=0.0."""
        settings = VADSettings(threshold=0.5)
        vad = SileroVAD(settings)
        vad._model = MagicMock()
        vad._running = True

        # Low-level static noise (RMS = ~0.002 < 0.005)
        quiet_noise = (np.random.randn(960) * 0.002).astype(np.float32)
        rms = float(np.sqrt(np.mean(quiet_noise ** 2)))
        assert rms < 0.005

        with patch.object(vad, "_eval_512_frame") as mock_eval:
            outcome = vad.is_speech(quiet_noise)
            # Should be muted by noise floor gate without invoking model eval
            assert mock_eval.call_count == 0
            assert outcome.is_speech is False
            assert outcome.confidence == 0.0


class TestStreamInitializationAndDeviceSelection:
    @pytest.mark.asyncio
    async def test_mic_stream_initialization_channel_handling(self):
        """Verify mic initialization tries requested device & channel parameters without PortAudio exceptions."""
        settings = AudioSettings(input_device_id=1, sample_rate=16000, channels=1)
        audio_input = SoundDeviceInput(settings)
        
        mock_dev_info = {
            "name": "Test Mic",
            "default_samplerate": 48000,
            "max_input_channels": 2,
        }

        with patch("sounddevice.query_devices", return_value=mock_dev_info):
            with patch("sounddevice.InputStream") as mock_stream_cls:
                mock_stream_instance = MagicMock()
                mock_stream_cls.return_value = mock_stream_instance

                await audio_input.start(device_id=1, loopback=False, capture_mic=True)
                assert audio_input._mic_stream is not None
                assert len(audio_input._device_init_errors) == 0
                await audio_input.stop()

    @pytest.mark.asyncio
    async def test_loopback_stream_wasapi_fallback_to_stereo_mix(self):
        """Verify WASAPI failure falls back robustly to sounddevice Stereo Mix or VB-Cable."""
        settings = AudioSettings(sample_rate=16000)
        audio_input = SoundDeviceInput(settings)

        # WASAPI fails, Stereo Mix exists
        with patch("services.audio.input.find_loopback_device", return_value=("WASAPI Device", "WASAPI")):
            with patch.object(audio_input, "_start_wasapi_loopback", side_effect=Exception("WASAPI failure")):
                with patch("services.audio.input.find_stereo_mix", return_value=2):
                    with patch.object(audio_input, "_start_sd_loopback", new_callable=AsyncMock) as mock_sd_loopback:
                        with patch.object(audio_input, "_start_mic", new_callable=AsyncMock):
                            await audio_input.start(loopback=True, capture_mic=False)
                            mock_sd_loopback.assert_called_once_with(2, "Stereo Mix")
                            assert len(audio_input._device_init_errors) == 1
                            await audio_input.stop()


class TestQueueDispatchReliability:
    @pytest.mark.asyncio
    async def test_queue_dispatch_evicts_oldest_chunk_on_overflow(self):
        """Verify queue overflow evicts oldest chunk safely and increments overflow counter."""
        settings = AudioSettings(sample_rate=16000)
        audio_input = SoundDeviceInput(settings)
        audio_input._running = True
        audio_input._loop = asyncio.get_running_loop()
        audio_input._queue = asyncio.Queue(maxsize=2)

        cb = audio_input._make_callback(16000, source="mic")

        indata1 = np.ones((480, 1), dtype=np.float32) * 0.1
        indata2 = np.ones((480, 1), dtype=np.float32) * 0.2
        indata3 = np.ones((480, 1), dtype=np.float32) * 0.3

        # Put 3 items into maxsize=2 queue
        cb(indata1, 480, None, None)
        cb(indata2, 480, None, None)
        cb(indata3, 480, None, None)

        # Allow event loop threadsafe callbacks to execute
        await asyncio.sleep(0.05)

        diag = audio_input.get_diagnostics()
        assert diag["overflow_count"] >= 1
        assert audio_input._queue.qsize() == 2

        # Verify oldest chunk (0.1) was evicted, leaving 0.2 and 0.3
        chunk_a = await audio_input._queue.get()
        chunk_b = await audio_input._queue.get()
        arr_a = np.frombuffer(chunk_a.data, dtype=np.float32)
        arr_b = np.frombuffer(chunk_b.data, dtype=np.float32)
        assert np.isclose(arr_a[0], 0.2)
        assert np.isclose(arr_b[0], 0.3)


class TestGainAndAntiClipping:
    def test_fixed_gain_and_anti_clipping_bounds(self):
        """Verify gain=1.0 maintains signal bounds and anti-clipping clamps audio strictly to [-1.0, 1.0]."""
        settings = AudioSettings(sample_rate=16000, volume=1.0)
        audio_input = SoundDeviceInput(settings)
        audio_input._running = True
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        mock_loop.is_closed.return_value = False
        audio_input._loop = mock_loop
        audio_input._queue = MagicMock()

        captured_chunk = []
        def mock_call_soon(fn):
            fn()

        mock_loop.call_soon_threadsafe = mock_call_soon
        def mock_put_nowait(chunk):
            captured_chunk.append(chunk)

        audio_input._queue.full.return_value = False
        audio_input._queue.put_nowait = mock_put_nowait


        cb = audio_input._make_callback(16000, source="mic")

        # Input array with excessive amplitude values (+2.5, -3.0)
        excessive_input = np.array([[2.5], [-3.0], [0.5], [-0.5]], dtype=np.float32)

        cb(excessive_input, 4, None, None)

        assert len(captured_chunk) == 1
        processed_data = np.frombuffer(captured_chunk[0].data, dtype=np.float32)
        assert np.max(processed_data) <= 1.0
        assert np.min(processed_data) >= -1.0
        assert np.isclose(processed_data[0], 1.0)
        assert np.isclose(processed_data[1], -1.0)



class TestStreamDiagnosticsQueryAndAssertion:
    def test_stream_diagnostics_query_and_assertion_success(self):
        """Verify StreamDiagnostics queries registered streams and asserts reliability when 0 errors/overflows."""
        diag_service = StreamDiagnostics()
        mock_stream = MagicMock()
        mock_stream.get_diagnostics.return_value = {
            "running": True,
            "overflow_count": 0,
            "underflow_count": 0,
            "total_chunks": 100,
            "device_init_errors": [],
        }

        diag_service.register_stream("mic_input", mock_stream)
        status = diag_service.get_stream_status("mic_input")
        assert status["registered"] is True
        assert status["overflow_count"] == 0

        global_diag = diag_service.get_all_diagnostics()
        assert global_diag["is_reliable"] is True
        assert global_diag["total_overflows"] == 0

        # Programmatic assertion should pass
        diag_service.assert_stream_reliability("mic_input")
        diag_service.assert_stream_reliability()

    def test_stream_diagnostics_assertion_failure_on_overflow(self):
        """Verify assert_stream_reliability raises AssertionError when buffer overflow is detected."""
        diag_service = StreamDiagnostics()
        mock_stream = MagicMock()
        mock_stream.get_diagnostics.return_value = {
            "running": True,
            "overflow_count": 3,
            "underflow_count": 0,
            "total_chunks": 100,
            "device_init_errors": [],
        }

        diag_service.register_stream("loopback_input", mock_stream)
        with pytest.raises(AssertionError) as exc_info:
            diag_service.assert_stream_reliability("loopback_input")

        assert "buffer overflows: 3" in str(exc_info.value)
