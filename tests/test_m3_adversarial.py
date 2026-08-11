from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.interfaces import (
    TranscriptionSegment,
    TranslationResult,
)
from app.pipeline import Pipeline


@pytest.fixture
def mock_pipeline():
    pipeline = Pipeline(
        audio_input=MagicMock(),
        vad=MagicMock(),
        stt=MagicMock(),
        translator=MagicMock(),
        tts=MagicMock(),
        audio_output=MagicMock(),
    )
    return pipeline


@pytest.mark.asyncio
async def test_translate_and_route_mic_english(mock_pipeline):
    """Mic English speech -> EN to HI routing."""
    results = []
    mock_pipeline.on_translation = lambda r: results.append(r)
    mock_pipeline._translator.translate = AsyncMock(
        return_value=TranslationResult(
            original_text="Hello world",
            translated_text="नमस्ते दुनिया",
            source_lang="EN",
            target_lang="HI",
            is_final=True,
        )
    )

    seg = TranscriptionSegment(
        text="Hello world",
        is_final=True,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="en",
        confidence=0.9,
        input_source="VOICE",
    )

    await mock_pipeline._translate_and_route(seg, is_final=True, enqueue_tts=True)

    assert len(results) == 1
    res = results[0]
    assert res.source_lang == "EN"
    assert res.target_lang == "HI"
    assert res.input_source == "VOICE"
    assert mock_pipeline.tts_queue.qsize() == 1


@pytest.mark.asyncio
async def test_translate_and_route_mic_hindi(mock_pipeline):
    """Mic Hindi speech -> HI to EN routing."""
    results = []
    mock_pipeline.on_translation = lambda r: results.append(r)
    mock_pipeline._translator.translate = AsyncMock(
        return_value=TranslationResult(
            original_text="नमस्ते दुनिया",
            translated_text="Hello world",
            source_lang="HI",
            target_lang="EN",
            is_final=True,
        )
    )

    seg = TranscriptionSegment(
        text="नमस्ते दुनिया",
        is_final=True,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="hi",
        confidence=0.9,
        input_source="VOICE",
    )

    await mock_pipeline._translate_and_route(seg, is_final=True, enqueue_tts=True)

    assert len(results) == 1
    res = results[0]
    assert res.source_lang == "HI"
    assert res.target_lang == "EN"
    assert res.input_source == "VOICE"
    assert mock_pipeline.tts_queue.qsize() == 1


@pytest.mark.asyncio
async def test_translate_and_route_loopback_english(mock_pipeline):
    """Loopback English speech -> EN to HI routing, Panel B (COMPUTER_AUDIO)."""
    results = []
    mock_pipeline.on_translation = lambda r: results.append(r)
    mock_pipeline._translator.translate = AsyncMock(
        return_value=TranslationResult(
            original_text="English meeting participant",
            translated_text="अंग्रेजी बैठक participant",
            source_lang="EN",
            target_lang="HI",
            is_final=True,
        )
    )

    seg = TranscriptionSegment(
        text="English meeting participant",
        is_final=True,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="en",
        confidence=0.95,
        input_source="COMPUTER_AUDIO",
    )

    await mock_pipeline._translate_and_route(seg, is_final=True, enqueue_tts=True)

    assert len(results) == 1
    res = results[0]
    assert res.source_lang == "EN"
    assert res.target_lang == "HI"
    assert res.input_source == "COMPUTER_AUDIO"
    assert mock_pipeline.tts_queue.qsize() == 1


@pytest.mark.asyncio
async def test_translate_and_route_loopback_hindi(mock_pipeline):
    """Loopback Hindi speech -> HI to EN routing, Panel B (COMPUTER_AUDIO)."""
    results = []
    mock_pipeline.on_translation = lambda r: results.append(r)
    mock_pipeline._translator.translate = AsyncMock(
        return_value=TranslationResult(
            original_text="हिंदी बैठक participant",
            translated_text="Hindi meeting participant",
            source_lang="HI",
            target_lang="EN",
            is_final=True,
        )
    )

    seg = TranscriptionSegment(
        text="हिंदी बैठक participant",
        is_final=True,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="hi",
        confidence=0.95,
        input_source="COMPUTER_AUDIO",
    )

    await mock_pipeline._translate_and_route(seg, is_final=True, enqueue_tts=True)

    assert len(results) == 1
    res = results[0]
    assert res.source_lang == "HI"
    assert res.target_lang == "EN"
    assert res.input_source == "COMPUTER_AUDIO"
    assert mock_pipeline.tts_queue.qsize() == 1


@pytest.mark.asyncio
async def test_speaker_toggle_matrix(mock_pipeline):
    """Test all 4 combinations of tts_enabled_a and tts_enabled_b."""
    mock_pipeline._translator.translate = AsyncMock(
        return_value=TranslationResult(
            original_text="Test",
            translated_text="Test Out",
            source_lang="EN",
            target_lang="HI",
            is_final=True,
        )
    )

    seg_a_mic = TranscriptionSegment(
        text="Mic text", is_final=True, start_time=datetime.now(), end_time=datetime.now(),
        language="en", confidence=0.9, input_source="VOICE"
    )
    seg_a_text = TranscriptionSegment(
        text="Typed text", is_final=True, start_time=datetime.now(), end_time=datetime.now(),
        language="en", confidence=1.0, input_source="TEXT"
    )
    seg_b_loop = TranscriptionSegment(
        text="Loop text", is_final=True, start_time=datetime.now(), end_time=datetime.now(),
        language="hi", confidence=0.9, input_source="COMPUTER_AUDIO"
    )

    # Combination 1: A=True, B=True -> All enqueue
    mock_pipeline.tts_enabled_a = True
    mock_pipeline.tts_enabled_b = True
    await mock_pipeline._translate_and_route(seg_a_mic, is_final=True, enqueue_tts=True)
    await mock_pipeline._translate_and_route(seg_a_text, is_final=True, enqueue_tts=True)
    await mock_pipeline._translate_and_route(seg_b_loop, is_final=True, enqueue_tts=True)
    assert mock_pipeline.tts_queue.qsize() == 3

    # Empty queue
    while not mock_pipeline.tts_queue.empty():
        mock_pipeline.tts_queue.get_nowait()

    # Combination 2: A=False, B=True -> Only B enqueues
    mock_pipeline.tts_enabled_a = False
    mock_pipeline.tts_enabled_b = True
    await mock_pipeline._translate_and_route(seg_a_mic, is_final=True, enqueue_tts=True)
    await mock_pipeline._translate_and_route(seg_a_text, is_final=True, enqueue_tts=True)
    assert mock_pipeline.tts_queue.qsize() == 0
    await mock_pipeline._translate_and_route(seg_b_loop, is_final=True, enqueue_tts=True)
    assert mock_pipeline.tts_queue.qsize() == 1

    # Empty queue
    while not mock_pipeline.tts_queue.empty():
        mock_pipeline.tts_queue.get_nowait()

    # Combination 3: A=True, B=False -> Only A enqueues
    mock_pipeline.tts_enabled_a = True
    mock_pipeline.tts_enabled_b = False
    await mock_pipeline._translate_and_route(seg_b_loop, is_final=True, enqueue_tts=True)
    assert mock_pipeline.tts_queue.qsize() == 0
    await mock_pipeline._translate_and_route(seg_a_mic, is_final=True, enqueue_tts=True)
    assert mock_pipeline.tts_queue.qsize() == 1

    # Empty queue
    while not mock_pipeline.tts_queue.empty():
        mock_pipeline.tts_queue.get_nowait()

    # Combination 4: A=False, B=False -> None enqueue
    mock_pipeline.tts_enabled_a = False
    mock_pipeline.tts_enabled_b = False
    await mock_pipeline._translate_and_route(seg_a_mic, is_final=True, enqueue_tts=True)
    await mock_pipeline._translate_and_route(seg_a_text, is_final=True, enqueue_tts=True)
    await mock_pipeline._translate_and_route(seg_b_loop, is_final=True, enqueue_tts=True)
    assert mock_pipeline.tts_queue.qsize() == 0


@pytest.mark.asyncio
async def test_low_confidence_filtering(mock_pipeline):
    """Low confidence segments (< 0.4) must be dropped before translation."""
    results = []
    mock_pipeline.on_translation = lambda r: results.append(r)
    seg = TranscriptionSegment(
        text="Low confidence audio",
        is_final=True,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="en",
        confidence=0.35,
        input_source="VOICE",
    )

    await mock_pipeline._translate_and_route(seg, is_final=True, enqueue_tts=True)

    assert len(results) == 0
    assert mock_pipeline.tts_queue.empty()
    mock_pipeline._translator.translate.assert_not_called()


@pytest.mark.asyncio
async def test_empty_translation_result(mock_pipeline):
    """Empty translated text returned by translator must not enqueue TTS or crash."""
    results = []
    mock_pipeline.on_translation = lambda r: results.append(r)
    mock_pipeline._translator.translate = AsyncMock(
        return_value=TranslationResult(
            original_text="Some text",
            translated_text="   ",
            source_lang="EN",
            target_lang="HI",
            is_final=True,
        )
    )

    seg = TranscriptionSegment(
        text="Some text",
        is_final=True,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="en",
        confidence=0.8,
        input_source="VOICE",
    )

    await mock_pipeline._translate_and_route(seg, is_final=True, enqueue_tts=True)

    assert len(results) == 0
    assert mock_pipeline.tts_queue.empty()


@pytest.mark.asyncio
async def test_translation_timeout_resilience(mock_pipeline):
    """Translation timeout must be handled gracefully without crashing pipeline."""
    mock_pipeline._translator.translate = AsyncMock(side_effect=asyncio.TimeoutError())

    seg = TranscriptionSegment(
        text="Slow translation",
        is_final=True,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="en",
        confidence=0.9,
        input_source="VOICE",
    )

    # Should not raise exception
    await mock_pipeline._translate_and_route(seg, is_final=True, enqueue_tts=True)
    assert mock_pipeline.tts_queue.empty()


@pytest.mark.asyncio
async def test_tts_queue_full_resilience(mock_pipeline):
    """When tts_queue is full, enqueue attempt logs warning without raising exception."""
    mock_pipeline._translator.translate = AsyncMock(
        return_value=TranslationResult(
            original_text="Test",
            translated_text="Test Out",
            source_lang="EN",
            target_lang="HI",
            is_final=True,
        )
    )
    mock_pipeline.tts_enabled_a = True

    # Fill tts_queue to maxsize
    for i in range(mock_pipeline.tts_queue.maxsize):
        mock_pipeline.tts_queue.put_nowait(
            TranslationResult(original_text=f"t{i}", translated_text=f"out{i}", source_lang="EN", target_lang="HI", is_final=True)
        )

    seg = TranscriptionSegment(
        text="Overflow text",
        is_final=True,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="en",
        confidence=0.9,
        input_source="VOICE",
    )

    await mock_pipeline._translate_and_route(seg, is_final=True, enqueue_tts=True)
    assert mock_pipeline.tts_queue.full()


@pytest.mark.asyncio
async def test_language_code_variants(mock_pipeline):
    """Test language codes like en-US, hi-IN, english, hindi, etc."""
    mock_pipeline._translator.translate = AsyncMock(
        return_value=TranslationResult(
            original_text="Test",
            translated_text="Res",
            source_lang="EN",
            target_lang="HI",
            is_final=True,
        )
    )

    # Loopback speech with language = "English"
    seg_loop_eng = TranscriptionSegment(
        text="Hello meeting", is_final=True, start_time=datetime.now(), end_time=datetime.now(),
        language="English", confidence=0.9, input_source="COMPUTER_AUDIO"
    )
    res_loop_eng = []
    mock_pipeline.on_translation = lambda r: res_loop_eng.append(r)
    await mock_pipeline._translate_and_route(seg_loop_eng, is_final=True, enqueue_tts=False)
    assert res_loop_eng[0].source_lang == "EN"
    assert res_loop_eng[0].target_lang == "HI"

    # Mic speech with language = "Hindi"
    seg_mic_hin = TranscriptionSegment(
        text="नमस्ते", is_final=True, start_time=datetime.now(), end_time=datetime.now(),
        language="Hindi", confidence=0.9, input_source="VOICE"
    )
    res_mic_hin = []
    mock_pipeline.on_translation = lambda r: res_mic_hin.append(r)
    await mock_pipeline._translate_and_route(seg_mic_hin, is_final=True, enqueue_tts=False)
    assert res_mic_hin[0].source_lang == "HI"
    assert res_mic_hin[0].target_lang == "EN"
