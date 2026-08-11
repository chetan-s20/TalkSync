"""Unit tests for Partial Speech Segment Translation & Side-Effect Isolation."""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import pytest_asyncio

from app.interfaces import TranscriptionSegment, TranslationResult
from app.pipeline import Pipeline


@pytest.fixture
def mock_pipeline_components():
    audio_input = MagicMock()
    vad = MagicMock()
    stt = AsyncMock()
    translator = AsyncMock()
    translator.translate.side_effect = lambda text, src, tgt, context=None: MagicMock(
        translated_text=f"Translated[{text}]", source_lang=src, target_lang=tgt
    )
    tts = AsyncMock()
    audio_output = AsyncMock()
    context_engine = MagicMock()
    db = MagicMock()
    settings = MagicMock()
    settings.keywords = ""
    settings.ai_assistant_enabled = False

    return {
        "audio_input": audio_input,
        "vad": vad,
        "stt": stt,
        "translator": translator,
        "tts": tts,
        "audio_output": audio_output,
        "context_engine": context_engine,
        "db": db,
        "settings": settings,
    }


@pytest.mark.asyncio
async def test_partial_segment_routing_and_translation(mock_pipeline_components):
    """Verify non-final segment translates dynamically and emits on_translation callback."""
    comp = mock_pipeline_components
    pipeline = Pipeline(
        audio_input=comp["audio_input"],
        vad=comp["vad"],
        stt=comp["stt"],
        translator=comp["translator"],
        tts=comp["tts"],
        audio_output=comp["audio_output"],
        context_engine=comp["context_engine"],
        settings=comp["settings"],
        db=comp["db"],
    )

    emitted_results: list[TranslationResult] = []

    def handle_translation(result: TranslationResult):
        emitted_results.append(result)

    pipeline.on_translation = handle_translation
    pipeline.running = True

    partial_segment = TranscriptionSegment(
        text="Hello how",
        is_final=False,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="en",
        confidence=0.9,
        input_source="VOICE",
    )

    await pipeline._translate_and_route(partial_segment, is_final=False, enqueue_tts=False)

    assert len(emitted_results) == 1
    res = emitted_results[0]
    assert res.original_text == "Hello how"
    assert res.translated_text == "Translated[Hello how]"
    assert res.is_final is False


@pytest.mark.asyncio
async def test_partial_segment_side_effect_isolation(mock_pipeline_components):
    """Verify that is_final=False asserts NO TTS, NO DB save, and NO ContextEngine mutation."""
    comp = mock_pipeline_components
    pipeline = Pipeline(
        audio_input=comp["audio_input"],
        vad=comp["vad"],
        stt=comp["stt"],
        translator=comp["translator"],
        tts=comp["tts"],
        audio_output=comp["audio_output"],
        context_engine=comp["context_engine"],
        settings=comp["settings"],
        db=comp["db"],
    )
    pipeline.running = True
    pipeline._db_blocks = []

    partial_segment = TranscriptionSegment(
        text="Partial segment testing side effects",
        is_final=False,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="en",
        confidence=0.95,
        input_source="VOICE",
    )

    await pipeline._translate_and_route(partial_segment, is_final=False, enqueue_tts=False)

    # 1. Assert NO item put into tts_queue
    assert pipeline.tts_queue.empty()

    # 2. Assert NO DB block saved for partial segment
    assert len(pipeline._db_blocks) == 0

    # 3. Assert NO ContextEngine mutation for partial segment
    comp["context_engine"].add_segment.assert_not_called()


@pytest.mark.asyncio
async def test_final_segment_triggers_side_effects(mock_pipeline_components):
    """Verify that is_final=True triggers TTS, DB save, and ContextEngine mutation."""
    comp = mock_pipeline_components
    pipeline = Pipeline(
        audio_input=comp["audio_input"],
        vad=comp["vad"],
        stt=comp["stt"],
        translator=comp["translator"],
        tts=comp["tts"],
        audio_output=comp["audio_output"],
        context_engine=comp["context_engine"],
        settings=comp["settings"],
        db=comp["db"],
    )
    pipeline.running = True
    pipeline._db_blocks = []

    final_segment = TranscriptionSegment(
        text="Final segment complete sentence.",
        is_final=True,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="en",
        confidence=0.95,
        input_source="VOICE",
    )

    await pipeline._translate_and_route(final_segment, is_final=True, enqueue_tts=True)

    # 1. Assert item put into tts_queue
    assert not pipeline.tts_queue.empty()
    queued_tts = pipeline.tts_queue.get_nowait()
    assert queued_tts.is_final is True
    assert queued_tts.original_text == "Final segment complete sentence."

    # 2. Assert DB block appended
    assert len(pipeline._db_blocks) == 1
    assert pipeline._db_blocks[0]["original"] == "Final segment complete sentence."

    # 3. Assert ContextEngine memory updated
    comp["context_engine"].add_segment.assert_called_once()
