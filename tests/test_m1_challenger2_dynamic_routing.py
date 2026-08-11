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
from services.stt.faster_whisper import FasterWhisperSTT
from services.stt.openai_stt import OpenAISTT


# ============================================================================
# 1. EMPIRICAL TEST: Dynamic Language Auto-Detection & Panel B Routing in Two-Way Mode
# ============================================================================

@pytest.mark.asyncio
async def test_twoway_english_loopback_speech_autodetect_and_panel_b_routing():
    """Verify English speech on loopback stream auto-detects language and routes EN -> HI on Panel B (COMPUTER_AUDIO)."""
    audio_input = MagicMock(spec=BaseAudioInput)
    vad = MagicMock(spec=BaseVAD)
    stt = MagicMock(spec=BaseSTT)
    translator = MagicMock(spec=BaseTranslator)
    tts = MagicMock(spec=BaseTTS)
    audio_output = MagicMock(spec=BaseAudioOutput)

    # Setup STT mock to verify lang_code passed when language auto-detect is active
    passed_lang_codes = []
    async def mock_transcribe(audio_bytes, is_final=True, language=None, initial_prompt=None):
        passed_lang_codes.append(language)
        return TranscriptionSegment(
            text="Hello everyone, thank you for joining the meeting.",
            is_final=True,
            start_time=datetime.now(),
            end_time=datetime.now(),
            language="en",
            confidence=0.96,
        )
    stt.transcribe = AsyncMock(side_effect=mock_transcribe)

    # Setup Translator mock to verify dynamic src/tgt routing
    translate_calls = []
    async def mock_translate(text, src, tgt, context=None):
        translate_calls.append((text, src, tgt))
        return TranslationResult(
            original_text=text,
            translated_text="आप सभी का बैठक में शामिल होने के लिए धन्यवाद।",
            source_lang=src,
            target_lang=tgt,
            is_final=True,
        )
    translator.translate = AsyncMock(side_effect=mock_translate)

    pipeline = Pipeline(
        audio_input=audio_input,
        vad=vad,
        stt=stt,
        translator=translator,
        tts=tts,
        audio_output=audio_output,
    )
    pipeline._translation_mode = "two_way"
    pipeline._source_lang = "EN"
    pipeline._target_lang = "HI"
    pipeline.running = True

    results = []
    pipeline.on_translation = lambda res: results.append(res)

    # Enqueue loopback job
    loopback_job = SttJob(
        source="loopback",
        audio=b"english_loopback_pcm",
        sample_rate=16000,
        is_final=True,
    )
    await pipeline.stt_queue.put(loopback_job)

    # Start STT and Translation workers briefly to process job
    stt_task = asyncio.create_task(pipeline._stt_worker())
    trans_task = asyncio.create_task(pipeline._translation_worker())

    await asyncio.sleep(0.3)
    pipeline.running = False
    stt_task.cancel()
    trans_task.cancel()

    # 1. Assert STT language auto-detection: lang_code should be None for loopback in two_way mode
    assert len(passed_lang_codes) == 1
    assert passed_lang_codes[0] is None, f"Expected lang_code=None for loopback auto-detect, got {passed_lang_codes[0]}"

    # 2. Assert Translation routing: EN -> HI
    assert len(translate_calls) == 1
    text, src, tgt = translate_calls[0]
    assert src.upper() == "EN"
    assert tgt.upper() == "HI"

    # 3. Assert Panel B routing: input_source == "COMPUTER_AUDIO"
    assert len(results) == 1
    res = results[0]
    assert res.input_source == "COMPUTER_AUDIO"
    assert res.source_lang == "EN"
    assert res.target_lang == "HI"


@pytest.mark.asyncio
async def test_twoway_hindi_loopback_speech_autodetect_and_panel_b_routing():
    """Verify Hindi speech on loopback stream auto-detects language and routes HI -> EN on Panel B (COMPUTER_AUDIO)."""
    audio_input = MagicMock(spec=BaseAudioInput)
    vad = MagicMock(spec=BaseVAD)
    stt = MagicMock(spec=BaseSTT)
    translator = MagicMock(spec=BaseTranslator)
    tts = MagicMock(spec=BaseTTS)
    audio_output = MagicMock(spec=BaseAudioOutput)

    passed_lang_codes = []
    async def mock_transcribe(audio_bytes, is_final=True, language=None, initial_prompt=None):
        passed_lang_codes.append(language)
        return TranscriptionSegment(
            text="नमस्ते, क्या आप मेरी आवाज सुन सकते हैं?",
            is_final=True,
            start_time=datetime.now(),
            end_time=datetime.now(),
            language="hi",
            confidence=0.94,
        )
    stt.transcribe = AsyncMock(side_effect=mock_transcribe)

    translate_calls = []
    async def mock_translate(text, src, tgt, context=None):
        translate_calls.append((text, src, tgt))
        return TranslationResult(
            original_text=text,
            translated_text="Hello, can you hear my voice?",
            source_lang=src,
            target_lang=tgt,
            is_final=True,
        )
    translator.translate = AsyncMock(side_effect=mock_translate)

    pipeline = Pipeline(
        audio_input=audio_input,
        vad=vad,
        stt=stt,
        translator=translator,
        tts=tts,
        audio_output=audio_output,
    )
    pipeline._translation_mode = "two_way"
    pipeline._source_lang = "EN"
    pipeline._target_lang = "HI"
    pipeline.running = True

    results = []
    pipeline.on_translation = lambda res: results.append(res)

    loopback_job = SttJob(
        source="loopback",
        audio=b"hindi_loopback_pcm",
        sample_rate=16000,
        is_final=True,
    )
    await pipeline.stt_queue.put(loopback_job)

    stt_task = asyncio.create_task(pipeline._stt_worker())
    trans_task = asyncio.create_task(pipeline._translation_worker())

    await asyncio.sleep(0.3)
    pipeline.running = False
    stt_task.cancel()
    trans_task.cancel()

    # 1. Assert STT language auto-detection: lang_code should be None
    assert len(passed_lang_codes) == 1
    assert passed_lang_codes[0] is None, f"Expected lang_code=None for loopback auto-detect, got {passed_lang_codes[0]}"

    # 2. Assert Translation routing: HI -> EN
    assert len(translate_calls) == 1
    text, src, tgt = translate_calls[0]
    assert src.upper() == "HI"
    assert tgt.upper() == "EN"

    # 3. Assert Panel B routing: input_source == "COMPUTER_AUDIO"
    assert len(results) == 1
    res = results[0]
    assert res.input_source == "COMPUTER_AUDIO"
    assert res.source_lang == "HI"
    assert res.target_lang == "EN"


@pytest.mark.asyncio
async def test_twoway_mic_speech_panel_a_routing():
    """Verify mic speech in two-way mode locks language to source_lang (EN) and routes EN -> HI on Panel A (VOICE)."""
    pipeline = Pipeline(
        audio_input=MagicMock(),
        vad=MagicMock(),
        stt=MagicMock(),
        translator=MagicMock(),
        tts=MagicMock(),
        audio_output=MagicMock(),
    )
    pipeline._translation_mode = "two_way"
    pipeline._source_lang = "EN"
    pipeline._target_lang = "HI"
    pipeline.running = True

    passed_lang_codes = []
    async def mock_transcribe(audio_bytes, is_final=True, language=None, initial_prompt=None):
        passed_lang_codes.append(language)
        return TranscriptionSegment(
            text="Testing local microphone input.",
            is_final=True,
            start_time=datetime.now(),
            end_time=datetime.now(),
            language="en",
            confidence=0.98,
        )
    pipeline._stt.transcribe = AsyncMock(side_effect=mock_transcribe)

    translate_calls = []
    async def mock_translate(text, src, tgt, context=None):
        translate_calls.append((text, src, tgt))
        return TranslationResult(
            original_text=text,
            translated_text="स्थानीय माइक्रोफ़ोन इनपुट का परीक्षण।",
            source_lang=src,
            target_lang=tgt,
            is_final=True,
        )
    pipeline._translator.translate = AsyncMock(side_effect=mock_translate)

    results = []
    pipeline.on_translation = lambda res: results.append(res)

    mic_job = SttJob(
        source="mic",
        audio=b"mic_pcm_data",
        sample_rate=16000,
        is_final=True,
    )
    await pipeline.stt_queue.put(mic_job)

    stt_task = asyncio.create_task(pipeline._stt_worker())
    trans_task = asyncio.create_task(pipeline._translation_worker())

    await asyncio.sleep(0.3)
    pipeline.running = False
    stt_task.cancel()
    trans_task.cancel()

    # 1. Mic input must set lang_code="en" (not None)
    assert len(passed_lang_codes) == 1
    assert passed_lang_codes[0] == "en"

    # 2. Translation must route EN -> HI
    assert len(translate_calls) == 1
    assert translate_calls[0][1].upper() == "EN"
    assert translate_calls[0][2].upper() == "HI"

    # 3. Panel A routing: input_source == "VOICE"
    assert len(results) == 1
    assert results[0].input_source == "VOICE"


# ============================================================================
# 2. EMPIRICAL TEST: ASR Prompt Sanitization & Quiet Audio Hallucination Prevention
# ============================================================================

@pytest.mark.asyncio
async def test_pipeline_stt_worker_prompt_sanitization():
    """Verify _stt_worker strips default prompt string 'TalkSync AI speech translation transcription' to None."""
    pipeline = Pipeline(
        audio_input=MagicMock(),
        vad=MagicMock(),
        stt=MagicMock(),
        translator=MagicMock(),
        tts=MagicMock(),
        audio_output=MagicMock(),
    )
    pipeline.running = True

    # Set settings with default prompt context
    settings_mock = MagicMock()
    settings_mock.context = "TalkSync AI speech translation transcription"
    settings_mock.keywords = ""
    pipeline._settings = settings_mock

    received_prompts = []
    async def mock_transcribe(audio_bytes, is_final=True, language=None, initial_prompt=None):
        received_prompts.append(initial_prompt)
        return None

    pipeline._stt.transcribe = AsyncMock(side_effect=mock_transcribe)

    job = SttJob(source="mic", audio=b"audio_bytes", sample_rate=16000, is_final=True)
    await pipeline.stt_queue.put(job)

    stt_task = asyncio.create_task(pipeline._stt_worker())
    await asyncio.sleep(0.2)
    pipeline.running = False
    stt_task.cancel()

    assert len(received_prompts) == 1
    assert received_prompts[0] is None, f"Expected initial_prompt=None, got '{received_prompts[0]}'"


def test_faster_whisper_rms_gate_and_prompt_sanitization_quiet_audio():
    """Verify FasterWhisperSTT rejects quiet/silent audio via RMS gate when initial_prompt is None."""
    with patch("faster_whisper.WhisperModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_model_cls.return_value = mock_model

        stt = FasterWhisperSTT(
            model_name="Systran/faster-whisper-small",
            device="cpu",
            rms_gate_threshold=0.005,
            initial_prompt=None,
        )

        # Generate quiet audio array (RMS 0.001 < threshold 0.005)
        quiet_audio = np.random.randn(16000).astype(np.float32) * 0.001
        actual_rms = float(np.sqrt(np.mean(quiet_audio.astype(np.float64) ** 2)))
        assert actual_rms < 0.005

        res = stt.transcribe(quiet_audio, sample_rate=16000, is_final=True, initial_prompt=None)
        
        # 1. Must return None (gated before Whisper model execution)
        assert res is None
        # 2. Whisper model transcribe method must not be called
        assert mock_model.transcribe.call_count == 0


@pytest.mark.asyncio
async def test_openai_stt_rms_gate_quiet_audio():
    """Verify OpenAISTT rejects quiet audio via RMS gate before calling OpenAI API."""
    stt = OpenAISTT()
    stt._rms_gate_threshold = 0.005
    stt._client = MagicMock()

    # Generate quiet audio array (RMS 0.001 < 0.005)
    quiet_audio = np.random.randn(16000).astype(np.float32) * 0.001

    res = await stt.transcribe(quiet_audio, sample_rate=16000, is_final=True, initial_prompt=None)

    # 1. Must return None
    assert res is None
    # 2. API call should not occur
    assert stt._client.audio.transcriptions.create.call_count == 0
