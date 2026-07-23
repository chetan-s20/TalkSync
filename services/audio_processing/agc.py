from __future__ import annotations

import numpy as np

from app.interfaces import AudioProcessor


class AutomaticGainControl(AudioProcessor):
    def __init__(self, target_rms: float = 0.2, attack: float = 0.01, release: float = 0.1):
        self._target_rms = target_rms
        self._attack = attack
        self._release = release
        self._gain = 1.0

    async def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        rms = np.sqrt(np.mean(audio ** 2))
        if rms < 1e-6:
            return audio
        target_gain = self._target_rms / rms
        time_constant = self._attack if target_gain > self._gain else self._release
        self._gain += (target_gain - self._gain) * time_constant
        return np.clip(audio * self._gain, -1.0, 1.0).astype(np.float32)
