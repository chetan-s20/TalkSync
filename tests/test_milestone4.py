from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from datetime import datetime

from app.interfaces import TranslationResult, TranscriptionSegment
from app.pipeline import Pipeline


class TestMilestone4TextInput:
    @pytest.mark.asyncio
    async def test_text_input_sends_to_translation_queue(self):
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline.running = True

        await pipeline.process_text_input("Hello world", source_lang="EN")
        assert pipeline.translation_queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_text_input_triggers_on_transcription(self):
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline.running = True

        on_transcription = MagicMock()
        pipeline.on_transcription = on_transcription

        await pipeline.process_text_input("Hello world", source_lang="EN")
        on_transcription.assert_called_once()
        segment = on_transcription.call_args[0][0]
        assert segment.text == "Hello world"
        assert segment.input_source == "TEXT"

    @pytest.mark.asyncio
    async def test_text_input_empty_ignored(self):
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline.running = True

        await pipeline.process_text_input("  ", source_lang="EN")
        assert pipeline.translation_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_text_input_long_rejected(self):
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)

        import pytest
        with pytest.raises(ValueError, match="5000"):
            await pipeline.process_text_input("x" * 5001, source_lang="EN")

    @pytest.mark.asyncio
    async def test_text_input_submit_text_input_when_loop_running(self):
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline.running = True

        loop = asyncio.get_running_loop()
        pipeline._loop = loop

        pipeline.submit_text_input("Hello", source_lang="EN")
        await asyncio.sleep(0.05)
        assert pipeline.translation_queue.qsize() >= 1

    @pytest.mark.asyncio
    async def test_text_mode_property(self):
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        assert pipeline.text_input_mode is False
        pipeline.text_input_mode = True
        assert pipeline.text_input_mode is True


class TestMilestone4DualPanel:
    @pytest.mark.asyncio
    async def test_translation_routes_to_correct_panel(self):
        audio_input = AsyncMock()
        vad = AsyncMock()
        stt = AsyncMock()
        translator = AsyncMock()
        tts = AsyncMock()
        audio_output = AsyncMock()

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline.running = True

        on_translation = MagicMock()
        pipeline.on_translation = on_translation
        pipeline._translation_mode = "one_way"

        now = datetime.now()
        segment = TranscriptionSegment(
            text="Hello",
            is_final=True,
            start_time=now,
            end_time=now,
            language="en",
            confidence=0.9,
            input_source="VOICE",
        )

        translator.translate.return_value = TranslationResult(
            original_text="Hello",
            translated_text="नमस्ते",
            source_lang="EN",
            target_lang="HI",
            is_final=True,
            input_source="VOICE",
        )

        await pipeline._translate_and_route(segment, is_final=True, enqueue_tts=False)
        on_translation.assert_called_once()
        result = on_translation.call_args[0][0]
        assert result.input_source == "VOICE"

    @pytest.mark.asyncio
    async def test_loopback_translation_routes_to_panel_b(self):
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
        pipeline._translation_mode = "one_way"

        on_translation = MagicMock()
        pipeline.on_translation = on_translation

        translator.translate.return_value = TranslationResult(
            original_text="Hola",
            translated_text="Hello",
            source_lang="HI",
            target_lang="EN",
            is_final=True,
            input_source="COMPUTER_AUDIO",
        )

        now = datetime.now()
        segment = TranscriptionSegment(
            text="Hola",
            is_final=True,
            start_time=now,
            end_time=now,
            language="",
            confidence=0.5,
            input_source="COMPUTER_AUDIO",
        )

        await pipeline._translate_and_route(segment, is_final=True, enqueue_tts=False)
        on_translation.assert_called_once()
        result = on_translation.call_args[0][0]
        assert result.input_source == "COMPUTER_AUDIO"
