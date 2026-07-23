from __future__ import annotations

import numpy as np

from app.interfaces import AudioProcessor


class EchoCancellation(AudioProcessor):
    async def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        return audio
