"""OpenAI TTS (tts-1) streaming service for TalkSync AI."""
from __future__ import annotations

import asyncio
import io
import time
import httpx
import numpy as np
from typing import AsyncIterator, Optional, Any

from app.interfaces import BaseTTS, SynthesisResult
from utils.logger import get_logger

logger = get_logger("openai_tts")


class OpenAITTS(BaseTTS):
    """Ultra-realistic, low-latency streaming TTS powered by OpenAI's tts-1 model."""

    OPENAI_SPEECH_URL = "https://api.openai.com/v1/audio/speech"

    def __init__(
        self,
        settings: Any = None,
        api_key: Optional[str] = None,
        model: str = "tts-1",
        voice: str = "alloy",
    ) -> None:
        self.settings = getattr(settings, "tts", settings) if settings else None
        
        # Extract OpenAI API key
        if not api_key:
            if hasattr(settings, "openai") and getattr(settings.openai, "api_key", ""):
                api_key = settings.openai.api_key
            elif hasattr(settings, "stt") and hasattr(settings, "openai"):
                api_key = getattr(settings.openai, "api_key", "")
            else:
                try:
                    from config.settings import load_settings
                    s = load_settings()
                    api_key = s.openai.api_key
                except Exception:
                    pass

        self.api_key = api_key or ""
        self.model = model
        self.voice = voice
        self.sample_rate = 24000
        self._client: Optional[httpx.AsyncClient] = None
        self._running = False
        logger.info(f"OpenAITTS initialized: model='{self.model}', voice='{self.voice}'")

    async def start(self) -> None:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(8.0, connect=3.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        self._running = True

    async def stop() -> None:
        self._running = False
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def synthesize(self, text: str, lang: str = "en") -> SynthesisResult:
        clean_text = text.strip()
        if not clean_text:
            return SynthesisResult(audio_data=b"", sample_rate=self.sample_rate, duration_ms=0.0)

        if not self.api_key:
            raise ValueError("OpenAI API key missing for OpenAITTS")

        if self._client is None or self._client.is_closed:
            await self.start()

        payload = {
            "model": self.model,
            "input": clean_text,
            "voice": self.voice,
            "response_format": "pcm",  # 24kHz 16-bit mono PCM raw bytes
            "speed": float(getattr(self.settings, "speed", 1.0) if self.settings else 1.0),
        }

        t_start = time.perf_counter()
        try:
            resp = await self._client.post(self.OPENAI_SPEECH_URL, json=payload)
            duration_ms = (time.perf_counter() - t_start) * 1000.0

            if resp.status_code != 200:
                logger.error(f"OpenAI TTS error HTTP {resp.status_code}: {resp.text}")
                return SynthesisResult(audio_data=b"", sample_rate=self.sample_rate, duration_ms=0.0)

            raw_pcm = resp.content
            # Convert 16-bit PCM bytes to float32 numpy array
            pcm_int16 = np.frombuffer(raw_pcm, dtype=np.int16)
            pcm_float32 = (pcm_int16.astype(np.float32) / 32767.0).tobytes()

            audio_duration_ms = (len(pcm_int16) / self.sample_rate) * 1000.0
            logger.info(f"OpenAI TTS synthesized {audio_duration_ms:.0f}ms audio in {duration_ms:.1f}ms TTFB")
            
            return SynthesisResult(
                audio_data=pcm_float32,
                sample_rate=self.sample_rate,
                duration_ms=audio_duration_ms,
            )
        except Exception as e:
            logger.error(f"OpenAI TTS synthesis failed: {e}")
            return SynthesisResult(audio_data=b"", sample_rate=self.sample_rate, duration_ms=0.0)

    async def synthesize_stream(self, text_stream: AsyncIterator[str], lang: str = "en") -> AsyncIterator[SynthesisResult]:
        async for chunk in text_stream:
            if chunk and chunk.strip():
                res = await self.synthesize(chunk, lang)
                if res.audio_data and len(res.audio_data) > 0:
                    yield res

    async def set_voice(self, voice_id: str) -> None:
        if voice_id:
            self.voice = voice_id

    async def set_speed(self, speed: float) -> None:
        pass
