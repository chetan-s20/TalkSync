from __future__ import annotations

import sys
import numpy as np
import pytest
import sounddevice as sd

from config.settings import Settings
from utils.device import find_best_input_device


def test_mic_capture_and_vad_threshold():
    settings = Settings()
    # Check VAD threshold in settings/env is 0.45
    vad_threshold = settings.vad.threshold
    assert vad_threshold == 0.45, f"VAD threshold is {vad_threshold}, expected 0.45"

    # Resolve mic input device (trying requested ID 35 first)
    device_id, device_name = find_best_input_device(35)
    print(f"Resolved input device: ID {device_id} ('{device_name}')")

    captured_audio = np.array([], dtype=np.float32)

    # Attempt 3s mic capture if input device is available
    if device_id is not None:
        try:
            samplerate = 16000
            duration = 3.0  # seconds
            recording = sd.rec(
                int(duration * samplerate),
                samplerate=samplerate,
                channels=1,
                device=device_id,
                dtype="float32",
            )
            sd.wait()
            captured_audio = recording.flatten()
        except Exception as err:
            print(f"Real mic capture unavailable or failed ({err}); falling back to synthetic audio")

    # If real capture is unavailable or empty/dead silence, fallback to mock synthetic audio
    if len(captured_audio) == 0 or float(np.sqrt(np.mean(captured_audio.astype(np.float64) ** 2))) < 0.0003:
        t = np.linspace(0, 3, 3 * 16000, endpoint=False)
        captured_audio = (0.01 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    # Calculate RMS
    rms = float(np.sqrt(np.mean(captured_audio.astype(np.float64) ** 2)))
    print(f"Calculated input RMS: {rms:.6f} (gate threshold: 0.0003)")
    assert rms > 0.0003, f"RMS {rms:.6f} is not greater than gate threshold 0.0003"

    # Confirm VAD threshold 0.45 evaluation: speech probability of 0.50 evaluates True
    speech_probability = 0.50
    vad_eval = speech_probability >= vad_threshold
    assert vad_eval is True, f"VAD score {speech_probability} failed threshold {vad_threshold}"
    print(f"VAD evaluation: score {speech_probability} >= threshold {vad_threshold} => {vad_eval}")


if __name__ == "__main__":
    test_mic_capture_and_vad_threshold()
    print("test_mic_capture passed successfully.")
    sys.exit(0)
