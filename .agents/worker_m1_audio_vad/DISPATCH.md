## 2026-08-07T10:20:39Z
You are Worker for Milestone 1: Audio Capture & VAD Reliability.
Working directory: d:\talksync\talksync\.agents\worker_m1_audio_vad
Read d:\talksync\talksync\.agents\ORIGINAL_REQUEST.md, d:\talksync\talksync\PROJECT.md, and d:\talksync\talksync\.agents\explorer_m1_audio_vad\handoff.md.

Task:
Implement the fixes for Milestone 1: Audio Capture & VAD Reliability as planned in explorer_m1_audio_vad/handoff.md:

1. `config/settings.py` (lines 33, 51):
   - Set default `rms_gate_threshold: float = Field(default=0.0003)` in `VADSettings` and `STTSettings`.

2. `services/vad/silero_vad.py` (lines 16, 104-108):
   - Update `RMS_GATE_THRESHOLD = 0.0003`.
   - Update `noise_floor_rms = getattr(self.settings, "rms_gate_threshold", 0.0003)` and if `noise_floor_rms <= 0.0`, fallback to `0.0003`.

3. `app/pipeline_state.py` (SpeechTracker) & `app/pipeline.py` (_vad_worker):
   - In `SpeechTracker`, record pending onset frames during `_speech_frames < SPEECH_FRAMES_TO_ACTIVATE`.
   - When `just_activated` becomes `True`, provide or yield all pending onset frames (frame 1 and frame 2) so they are preserved in `PerSourceAudioBuffer` (`buf`) rather than discarding frame 1.

4. `utils/device.py` (headset_keywords):
   - Add `"boult"`, `"airbass"`, `"bluetooth"`, `"wireless"`, `"earbuds"` to `headset_keywords` list.

5. `services/audio/input.py` (_start_loopback):
   - Fix issue where `if loop_dev is None:` sets `self._running = False` before raising `RuntimeError`. Ensure `self._running` remains `True` when falling back to microphone-only mode in `start()`.

6. `tests/test_vad.py` (line 275):
   - Update test assertion for `test_vad_model_none_fallback` to `assert results[0].confidence == 0.2`.

7. Run test verification using pytest:
   - Run `pytest tests/test_audio_input.py tests/test_vad.py tests/test_device_detection.py tests/test_mic_capture.py tests/test_pipeline.py`.
   - Report test execution output and results.

Write your changes summary and handoff report to d:\talksync\talksync\.agents\worker_m1_audio_vad\handoff.md.
