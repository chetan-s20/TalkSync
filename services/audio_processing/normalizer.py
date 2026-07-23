from __future__ import annotations

import numpy as np

from app.interfaces import AudioProcessor


class PeakNormalizer(AudioProcessor):
    async def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        peak = np.max(np.abs(audio))
        if peak < 1e-6:
            return audio
        return (audio / peak).astype(np.float32)
