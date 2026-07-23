from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import AsyncIterator, Optional

import numpy as np

from app.interfaces import SynthesisResult, BaseTTS
from services.tts.voice_cache import find_voice_model
from utils.logger import get_logger

logger = get_logger("tts_piper")


class PiperTTS(BaseTTS):
    def __init__(self, settings):
        self.settings = settings
        self._voice = None
        self._voice_name = getattr(settings, "piper_voice", "en_US-lessac-medium")

    async def start(self) -> None:
        logger.info(f"Loading Piper TTS voice: {self._voice_name}")
        try:
            import piper
            model_path = find_voice_model(self._voice_name)
            if model_path is None:
                logger.warning(f"Piper voice {self._voice_name} not found locally")
                return
            config_path = f"{model_path}.json"
            if not os.path.exists(config_path):
                logger.warning(f"Piper config not found: {config_path}")
                return
            self._voice = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: piper.PiperVoice.load(
                    model_path, config_path=config_path, use_cuda=False,
                ),
            )
            logger.info(f"Piper TTS loaded: {self._voice_name}")
        except Exception as e:
            logger.warning(f"Piper TTS load failed: {e}")
            self._voice = None

    async def stop(self) -> None:
        self._voice = None

    async def synthesize(self, text: str, lang: str = "en") -> SynthesisResult:
        if self._voice is None:
            return SynthesisResult(
                audio_data=np.zeros(16000, dtype=np.float32).tobytes(),
                sample_rate=16000, duration_ms=1000.0,
            )
        try:
            audio_chunks = list(self._voice.synthesize(text))
            if not audio_chunks:
                return SynthesisResult(
                    audio_data=np.zeros(16000, dtype=np.float32).tobytes(),
                    sample_rate=16000, duration_ms=1000.0,
                )
            # piper-tts v1.5.0: AudioChunk has .audio_array (int16 PCM)
            # Older builds may have .audio_float_array — try both
            parts = []
            for c in audio_chunks:
                if hasattr(c, "audio_float_array"):
                    parts.append(np.asarray(c.audio_float_array, dtype=np.float32))
                elif hasattr(c, "audio_array"):
                    parts.append(np.asarray(c.audio_array, dtype=np.float32) / 32768.0)
                else:
                    # Fallback: treat as raw bytes
                    parts.append(np.frombuffer(bytes(c), dtype=np.int16).astype(np.float32) / 32768.0)
            audio_data = np.concatenate(parts) if parts else np.zeros(16000, dtype=np.float32)
            sr = self._voice.config.sample_rate
            return SynthesisResult(
                audio_data=audio_data.tobytes(),
                sample_rate=sr, duration_ms=(len(audio_data) / sr) * 1000,
            )
        except Exception as e:
            logger.error(f"Piper synthesis error: {e}")
            return SynthesisResult(
                audio_data=np.zeros(16000, dtype=np.float32).tobytes(),
                sample_rate=16000, duration_ms=1000.0,
            )

    async def synthesize_stream(self, text_stream, lang: str = "en") -> AsyncIterator[SynthesisResult]:
        async for text in text_stream:
            if text.strip():
                yield await self.synthesize(text.strip())

    async def set_voice(self, voice_id: str) -> None:
        self._voice_name = voice_id

    async def set_speed(self, speed: float) -> None:
        pass
