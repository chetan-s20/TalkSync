from __future__ import annotations

from typing import Optional

import sounddevice as sd

from utils.logger import get_logger

logger = get_logger("fallback")

OUTPUT_RATES = (24000, 44100, 48000, 16000)
OUTPUT_CHANNELS = (2, 1)


def try_open_output(device_id: Optional[int] = None) -> tuple[Optional[int], Optional[int]]:
    for rate in OUTPUT_RATES:
        for channels in OUTPUT_CHANNELS:
            try:
                stream = sd.OutputStream(
                    samplerate=rate, channels=channels,
                    dtype="float32", device=device_id,
                )
                stream.stop()
                stream.close()
                logger.info(f"Output combo OK: rate={rate}, ch={channels}")
                return rate, channels
            except Exception:
                continue
    return None, None
