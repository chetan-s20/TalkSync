"""Adversarial Verification Test Suite for M2 Device Detection and Mic Sensitivity."""
import sys
import math
import numpy as np
from unittest.mock import patch, MagicMock

from config.settings import Settings, AudioSettings
from app.application import validate_and_resolve_audio_devices, Application
from utils.device import find_best_input_device, find_best_output_device


def run_adversarial_tests():
    print("=== STARTING ADVERSARIAL M2 TESTS ===")
    passed = 0
    failed = 0

    def assert_test(cond, msg):
        nonlocal passed, failed
        if cond:
            print(f"  [PASS] {msg}")
            passed += 1
        else:
            print(f"  [FAIL] {msg}")
            failed += 1

    # 1. Edge Case Device IDs: None, Negative, Out of Bounds, Strings, Floats
    print("\n--- Test Suite 1: Input Device ID Edge Cases ---")
    test_cases_input = [
        (None, "None device ID"),
        (-1, "Negative ID (-1)"),
        (-9999, "Large negative ID (-9999)"),
        (99999, "Large out-of-bounds ID (99999)"),
        ("35", "String integer ('35')"),
        ("invalid_str", "Non-numeric string ('invalid_str')"),
        (3.14, "Float ID (3.14)"),
        (float("nan"), "NaN float ID"),
    ]

    for req_id, name in test_cases_input:
        try:
            res_id, res_name = find_best_input_device(req_id)
            assert_test(isinstance(res_name, str) and len(res_name) > 0, f"find_best_input_device({name}) returned valid name '{res_name}'")
            if req_id in (-1, -9999, 99999, "invalid_str"):
                assert_test(res_id != req_id, f"find_best_input_device({name}) successfully fell back (ID={res_id})")
        except Exception as e:
            assert_test(False, f"find_best_input_device({name}) raised exception: {e}")

    print("\n--- Test Suite 2: Output Device ID Edge Cases ---")
    test_cases_output = [
        (None, "None device ID"),
        (-1, "Negative ID (-1)"),
        (-9999, "Large negative ID (-9999)"),
        (99999, "Large out-of-bounds ID (99999)"),
        ("36", "String integer ('36')"),
        ("invalid_str", "Non-numeric string ('invalid_str')"),
        (3.14, "Float ID (3.14)"),
        (float("nan"), "NaN float ID"),
    ]

    for req_id, name in test_cases_output:
        try:
            res_id, res_name = find_best_output_device(req_id)
            assert_test(isinstance(res_name, str) and len(res_name) > 0, f"find_best_output_device({name}) returned valid name '{res_name}'")
            if req_id in (-1, -9999, 99999, "invalid_str"):
                assert_test(res_id != req_id, f"find_best_output_device({name}) successfully fell back (ID={res_id})")
        except Exception as e:
            assert_test(False, f"find_best_output_device({name}) raised exception: {e}")

    print("\n--- Test Suite 3: Malformed Device Query Environment Mocking ---")
    
    # Case 3.1: sounddevice raises Exception
    with patch("sounddevice.query_devices", side_effect=RuntimeError("Audio subsystem crashed")):
        try:
            in_id, in_name = find_best_input_device(0)
            assert_test(in_id is None and in_name == "System Default Input", "find_best_input_device handles query_devices RuntimeError cleanly")
            out_id, out_name = find_best_output_device(0)
            assert_test(out_id is None and out_name == "System Default Output", "find_best_output_device handles query_devices RuntimeError cleanly")
        except Exception as e:
            assert_test(False, f"Failed on query_devices RuntimeError: {e}")

    # Case 3.2: sounddevice returns empty list
    with patch("sounddevice.query_devices", return_value=[]):
        with patch("sounddevice.default.device", [None, None]):
            try:
                in_id, in_name = find_best_input_device(0)
                assert_test(in_id is None and in_name == "System Default Input", "find_best_input_device handles empty device list cleanly")
                out_id, out_name = find_best_output_device(0)
                assert_test(out_id is None and out_name == "System Default Output", "find_best_output_device handles empty device list cleanly")
            except Exception as e:
                assert_test(False, f"Failed on empty device list: {e}")

    # Case 3.3: sounddevice returns malformed device dictionaries
    malformed_devices = [
        {"name": "Bad Device 1"},  # missing max_input_channels, max_output_channels
        "not_a_dict",  # non-dict entry
        {"max_input_channels": -5},  # negative channels
        {"max_input_channels": "two", "max_output_channels": "two"},  # non-int channel string
    ]
    with patch("sounddevice.query_devices", return_value=malformed_devices):
        with patch("sounddevice.default.device", [0, 0]):
            try:
                in_id, in_name = find_best_input_device(None)
                out_id, out_name = find_best_output_device(None)
                assert_test(True, "find_best_input_device & find_best_output_device survived malformed device dicts")
            except TypeError as te:
                assert_test(False, f"find_best_input_device / find_best_output_device crashed with TypeError on non-int channels: {te}")
            except Exception as e:
                assert_test(False, f"Failed on malformed device dicts: {e}")

    print("\n--- Test Suite 4: validate_and_resolve_audio_devices Integration ---")
    try:
        mock_devices = [
            {"name": "Mic A", "max_input_channels": 2, "max_output_channels": 0, "hostapi": 0},
            {"name": "Headphones B", "max_input_channels": 0, "max_output_channels": 2, "hostapi": 0},
        ]
        with patch("sounddevice.query_devices", return_value=mock_devices):
            with patch("sounddevice.default.device", [0, 1]):
                settings = Settings(audio=AudioSettings(input_device_id=-99, output_device_id=999))
                validate_and_resolve_audio_devices(settings)
                assert_test(settings.audio.input_device_id == 0, f"validate_and_resolve_audio_devices fixed input_device_id to 0 (was -99)")
                assert_test(settings.selected_input_device_name == "Mic A", "Selected input device name populated correctly")
                assert_test(settings.audio.output_device_id == 1, f"validate_and_resolve_audio_devices fixed output_device_id to 1 (was 999)")
                assert_test(settings.selected_output_device_name == "Headphones B", "Selected output device name populated correctly")
    except Exception as e:
        assert_test(False, f"validate_and_resolve_audio_devices failed: {e}")

    print("\n--- Test Suite 5: Application Initialization Edge Cases ---")
    try:
        mock_devices = [
            {"name": "Mic A", "max_input_channels": 1, "max_output_channels": 0, "hostapi": 0},
            {"name": "Speaker B", "max_input_channels": 0, "max_output_channels": 2, "hostapi": 0},
        ]
        with patch("sounddevice.query_devices", return_value=mock_devices):
            with patch("sounddevice.default.device", [0, 1]):
                settings = Settings()
                settings.audio.input_device_id = None
                settings.audio.output_device_id = None
                app = Application(settings)
                assert_test(app.settings.audio.input_device_id == 0, "Application init resolved None input_device_id to 0")
                assert_test(app.settings.audio.output_device_id == 1, "Application init resolved None output_device_id to 1")
    except Exception as e:
        assert_test(False, f"Application init test failed: {e}")

    print("\n--- Test Suite 6: Mic Sensitivity & AGC Configuration Verification ---")
    settings = Settings()
    assert_test(settings.vad.threshold == 0.45, f"settings.vad.threshold is {settings.vad.threshold} (expected 0.45)")
    assert_test(settings.stt.rms_gate_threshold == 0.0003, f"settings.stt.rms_gate_threshold is {settings.stt.rms_gate_threshold} (expected 0.0003)")

    # Check OpenAI STT AGC target RMS
    try:
        from services.stt.openai_stt import OpenAISTT
        import inspect
        src = inspect.getsource(OpenAISTT._apply_agc)
        assert_test("target_rms = 0.2" in src, "OpenAISTT._apply_agc uses target_rms = 0.2")
    except Exception as e:
        assert_test(False, f"OpenAISTT inspection failed: {e}")

    # Check FasterWhisper STT AGC target RMS (in transcribe method)
    try:
        from services.stt.faster_whisper import FasterWhisperSTT
        import inspect
        src = inspect.getsource(FasterWhisperSTT.transcribe)
        assert_test("target_rms = 0.2" in src, "FasterWhisperSTT.transcribe uses target_rms = 0.2")
    except Exception as e:
        assert_test(False, f"FasterWhisperSTT inspection failed: {e}")

    print(f"\n=== SUMMARY: {passed} PASSED, {failed} FAILED ===")
    return failed == 0


if __name__ == "__main__":
    success = run_adversarial_tests()
    sys.exit(0 if success else 1)
