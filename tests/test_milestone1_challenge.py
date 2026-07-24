"""Empirical Challenge Test Suite for Milestone 1.

Stress-tests:
1. SileroVAD.is_speech() with large audio buffers (2048, 4096 samples) containing mixed speech and silent frames.
2. Anti-clipping bounds with extreme amplitude arrays (+10.0, -10.0, infinity, NaN) to verify [-1.0, 1.0] clamping protection.
3. High-throughput queue insertion to verify that asyncio.Queue overflow eviction (get_nowait) prevents pipeline locks or memory leaks.
"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.interfaces import AudioChunk
from config.settings import AudioSettings, VADSettings
from services.audio.input import SoundDeviceInput
from services.vad.silero_vad import SileroVAD as ServicesSileroVAD, VADSpeechOutcome
from vad.silero_vad import SileroVAD as RootSileroVAD


class TestSileroVADLargeBufferStress:
    """Stress-test SileroVAD.is_speech() with large audio buffers (2048, 4096 samples) containing mixed speech and silent frames."""

    @pytest.mark.parametrize("VADClass", [ServicesSileroVAD, RootSileroVAD])
    def test_silero_vad_2048_buffer_mixed_speech_at_end(self, VADClass):
        """Test 2048-sample buffer where first 1536 samples are silent and last 512 samples contain speech."""
        settings = VADSettings(threshold=0.5)
        vad = VADClass(settings)
        vad._model = MagicMock()
        vad._running = True

        # First 1536 samples quiet noise (RMS < 0.005 overall RMS will depend on full array, but let's make speech strong)
        sr = 16000
        silence = np.zeros(1536, dtype=np.float32)
        t = np.linspace(0, 512 / sr, 512, endpoint=False)
        speech = (0.8 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        audio_2048 = np.concatenate([silence, speech])

        # Mock frame evaluator: return 0.05 for silent frames, 0.85 for speech frame
        def mock_eval(frame):
            rms = float(np.sqrt(np.mean(frame ** 2)))
            return 0.85 if rms > 0.1 else 0.05

        with patch.object(vad, "_eval_512_frame", side_effect=mock_eval) as mock_eval_fn:
            outcome = vad.is_speech(audio_2048)

            # 2048 / 512 = 4 frames
            assert mock_eval_fn.call_count == 4
            is_speech = outcome[0] if isinstance(outcome, tuple) else outcome.is_speech
            confidence = outcome[1] if isinstance(outcome, tuple) else outcome.confidence

            assert is_speech is True
            assert confidence == pytest.approx(0.85)

    @pytest.mark.parametrize("VADClass", [ServicesSileroVAD, RootSileroVAD])
    def test_silero_vad_2048_buffer_mixed_speech_at_start(self, VADClass):
        """Test 2048-sample buffer where first 512 samples contain speech and remaining 1536 samples are silent."""
        settings = VADSettings(threshold=0.5)
        vad = VADClass(settings)
        vad._model = MagicMock()
        vad._running = True

        sr = 16000
        t = np.linspace(0, 512 / sr, 512, endpoint=False)
        speech = (0.7 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        silence = np.zeros(1536, dtype=np.float32)
        audio_2048 = np.concatenate([speech, silence])

        def mock_eval(frame):
            rms = float(np.sqrt(np.mean(frame ** 2)))
            return 0.88 if rms > 0.1 else 0.02

        with patch.object(vad, "_eval_512_frame", side_effect=mock_eval) as mock_eval_fn:
            outcome = vad.is_speech(audio_2048)

            assert mock_eval_fn.call_count == 4
            is_speech = outcome[0] if isinstance(outcome, tuple) else outcome.is_speech
            confidence = outcome[1] if isinstance(outcome, tuple) else outcome.confidence

            assert is_speech is True
            assert confidence == pytest.approx(0.88)

    @pytest.mark.parametrize("VADClass", [ServicesSileroVAD, RootSileroVAD])
    def test_silero_vad_4096_buffer_mixed_interleaved(self, VADClass):
        """Test 4096-sample buffer (8 sub-frames of 512) with interleaved speech and silence frames."""
        settings = VADSettings(threshold=0.5)
        vad = VADClass(settings)
        vad._model = MagicMock()
        vad._running = True

        sr = 16000
        frames = []
        expected_probs = [0.01, 0.92, 0.03, 0.01, 0.87, 0.02, 0.01, 0.04]

        for prob in expected_probs:
            if prob > 0.5:
                t = np.linspace(0, 512 / sr, 512, endpoint=False)
                frame = (0.6 * np.sin(2 * np.pi * 800 * t)).astype(np.float32)
            else:
                frame = (np.random.randn(512) * 0.0001).astype(np.float32)
            frames.append(frame)

        audio_4096 = np.concatenate(frames)

        def mock_eval(frame):
            rms = float(np.sqrt(np.mean(frame ** 2)))
            return 0.92 if rms > 0.05 else 0.02

        with patch.object(vad, "_eval_512_frame", side_effect=mock_eval) as mock_eval_fn:
            outcome = vad.is_speech(audio_4096)

            assert mock_eval_fn.call_count == 8
            is_speech = outcome[0] if isinstance(outcome, tuple) else outcome.is_speech
            confidence = outcome[1] if isinstance(outcome, tuple) else outcome.confidence

            assert is_speech is True
            assert confidence == pytest.approx(0.92)

    @pytest.mark.parametrize("VADClass", [ServicesSileroVAD, RootSileroVAD])
    def test_silero_vad_pure_silence_large_buffers(self, VADClass):
        """Test 2048 and 4096 sample buffers containing pure silent static (RMS < 0.005)."""
        settings = VADSettings(threshold=0.5)
        vad = VADClass(settings)
        vad._model = MagicMock()
        vad._running = True

        for size in [2048, 4096]:
            silent_audio = (np.random.randn(size) * 0.001).astype(np.float32)

            with patch.object(vad, "_eval_512_frame") as mock_eval_fn:
                outcome = vad.is_speech(silent_audio)
                # Should be gated by noise floor check without invoking model evaluation
                assert mock_eval_fn.call_count == 0
                is_speech = outcome[0] if isinstance(outcome, tuple) else outcome.is_speech
                confidence = outcome[1] if isinstance(outcome, tuple) else outcome.confidence

                assert is_speech is False
                assert confidence == 0.0


class TestAntiClippingBoundsStress:
    """Stress-test anti-clipping bounds by feeding extreme amplitude arrays (+10.0, -10.0, infinity, NaN)."""

    def test_anti_clipping_extreme_amplitudes_callback(self):
        """Verify extreme values (+10.0, -10.0, +500.0, -500.0) are clamped strictly to [-1.0, 1.0]."""
        settings = AudioSettings(sample_rate=16000, volume=1.0)
        audio_input = SoundDeviceInput(settings)
        audio_input._running = True
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        mock_loop.is_closed.return_value = False
        audio_input._loop = mock_loop
        audio_input._queue = MagicMock()

        captured_chunks = []

        def mock_call_soon(fn):
            fn()

        mock_loop.call_soon_threadsafe = mock_call_soon

        def mock_put_nowait(chunk):
            captured_chunks.append(chunk)

        audio_input._queue.full.return_value = False
        audio_input._queue.put_nowait = mock_put_nowait

        cb = audio_input._make_callback(16000, source="mic")

        extreme_data = np.array([[10.0], [-10.0], [500.0], [-500.0], [0.5], [-0.5]], dtype=np.float32)
        cb(extreme_data, 6, None, None)

        assert len(captured_chunks) == 1
        processed = np.frombuffer(captured_chunks[0].data, dtype=np.float32)

        assert np.all(processed >= -1.0)
        assert np.all(processed <= 1.0)
        assert np.isclose(processed[0], 1.0)
        assert np.isclose(processed[1], -1.0)
        assert np.isclose(processed[2], 1.0)
        assert np.isclose(processed[3], -1.0)
        assert np.isclose(processed[4], 0.5)
        assert np.isclose(processed[5], -0.5)

    def test_anti_clipping_nan_and_infinity_resilience(self):
        """Verify arrays containing NaN, +inf, and -inf are safely sanitized and clamped without raising exceptions."""
        settings = AudioSettings(sample_rate=16000, volume=1.0)
        audio_input = SoundDeviceInput(settings)
        audio_input._running = True
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        mock_loop.is_closed.return_value = False
        audio_input._loop = mock_loop
        audio_input._queue = MagicMock()

        captured_chunks = []

        def mock_call_soon(fn):
            fn()

        mock_loop.call_soon_threadsafe = mock_call_soon

        def mock_put_nowait(chunk):
            captured_chunks.append(chunk)

        audio_input._queue.full.return_value = False
        audio_input._queue.put_nowait = mock_put_nowait

        cb = audio_input._make_callback(16000, source="mic")

        # Input containing NaN, +inf, -inf
        invalid_data = np.array([[np.nan], [np.inf], [-np.inf], [2.0], [-2.0]], dtype=np.float32)
        cb(invalid_data, 5, None, None)

        assert len(captured_chunks) == 1
        processed = np.frombuffer(captured_chunks[0].data, dtype=np.float32)

        # Output must be free of NaNs and Infs, and bounded in [-1.0, 1.0]
        assert not np.any(np.isnan(processed))
        assert not np.any(np.isinf(processed))
        assert np.all(processed >= -1.0)
        assert np.all(processed <= 1.0)

    def test_wasapi_loopback_nan_propagation_vulnerability(self):
        """Verify np.clip in loopback stream processing allows NaN values to propagate into AudioChunk."""
        # Directly test the raw np.clip operation used in SoundDeviceInput._make_callback and _start_wasapi_loopback
        raw_audio_with_nan = np.array([np.nan, 2.5, -3.0, np.inf, -np.inf], dtype=np.float32)
        clipped = np.clip(raw_audio_with_nan, -1.0, 1.0)
        
        # Demonstrates that np.clip leaves NaN untouched (np.isnan(clipped[0]) is True)
        assert np.isnan(clipped[0])  # Confirms vulnerability: np.clip fails to sanitize NaNs

    @pytest.mark.parametrize("VADClass", [ServicesSileroVAD, RootSileroVAD])
    def test_silero_vad_nan_inf_extreme_arrays(self, VADClass):
        """Verify SileroVAD.is_speech() sanitizes NaNs and Infs without throwing exceptions or returning NaN confidence."""
        settings = VADSettings(threshold=0.5)
        vad = VADClass(settings)
        vad._model = MagicMock()
        vad._running = True

        bad_audio = np.array([np.nan, np.inf, -np.inf, 10.0, -10.0] * 100, dtype=np.float32)

        with patch.object(vad, "_eval_512_frame", return_value=0.55):
            outcome = vad.is_speech(bad_audio)
            confidence = outcome[1] if isinstance(outcome, tuple) else outcome.confidence
            assert not np.isnan(confidence)
            assert not np.isinf(confidence)


class TestHighThroughputQueueInsertionStress:
    """Stress-test high-throughput queue insertion to verify overflow eviction (get_nowait) prevents locks or leaks."""

    @pytest.mark.asyncio
    async def test_high_throughput_queue_eviction_prevents_lock_or_leak(self):
        """Insert 1,000 items into a maxsize=10 queue at high throughput to verify eviction and boundary metrics."""
        settings = AudioSettings(sample_rate=16000)
        audio_input = SoundDeviceInput(settings)
        audio_input._running = True
        audio_input._loop = asyncio.get_running_loop()
        max_qsize = 10
        audio_input._queue = asyncio.Queue(maxsize=max_qsize)

        cb = audio_input._make_callback(16000, source="mic")

        total_chunks_to_send = 1000
        for i in range(total_chunks_to_send):
            data = np.ones((480, 1), dtype=np.float32) * (i / 1000.0)
            cb(data, 480, None, None)

        # Allow event loop threadsafe tasks to process
        await asyncio.sleep(0.1)

        diag = audio_input.get_diagnostics()

        # Queue size must be bounded at maxsize=10
        assert audio_input._queue.qsize() == max_qsize
        # Overflow count should be total sent minus initial capacity
        assert diag["overflow_count"] == total_chunks_to_send - max_qsize

        # Verify FIFO eviction: queue should contain the LAST 10 chunks (indices 990 to 999)
        remaining_chunks = []
        while not audio_input._queue.empty():
            c = await audio_input._queue.get()
            arr = np.frombuffer(c.data, dtype=np.float32)
            remaining_chunks.append(arr[0])

        assert len(remaining_chunks) == max_qsize
        first_remaining_val = remaining_chunks[0]
        expected_first_val = 990.0 / 1000.0
        assert np.isclose(first_remaining_val, expected_first_val, atol=1e-3)

    @pytest.mark.asyncio
    async def test_multithreaded_high_throughput_queue_eviction(self):
        """Simulate concurrent high-throughput callbacks from multiple background threads into queue."""
        settings = AudioSettings(sample_rate=16000)
        audio_input = SoundDeviceInput(settings)
        audio_input._running = True
        audio_input._loop = asyncio.get_running_loop()
        audio_input._queue = asyncio.Queue(maxsize=20)

        cb = audio_input._make_callback(16000, source="mic")

        chunks_per_thread = 500
        num_threads = 4
        threads = []

        def producer_thread(thread_idx):
            for i in range(chunks_per_thread):
                data = np.ones((480, 1), dtype=np.float32) * (thread_idx + 0.1)
                cb(data, 480, None, None)

        for t_idx in range(num_threads):
            t = threading.Thread(target=producer_thread, args=(t_idx,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        await asyncio.sleep(0.15)

        diag = audio_input.get_diagnostics()
        assert audio_input._queue.qsize() == 20
        total_sent = num_threads * chunks_per_thread
        assert diag["overflow_count"] == total_sent - 20
        assert diag["total_chunks"] == total_sent
