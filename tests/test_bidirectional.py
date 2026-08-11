from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.interfaces import (
    AudioChunk,
    BaseAudioInput,
    BaseAudioOutput,
    BaseSTT,
    BaseTTS,
    BaseTranslator,
    BaseVAD,
    TranscriptionSegment,
    TranslationResult,
)
from app.pipeline import Pipeline
from app.pipeline_state import SttJob


async def _empty_async_gen():
    if False:
        yield None


@pytest.mark.asyncio
async def test_bidirectional_translation_pipeline():
    audio_input = MagicMock(spec=BaseAudioInput)
    audio_input.start = AsyncMock()
    audio_input.stop = AsyncMock()
    audio_input.stream = MagicMock(return_value=_empty_async_gen())
    audio_input.stream_loopback = MagicMock(return_value=_empty_async_gen())

    vad = MagicMock(spec=BaseVAD)
    vad.start = AsyncMock()
    vad.stop = AsyncMock()

    stt = MagicMock(spec=BaseSTT)
    stt.start = AsyncMock()
    stt.stop = AsyncMock()

    async def mock_transcribe(audio_bytes, is_final=True, language=None, initial_prompt=None):
        if audio_bytes == b"mic_audio_data":
            return TranscriptionSegment(
                text="Hello world, this is a test.",
                is_final=True,
                start_time=datetime.now(),
                end_time=datetime.now(),
                language="en",
                confidence=0.95,
            )
        else:
            return TranscriptionSegment(
                text="नमस्ते दोस्तों, आप कैसे हैं",
                is_final=True,
                start_time=datetime.now(),
                end_time=datetime.now(),
                language="hi",
                confidence=0.92,
            )

    stt.transcribe = AsyncMock(side_effect=mock_transcribe)

    translator = MagicMock(spec=BaseTranslator)
    translator.start = AsyncMock()
    translator.stop = AsyncMock()

    async def mock_translate(text, src, tgt, context=None):
        if src.upper() == "EN":
            return TranslationResult(
                original_text=text,
                translated_text="नमस्ते दुनिया, यह एक परीक्षण है।",
                source_lang="EN",
                target_lang="HI",
                is_final=True,
            )
        else:
            return TranslationResult(
                original_text=text,
                translated_text="Hello friends, how are you",
                source_lang="HI",
                target_lang="EN",
                is_final=True,
            )

    translator.translate = AsyncMock(side_effect=mock_translate)

    tts = MagicMock(spec=BaseTTS)
    tts.start = AsyncMock()
    tts.stop = AsyncMock()
    tts.synthesize_stream = MagicMock(return_value=_empty_async_gen())

    audio_output = MagicMock(spec=BaseAudioOutput)
    audio_output.start = AsyncMock()
    audio_output.stop = AsyncMock()

    pipeline = Pipeline(
        audio_input=audio_input,
        vad=vad,
        stt=stt,
        translator=translator,
        tts=tts,
        audio_output=audio_output,
    )

    results = []

    def on_translation_cb(res: TranslationResult):
        results.append(res)

    pipeline.on_translation = on_translation_cb

    await pipeline.start("EN", "HI", loopback=True)

    # Feed synthetic English mic audio job
    mic_job = SttJob(
        source="mic",
        audio=b"mic_audio_data",
        sample_rate=16000,
        is_final=True,
    )

    # Feed synthetic Hindi loopback audio job
    loopback_job = SttJob(
        source="loopback",
        audio=b"loopback_audio_data",
        sample_rate=16000,
        is_final=True,
    )

    await pipeline.stt_queue.put(mic_job)
    await pipeline.stt_queue.put(loopback_job)

    # Allow worker loop to process jobs
    await asyncio.sleep(0.6)

    await pipeline.stop()

    panel_a_results = [r for r in results if getattr(r, "input_source", "") == "VOICE" and r.is_final]
    panel_b_results = [r for r in results if getattr(r, "input_source", "") == "COMPUTER_AUDIO" and r.is_final]

    assert len(panel_a_results) > 0, "Panel A (VOICE mic) should produce at least one TranslationResult"
    res_a = panel_a_results[0]
    assert res_a.source_lang.upper() == "EN"
    assert res_a.target_lang.upper() == "HI"
    assert res_a.translated_text != ""
    assert res_a.input_source == "VOICE"

    assert len(panel_b_results) > 0, "Panel B (COMPUTER_AUDIO loopback) should produce at least one TranslationResult"
    res_b = panel_b_results[0]
    assert res_b.source_lang.upper() == "HI"
    assert res_b.target_lang.upper() == "EN"
    assert res_b.translated_text != ""
    assert res_b.input_source == "COMPUTER_AUDIO"


@pytest.mark.asyncio
async def test_dynamic_language_routing_loopback_english():
    pipeline = Pipeline(
        audio_input=MagicMock(),
        vad=MagicMock(),
        stt=MagicMock(),
        translator=MagicMock(),
        tts=MagicMock(),
        audio_output=MagicMock(),
    )

    translated_results = []
    pipeline.on_translation = lambda res: translated_results.append(res)
    pipeline._translator.translate = AsyncMock(
        return_value=TranslationResult(
            original_text="English meeting speech",
            translated_text="अंग्रेजी बैठक भाषण",
            source_lang="EN",
            target_lang="HI",
            is_final=True,
        )
    )

    segment = TranscriptionSegment(
        text="English meeting speech",
        is_final=True,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="en",
        confidence=0.9,
        input_source="COMPUTER_AUDIO",
    )

    await pipeline._translate_and_route(segment, is_final=True, enqueue_tts=False)

    assert len(translated_results) == 1
    res = translated_results[0]
    assert res.input_source == "COMPUTER_AUDIO"
    assert res.source_lang == "EN"
    assert res.target_lang == "HI"


@pytest.mark.asyncio
async def test_per_panel_speaker_gating():
    pipeline = Pipeline(
        audio_input=MagicMock(),
        vad=MagicMock(),
        stt=MagicMock(),
        translator=MagicMock(),
        tts=MagicMock(),
        audio_output=MagicMock(),
    )
    pipeline._translator.translate = AsyncMock(
        return_value=TranslationResult(
            original_text="Test",
            translated_text="परीक्षण",
            source_lang="EN",
            target_lang="HI",
            is_final=True,
        )
    )

    # Disable Panel A speaker
    pipeline.tts_enabled_a = False
    pipeline.tts_enabled_b = True

    seg_a = TranscriptionSegment(
        text="Test mic",
        is_final=True,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="en",
        confidence=0.9,
        input_source="VOICE",
    )

    await pipeline._translate_and_route(seg_a, is_final=True, enqueue_tts=True)

    # Should NOT be enqueued to tts_queue because tts_enabled_a is False
    assert pipeline.tts_queue.empty()

    # Enable Panel A, Disable Panel B speaker
    pipeline.tts_enabled_a = True
    pipeline.tts_enabled_b = False

    seg_b = TranscriptionSegment(
        text="Test loopback",
        is_final=True,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="hi",
        confidence=0.9,
        input_source="COMPUTER_AUDIO",
    )

    await pipeline._translate_and_route(seg_b, is_final=True, enqueue_tts=True)

    # Should NOT be enqueued to tts_queue because tts_enabled_b is False
    assert pipeline.tts_queue.empty()
