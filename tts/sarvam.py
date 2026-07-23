"""Sarvam AI TTS engine."""
import asyncio
import numpy as np
from typing import AsyncIterator
from core.interfaces import SynthesisResult
from tts.base import BaseTTS
from utils.logger import get_logger

logger = get_logger("tts_sarvam")


class SarvamTTS(BaseTTS):

    def __init__(self, settings):
        self.settings = settings
        self._api_key = getattr(settings, "sarvam_api_key", "")
        self._voice = getattr(settings, "sarvam_voice", "shubh")
        self._lang = "hi-IN"

    async def start(self) -> None:
        logger.info(f"Sarvam TTS initialized: voice={self._voice}, lang={self._lang}")

    async def stop(self) -> None:
        pass

    async def synthesize(self, text: str) -> SynthesisResult:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.sarvam.ai/v1/text-to-speech",
                    json={"text": text, "voice": self._voice, "language": self._lang},
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    import base64
                    audio_bytes = base64.b64decode(data.get("audio", ""))
                    if audio_bytes:
                        sr = 24000
                        audio = np.frombuffer(audio_bytes, dtype=np.float32)
                        return SynthesisResult(
                            audio_data=audio.tobytes(), sample_rate=sr,
                            duration_ms=(len(audio) / sr) * 1000, is_streaming=False,
                        )
        except Exception as e:
            logger.warning(f"Sarvam TTS failed: {e}")
        return SynthesisResult(
            audio_data=np.zeros(16000, dtype=np.float32).tobytes(),
            sample_rate=16000, duration_ms=1000.0, is_streaming=False,
        )

    async def synthesize_stream(self, text_stream, target_lang: str | None = None) -> AsyncIterator[SynthesisResult]:
        async for text in text_stream:
            if text.strip():
                yield await self.synthesize(text.strip())

    async def set_voice(self, voice_id: str) -> None:
        self._voice = voice_id

    async def set_speed(self, speed: float) -> None:
        pass

    async def set_language(self, lang: str) -> None:
        self._lang = lang
