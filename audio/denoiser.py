"""Optional audio denoiser wrapper for TalkSync Pro."""
from __future__ import annotations

from typing import Optional
import numpy as np

from utils.logger import get_logger

logger = get_logger("denoiser")


class Denoiser:
    def __init__(self, settings):
        self.enabled = getattr(settings, "enabled", False)
        self._rnnoise: Optional[object] = None
        if self.enabled:
            try:
                from audio.rnnoise_native import RNNoiseDenoiser
                self._rnnoise = RNNoiseDenoiser()
                logger.info("RNNoise denoiser loaded")
            except Exception as e:
                logger.warning(f"Denoiser unavailable: {e}")
                self.enabled = False

    def start(self) -> None:
        pass

    async def stop(self) -> None:
        if self._rnnoise is not None:
            try:
                self._rnnoise.close()
            except Exception:
                pass
            self._rnnoise = None

    async def process_chunk(self, chunk) -> Optional[object]:
        if not self.enabled or self._rnnoise is None:
            return chunk
        try:
            audio = np.frombuffer(chunk.data, dtype=np.float32)
            cleaned = self._rnnoise.process_frame(audio)
            chunk.data = cleaned.astype(np.float32).tobytes()
        except Exception as e:
            logger.debug(f"Denoiser process error: {e}")
        return chunk


RNNoiseDenoiser = Denoiser
