# Milestone 1 Analysis Report: Audio Capture & VAD Reliability

## Executive Summary
This report presents a comprehensive root-cause analysis and precise fix strategy for **Milestone 1: Audio Capture & VAD Reliability** in TalkSync. The investigation covers four core areas:
1. VAD noise floor threshold reconciliation across `services/vad/silero_vad.py`, `config/settings.py`, `app/pipeline.py`, and STT engines.
2. Speech onset frame preservation in `app/pipeline_state.py` (`SpeechTracker`) and `app/pipeline.py` (`_vad_worker`).
3. Audio input device auto-detection (Boult Audio Airbass / Index 16) and WASAPI/sounddevice loopback fallback safety in `utils/device.py` and `services/audio/input.py`.
4. Comprehensive test execution plan and test suite verification results.

---

## 1. Deep-Dive Analysis: VAD Noise Floor Threshold Reconciliation

### Observations & Evidence
- In `services/vad/silero_vad.py` (line 16):
  `RMS_GATE_THRESHOLD = 0.005` is hardcoded as a top-level module constant.
  When Quiet Speech occurs (typical RMS energy levels ranging from `0.0005` to `0.003`), setting or defaulting to `0.005` drops valid quiet speech chunks before VAD model processing.
- In `config/settings.py` (lines 33 and 51):
  `VADSettings.rms_gate_threshold` and `STTSettings.rms_gate_threshold` default to `0.0`.
- In `services/vad/silero_vad.py` (line 104):
  `noise_floor_rms = getattr(self.settings, "rms_gate_threshold", 0.0003)`
  Because `self.settings.rms_gate_threshold` exists on `VADSettings` and is set to `0.0`, `getattr` returns `0.0`. Consequently, `rms < noise_floor_rms` evaluates to `rms < 0.0` (which is never true), effectively disabling noise floor gating when default settings are loaded!
- Across other system modules:
  - `app/bridge.py` (lines 36, 55): `"rms_gate": 0.0003`
  - `app/pipeline.py` (line 319): `threshold = getattr(self._settings.stt, "rms_gate_threshold", 0.0003)`
  - `services/stt/faster_whisper.py` (line 57): `self._rms_gate_threshold = getattr(stt_settings, "rms_gate_threshold", 0.0003)`
  - `services/stt/openai_stt.py` (line 73): `self._rms_gate_threshold = getattr(stt_cfg, "rms_gate_threshold", 0.0003)`

### Proposed Fix Strategy
1. Update default `rms_gate_threshold` in `VADSettings` and `STTSettings` in `config/settings.py` from `0.0` to `0.0003`.
2. Update `RMS_GATE_THRESHOLD = 0.0003` in `services/vad/silero_vad.py` (line 16).
3. In `silero_vad.py` `is_speech()` (line 104):
   ```python
   noise_floor_rms = getattr(self.settings, "rms_gate_threshold", 0.0003)
   if noise_floor_rms <= 0.0:
       noise_floor_rms = RMS_GATE_THRESHOLD
   ```
4. Fix test assertion in `tests/test_vad.py` line 275 (`test_vad_model_none_fallback`), where fallback model returned `0.2` confidence when `is_speech=False`. Update test to assert `results[0].confidence == 0.2` or adjust fallback probability cleanly.

---

## 2. Deep-Dive Analysis: Speech Onset Frame Truncation

### Observations & Evidence
- In `app/pipeline_state.py` (lines 14–32), `SpeechTracker.update(is_speech: bool)` operates as follows:
  ```python
  SPEECH_FRAMES_TO_ACTIVATE = 2

  def update(self, is_speech: bool) -> bool:
      if is_speech:
          self._speech_frames += 1
          self._silence_frames = 0
          if not self._speech_active and self._speech_frames >= SPEECH_FRAMES_TO_ACTIVATE:
              self._speech_active = True
      ...
      return self._speech_active
  ```
- In `app/pipeline.py` (lines 386–393), `_vad_worker` processes incoming audio chunks:
  ```python
  is_active = tracker.update(effective_is_speech)
  if is_active or tracker.just_activated:
      buf.append(audio_array)
  ```
- **Execution Flow Trace**:
  - **Frame 1 (Speech Onset Chunk)**: `effective_is_speech = True`. `tracker.update(True)` runs:
    `self._speech_frames` becomes `1`. `self._speech_active` remains `False` (since `1 < 2`). `update()` returns `False`.
    `is_active` is `False`. `tracker.just_activated` is `False` (`self._speech_active` is `False`).
    Condition `if is_active or tracker.just_activated:` evaluates to `False`.
    **Result**: Frame 1 (the initial speech onset chunk) is **never appended** to `buf` and is discarded!
  - **Frame 2**: `effective_is_speech = True`. `tracker.update(True)` runs:
    `self._speech_frames` becomes `2`. `self._speech_active` transitions to `True`. `update()` returns `True`.
    `is_active` is `True`. Frame 2 is appended to `buf`.
- **Impact**: The initial 30ms–60ms of speech (consonants/onset syllables like "T", "P", "S", "Hi") is truncated, causing Whisper STT to misinterpret or drop word prefixes.

### Proposed Fix Strategy
1. Enhance `SpeechTracker` in `app/pipeline_state.py` to buffer pre-activation pending onset frames:
   - Add `self._pending_frames: list[np.ndarray] = []` in `SpeechTracker.__init__`.
   - Update `update(self, is_speech: bool, frame_audio: Optional[np.ndarray] = None) -> bool`:
     - When `is_speech` is True and `frame_audio` is provided, if `not self._speech_active`, append `frame_audio` to `self._pending_frames`.
     - When `is_speech` is False and `not self._speech_active`, clear `self._pending_frames`.
   - Add method `pop_pending_frames(self) -> list[np.ndarray]`:
     ```python
     def pop_pending_frames(self) -> list[np.ndarray]:
         frames = list(self._pending_frames)
         self._pending_frames.clear()
         return frames
     ```
2. In `app/pipeline.py` `_vad_worker()` (lines 386–393):
   ```python
   is_active = tracker.update(effective_is_speech, frame_audio=audio_array)
   if tracker.just_activated:
       for pending in tracker.pop_pending_frames():
           buf.append(pending)
   elif is_active:
       buf.append(audio_array)
   ```
This guarantees frame 1 (onset frame) and any intermediate activation frames are preserved and prepended to `buf` when speech activates.

---

## 3. Deep-Dive Analysis: Device Index 16 (Boult Audio Airbass) & Loopback Fallback

### Observations & Evidence
1. **Device Index 16 / Bluetooth Headset Detection**:
   - In `utils/device.py` (`find_best_input_device` & `find_best_output_device`):
     - `requested_id` validation (lines 97–115) checks `0 <= req_idx < num_devices` and verifies `max_input_channels > 0`.
     - If index 16 is specified and valid, it returns `(16, dev_name)`.
     - If index 16 is invalid or has 0 channels (e.g. Bluetooth A2DP audio profile active without SCO mic profile), it logs a clean warning and falls back to auto-detection scoring.
     - **Keyword Scoring Improvement**: In line 126 of `utils/device.py`:
       `headset_keywords = ("headset", "headphone", "hands-free", "earphone", "buds", "airwave")`
       Device name `"Boult Audio Airbass"` will not match `"headset"` or `"headphone"`. Adding `"boult"`, `"airbass"`, `"bluetooth"`, `"wireless"`, `"earbuds"` to `headset_keywords` ensures +600 score boost during auto-detection.

2. **Critical Bug in Loopback Fallback Logic**:
   - In `services/audio/input.py` (`_start_loopback()`, line 144):
     ```python
     if loop_dev is None:
         self._running = False  # <--- CRITICAL BUG
         raise RuntimeError("No loopback device found (WASAPI, Stereo Mix, or VB-Cable)")
     ```
   - In `SoundDeviceInput.start(loopback=True)` (lines 125–134):
     ```python
     try:
         if loopback:
             try:
                 await self._start_loopback(device_id, capture_mic)
             except Exception as loop_e:
                 logger.warning(f"... falling back cleanly to microphone-only capture")
                 self._loopback_queue = None
                 self._loopback_stream = None
                 if capture_mic:
                     await self._start_mic(device_id)
     ```
   - **Trace**: When `find_loopback_device()` returns `None` (or raises an exception), line 144 sets `self._running = False`. `start()` catches `RuntimeError`, logs a warning, and calls `_start_mic(device_id)`. However, `self._running` remains `False`!
   - As a result, when `stream()` (line 432: `while self._running:`) is called by `_capture_worker`, it immediately exits, **killing mic capture during loopback fallback**!

### Proposed Fix Strategy
1. In `services/audio/input.py` line 144: Do NOT set `self._running = False` inside `_start_loopback()` before raising `RuntimeError`. Alternatively, ensure `self._running = True` is preserved in `start()` when falling back to microphone-only capture.
2. In `utils/device.py` lines 126 & 234: Add `"boult"`, `"airbass"`, `"bluetooth"`, `"wireless"`, `"earbuds"` to `headset_keywords` and `headphone_keywords`.

---

## 4. Target Files, Functions, Lines, and Test Plan

| File Path | Function / Class | Line(s) | Summary of Change |
|-----------|------------------|---------|-------------------|
| `config/settings.py` | `VADSettings`, `STTSettings` | 33, 51 | Set `rms_gate_threshold: float = Field(default=0.0003)` |
| `services/vad/silero_vad.py` | `RMS_GATE_THRESHOLD`, `SileroVAD.is_speech` | 16, 104-108 | Change constant to `0.0003`; sanitize `noise_floor_rms` fallback |
| `app/pipeline_state.py` | `SpeechTracker` | 15-49 | Add `_pending_frames` buffer and `pop_pending_frames()` |
| `app/pipeline.py` | `Pipeline._vad_worker` | 386-395 | Append pending onset frames when `tracker.just_activated` |
| `utils/device.py` | `find_best_input_device`, `find_best_output_device` | 126, 234 | Add `"boult"`, `"airbass"`, `"bluetooth"`, `"wireless"`, `"earbuds"` keywords |
| `services/audio/input.py` | `SoundDeviceInput._start_loopback` | 125-145 | Fix `self._running` state persistence on loopback fallback to mic |
| `tests/test_vad.py` | `TestVADEdgeCases.test_vad_model_none_fallback` | 275 | Fix assertion for model=None fallback confidence (`0.2`) |

---

## 5. Verification Commands

Run the following test commands to verify all Milestone 1 fixes:
```bash
# 1. Milestone 1 Core Audio Input, VAD, Device Detection, and Mic Capture Tests
pytest tests/test_audio_input.py tests/test_vad.py tests/test_device_detection.py tests/test_mic_capture.py

# 2. Pipeline State, Stream Reliability, and Loopback Headphone Fallback Tests
pytest tests/test_pipeline.py tests/test_audio_stream_reliability.py tests/test_loopback_headphones.py tests/test_milestone1_challenge.py

# 3. Full Test Suite Regression Verification
pytest
```
