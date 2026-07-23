from __future__ import annotations

from typing import Optional

import numpy as np

from app.interfaces import AudioProcessor
from utils.logger import get_logger

logger = get_logger("rnnoise")


class RNNoiseProcessor(AudioProcessor):
    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self._rnnoise: Optional[object] = None
        if enabled:
            try:
                from audio.rnnoise_native import RNNoiseDenoiser
                self._rnnoise = RNNoiseDenoiser()
                logger.info("RNNoise loaded")
            except Exception as e:
                logger.warning(f"RNNoise unavailable: {e}")
                self.enabled = False

    async def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        if not self.enabled or self._rnnoise is None:
            return audio
        try:
            if len(audio) == 480:
                return self._rnnoise.process_frame(audio)
            if len(audio) > 480:
                cleaned = np.empty_like(audio)
                for i in range(0, len(audio) - 480 + 1, 480):
                    cleaned[i:i + 480] = self._rnnoise.process_frame(audio[i:i + 480])
                remainder = len(audio) % 480
                if remainder:
                    cleaned[-remainder:] = audio[-remainder:]
                return cleaned
            return audio
        except Exception as e:
            logger.debug(f"RNNoise process error: {e}")
            return audio

    async def stop(self) -> None:
        if self._rnnoise is not None:
            try:
                self._rnnoise.close()
            except Exception:
                pass
            self._rnnoise = None
