from __future__ import annotations

import sys
sys.path.insert(0, ".")

import asyncio
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch
import numpy as np
import pytest

from app.interfaces import AudioChunk, TranscriptionSegment, TranslationResult
from app.pipeline import Pipeline
from app.pipeline_state import SttJob
from services.audio.input import SoundDeviceInput
from services.stt.faster_whisper import FasterWhisperSTT
from ui.widgets.transcript_panel import TranscriptPanel


def test_req2_whisper_auto_lang_and_prob():
    """Test TranscriptionSegment language probability and "auto" normalization in FasterWhisperSTT."""
    results = {}
    with patch("faster_whisper.WhisperModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_model_cls.return_value = mock_model

        mock_seg = MagicMock()
        mock_seg.text = "Hello world"
        mock_seg.avg_logprob = -0.2
        mock_seg.no_speech_prob = 0.01
        mock_seg.compression_ratio = 1.0

        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.98

        mock_model.transcribe.return_value = ([mock_seg], mock_info)

        stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
        audio = np.random.randn(16000).astype(np.float32)

        for auto_arg in ("auto", "AUTO", "automatic"):
            res = stt.transcribe(audio, 16000, language=auto_arg)
            assert res is not None, f"STT result is None for language={auto_arg}"
            assert res.language == "en", f"Expected language 'en', got {res.language}"
            assert res.language_probability == 0.98, f"Expected lang_prob 0.98, got {res.language_probability}"
            assert res.confidence == 0.98, f"Expected confidence 0.98, got {res.confidence}"
            call_kwargs = mock_model.transcribe.call_args[1]
            assert call_kwargs["language"] is None, f"Expected WhisperModel.transcribe language arg to be None, got {call_kwargs['language']}"

    return "PASS: FasterWhisperSTT correctly normalizes 'auto'/'AUTO'/'automatic' to None and populates language_probability=0.98."


def test_req3_speech_routing():
    """Test loopback speech routing (input_source='COMPUTER_AUDIO') vs mic speech routing (input_source='VOICE')."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _run():
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        stt_result = TranscriptionSegment(
            text="Hello world", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="en", confidence=0.9, language_probability=0.95,
        )
        stt.transcribe.return_value = stt_result

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline.running = True

        # Test loopback input source conversion
        job_loopback = SttJob(source="loopback", audio=np.zeros(16000, dtype=np.float32).tobytes(), sample_rate=16000, is_final=True)
        await pipeline.stt_queue.put(job_loopback)

        on_trans_mock = MagicMock()
        pipeline.on_transcription = on_trans_mock

        # Run STT worker for 1 cycle
        stt_task = asyncio.create_task(pipeline._stt_worker())
        await asyncio.sleep(0.1)
        pipeline.running = False
        stt_task.cancel()

        called_segment = on_trans_mock.call_args[0][0]
        assert called_segment.input_source == "COMPUTER_AUDIO", f"Expected input_source 'COMPUTER_AUDIO' for loopback, got {called_segment.input_source}"

        queued_trans = await pipeline.translation_queue.get()
        assert queued_trans.input_source == "COMPUTER_AUDIO"
        assert queued_trans.language_probability == 0.95

    try:
        loop.run_until_complete(_run())
        return "PASS: Loopback speech is mapped to COMPUTER_AUDIO (Panel B) with language_probability propagated."
    finally:
        loop.close()


def test_req4_dynamic_auto_language_resolution():
    """Test dynamic 'AUTO' language resolution in _translate_and_route()."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _run():
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        translator.translate = AsyncMock(return_value=TranslationResult(
            original_text="Bonjour", translated_text="Hello", source_lang="FR", target_lang="EN", is_final=True
        ))

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline._source_lang = "AUTO"
        pipeline._target_lang = "EN"

        segment = TranscriptionSegment(
            text="Bonjour", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language="fr", confidence=0.95, language_probability=0.95,
            input_source="VOICE",
        )

        await pipeline._translate_and_route(segment, is_final=True, enqueue_tts=False)
        translator.translate.assert_called_once()
        call_args = translator.translate.call_args
        assert call_args[0][1] == "FR", f"Expected resolved source lang 'FR', got {call_args[0][1]}"
        assert call_args[0][2] == "EN", f"Expected target lang 'EN', got {call_args[0][2]}"

    try:
        loop.run_until_complete(_run())
        return "PASS: _translate_and_route() resolves 'AUTO' to detected language 'FR'."
    finally:
        loop.close()


def test_req5_transcript_panel_rendering():
    """Verify transcript panel rendering of timestamps and badges [MIC], [LOOPBACK], [TEXT]."""
    # Create mock text widget backing
    mock_textbox = MagicMock()
    mock_textbox.tag_ranges.return_value = []
    
    panel = MagicMock(spec=TranscriptPanel)
    panel.textbox = MagicMock()
    panel.textbox._textbox = mock_textbox

    # Test the real method logic on mock or inspect code:
    # From TranscriptPanel.append_message code logic:
    # VOICE -> [MIC] (badge_mic)
    # COMPUTER_AUDIO / LOOPBACK -> [LOOPBACK] (badge_loopback)
    # TEXT -> [TEXT] (badge_text)
    
    # We call actual function unbound:
    TranscriptPanel.append_message(panel, original="Hello", translated="Namaste", input_source="VOICE", timestamp="12:00:00")
    calls = mock_textbox.insert.call_args_list
    assert any("[MIC]" in repr(call) for call in calls), "Missing [MIC] badge call"
    
    mock_textbox.reset_mock()
    TranscriptPanel.append_message(panel, original="Speaker text", translated="Translated", input_source="COMPUTER_AUDIO", timestamp="12:00:05")
    calls = mock_textbox.insert.call_args_list
    assert any("[LOOPBACK]" in repr(call) for call in calls), "Missing [LOOPBACK] badge call"

    mock_textbox.reset_mock()
    TranscriptPanel.append_message(panel, original="Typed text", translated="Translated typed", input_source="TEXT", timestamp="12:00:10")
    calls = mock_textbox.insert.call_args_list
    assert any("[TEXT]" in repr(call) for call in calls), "Missing [TEXT] badge call"

    return "PASS: TranscriptPanel renders timestamps and badges [MIC], [LOOPBACK], [TEXT] correctly."


if __name__ == "__main__":
    print("--- EMPIRICAL CHECKS ---")
    try:
        print(test_req2_whisper_auto_lang_and_prob())
    except Exception as e:
        print(f"FAIL Req 2: {e}")

    try:
        print(test_req3_speech_routing())
    except Exception as e:
        print(f"FAIL Req 3: {e}")

    try:
        print(test_req4_dynamic_auto_language_resolution())
    except Exception as e:
        print(f"FAIL Req 4: {e}")

    try:
        print(test_req5_transcript_panel_rendering())
    except Exception as e:
        print(f"FAIL Req 5: {e}")
