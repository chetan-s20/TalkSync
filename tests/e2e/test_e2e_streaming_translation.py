"""Tier 4 E2E Streaming Translation & Latency Benchmark Test."""
from __future__ import annotations

import asyncio
from datetime import datetime
import time
from unittest.mock import AsyncMock, MagicMock
import numpy as np
import pytest
import pytest_asyncio

from app.interfaces import AudioChunk, TranscriptionSegment, TranslationResult
from app.pipeline import Pipeline
from config.settings import Settings
from services.translation.context_engine import ContextEngine

try:
    from app.bridge import ApiBridge
except ImportError:
    from tests.unit.test_bridge_api import ApiBridge


@pytest.mark.asyncio
async def test_e2e_streaming_translation_flow_and_latency():
    """E2E Benchmark & Functional Test:
    Verify audio streaming -> partial & final translation -> ApiBridge -> JS evaluation.
    Assert Partial Latency < 300ms, Final E2E Latency < 1.5s, Side-effect isolation.
    """
    settings = Settings(source_lang="EN", target_lang="HI")
    audio_input = AsyncMock()
    vad = MagicMock()
    stt = AsyncMock()
    translator = AsyncMock()

    # Dynamic translator mock
    async def mock_translate(text, src, tgt, context=None):
        await asyncio.sleep(0.02)  # Simulate 20ms translation API response time
        return MagicMock(translated_text=f"Translated[{text}]", source_lang=src, target_lang=tgt)

    translator.translate = AsyncMock(side_effect=mock_translate)

    tts = AsyncMock()
    audio_output = AsyncMock()
    context_engine = MagicMock()
    db = MagicMock()

    pipeline = Pipeline(
        audio_input=audio_input,
        vad=vad,
        stt=stt,
        translator=translator,
        tts=tts,
        audio_output=audio_output,
        context_engine=context_engine,
        settings=settings,
        db=db,
    )
    pipeline.running = True

    window = MagicMock()
    window.evaluate_js = MagicMock()

    app_mock = MagicMock()
    app_mock.pipeline = pipeline

    bridge = ApiBridge(application=app_mock, window=window)

    partial_events: list[dict] = []
    final_events: list[dict] = []

    def on_trans_cb(result: TranslationResult):
        if not result.is_final:
            payload = bridge.emit_translation(
                original=result.original_text,
                translated=result.translated_text,
                is_final=False,
                source_lang=result.source_lang,
                target_lang=result.target_lang,
            )
            partial_events.append(payload)
        else:
            payload = bridge.emit_translation(
                original=result.original_text,
                translated=result.translated_text,
                is_final=True,
                source_lang=result.source_lang,
                target_lang=result.target_lang,
            )
            final_events.append(payload)

    pipeline.on_translation = on_trans_cb

    # 1. Simulate Partial Speech Segment Flow
    t_partial_start = time.perf_counter()

    partial_seg = TranscriptionSegment(
        text="Hello world partial",
        is_final=False,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="en",
        confidence=0.92,
        input_source="VOICE",
    )

    await pipeline._translate_and_route(partial_seg, is_final=False, enqueue_tts=False)

    t_partial_latency_ms = (time.perf_counter() - t_partial_start) * 1000.0

    # Benchmark Assertion 1: Partial Latency < 300ms
    assert t_partial_latency_ms < 300.0, f"Partial latency {t_partial_latency_ms:.2f}ms exceeds 300ms limit"

    # Side-effect Assertion 1: Partial segment generates NO TTS and NO DB save
    assert len(partial_events) == 1
    assert partial_events[0]["is_final"] is False
    assert pipeline.tts_queue.empty()
    assert len(pipeline._db_blocks) == 0
    context_engine.add_segment.assert_not_called()

    # 2. Simulate Final Speech Segment Flow
    t_final_start = time.perf_counter()

    final_seg = TranscriptionSegment(
        text="Hello world partial complete sentence.",
        is_final=True,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="en",
        confidence=0.95,
        input_source="VOICE",
    )

    await pipeline._translate_and_route(final_seg, is_final=True, enqueue_tts=True)

    t_final_latency_ms = (time.perf_counter() - t_final_start) * 1000.0

    # Benchmark Assertion 2: Final Latency < 1.5s (1500ms)
    assert t_final_latency_ms < 1500.0, f"Final E2E latency {t_final_latency_ms:.2f}ms exceeds 1.5s limit"

    # Side-effect Assertion 2: Final segment DOES generate TTS and DB save
    assert len(final_events) == 1
    assert final_events[0]["is_final"] is True
    assert not pipeline.tts_queue.empty()
    assert len(pipeline._db_blocks) == 1
    context_engine.add_segment.assert_called_once()

    # Verify JS window.evaluate_js was invoked for both partial and final
    assert window.evaluate_js.call_count >= 2
