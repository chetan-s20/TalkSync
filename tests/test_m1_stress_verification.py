from __future__ import annotations

import asyncio
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.interfaces import AudioChunk, SynthesisResult, TranscriptionSegment
from app.pipeline import Pipeline
from services.tts.sarvam import SarvamTTS


class TestMuteGateQueuePurgeStress:
    """Stress tests for _activate_tts_mute_gate and _purge_loopback_queues in app/pipeline.py."""

    @pytest.mark.asyncio
    async def test_purge_loopback_queues_queue_full_race_condition(self):
        """Test _purge_loopback_queues when audio_queue or stt_queue are bounded and full."""
        pipeline = MagicMock(spec=Pipeline)
        pipeline.audio_queue = asyncio.Queue(maxsize=10)
        pipeline.stt_queue = asyncio.Queue(maxsize=10)
        pipeline._ignore_loopback_until = 0.0
        pipeline._ignore_mic_until = 0.0
        pipeline._state = MagicMock()
        pipeline._state.get_buffer.return_value = []
        pipeline._state.get_speech_tracker.return_value = MagicMock()

        pipeline._activate_tts_mute_gate = Pipeline._activate_tts_mute_gate.__get__(pipeline, Pipeline)
        pipeline._purge_loopback_queues = Pipeline._purge_loopback_queues.__get__(pipeline, Pipeline)

        # Fill audio_queue with 10 mic items
        for i in range(10):
            chunk = AudioChunk(data=b"1234", sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=10.0, source="mic")
            pipeline.audio_queue.put_nowait(chunk)

        pipeline._purge_loopback_queues()
        assert pipeline.audio_queue.qsize() == 10

    @pytest.mark.asyncio
    async def test_purge_loopback_queues_concurrent_producer_overflow_crash(self):
        """Empirically test if concurrent producer filling queue during purging causes QueueFull crash in _purge_loopback_queues."""
        pipeline = MagicMock(spec=Pipeline)
        pipeline.audio_queue = asyncio.Queue(maxsize=5)
        pipeline.stt_queue = asyncio.Queue(maxsize=5)
        pipeline._ignore_loopback_until = 0.0
        pipeline._ignore_mic_until = 0.0
        pipeline._state = MagicMock()
        pipeline._state.get_buffer.return_value = []
        pipeline._state.get_speech_tracker.return_value = MagicMock()

        pipeline._activate_tts_mute_gate = Pipeline._activate_tts_mute_gate.__get__(pipeline, Pipeline)
        pipeline._purge_loopback_queues = Pipeline._purge_loopback_queues.__get__(pipeline, Pipeline)

        # Put 5 mic items in audio_queue
        for _ in range(5):
            pipeline.audio_queue.put_nowait(
                AudioChunk(data=b"1234", sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=10.0, source="mic")
            )

        original_get_nowait = pipeline.audio_queue.get_nowait
        drain_count = 0

        def evil_get_nowait():
            nonlocal drain_count
            item = original_get_nowait()
            drain_count += 1
            if drain_count == 2:
                # Concurrent producer pushes 3 items into the queue while purger is draining!
                for _ in range(3):
                    try:
                        pipeline.audio_queue.put_nowait(
                            AudioChunk(data=b"PRODUCER", sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=10.0, source="mic")
                        )
                    except asyncio.QueueFull:
                        pass
            return item

        pipeline.audio_queue.get_nowait = evil_get_nowait

        raised_queue_full = False
        try:
            pipeline._purge_loopback_queues()
        except asyncio.QueueFull as e:
            raised_queue_full = True
            print(f"\nCRITICAL BUG VERIFIED: _purge_loopback_queues crashed with unhandled asyncio.QueueFull! {e}")

        # Assert that QueueFull was NOT raised because _purge_loopback_queues safely catches asyncio.QueueFull
        assert not raised_queue_full, "_purge_loopback_queues should not fail with QueueFull when concurrent producers overflow queue during re-insertion"

    @pytest.mark.asyncio
    async def test_purge_loopback_queues_heavy_concurrent_load(self):
        """Simulate 50 concurrent producers and callers under heavy load."""
        pipeline = MagicMock(spec=Pipeline)
        pipeline.audio_queue = asyncio.Queue(maxsize=100)
        pipeline.stt_queue = asyncio.Queue(maxsize=50)
        pipeline._ignore_loopback_until = 0.0
        pipeline._ignore_mic_until = 0.0
        pipeline._state = MagicMock()
        pipeline._state.get_buffer.return_value = [b"chunk1", b"chunk2"]
        pipeline._state.get_speech_tracker.return_value = MagicMock()

        pipeline._activate_tts_mute_gate = Pipeline._activate_tts_mute_gate.__get__(pipeline, Pipeline)
        pipeline._purge_loopback_queues = Pipeline._purge_loopback_queues.__get__(pipeline, Pipeline)

        running = True
        errors = []

        async def audio_producer():
            while running:
                src = "loopback" if np.random.rand() > 0.5 else "mic"
                chunk = AudioChunk(data=b"test", sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=10.0, source=src)
                try:
                    pipeline.audio_queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass
                await asyncio.sleep(0.001)

        async def stt_producer():
            while running:
                src = "loopback" if np.random.rand() > 0.5 else "mic"
                job = MagicMock(source=src)
                try:
                    pipeline.stt_queue.put_nowait(job)
                except asyncio.QueueFull:
                    pass
                await asyncio.sleep(0.001)

        async def mute_gate_caller():
            while running:
                try:
                    pipeline._activate_tts_mute_gate(0.1)
                except Exception as e:
                    errors.append(e)
                await asyncio.sleep(0.002)

        producers = [asyncio.create_task(audio_producer()) for _ in range(10)] + \
                    [asyncio.create_task(stt_producer()) for _ in range(10)] + \
                    [asyncio.create_task(mute_gate_caller()) for _ in range(5)]

        await asyncio.sleep(0.5)
        running = False
        await asyncio.gather(*producers, return_exceptions=True)

        if errors:
            print(f"\nCRITICAL BUG VERIFIED: _activate_tts_mute_gate raised exceptions under heavy load: {errors}")


class TestSarvamTTSConnectionPoolStress:
    """Stress tests for SarvamTTS persistent connection pooling in services/tts/sarvam.py."""

    @pytest.mark.asyncio
    async def test_sarvam_tts_concurrent_first_client_init_leak(self):
        """Verify if concurrent calls to _get_client when proxy/client initialization is async create multiple client instances."""
        settings = MagicMock()
        settings.sarvam_api_key = "test-key"
        settings.sarvam_voice = "ritu"
        settings.sarvam_lang = "hi-IN"
        settings.sarvam_timeout_s = 5.0

        tts = SarvamTTS(settings)
        tts._client = None

        created_clients = []

        import httpx
        original_async_client = httpx.AsyncClient

        def mock_create_client(*args, **kwargs):
            client = original_async_client(*args, **kwargs)
            created_clients.append(client)
            return client

        # If _get_client encounters fallback to create_async_client or async yielding
        with patch("services.tts.sarvam.create_async_client", side_effect=mock_create_client):
            with patch("httpx.AsyncClient", side_effect=Exception("Trigger fallback or async init")):
                tasks = [asyncio.create_task(tts._get_client()) for _ in range(10)]
                clients = await asyncio.gather(*tasks)

        # Clean up created clients
        for c in created_clients:
            await c.aclose()

        print(f"\n[EMPIRE TEST] Total clients created during fallback/async init: {len(created_clients)}")
        assert len(created_clients) == 1, f"Race condition in _get_client created {len(created_clients)} distinct clients concurrently!"

    @pytest.mark.asyncio
    async def test_sarvam_tts_rapid_concurrent_synthesis(self):
        """Verify SarvamTTS under 50 rapid concurrent synthesis requests."""
        settings = MagicMock()
        settings.sarvam_api_key = "test-key"
        settings.sarvam_voice = "ritu"
        settings.sarvam_lang = "hi-IN"
        settings.sarvam_timeout_s = 5.0

        tts = SarvamTTS(settings)
        await tts.start()

        import base64
        import io
        import wave

        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            wf.writeframes(np.zeros(22050, dtype=np.int16).tobytes())
        dummy_wav_b64 = base64.b64encode(wav_io.getvalue()).decode("utf-8")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"audios": [dummy_wav_b64]}

        client = await tts._get_client()
        with patch.object(client, "post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            tasks = [asyncio.create_task(tts.synthesize(f"Text {i}", "hi")) for i in range(50)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        await tts.stop()

        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Concurrent synthesis threw exceptions: {exceptions}"
        assert len(results) == 50
        assert mock_post.call_count == 50

    @pytest.mark.asyncio
    async def test_sarvam_tts_network_error_recovery(self):
        """Verify SarvamTTS recovers cleanly when HTTP post fails or times out."""
        settings = MagicMock()
        settings.sarvam_api_key = "test-key"
        settings.sarvam_voice = "ritu"
        settings.sarvam_lang = "hi-IN"
        settings.sarvam_timeout_s = 5.0

        tts = SarvamTTS(settings)
        await tts.start()

        client = await tts._get_client()
        import httpx
        with patch.object(client, "post", side_effect=httpx.ConnectTimeout("Connection timed out")):
            result = await tts.synthesize("Test failure", "hi")

        assert result is not None
        assert len(result.audio_data) > 0
        assert result.sample_rate == 8000
        assert result.duration_ms == 1000.0

        await tts.stop()
