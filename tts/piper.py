"""Piper TTS engine using piper-tts v1.5+ API."""
import asyncio
import json
import os
from pathlib import Path
from typing import AsyncIterator, Optional

import numpy as np
import onnxruntime

from core.interfaces import SynthesisResult
from tts.base import BaseTTS
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
            model_path = self._find_voice_model(self._voice_name)
            if model_path is None:
                logger.warning(f"Piper voice {self._voice_name} not found locally")
                return
            config_path = f"{model_path}.json"
            if not os.path.exists(config_path):
                logger.warning(f"Piper voice config not found: {config_path}")
                return
            loop = asyncio.get_event_loop()
            self._voice = await loop.run_in_executor(
                None,
                lambda: piper.PiperVoice.load(
                    model_path, config_path=config_path, use_cuda=False,
                ),
            )
            logger.info(f"Piper TTS voice loaded: {self._voice_name}")
        except Exception as e:
            logger.warning(f"Piper TTS load failed: {e}")
            self._voice = None

    def _find_voice_model(self, voice_name: str) -> Optional[str]:
        search_dirs = [
            os.getcwd(),
            os.path.join(os.getcwd(), "voices"),
            os.path.join(os.path.dirname(__file__), "..", "..", "voices"),
            os.path.expanduser("~"),
            os.path.expanduser("~/.local/share/piper/voices"),
        ]
        for base in search_dirs:
            for root, dirs, files in os.walk(base):
                for f in files:
                    if f.endswith(".onnx") and voice_name.replace("-", "_") in f:
                        return os.path.join(root, f)
        return None

    async def stop(self) -> None:
        self._voice = None

    async def synthesize(self, text: str) -> SynthesisResult:
        if self._voice is None:
            return SynthesisResult(
                audio_data=np.zeros(16000, dtype=np.float32).tobytes(),
                sample_rate=16000, duration_ms=1000.0, is_streaming=False,
            )
        try:
            from piper.voice import AudioChunk as PiperAudioChunk
            audio_chunks: list[PiperAudioChunk] = list(self._voice.synthesize(text))
            if not audio_chunks:
                return SynthesisResult(
                    audio_data=np.zeros(16000, dtype=np.float32).tobytes(),
                    sample_rate=16000, duration_ms=1000.0, is_streaming=False,
                )
            audio_data = np.concatenate([c.audio_float_array for c in audio_chunks])
            sr = self._voice.config.sample_rate
            return SynthesisResult(
                audio_data=audio_data.tobytes(),
                sample_rate=sr, duration_ms=(len(audio_data) / sr) * 1000,
                is_streaming=False,
            )
        except Exception as e:
            logger.error(f"Piper synthesis error: {e}")
            return SynthesisResult(
                audio_data=np.zeros(16000, dtype=np.float32).tobytes(),
                sample_rate=16000, duration_ms=1000.0, is_streaming=False,
            )

    async def synthesize_stream(self, text_stream, target_lang: str | None = None) -> AsyncIterator[SynthesisResult]:
        async for text in text_stream:
            if text.strip():
                yield await self.synthesize(text.strip())

    async def set_voice(self, voice_id: str) -> None:
        self._voice_name = voice_id

    async def set_speed(self, speed: float) -> None:
        pass
