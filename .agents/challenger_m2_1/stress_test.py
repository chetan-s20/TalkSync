"""
Empirical Stress Test Suite for TalkSync AI Milestone 2
Dual Audio Capture System, Queue Load, Overflow Logging, Thread Safety & Resource Cleanup
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.interfaces import AudioChunk, AudioProcessor
from app.pipeline import Pipeline
from config.settings import AudioSettings
from services.audio.input import SoundDeviceInput


class CapturingLoggerHandler(logging.Handler):
    """Utility logging handler to capture log records during tests."""
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


# Dummy test fixtures/mocks for Pipeline tests
class DummyVAD:
    async def start(self): pass
    async def stop(self): pass
    async def process(self, chunk):
        if False:
            yield None

class DummySTT:
    async def start(self): pass
    async def stop(self): pass
    async def transcribe(self, audio, is_final=True):
        res = MagicMock()
        res.text = ""
        res.language = "EN"
        res.confidence = 1.0
        return res

class DummyTranslator:
    async def start(self): pass
    async def stop(self): pass
    async def translate(self, text, src, tgt, context=None):
        res = MagicMock()
        res.translated_text = "translated " + text
        return res

class DummyTTS:
    async def start(self): pass
    async def stop(self): pass
    async def synthesize_stream(self, text_gen, lang):
        if False:
            yield None
    async def synthesize(self, text, lang):
        return None

class DummyOutput:
    async def start(self): pass
    async def stop(self): pass
    async def play(self, chunk): pass


@pytest.mark.asyncio
async def test_dual_audio_capture_routing():
    """Test 1: Verify dual audio capture setup and routing (mic vs loopback)."""
    settings = AudioSettings(sample_rate=16000, chunk_duration_ms=30)
    audio_input = SoundDeviceInput(settings)

    mock_mic_stream = MagicMock()
    mock_loop_stream = MagicMock()

    with patch("services.audio.input.sd.InputStream") as mock_input_stream, \
         patch("services.audio.input.find_loopback_device", return_value=(1, "Stereo Mix")), \
         patch("sounddevice.query_devices", return_value={"default_samplerate": 16000, "max_input_channels": 2}):

        mock_input_stream.side_effect = [mock_loop_stream, mock_mic_stream]

        await audio_input.start(loopback=True, capture_mic=True)

        assert audio_input._running is True
        assert audio_input._queue is not None
        assert audio_input._loopback_queue is not None

        # Extract callbacks passed to InputStream
        loopback_cb = mock_input_stream.call_args_list[0].kwargs["callback"]
        mic_cb = mock_input_stream.call_args_list[1].kwargs["callback"]

        # Simulate audio frame data
        dummy_pcm = np.ones((480, 1), dtype=np.float32)

        # Call callbacks from background threads or current thread
        mic_cb(dummy_pcm, 480, None, None)
        loopback_cb(dummy_pcm, 480, None, None)

        await asyncio.sleep(0.05)

        # Verify queues received correct chunks with appropriate sources
        assert audio_input._queue.qsize() == 1
        assert audio_input._loopback_queue.qsize() == 1

        mic_chunk = await audio_input._queue.get()
        loop_chunk = await audio_input._loopback_queue.get()

        assert mic_chunk.source == "mic"
        assert loop_chunk.source == "loopback"
        assert mic_chunk.sample_rate == 16000
        assert loop_chunk.sample_rate == 16000

        await audio_input.stop()


@pytest.mark.asyncio
async def test_high_queue_load_and_overflow_logging():
    """Test 2: High queue load & overflow logging verification."""
    settings = AudioSettings(sample_rate=16000, chunk_duration_ms=30)
    audio_input = SoundDeviceInput(settings)

    # Attach custom log handler to audio_input logger
    from services.audio.input import logger as audio_logger
    handler = CapturingLoggerHandler()
    audio_logger.addHandler(handler)

    mock_stream = MagicMock()
    with patch("services.audio.input.sd.InputStream", return_value=mock_stream), \
         patch("sounddevice.query_devices", return_value={"default_samplerate": 16000, "max_input_channels": 1}):

        await audio_input.start(loopback=False, capture_mic=True)
        cb = audio_input._make_callback(native_sr=16000, source="mic")

        # Fill the queue (maxsize=100) to capacity
        dummy_pcm = np.zeros((480, 1), dtype=np.float32)
        for _ in range(100):
            cb(dummy_pcm, 480, None, None)

        await asyncio.sleep(0.05)
        assert audio_input._queue.qsize() == 100

        # Reset handler records and push 20 additional items to trigger overflow logging
        handler.records.clear()
        for _ in range(20):
            cb(dummy_pcm, 480, None, None)

        await asyncio.sleep(0.05)

        # Check for expected warning messages
        overflow_logs = [r.getMessage() for r in handler.records if "overflow" in r.getMessage().lower()]
        assert len(overflow_logs) > 0, "Queue overflow warnings were not logged!"
        assert any("Audio input queue overflow for source 'mic'" in msg for msg in overflow_logs)

        # Ensure queue maxsize was respected (not exceeded)
        assert audio_input._queue.qsize() == 100

        await audio_input.stop()
        audio_logger.removeHandler(handler)


@pytest.mark.asyncio
async def test_thread_safety_concurrent_callbacks():
    """Test 3: Thread safety under concurrent callback invocations."""
    settings = AudioSettings(sample_rate=16000, chunk_duration_ms=30)
    audio_input = SoundDeviceInput(settings)

    mock_stream = MagicMock()
    with patch("services.audio.input.sd.InputStream", return_value=mock_stream), \
         patch("sounddevice.query_devices", return_value={"default_samplerate": 16000, "max_input_channels": 1}):

        await audio_input.start(loopback=True, capture_mic=True)
        mic_cb = audio_input._make_callback(16000, "mic")
        loop_cb = audio_input._make_callback(16000, "loopback")

        dummy_pcm = np.random.randn(480, 1).astype(np.float32)
        stop_threads = False
        exceptions = []

        def producer_worker(cb):
            while not stop_threads:
                try:
                    cb(dummy_pcm, 480, None, None)
                    time.sleep(0.0001)
                except Exception as e:
                    exceptions.append(e)

        threads = []
        for _ in range(5):
            t1 = threading.Thread(target=producer_worker, args=(mic_cb,))
            t2 = threading.Thread(target=producer_worker, args=(loop_cb,))
            threads.extend([t1, t2])
            t1.start()
            t2.start()

        # Consume streams concurrently
        received_mic = 0
        received_loop = 0

        async def drain_mic():
            nonlocal received_mic
            async for chunk in audio_input.stream():
                received_mic += 1
                if received_mic >= 50:
                    break

        async def drain_loop():
            nonlocal received_loop
            async for chunk in audio_input.stream_loopback():
                received_loop += 1
                if received_loop >= 50:
                    break

        await asyncio.gather(drain_mic(), drain_loop())

        stop_threads = True
        for t in threads:
            t.join()

        assert len(exceptions) == 0, f"Thread safety test encountered exceptions: {exceptions}"
        assert received_mic >= 50
        assert received_loop >= 50

        await audio_input.stop()


@pytest.mark.asyncio
async def test_resource_cleanup_on_stop():
    """Test 4: Verify complete resource cleanup on stop."""
    settings = AudioSettings(sample_rate=16000, chunk_duration_ms=30)
    audio_input = SoundDeviceInput(settings)

    mock_mic = MagicMock()
    mock_loop = MagicMock()

    with patch("services.audio.input.sd.InputStream") as mock_input_stream, \
         patch("services.audio.input.find_loopback_device", return_value=(1, "Stereo Mix")), \
         patch("sounddevice.query_devices", return_value={"default_samplerate": 16000, "max_input_channels": 2}):

        mock_input_stream.side_effect = [mock_loop, mock_mic]

        await audio_input.start(loopback=True, capture_mic=True)
        assert audio_input._running is True

        mic_queue = audio_input._queue
        loop_queue = audio_input._loopback_queue

        # Call stop
        await audio_input.stop()

        # Check internal state reset
        assert audio_input._running is False
        assert audio_input._mic_stream is None
        assert audio_input._loopback_stream is None

        # Check sounddevice stream cleanup
        mock_mic.stop.assert_called_once()
        mock_mic.close.assert_called_once()
        mock_loop.stop.assert_called_once()
        mock_loop.close.assert_called_once()

        # Check sentinel None was pushed to queues
        item_mic = await mic_queue.get()
        item_loop = await loop_queue.get()
        assert item_mic is None
        assert item_loop is None

        # Test idempotency of stop (calling stop again should not crash)
        await audio_input.stop()


@pytest.mark.asyncio
async def test_pipeline_dual_capture_integration():
    """Test 5: Full Pipeline integration with dual capture workers under load."""
    settings = AudioSettings(sample_rate=16000, chunk_duration_ms=30)
    audio_input = SoundDeviceInput(settings)

    pipeline = Pipeline(
        audio_input=audio_input,
        vad=DummyVAD(),
        stt=DummySTT(),
        translator=DummyTranslator(),
        tts=DummyTTS(),
        audio_output=DummyOutput(),
        settings=settings,
    )

    mock_mic = MagicMock()
    mock_loop = MagicMock()

    with patch("services.audio.input.sd.InputStream") as mock_input_stream, \
         patch("services.audio.input.find_loopback_device", return_value=(1, "Stereo Mix")), \
         patch("sounddevice.query_devices", return_value={"default_samplerate": 16000, "max_input_channels": 2}), \
         patch.object(DummyTranslator, "translate", return_value=MagicMock(translated_text="warm")):

        mock_input_stream.side_effect = [mock_loop, mock_mic]

        await pipeline.start(source_lang="EN", target_lang="HI", loopback=True, text_mode=False)

        assert pipeline.running is True
        assert len(pipeline._tasks) == 7  # vad, stt, translation, tts, stats, mic_capture, loopback_capture

        loop_cb = mock_input_stream.call_args_list[0].kwargs["callback"]
        mic_cb = mock_input_stream.call_args_list[1].kwargs["callback"]

        dummy_pcm = np.ones((480, 1), dtype=np.float32)

        # Feed 10 chunks to mic and loopback
        for _ in range(10):
            mic_cb(dummy_pcm, 480, None, None)
            loop_cb(dummy_pcm, 480, None, None)

        await asyncio.sleep(0.1)

        # Check chunks in pipeline.audio_queue
        sources_found = set()
        while not pipeline.audio_queue.empty():
            c = await pipeline.audio_queue.get()
            sources_found.add(c.source)

        assert "mic" in sources_found
        assert "loopback" in sources_found

        await pipeline.stop()
        assert pipeline.running is False
        assert len(pipeline._tasks) == 0


if __name__ == "__main__":
    pytest.main(["-v", __file__])
