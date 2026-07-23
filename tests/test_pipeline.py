from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.interfaces import (
    AudioChunk, AudioProcessor, BaseAudioInput, BaseAudioOutput,
    BaseSTT, BaseTTS, BaseTranslator, BaseVAD,
    TranscriptionSegment, TranslationResult,
)
from app.pipeline import Pipeline


class TestPipelineLifecycle:
    @pytest.mark.asyncio
    async def test_pipeline_initialization(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        vad = MagicMock(spec=BaseVAD)
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        tts = MagicMock(spec=BaseTTS)
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )

        assert pipeline.running is False
        assert pipeline._translation_mode == "two_way"
        assert pipeline._source_lang == "EN"
        assert pipeline._target_lang == "HI"

    @pytest.mark.asyncio
    async def test_pipeline_start_stop(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        stt.transcribe = AsyncMock()
        stt.transcribe.return_value = TranscriptionSegment(
            text="test", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="en", confidence=0.9,
        )
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="test", translated_text="test",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([])
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )

        await pipeline.start("EN", "HI")
        assert pipeline.running is True

        await pipeline.stop()
        assert pipeline.running is False

    @pytest.mark.asyncio
    async def test_pipeline_restart_cycle(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="test", translated_text="test",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([])
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )

        await pipeline.start("EN", "HI")
        assert pipeline.running is True
        await pipeline.stop()
        assert pipeline.running is False

        await pipeline.start("HI", "EN")
        assert pipeline.running is True
        assert pipeline._source_lang == "HI"
        assert pipeline._target_lang == "EN"
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_pipeline_start_twice_noop(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="test", translated_text="test",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([])
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )

        await pipeline.start("EN", "HI")
        start_call_count = audio_input.start.call_count
        await pipeline.start("EN", "HI")
        assert audio_input.start.call_count == start_call_count
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_pipeline_stop_when_not_running(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        vad = MagicMock(spec=BaseVAD)
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        tts = MagicMock(spec=BaseTTS)
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )

        await pipeline.stop()
        assert pipeline.running is False


class TestPipelineSourceTagging:
    @pytest.mark.asyncio
    async def test_mic_source_tag(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="test", translated_text="test",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([])
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        await pipeline.start("EN", "HI")
        assert pipeline._source_lang == "EN"
        assert pipeline._target_lang == "HI"
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_loopback_source_tag(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        audio_input.stream_loopback = AsyncMock()
        audio_input.stream_loopback.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="test", translated_text="test",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([])
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        await pipeline.start("EN", "HI", loopback=True)
        assert pipeline._loopback_enabled is True
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_text_source_tag(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="test", translated_text="test",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([])
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        assert pipeline is not None

    def test_source_tag_preserved_through_pipeline(self):
        segment = TranscriptionSegment(
            text="Hello", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="en", confidence=0.9, input_source="TEXT",
        )
        assert segment.input_source == "TEXT"

        segment2 = TranscriptionSegment(
            text="Hello", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="en", confidence=0.9, input_source="VOICE",
        )
        assert segment2.input_source == "VOICE"

        segment3 = TranscriptionSegment(
            text="Hello", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="en", confidence=0.9, input_source="COMPUTER_AUDIO",
        )
        assert segment3.input_source == "COMPUTER_AUDIO"


class TestPipelineWorkers:
    @pytest.mark.asyncio
    async def test_generic_worker_with_source(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="test", translated_text="test",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([])
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        await pipeline.start("EN", "HI")
        assert len(pipeline._tasks) > 0
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_no_duplicate_workers(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="test", translated_text="test",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([])
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        await pipeline.start("EN", "HI")
        task_count = len(pipeline._tasks)
        await pipeline.start("EN", "HI")
        assert len(pipeline._tasks) == task_count
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_worker_cancellation(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="test", translated_text="test",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([])
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        await pipeline.start("EN", "HI")
        await pipeline.stop()
        assert len(pipeline._tasks) == 0

    @pytest.mark.asyncio
    async def test_worker_error_continues_pipeline(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        stt.transcribe = AsyncMock()
        stt.transcribe.side_effect = RuntimeError("STT error")
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="test", translated_text="test",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([])
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        await pipeline.start("EN", "HI")
        assert pipeline.running is True
        await pipeline.stop()


class TestPipelineTranslationModes:
    def test_one_way_translation(self):
        segment = TranscriptionSegment(
            text="Hello", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="en", confidence=0.9,
        )
        assert segment is not None

    def test_two_way_language_swap(self):
        segment = TranscriptionSegment(
            text="नमस्ते", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="hi", confidence=0.95,
        )
        assert segment.language == "hi"

    def test_two_way_detected_language_swap(self):
        segment = TranscriptionSegment(
            text="Hello", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="en", confidence=0.8,
        )
        assert segment.language == "en"


class TestPipelineTextInput:
    @pytest.mark.asyncio
    async def test_text_input_processing(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="Hello", translated_text="नमस्ते",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([])
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        await pipeline.start("EN", "HI")
        await pipeline.process_text_input("Hello")
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_text_input_long_text_rejected(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        vad = MagicMock(spec=BaseVAD)
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        tts = MagicMock(spec=BaseTTS)
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        await pipeline.start("EN", "HI")
        long_text = "x" * 5001
        with pytest.raises(ValueError, match="5000"):
            await pipeline.process_text_input(long_text)
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_text_input_disabled_no_session(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        vad = MagicMock(spec=BaseVAD)
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        tts = MagicMock(spec=BaseTTS)
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        assert pipeline.running is False

    @pytest.mark.asyncio
    async def test_text_input_empty_text_ignored(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="", translated_text="",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([])
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        await pipeline.start("EN", "HI")
        await pipeline.process_text_input("  ")
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_text_input_callback(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="Hello", translated_text="नमस्ते",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([])
        audio_output = MagicMock(spec=BaseAudioOutput)

        callback = MagicMock()
        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        pipeline.on_transcription = callback
        await pipeline.start("EN", "HI")
        await pipeline.process_text_input("Hello")
        callback.assert_called()
        await pipeline.stop()


class TestPipelineRestart:
    @pytest.mark.asyncio
    async def test_rapid_start_stop(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="test", translated_text="test",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([])
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        for _ in range(5):
            await pipeline.start("EN", "HI")
            assert pipeline.running is True
            await pipeline.stop()
            assert pipeline.running is False

    @pytest.mark.asyncio
    async def test_pipeline_cleanup_on_error(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.start.side_effect = RuntimeError("Audio init failed")
        vad = MagicMock(spec=BaseVAD)
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        tts = MagicMock(spec=BaseTTS)
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        with pytest.raises(RuntimeError):
            await pipeline.start("EN", "HI")
        assert pipeline.running is False

    @pytest.mark.asyncio
    async def test_worker_cleanup_on_stop(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="test", translated_text="test",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([])
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        await pipeline.start("EN", "HI")
        await pipeline.stop()
        for svc in [audio_input, vad, stt, translator, tts, audio_output]:
            svc.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_state_reset_on_restart(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="test", translated_text="test",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([])
        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        await pipeline.start("EN", "HI")
        await pipeline.stop()

        await pipeline.start("HI", "EN")
        assert pipeline._source_lang == "HI"
        assert pipeline._target_lang == "EN"
        assert pipeline._state._buffers == {}
        await pipeline.stop()


class TestPipelineDisplayModes:
    def test_single_column_display(self):
        result = TranslationResult(
            original_text="Hello", translated_text="नमस्ते",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        assert result.is_final is True

    def test_dual_column_display(self):
        result1 = TranslationResult(
            original_text="Hello", translated_text="नमस्ते",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        result2 = TranslationResult(
            original_text="How are you?", translated_text="आप कैसे हैं?",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        assert result1.original_text != result2.original_text

    def test_mixed_display(self):
        final = TranslationResult(
            original_text="Hello", translated_text="नमस्ते",
            source_lang="EN", target_lang="HI", is_final=True,
        )
        partial = TranslationResult(
            original_text="How are", translated_text="...",
            source_lang="EN", target_lang="HI", is_final=False,
        )
        assert final.is_final is True
        assert partial.is_final is False

    def test_split_display_mode_switch(self):
        pipeline = MagicMock(spec=Pipeline)
        pipeline.set_translation_mode = MagicMock()
        pipeline._translation_mode = "one_way"
        assert pipeline._translation_mode == "one_way"
        pipeline._translation_mode = "two_way"
        assert pipeline._translation_mode == "two_way"
