from __future__ import annotations

import numpy as np


def resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate:
        return audio
    src_len = len(audio)
    dst_len = int(src_len * dst_rate / src_rate)
    indices = np.arange(dst_len) * src_len / dst_len
    return np.interp(indices, np.arange(src_len), audio).astype(np.float32)
