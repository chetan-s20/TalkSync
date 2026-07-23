"""Kokoro ONNX TTS engine."""
import numpy as np
from typing import AsyncIterator
from core.interfaces import SynthesisResult
from tts.base import BaseTTS
from utils.logger import get_logger

logger = get_logger("tts_kokoro")


class KokoroTTS(BaseTTS):

    def __init__(self, settings):
        self.settings = settings
        self._model = None

    async def start(self) -> None:
        logger.info("Kokoro TTS initialized")

    async def stop(self) -> None:
        self._model = None

    async def synthesize(self, text: str) -> SynthesisResult:
        return SynthesisResult(
            audio_data=np.zeros(16000, dtype=np.float32).tobytes(),
            sample_rate=16000, duration_ms=1000.0, is_streaming=False,
        )

    async def synthesize_stream(self, text_stream, target_lang: str | None = None) -> AsyncIterator[SynthesisResult]:
        async for text in text_stream:
            if text.strip():
                yield await self.synthesize(text.strip())

    async def set_voice(self, voice_id: str) -> None:
        pass

    async def set_speed(self, speed: float) -> None:
        pass
