# Handoff Report — Audio Device Worker

## 1. Observation

- **Hardcoded Device Index 37**: Querying `sounddevice.query_devices()` on the host system revealed that device index 37 is `"Headphones 2 (Realtek HD Audio 2nd output with HAP)"`, with `max_input_channels = 0` and `max_output_channels = 2`.
  - Command: `python -c "import sounddevice as sd; print(sd.query_devices())"`
  - Result excerpt:
    ```
    37 Headphones 2 (Realtek HD Audio 2nd output with HAP), Windows WDM-KS (0 in, 2 out)
    ```
- **Input Stream Initialization Failure**: When `audio_input_device_id=37` was configured in `.env`, `SoundDeviceInput` attempted to open index 37 as an input device (`channels=1`), causing PortAudio input stream creation errors because device 37 has 0 input channels.
- **Audio Device Auto-Detection Logic**: Prior implementation lacked scoring/preference for headset/headphone microphones over speakers or generic inputs, and did not validate whether a requested `device_id` supported the required direction (input vs output).
- **Test Suite Results**:
  - Command: `python -m pytest tests/test_audio_input.py -v`
  - Output: `19 passed in 0.90s` (including 3 new test cases).

---

## 2. Logic Chain

1. **Observation**: Device index 37 in `.env` corresponds to a headphone playback endpoint with `max_input_channels = 0`.
2. **Reasoning**: Passing device index 37 directly as `input_device_id` to `sd.InputStream` fails because PortAudio cannot capture audio from a 0-input-channel output device.
3. **Observation**: The requirements state:
   - "Query `sounddevice.query_devices()` to find the best available microphone (prefer headset/headphone mic if present, then default system mic)."
   - "Query output devices and prefer headphones/headset over speakers."
   - "Handle hardcoded device index (37) from `.env`: if valid and has input channels, keep using it; otherwise fallback cleanly to auto-detection."
   - "Log clearly which input and output devices were selected at startup."
4. **Resolution Strategy**:
   - Implemented `find_best_input_device(requested_id)` and `find_best_output_device(requested_id)` in `utils/device.py`.
   - The validation step checks `0 <= requested_id < len(all_devices)` and `max_input_channels > 0` (for input) or `max_output_channels > 0` (for output).
   - If `requested_id` (e.g., 37 for input) is invalid or has 0 input channels, a warning is logged:
     `"Configured input device ID 37 ('Headphones 2 ...') has 0 input channels ... falling back cleanly to auto-detection."`
   - Auto-detection scores candidates by name keywords (`headset`, `headphone`, `hands-free`, `earphone`, `buds` get priority), system default status (`sd.default.device`), host API stability (MME/DirectSound/WASAPI over raw WDM-KS), while filtering out explicit loopback/virtual endpoints from mic selection.
   - For output: `requested_id = 37` is a valid headphone playback device (`max_output_channels = 2`), so it is selected for output playback; for unconstrained auto-detection (`requested_id = None`), index 5 (`Headphones (Realtek(R) Audio)`) is auto-detected.
   - Updated `SoundDeviceInput._start_mic` in `services/audio/input.py` and `SoundDeviceOutput.start` in `services/audio/output.py` to use these helpers and log resolved device names/IDs clearly at startup.
   - Re-exported functions in `services/audio/loopback.py`.

---

## 3. Caveats

- If no headset microphone is plugged in, auto-detection cleanly falls back to the system default microphone (e.g. `Microphone Array`).
- WDM-KS devices are given a lower host API score than WASAPI/MME/DirectSound endpoints to maximize PortAudio stream stability across Windows versions.

---

## 4. Conclusion

- Audio device auto-detection and validation logic is fully implemented and verified.
- Hardcoded device index 37 from `.env` is cleanly validated for both input and output paths:
  - Input path detects 37 has 0 input channels, logs a clear warning, and falls back cleanly to auto-detecting the best available microphone (preferring headset mic).
  - Output path validates 37 has output channels and uses it for headphone playback (or auto-detects system headphone device when unconstrained).
- Startup logging clearly reports resolved device IDs, names, sample rates, and channel counts.
- All 19 tests in `tests/test_audio_input.py` pass without errors or tracebacks.

---

## 5. Verification Method

To independently verify the implementation:

1. **Run Unit Tests**:
   ```bash
   python -m pytest tests/test_audio_input.py -v
   ```
   *Expected Result*: 19 tests pass (including `test_find_best_input_device_prefer_headset`, `test_find_best_input_device_fallback_from_invalid_37`, and `test_find_best_output_device_prefer_headphones`).

2. **Run Interactive Verification**:
   ```bash
   python -c "from utils.device import find_best_input_device, find_best_output_device; print('Input (37):', find_best_input_device(37)); print('Output (37):', find_best_output_device(37))"
   ```
   *Expected Result*: Input fallback warning for index 37 and auto-detected mic ID; Output resolves device 37 or headphone output cleanly.
