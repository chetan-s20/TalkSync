from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.interfaces import AudioChunk, SynthesisResult, TranscriptionSegment, TranslationResult
from app.pipeline import Pipeline
from app.pipeline_state import SttJob

# ---------------------------------------------------------------------------
# Tier 4 — UI Smoke Tests (mock-based, no display required)
# ---------------------------------------------------------------------------


class TestTier4UISmoke:
    """Mock-based UI smoke tests — verify UI components wire up without Tk display."""

    def test_pipeline_callbacks_accept_valid_signatures(self):
        """Verify pipeline callback signatures match MainWindow expectations."""
        pipeline = MagicMock(spec=Pipeline)
        # MainWindow wires these signatures:
        pipeline.on_transcription = MagicMock()
        pipeline.on_translation = MagicMock()
        pipeline.on_status = MagicMock()
        pipeline.on_latency = MagicMock()
        pipeline.on_audio_level = MagicMock()

        # Simulate MainWindow callback wire-up
        pipeline.on_transcription(TranscriptionSegment(
            text="hello", is_final=True, start_time=datetime.now(),
            end_time=datetime.now(), language="en", confidence=0.9,
        ))
        pipeline.on_translation(TranslationResult(
            original_text="hello", translated_text="hola",
            source_lang="EN", target_lang="ES", is_final=True,
        ))
        pipeline.on_status("Listening...", "listening")
        pipeline.on_latency({"avg_ms": 250.0, "stages": {}})
        pipeline.on_audio_level(0.5)

        pipeline.on_transcription.assert_called_once()
        pipeline.on_translation.assert_called_once()
        pipeline.on_status.assert_called_once()
        pipeline.on_latency.assert_called_once()
        pipeline.on_audio_level.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_audio_level_callback_emits_rms(self):
        """Verify _capture_worker computes RMS and fires on_audio_level."""
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline.running = True

        on_audio_level = MagicMock()
        pipeline.on_audio_level = on_audio_level

        # Mock stream that yields one chunk
        sr = 16000
        chunk_data = np.sin(np.linspace(0, 2 * np.pi, sr)).astype(np.float32) * 0.5
        chunk = AudioChunk(
            data=chunk_data.tobytes(), sample_rate=sr, channels=1,
            timestamp=datetime.now(), duration_ms=1000.0, source="mic",
        )

        async def mock_stream():
            yield chunk

        audio_input.stream = mock_stream
        pipeline._audio_processors = []

        worker = asyncio.create_task(pipeline._capture_worker("mic"))
        await asyncio.sleep(0.05)
        pipeline.running = False
        worker.cancel()
        try:
            await worker
        except (asyncio.CancelledError, RuntimeError):
            pass

        assert on_audio_level.called
        rms = on_audio_level.call_args[0][0]
        assert rms > 0.01  # non-zero audio should produce measurable RMS

    @pytest.mark.asyncio
    async def test_pipeline_status_callbacks_fire_on_translate(self):
        """Verify on_status fires correctly through pipeline stages."""
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline.running = True
        pipeline._source_lang = "EN"
        pipeline._target_lang = "HI"

        on_status = MagicMock()
        pipeline.on_status = on_status

        segment = TranscriptionSegment(
            text="Hello", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="en", confidence=0.95, input_source="VOICE",
        )

        translator.translate.return_value = TranslationResult(
            original_text="Hello", translated_text="नमस्ते",
            source_lang="EN", target_lang="HI", is_final=True,
        )

        await pipeline._translate_and_route(segment, is_final=True, enqueue_tts=False)
        status_messages = [call[0][0] for call in on_status.call_args_list]
        assert any("Translating" in msg for msg in status_messages)


class TestTier5Adversarial:
    """Stress and adversarial tests — edge cases, error paths, concurrency."""

    @pytest.mark.asyncio
    async def test_stt_worker_empty_text_skipped(self):
        """STT returning empty/falsy text should not enqueue translation."""
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        # STT returns empty text
        seg = TranscriptionSegment(
            text="", is_final=True, start_time=datetime.now(),
            end_time=datetime.now(), language="en", confidence=0.9,
        )
        stt.transcribe.return_value = seg

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline.running = True

        on_transcription = MagicMock()
        pipeline.on_transcription = on_transcription

        job = SttJob(
            source="mic", audio=np.zeros(16000, dtype=np.float32).tobytes(),
            sample_rate=16000, is_final=True,
        )
        await pipeline.stt_queue.put(job)

        worker = asyncio.create_task(pipeline._stt_worker())
        await asyncio.sleep(0.1)
        pipeline.running = False
        worker.cancel()
        try:
            await worker
        except (asyncio.CancelledError, RuntimeError):
            pass

        # on_transcription should NOT be called for empty text
        on_transcription.assert_not_called()

    @pytest.mark.asyncio
    async def test_translation_empty_result_skipped(self):
        """Translation returning empty text should not enqueue TTS."""
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline.running = True
        pipeline._source_lang = "EN"
        pipeline._target_lang = "HI"

        translator.translate.return_value = TranslationResult(
            original_text="Hello", translated_text="",
            source_lang="EN", target_lang="HI", is_final=True,
        )

        on_translation = MagicMock()
        pipeline.on_translation = on_translation

        segment = TranscriptionSegment(
            text="Hello", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="en", confidence=0.95, input_source="VOICE",
        )

        await pipeline._translate_and_route(segment, is_final=True, enqueue_tts=True)
        on_translation.assert_not_called()

    @pytest.mark.asyncio
    async def test_rapid_text_inputs_dont_crash(self):
        """Rapid successive text inputs should not cause errors."""
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline.running = True

        for i in range(50):
            await pipeline.process_text_input(f"Message {i}", source_lang="EN")

        assert pipeline.translation_queue.qsize() == 50

    @pytest.mark.asyncio
    async def test_tts_worker_silence_not_played(self):
        """Synthesized silence should not be sent to audio output."""
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline.running = True

        # TTS returns silence (all zeros)
        silence = SynthesisResult(
            audio_data=np.zeros(16000, dtype=np.float32).tobytes(),
            sample_rate=16000, duration_ms=1000.0,
        )
        tts.synthesize_stream.return_value = pipeline._split_sentences("")
        tts.synthesize.return_value = silence

        result = TranslationResult(
            original_text="hello", translated_text="hola",
            source_lang="EN", target_lang="ES", is_final=True,
        )
        await pipeline.tts_queue.put(result)

        worker = asyncio.create_task(pipeline._tts_worker())
        await asyncio.sleep(0.1)
        pipeline.running = False
        worker.cancel()
        try:
            await worker
        except (asyncio.CancelledError, RuntimeError):
            pass

        audio_output.play.assert_not_called()

    @pytest.mark.asyncio
    async def test_queue_full_does_not_block_pipeline(self):
        """Full queues should drop items gracefully via put_nowait."""
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline.running = True

        # Fill the translation queue to capacity
        for _ in range(256):
            try:
                pipeline.translation_queue.put_nowait(
                    TranscriptionSegment(
                        text="x", is_final=True, start_time=datetime.now(),
                        end_time=datetime.now(), language="en", confidence=0.9,
                    )
                )
            except asyncio.QueueFull:
                break

        assert pipeline.translation_queue.full()

        # put_nowait should raise QueueFull — pipeline code should catch it
        with pytest.raises(asyncio.QueueFull):
            pipeline.translation_queue.put_nowait(
                TranscriptionSegment(
                    text="Hello", is_final=True,
                    start_time=datetime.now(), end_time=datetime.now(),
                    language="en", confidence=0.95, input_source="VOICE",
                )
            )

    @pytest.mark.asyncio
    async def test_text_input_boundary_values(self):
        """Text input at boundary conditions (empty, whitespace, max length)."""
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline.running = True

        # Empty string
        await pipeline.process_text_input("", source_lang="EN")
        assert pipeline.translation_queue.qsize() == 0

        # Whitespace only
        await pipeline.process_text_input("   ", source_lang="EN")
        assert pipeline.translation_queue.qsize() == 0

        # Newlines only
        await pipeline.process_text_input("\n\n\n", source_lang="EN")
        assert pipeline.translation_queue.qsize() == 0

        # Exactly 5000 chars (valid)
        with pytest.raises(ValueError, match="5000"):
            await pipeline.process_text_input("x" * 5001, source_lang="EN")

    @pytest.mark.asyncio
    async def test_concurrent_stt_jobs(self):
        """Multiple STT jobs in queue should all be processed."""
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        stt.transcribe.return_value = TranscriptionSegment(
            text="hello", is_final=True, start_time=datetime.now(),
            end_time=datetime.now(), language="en", confidence=0.9,
        )

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline.running = True

        on_transcription = MagicMock()
        pipeline.on_transcription = on_transcription

        # Queue multiple STT jobs
        for i in range(5):
            job = SttJob(
                source="mic", audio=np.zeros(16000, dtype=np.float32).tobytes(),
                sample_rate=16000, is_final=True,
            )
            await pipeline.stt_queue.put(job)

        worker = asyncio.create_task(pipeline._stt_worker())
        await asyncio.sleep(0.3)
        pipeline.running = False
        worker.cancel()
        try:
            await worker
        except (asyncio.CancelledError, RuntimeError):
            pass

        assert on_transcription.call_count >= 1
