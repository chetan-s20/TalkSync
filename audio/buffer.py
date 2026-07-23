"""Ring-buffer for audio samples used in streaming VAD/STT."""
from __future__ import annotations

import array
from typing import Optional


class AudioBuffer:
    def __init__(self, max_seconds: float = 30.0, sample_rate: int = 16000):
        self._sample_rate = sample_rate
        self._max_samples = int(max_seconds * sample_rate)
        self._buf: array.array = array.array("f")
        self._lock = __import__("threading").Lock()

    def write(self, samples) -> None:
        with self._lock:
            self._buf.extend(samples)
            overflow = len(self._buf) - self._max_samples
            if overflow > 0:
                self._buf = self._buf[overflow:]

    def read(self, n_samples: int) -> array.array:
        with self._lock:
            if n_samples >= len(self._buf):
                out = array.array("f", self._buf)
                self._buf = array.array("f")
                return out
            start = len(self._buf) - n_samples
            out = array.array("f", self._buf[start:])
            self._buf = self._buf[:start]
            return out

    def read_all(self) -> array.array:
        with self._lock:
            out = array.array("f", self._buf)
            self._buf = array.array("f")
            return out

    def clear(self) -> None:
        with self._lock:
            self._buf = array.array("f")

    @property
    def duration_s(self) -> float:
        return len(self._buf) / self._sample_rate

    def __len__(self) -> int:
        return len(self._buf)
