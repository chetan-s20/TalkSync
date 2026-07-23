"""OpenAI Whisper STT implementation."""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import numpy as np

from core.interfaces import TranscriptionSegment
from config.settings import STTSettings
from utils.logger import get_logger

logger = get_logger("whisper_stt")


class WhisperSTT:
    def __init__(self, settings):
        self.settings = settings

    async def start(self, language: str = "auto") -> None:
        try:
            import whisper
            self._model = whisper.load_model("base")
        except Exception as e:
            logger.error(f"Whisper load failed: {e}")
            self._model = None

    async def stop(self) -> None:
        self._model = None

    async def stream(self, audio: Any) -> AsyncIterator[TranscriptionSegment]:
        yield await self.transcribe(audio)

    async def transcribe(self, audio: Any, **kwargs) -> TranscriptionSegment:
        if self._model is None:
            return TranscriptionSegment(
                text="", is_final=True,
                start_time=__import__("datetime").datetime.now(),
                end_time=__import__("datetime").datetime.now(),
                language="", confidence=0.0,
            )

        def _run():
            return self._model.transcribe(audio, fp16=False)

        try:
            result = await asyncio.get_running_loop().run_in_executor(None, _run)
            return TranscriptionSegment(
                text=(result.get("text") or "").strip(),
                is_final=True,
                start_time=__import__("datetime").datetime.now(),
                end_time=__import__("datetime").datetime.now(),
                language=result.get("language", ""),
                confidence=0.0,
            )
        except Exception as e:
            logger.error(f"Whisper transcribe error: {e}")
            return TranscriptionSegment(
                text="", is_final=True,
                start_time=__import__("datetime").datetime.now(),
                end_time=__import__("datetime").datetime.now(),
                language="", confidence=0.0,
            )
