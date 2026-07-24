"""Silero VAD wrapper for speech detection."""
from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator, Optional

import numpy as np

from core.interfaces import AudioChunk, VADResult, BaseVAD
from config.settings import VADSettings
from utils.logger import get_logger

logger = get_logger("vad")


class SileroVAD(BaseVAD):
    def __init__(self, settings: VADSettings):
        self.settings = settings
        self._model = None
        self._running = False
        self._speech_active = False
        self._speech_start: Optional[float] = None
        self._speech_end: Optional[float] = None
        self._last_activity = 0.0
        self._threshold = getattr(settings, "threshold", 0.6)
        self._min_speech_ms = getattr(settings, "min_speech_duration_ms", 250)
        self._min_silence_ms = getattr(settings, "min_silence_duration_ms", 550)

    async def start(self) -> None:
        try:
            import torch
            self._model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                onnx=False,
            )
            self._running = True
            self._model.eval()
            logger.info("Silero VAD loaded")
        except Exception as e:
            logger.error(f"Silero VAD failed to load: {e}")
            self._model = None
            self._running = True

    async def stop(self) -> None:
        self._running = False
        self._model = None

    def is_speech_active(self) -> bool:
        return self._speech_active

    def _eval_512_frame(self, frame_512: np.ndarray) -> float:
        if self._model is None:
            return 0.0
        try:
            import torch
            audio_writable = np.ascontiguousarray(frame_512, dtype=np.float32)
            tensor = torch.from_numpy(audio_writable).float().unsqueeze(0)
            with torch.no_grad():
                prob = float(self._model(tensor, 16000).item())
            return prob
        except Exception as e:
            logger.debug(f"Silero VAD frame eval error: {e}")
            return 0.0

    def is_speech(self, audio: np.ndarray) -> tuple[bool, float]:
        if audio is None or len(audio) == 0:
            return False, 0.0

        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
        NOISE_FLOOR_RMS = 0.005
        if rms < NOISE_FLOOR_RMS:
            return False, 0.0

        threshold = getattr(self, "_threshold", 0.55)

        if self._model is None:
            is_sp = bool(np.mean(np.abs(audio)) > 0.01 and rms >= NOISE_FLOOR_RMS)
            prob = 0.8 if is_sp else 0.2
            return is_sp, prob

        chunk_len = len(audio)
        frame_probs = []

        if chunk_len < 512:
            padded = np.pad(audio, (0, 512 - chunk_len))
            frame_probs.append(self._eval_512_frame(padded))
        else:
            step = 512
            for i in range(0, chunk_len, step):
                frame = audio[i : i + 512]
                if len(frame) < 512:
                    frame = np.pad(frame, (0, 512 - len(frame)))
                prob = self._eval_512_frame(frame)
                frame_probs.append(prob)

        max_prob = float(max(frame_probs)) if frame_probs else 0.0
        is_speech_bool = max_prob >= threshold
        return is_speech_bool, max_prob

    async def process(self, chunk: AudioChunk) -> AsyncIterator[VADResult]:
        if not self._running:
            return
        try:
            audio = np.frombuffer(chunk.data, dtype=np.float32)
            duration_ms = chunk.duration_ms or 0.0
            now = time.time()

            is_speech, prob = self.is_speech(audio)

            if is_speech:
                if not self._speech_active:
                    self._speech_active = True
                    self._speech_start = now
                self._last_activity = now
                speech_end = None
            else:
                if self._speech_active:
                    silence_duration = (now - self._last_activity) * 1000
                    if silence_duration >= self._min_silence_ms:
                        self._speech_active = False
                        self._speech_end = self._last_activity
                        speech_end = self._speech_end
                    else:
                        speech_end = None
                else:
                    speech_end = None

            yield VADResult(
                is_speech=is_speech,
                speech_start=self._speech_start,
                speech_end=speech_end,
                confidence=prob,
                chunk=chunk,
            )
        except Exception as e:
            logger.debug(f"VAD process error: {e}")
            yield VADResult(
                is_speech=False,
                speech_start=None,
                speech_end=None,
                confidence=0.0,
                chunk=chunk,
            )

