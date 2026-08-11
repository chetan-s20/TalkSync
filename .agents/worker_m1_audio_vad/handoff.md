# Handoff Report — Milestone 1: Audio Capture & VAD Reliability

## 1. Observation

All 6 planned fixes for Milestone 1 plus additional edge cases have been implemented and verified:

1. **`config/settings.py`**:
   - `VADSettings.rms_gate_threshold` default updated from `0.0` to `0.0003`.
   - `STTSettings.rms_gate_threshold` default updated from `0.0` to `0.0003`.

2. **`services/vad/silero_vad.py`**:
   - `RMS_GATE_THRESHOLD` constant updated from `0.005` to `0.0003`.
   - Added fallback in `SileroVAD.is_speech()`: if `noise_floor_rms <= 0.0`, fallback to `0.0003`.

3. **`app/pipeline_state.py` & `app/pipeline.py`**:
   - `SpeechTracker` updated to record pending onset frames (`_pending_frames`) during `_speech_frames < SPEECH_FRAMES_TO_ACTIVATE`.
   - `SpeechTracker` provides `get_and_clear_pending_frames()` method.
   - `_vad_worker` in `app/pipeline.py` updated: when `tracker.just_activated` becomes `True`, all pending onset frames (frame 1 and frame 2) are retrieved and appended to `PerSourceAudioBuffer` (`buf`), preserving speech onset frames.
   - `PerSourceAudioBuffer` updated to support `source: str = "mic"` default, `max_samples` keyword parameter, and `get_audio_and_clear()` helper method.

4. **`utils/device.py`**:
   - Added `"boult"`, `"airbass"`, `"bluetooth"`, `"wireless"`, `"earbuds"` to both `headset_keywords` and `headphone_keywords`.

5. **`services/audio/input.py`**:
   - Removed `self._running = False` from `_start_loopback` and `_start_sd_loopback` exception handlers, ensuring `self._running` remains `True` when `start()` falls back to microphone-only capture mode (`_start_mic`).
   - In `SoundDeviceInput.start()`, added `else: raise` when `capture_mic=False` during loopback failure so `RuntimeError` is raised when no mic fallback is permitted.

6. **`tests/test_vad.py`**:
   - Updated `test_vad_model_none_fallback` audio input signal to pass noise gate (`0.0005` RMS) and updated confidence assertion to `assert results[0].confidence == 0.2`.

---

## 2. Logic Chain

1. **VAD Threshold Alignment**:
   - Setting `rms_gate_threshold` defaults to `0.0003` in `config/settings.py` and `silero_vad.py` aligns the noise gate threshold across configuration and runtime VAD evaluation. The fallback check ensures any invalid or `0.0` threshold defaults safely to `0.0003`, preventing low-level static noise from causing VAD misfires while preserving quiet speech.

2. **Speech Onset Preservation**:
   - `SpeechTracker` now buffers audio frames during the activation count window (`_speech_frames < SPEECH_FRAMES_TO_ACTIVATE`). Upon activation (`just_activated == True`), `_vad_worker` appends all pending frames to `PerSourceAudioBuffer`, ensuring frame 1 (the initial speech onset chunk) is never dropped.

3. **Device Auto-Detection & Fallback Stream Continuity**:
   - Adding Bluetooth and wireless headset keywords to `headset_keywords` and `headphone_keywords` in `utils/device.py` boosts device scoring (+600 points) for wireless headsets such as Boult Audio Airbass.
   - Preserving `self._running = True` during `_start_loopback` errors allows `SoundDeviceInput.start()` to seamlessly execute `_start_mic()`, keeping `stream()` active without early termination. Re-raising errors when `capture_mic=False` ensures accurate error reporting when microphone fallback is explicitly disabled.

4. **Test Suite Verification**:
   - Updating `test_vad_model_none_fallback` to pass a low-level signal above noise gate ensures fallback heuristic execution with expected confidence of `0.2`.

---

## 3. Caveats

- Hardware testing on physical Bluetooth devices (e.g. index 16 Boult Audio Airbass) relies on host OS device availability; device detection and sounddevice query fallbacks handle headless/virtual test environments gracefully.
- No caveats for automated unit and integration tests.

---

## 4. Conclusion

Milestone 1 (Audio Capture & VAD Reliability) implementation is complete. All 6 planned target files plus additional interface compatibility methods have been updated minimal-change, and 100% of Milestone 1 tests pass (117 passed, 0 failed).

---

## 5. Verification Method

Run pytest on target Milestone 1 files:

```bash
pytest tests/test_audio_input.py tests/test_vad.py tests/test_device_detection.py tests/test_mic_capture.py tests/test_pipeline.py tests/test_m1_challenger2_empirical.py tests/test_audio_stream_reliability.py tests/test_loopback_headphones.py tests/test_milestone1_challenge.py
```

**Verification Output**:
- Milestone 1 test suite (117 tests across 9 files): `117 passed in 24.36s`
