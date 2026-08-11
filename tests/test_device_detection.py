from __future__ import annotations

import sys
from unittest.mock import patch
import pytest

from app.application import Application, validate_and_resolve_audio_devices
from config.settings import AudioSettings, Settings
from utils.device import find_best_input_device, find_best_output_device


def test_invalid_device_id_fallback():
    """Test that out-of-range IDs like 9999 and -1 fall back to valid devices without crashing."""
    in_id_9999, in_name_9999 = find_best_input_device(9999)
    in_id_neg1, in_name_neg1 = find_best_input_device(-1)

    out_id_9999, out_name_9999 = find_best_output_device(9999)
    out_id_neg1, out_name_neg1 = find_best_output_device(-1)

    assert in_id_9999 != 9999
    assert in_id_neg1 != -1
    assert out_id_9999 != 9999
    assert out_id_neg1 != -1


def test_zero_channel_device_fallback():
    """Test that requesting a device index with 0 input/output channels falls back to a device with >0 channels."""
    mock_devices = [
        {"name": "Zero Channel Mic", "max_input_channels": 0, "max_output_channels": 0, "hostapi": 0},
        {"name": "Valid Microphone", "max_input_channels": 2, "max_output_channels": 0, "hostapi": 0},
        {"name": "Valid Headset", "max_input_channels": 1, "max_output_channels": 2, "hostapi": 0},
    ]

    with patch("sounddevice.query_devices", return_value=mock_devices):
        with patch("sounddevice.default.device", [1, 2]):
            # Request index 0 which has 0 input channels
            best_in_id, best_in_name = find_best_input_device(0)
            assert best_in_id != 0, "Should not return 0-channel device index 0"
            assert best_in_id in (1, 2)
            assert best_in_name in ("Valid Microphone", "Valid Headset")

            # Request index 0 which has 0 output channels
            best_out_id, best_out_name = find_best_output_device(0)
            assert best_out_id != 0, "Should not return 0-channel device index 0"
            assert best_out_id == 2
            assert best_out_name == "Valid Headset"


def test_application_startup_device_resolution():
    """Test that Application startup resolves invalid device IDs to valid devices."""
    mock_devices = [
        {"name": "Built-in Mic", "max_input_channels": 2, "max_output_channels": 0, "hostapi": 0},
        {"name": "Headphones", "max_input_channels": 0, "max_output_channels": 2, "hostapi": 0},
    ]

    with patch("sounddevice.query_devices", return_value=mock_devices):
        with patch("sounddevice.default.device", [0, 1]):
            settings = Settings(audio=AudioSettings(input_device_id=9999, output_device_id=-1))
            app = Application(settings)

            assert app.settings.audio.input_device_id == 0
            assert app.settings.selected_input_device_name == "Built-in Mic"
            assert app.settings.audio.output_device_id == 1
            assert app.settings.selected_output_device_name == "Headphones"


if __name__ == "__main__":
    test_invalid_device_id_fallback()
    test_zero_channel_device_fallback()
    test_application_startup_device_resolution()
    print("test_device_detection passed successfully.")
    sys.exit(0)
