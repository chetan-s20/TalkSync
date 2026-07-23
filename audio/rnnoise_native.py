"""Optional RNNoise denoiser wrapper using ctypes."""
from __future__ import annotations

import ctypes
import os
import numpy as np
from typing import Optional
from pathlib import Path


_LIB_NAMES = {
    "win32": ["rnnoise.dll", "librnnoise.dll"],
    "linux": ["librnnoise.so"],
    "darwin": ["librnnoise.dylib"],
}


class RNNoiseDenoiser:
    def __init__(self):
        self._lib = self._load_library()
        if self._lib is None:
            raise RuntimeError("RNNoise library not found")
        self._state = self._lib.rnnoise_create(None)
        if not self._state:
            raise RuntimeError("rnnoise_create failed")

    def _load_library(self) -> Optional[ctypes.CDLL]:
        candidates = _LIB_NAMES.get(os.name, [])
        for name in candidates:
            path = Path(__file__).parent.parent / "libs" / name
            if path.exists():
                try:
                    return ctypes.CDLL(str(path))
                except OSError:
                    continue
        for name in candidates:
            try:
                return ctypes.CDLL(name)
            except OSError:
                continue
        return None

    def process_frame(self, samples: np.ndarray) -> np.ndarray:
        if self._lib is None or self._state is None:
            return samples
        if len(samples) != 480:
            return samples
        frame = samples.astype(np.float32)
        out = frame.copy()
        ptr = frame.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        out_ptr = out.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        self._lib.rnnoise_process_frame(self._state, out_ptr, ptr)
        return out

    def close(self) -> None:
        if self._lib is not None and self._state is not None:
            self._lib.rnnoise_destroy(self._state)
            self._state = None
