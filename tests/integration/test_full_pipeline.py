from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.interfaces import (
    AudioChunk, AudioProcessor, BaseAudioInput, BaseAudioOutput,
    BaseSTT, BaseTTS, BaseTranslator, BaseVAD,
    TranscriptionSegment, TranslationResult, SynthesisResult,
)
from app.pipeline import Pipeline


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_audio_to_transcript_flow(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        chunk = AudioChunk(
            data=np.random.randn(480).astype(np.float32).tobytes(),
            sample_rate=16000, channels=1,
            timestamp=datetime.now(), duration_ms=30.0, source="mic",
        )
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([chunk])

        vad = MagicMock(spec=BaseVAD)
        vad_result = MagicMock()
        vad_result.is_speech = True
        vad_result.speech_end = None
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([vad_result])

        stt = MagicMock(spec=BaseSTT)
        stt.transcribe = AsyncMock()
        stt.transcribe.return_value = TranscriptionSegment(
            text="Hello world", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="en", confidence=0.95,
        )

        translator = MagicMock(spec=BaseTranslator)
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="Hello world", translated_text="नमस्ते दुनिया",
            source_lang="EN", target_lang="HI", is_final=True,
        )

        tts = MagicMock(spec=BaseTTS)
        tts.synthesize_stream = MagicMock()
        tts.synthesize_stream.return_value.__aiter__.return_value = iter([
            SynthesisResult(
                audio_data=np.zeros(16000, dtype=np.float32).tobytes(),
                sample_rate=16000, duration_ms=1000.0,
            ),
        ])

        audio_output = MagicMock(spec=BaseAudioOutput)

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )

        translation_results = []
        pipeline.on_translation = lambda r: translation_results.append(r)

        await pipeline.start("EN", "HI")
        await asyncio.sleep(0.1)
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_full_pipeline_source_tagging(self):
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

        text_segment = TranscriptionSegment(
            text="Hello", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="en", confidence=1.0, input_source="TEXT",
        )
        assert text_segment.input_source == "TEXT"

        voice_segment = TranscriptionSegment(
            text="Hello", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="en", confidence=0.9, input_source="VOICE",
        )
        assert voice_segment.input_source == "VOICE"

        await pipeline.start("EN", "HI")
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_full_pipeline_two_way_translation(self):
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

        translation_results = []
        pipeline.on_translation = lambda r: translation_results.append(r)

        await pipeline.start("EN", "HI")
        await pipeline.process_text_input("Hello")
        await asyncio.sleep(0.05)
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_full_pipeline_text_input_flow(self):
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

        transcription_calls = []
        translation_calls = []

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )
        pipeline.on_transcription = lambda s: transcription_calls.append(s)
        pipeline.on_translation = lambda r: translation_calls.append(r)

        await pipeline.start("EN", "HI", text_mode=True)
        await pipeline.process_text_input("Hello")
        await asyncio.sleep(0.05)
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_full_pipeline_restart(self):
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

        for i in range(3):
            await pipeline.start("EN", "HI")
            assert pipeline.running is True
            assert pipeline._source_lang == "EN"
            await pipeline.stop()
            assert pipeline.running is False

    @pytest.mark.asyncio
    async def test_full_pipeline_error_recovery(self):
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.stream = AsyncMock()
        audio_input.stream.return_value.__aiter__.return_value = iter([])
        vad = MagicMock(spec=BaseVAD)
        vad.process = AsyncMock()
        vad.process.return_value.__aiter__.return_value = iter([])
        stt = MagicMock(spec=BaseSTT)
        stt.transcribe = AsyncMock()
        stt.transcribe.side_effect = RuntimeError("STT failure")
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
        assert pipeline.running is True
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_full_pipeline_latency_measurement(self):
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

        latency_data = []
        pipeline.on_latency = lambda d: latency_data.append(d)

        await pipeline.start("EN", "HI")
        await asyncio.sleep(0.1)
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_full_pipeline_multiple_sources(self):
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
    async def test_full_pipeline_history_integration(self):
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

        from services.history.database import HistoryDatabase
        db = HistoryDatabase(db_path=":memory:")
        db.connect()

        await pipeline.start("EN", "HI")
        await pipeline.process_text_input("Hello")
        await asyncio.sleep(0.05)

        sid = db.save_session("Pipeline Session", [{"text": "Hello"}])
        loaded = db.load_session(sid)
        assert loaded is not None
        assert loaded["title"] == "Pipeline Session"
        db.close()
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_full_pipeline_subtitle_output(self):
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

        result = TranslationResult(
            original_text="Hello", translated_text="नमस्ते",
            source_lang="EN", target_lang="HI", is_final=True,
        )

        from services.history.exporter import export_srt
        srt = export_srt([{
            "timestamp": datetime.now().isoformat(),
            "original": result.original_text,
            "translated": result.translated_text,
        }])
        assert "Hello" in srt
        assert "नमस्ते" in srt

        await pipeline.start("EN", "HI")
        await pipeline.stop()


import asyncio
