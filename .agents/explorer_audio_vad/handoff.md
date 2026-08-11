# Handoff Report — Explorer 1 (audio_vad)

## 1. Observation

Direct observations from examining the codebase at `d:\talksync\talksync`:

1. **Dual Code Architecture**:
   - `app/application.py` lines 53-55 loads audio and VAD services from `services/`:
     ```python
     from services.audio.input import SoundDeviceInput
     from services.audio.output import SoundDeviceOutput
     from services.vad.silero_vad import SileroVAD
     ```
   - Legacy core files `audio/input.py` and `vad/silero_vad.py` also exist in root.
2. **Audio Input Device Resolution & Fallbacks**:
   - `utils/device.py` lines 97-115 (`find_best_input_device`) validates configured device IDs (e.g. index 16 for Boult Audio Airbass or index 35 from `.env`). If an index is out of bounds or has 0 input channels (`dev.get("max_input_channels", 0) > 0`), it logs a warning and auto-detects an active input device based on score.
   - `services/audio/input.py` lines 128-132:
     ```python
     except Exception as loop_e:
         logger.warning(f"Audio loopback capture initialization failed ({loop_e}) — falling back cleanly to microphone-only capture")
         self._loopback_queue = None
         self._loopback_stream = None
         if capture_mic:
             await self._start_mic(device_id)
     ```
   - Root `audio/input.py` line 148-149 raises an unhandled exception if no loopback device is found:
     ```python
     if not loop_ok:
         self._running = False
         raise RuntimeError("No loopback device found.")
     ```
3. **WASAPI & Multi-Tier Loopback Capture**:
   - `services/audio/loopback.py` lines 124-154 (`find_loopback_device`) checks loopback devices in priority:
     1. `find_wasapi_loopback` (WASAPI via `soundcard`, prefers headphone endpoints)
     2. `find_stereo_mix` (Stereo Mix via `sounddevice`, prefers HD Audio/HAP driver)
     3. `find_vb_cable` (VB-Audio Virtual Cable Output)
4. **VAD Chunk Slicing & RMS Noise Floor Gating**:
   - `vad/silero_vad.py` line 76 has hardcoded noise floor gate:
     ```python
     NOISE_FLOOR_RMS = 0.005
     if rms < NOISE_FLOOR_RMS:
         return False, 0.0
     ```
   - `services/vad/silero_vad.py` lines 87-105 slices chunks >512 samples into 512-sample frames (32ms at 16kHz) and pads short chunks (<512 samples) with zeros to 512 samples before evaluating PyTorch model frames.
5. **Speech State Tracking & Buffer Finalization**:
   - `app/pipeline_state.py` lines 21-32 (`SpeechTracker.update`):
     Requires `SPEECH_FRAMES_TO_ACTIVATE = 2` chunks to activate speech state, and `SILENCE_FRAMES_TO_DEACTIVATE = 18` chunks (~900ms) to deactivate speech state.
   - `app/pipeline.py` lines 382-422 (`_vad_worker`):
     Processes chunks from `self.audio_queue` (maxsize=1000). On `just_deactivated` or `is_full` or periodic interval (0.3s), finalizes `PerSourceAudioBuffer` into `SttJob` and puts it into `self.stt_queue`.

---

## 2. Logic Chain

1. **Observation 1 & 2** show that `app/application.py` relies on `services/audio/input.py` rather than root `audio/input.py`. `services/audio/input.py` contains robust device auto-detection and channel validation via `utils/device.py`.
2. **Observation 2** explains how target hardware like Boult Audio Airbass (index 16) is handled. If the headset connects via A2DP profile (`max_input_channels = 0`) or if index 16 is invalid/disconnected, `find_best_input_device(16)` detects `channels <= 0`, logs a warning, and falls back to a valid microphone (e.g. system default or headset mic) without throwing an unhandled PortAudio crash. However, if using root `audio/input.py` directly, an out-of-range index or missing loopback device would cause an unhandled `RuntimeError`.
3. **Observation 3** shows that computer audio loopback is managed via a 3-tier fallback system: WASAPI via `soundcard` background thread -> Stereo Mix via `sounddevice` -> VB-Cable Output. If loopback fails entirely, `services/audio/input.py` catches the error and falls back to mic-only capture.
4. **Observation 4 & 5** establish the VAD worker architecture. Audio chunks from mic/loopback enter `audio_queue`, are sliced into 512-sample frames, and evaluated by `SileroVAD`. The `SpeechTracker` filters transient noise spikes by requiring 2 consecutive speech chunks (~100ms) to activate speech and 18 silence chunks (~900ms) to deactivate speech. Finalized speech buffers are converted to `SttJob` and pushed to `stt_queue`.
5. **Observation 4** highlights a potential silence/drop bug: legacy `vad/silero_vad.py` line 76 hardcodes `NOISE_FLOOR_RMS = 0.005`, which drops quiet speech (RMS 0.0005 to 0.0049) before VAD model evaluation.

---

## 3. Caveats

- **Hardware Availability**: Tests running in headless or CI environments without active audio hardware rely on mock/synthetic audio device drivers or test fixtures (`mock_device_list`).
- **Bluetooth Dynamic Profile Behavior**: Bluetooth headsets like Boult Audio Airbass physically change Windows driver channel counts depending on whether audio recording software opens the mic (triggering HFP/HSP mono profile switch).

---

## 4. Conclusion

1. **Audio Capture Architecture**: The active production pipeline uses `services/audio/input.py` (`SoundDeviceInput`) and `services/audio/loopback.py`. Microphone input streams use score-based auto-detection (`utils/device.py`) to handle missing or invalid hardware indices cleanly. Computer audio loopback utilizes a 3-tier strategy (WASAPI `soundcard` -> Stereo Mix `sounddevice` -> VB-Cable) with fallback to mic-only mode.
2. **Hardware & Crash Prevention**: Device index 16 (Boult Audio Airbass) and index overrides in `.env` are validated against channel availability (`max_input_channels > 0`) at startup. If index 16 has 0 input channels or is unplugged, TalkSync falls back to system input without crashing.
3. **Silero VAD Architecture**: `_vad_worker` in `app/pipeline.py` dequeues float32 audio chunks from `audio_queue`, evaluates 512-sample frame probabilities using `SileroVAD`, updates `SpeechTracker` state (2 frames activate, 18 frames deactivate), and finalizes speech buffers in `PerSourceAudioBuffer` to send `SttJob` objects to `stt_queue`.
4. **Actionable Recommendations**:
   - Ensure the pipeline exclusively references `services/audio/input.py` and `services/vad/silero_vad.py`.
   - Reconcile `vad/silero_vad.py`'s hardcoded `NOISE_FLOOR_RMS = 0.005` with `services/vad/silero_vad.py`'s configurable threshold (0.0003–0.0005) to ensure soft headset speech is not muted.

---

## 5. Verification Method

To independently verify the analysis and test suite:

1. **Inspect Source Files**:
   - `services/audio/input.py` lines 111-180 (`start`, `_start_loopback`, `_start_mic`)
   - `services/audio/loopback.py` lines 14-65 (`find_wasapi_loopback`) and 124-155 (`find_loopback_device`)
   - `utils/device.py` lines 71-177 (`find_best_input_device`)
   - `services/vad/silero_vad.py` lines 68-105 (`is_speech`) and 106-150 (`process`)
   - `app/pipeline.py` lines 309-362 (`_capture_worker`) and 363-426 (`_vad_worker`)
   - `app/pipeline_state.py` lines 14-50 (`SpeechTracker`) and 63-146 (`PerSourceAudioBuffer`)
2. **Run Programmatic Unit & Stream Reliability Tests**:
   - Run stream reliability & VAD tests:
     `pytest tests/test_audio_stream_reliability.py tests/test_vad.py tests/test_device_detection.py tests/test_mic_capture.py`
   - Run device fallback script:
     `python tests/test_device_detection.py`
