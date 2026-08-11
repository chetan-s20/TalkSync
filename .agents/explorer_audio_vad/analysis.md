# E2E Audio Capture and VAD Architecture Analysis — TalkSync AI

## Executive Summary
This document details the read-only architectural investigation into the End-to-End (E2E) audio capture, stream management, hardware device resolution, and Silero Voice Activity Detection (VAD) subsystem in TalkSync AI (`d:\talksync\talksync`).

---

## 1. Stream Initialization and Management (Microphone & Loopback)

### Architecture & Service Module Hierarchy
TalkSync contains two implementations of audio input:
1. Active Production Service: `services/audio/input.py` (`SoundDeviceInput`), instantiated via `app/application.py` (`Application.build_pipeline()`).
2. Legacy Core Component: `audio/input.py` (`SoundDeviceInput`), providing basic sounddevice callback input.

### Microphone Input Stream Lifecycle
- **Device Resolution (`utils/device.py` line 71: `find_best_input_device`)**:
  - Validates requested `device_id` (e.g. from `.env` or UI). If valid and `max_input_channels > 0`, returns it.
  - Otherwise, executes score-based auto-detection ranking devices by:
    - Channel capability (`max_input_channels > 0`).
    - Device type keywords (scores: headset/headphone/hands-free +600, mic/microphone +200).
    - Default system input (+300).
    - Host API priority (WASAPI / DirectSound / MME +50).
  - Explicitly penalizes loopback keywords (`stereo mix`, `cable output`, `virtual cable`) with score -500 to prevent loopback devices from being selected as the microphone.
- **Stream Creation (`services/audio/input.py` line 344: `_start_mic`)**:
  - Builds a sequence of fallback candidate tuples: `(device_id, sample_rate, channels)`.
  - Attempts to open `sounddevice.InputStream` with parameters:
    `samplerate=sr`, `channels=ch`, `dtype="float32"`, `blocksize=int(sr * chunk_duration_ms / 1000)`, `callback=cb`, `device=dev`.
- **Callback Processing (`services/audio/input.py` line 37: `_make_callback`)**:
  - Converts multi-channel array to 1D mono via `np.mean(audio, axis=1)`.
  - Applies volume gain and anti-clipping protection via `np.clip(audio, -1.0, 1.0)`.
  - Resamples audio from native device sample rate (e.g., 44.1kHz or 48kHz) to target 16kHz using linear interpolation (`services/audio/resampler.py`).
  - Wraps audio array as an `AudioChunk` dataclass.
  - Safely dispatches `AudioChunk` to `self._queue` (maxsize=500) using `loop.call_soon_threadsafe`.
  - **Overflow Protection**: If `self._queue` is full, evicts the oldest chunk (`_queue.get_nowait()`) to prevent pipeline stalls and increments `self._overflow_count`.

### Loopback Stream Lifecycle (Computer Audio Capture)
- **Multi-Tier Loopback Resolution (`services/audio/loopback.py` line 124: `find_loopback_device`)**:
  1. **Tier 1 — WASAPI Loopback via `soundcard` library (`find_wasapi_loopback`)**:
     - Enumerates loopback microphones (`sc.all_microphones(include_loopback=True)`).
     - Matches active output device type (preferring headphone/headset loopback endpoints).
     - Spawned in background daemon thread `_wasapi_thread` (`services/audio/input.py` line 209).
     - Iterates through sample rates (16kHz, native rate, 44.1kHz, 48kHz), recording `numframes=block` per iteration.
  2. **Tier 2 — Stereo Mix via `sounddevice` (`find_stereo_mix`)**:
     - Two-pass search querying `sd.query_devices()`.
     - Pass 1 prefers Realtek HD Audio / HAP driver endpoints.
     - Pass 2 accepts generic Stereo Mix endpoints (`max_input_channels > 0` and `"stereo mix" in name.lower()`).
     - Opened at native sample rate (44.1kHz/48kHz) with WASAPI extra settings (`sd.WasapiSettings(exclusive=False)`). Resampled to 16kHz in callback.
  3. **Tier 3 — VB-Audio Virtual Cable Output (`find_vb_cable`)**:
     - Queries `sd.query_devices()` for `"CABLE Output"` or `"VB-Audio Virtual Cable"` with input channels.
- **Fail-Safe Fallback**:
  - If WASAPI loopback fails at runtime, `services/audio/input.py` line 155 logs warning and invokes `_start_fallback_loopback()`.
  - If all loopback initialization methods fail, `services/audio/input.py` line 128 catches the exception cleanly, logs a warning, sets `self._loopback_queue = None`, and continues in **Microphone-Only Capture Mode** without crashing the application.

---

## 2. Stream Reliability, Crashes, Silence Issues & Hardware Edge Cases

### Target Hardware: Boult Audio Airbass (Bluetooth Headset — Index 16)
- **Root Cause of Index 16 Failures**:
  - Bluetooth device index numbers in Windows PortAudio (`sounddevice`) are dynamic and change whenever devices connect/disconnect or when host APIs enumerate.
  - Windows Bluetooth headsets register two separate driver profiles:
    1. **Hands-Free AG Audio (HFP/HSP)**: Input = 1 channel (8kHz/16kHz), Output = 1 channel.
    2. **Stereo Headphones (A2DP)**: Input = 0 channels, Output = 2 channels (44.1kHz/48kHz).
  - If Boult Audio Airbass is connected in A2DP Stereo mode, device index 16 reports `max_input_channels = 0`.
  - Attempting to pass `device=16` directly to `sd.InputStream(channels=1)` raises `PortAudioError: PaErrorCode -9998 (Invalid number of channels)` or `PaErrorCode -9996 (Invalid device index)` if index 16 shifted.
- **TalkSync Safeguards**:
  - `app/application.py` line 37 executes `validate_and_resolve_audio_devices(settings)` at startup.
  - `utils/device.py` lines 97-115 check if requested index 16 has `max_input_channels > 0`. If 0 channels or out-of-range, logs a warning and falls back smoothly to auto-detecting the best available input device.

### Silence & Drop Issues
1. **Double Noise Floor Gating**:
   - `app/pipeline.py` `_capture_worker` line 319 filters audio chunks against `rms_gate_threshold` (default 0.0003). Chunks below 0.0003 are zero-filled.
   - `vad/silero_vad.py` line 76 contains a hardcoded `NOISE_FLOOR_RMS = 0.005`.
   - *Issue*: Soft spoken speech on wired/Bluetooth headset mics often yields RMS levels in the range `0.0005` – `0.0045`. While passing `_capture_worker`'s 0.0003 gate, `vad/silero_vad.py` drops these frames immediately before calling the Silero neural network model. (Note: `services/vad/silero_vad.py` uses configurable settings threshold `0.35`–`0.45`).
2. **Callback Exception Swallowing**:
   - In root `audio/input.py` line 68, callback exceptions are wrapped in `except Exception: pass`. If an unhandled exception occurs inside the callback, stream silently halts data queueing without reporting errors.
3. **Loopback Device Absence**:
   - In Windows 10/11, Stereo Mix is disabled by default. If VB-Cable is not installed, sounddevice loopback fails. While `services/audio/input.py` handles this with mic fallback, root `audio/input.py` line 149 raises unhandled `RuntimeError: No loopback device found.`.
4. **TTS Mute Gate Queue Purging**:
   - When TTS plays back, `_activate_tts_mute_gate` in `app/pipeline.py` sets `_ignore_mic_until` and `_ignore_loopback_until` for `duration_s + 0.5s` to prevent loopback/mic feedback. If TTS duration is miscalculated, audio chunks are dropped continuously.

---

## 3. Silero VAD Worker & Speech Detection Implementation

### VAD Pipeline Flow
```
Audio Capture Worker (mic / loopback)
       │
       ▼  (AudioChunk float32 data, 16kHz)
  audio_queue (maxsize=1000)
       │
       ▼ Dequeue chunk
   _vad_worker()  [app/pipeline.py:363]
       │
       ├──► SileroVAD.process(chunk)  [services/vad/silero_vad.py:106]
       │       ├── RMS Gating (RMS >= noise floor threshold)
       │       ├── Slices audio into 512-sample frames (32ms at 16kHz)
       │       ├── Evaluates PyTorch ONNX model for frame probabilities
       │       └── Returns VADResult(is_speech, confidence, chunk)
       │
       ├──► SpeechTracker.update(is_speech)  [app/pipeline_state.py:14]
       │       ├── SPEECH_FRAMES_TO_ACTIVATE = 2 (requires 2 speech chunks ~100ms)
       │       └── SILENCE_FRAMES_TO_DEACTIVATE = 18 (requires 18 silence chunks ~900ms)
       │
       └──► PerSourceAudioBuffer.append(audio_array)  [app/pipeline_state.py:63]
               ├── Finalizes speech segment when just_deactivated & total_samples >= 4000 (250ms)
               ├── Finalizes partial job when total_samples >= 16000 & feed interval >= 0.3s
               └── Enqueues SttJob -> stt_queue
```

### Event Propagation & Bridge Dispatch
- When speech is finalized or partial chunk emitted, `_vad_worker` sends `SttJob` to `stt_queue`.
- Status updates (`on_status("Processing speech...", "processing")`) and VAD state events (`emit_vad_state(is_speech)`) are emitted to `ApiBridge` (`app/bridge.py`), which calls `window.evaluate_js()` for pywebview UI rendering.

---

## 4. Tests, Entry Points, and Test Runner Scripts

### Main Entry Points
- Application CLI/UI Entry: `main.py`
- App Orchestrator: `app/application.py` (`Application.build_pipeline()`)
- PyWebView API Bridge: `app/bridge.py` (`ApiBridge`)
- Async Pipeline Engine: `app/pipeline.py` (`Pipeline`)

### Core Audio & VAD Modules
- `services/audio/input.py` — Active production audio input service (`SoundDeviceInput`)
- `services/audio/loopback.py` — Multi-tier WASAPI/Stereo Mix/VB-Cable loopback discovery
- `services/audio/output.py` — Audio output router (`SoundDeviceOutput`)
- `services/vad/silero_vad.py` — Silero VAD engine wrapper
- `utils/device.py` — Input/output device auto-detection and channel validation
- `audio/input.py` & `vad/silero_vad.py` — Legacy root implementations

### Audio & VAD Test Suite Catalog
| Test File Path | Primary Focus & Coverage |
|---|---|
| `tests/test_audio_input.py` | Loopback device discovery (Stereo Mix, VB-Cable), resampler, peak normalizer, AGC, audio level calculations. |
| `tests/test_audio_stream_reliability.py` | Silero VAD sliding window chunking (>512 samples), short chunk padding, noise floor gate, mic channel handling, WASAPI fallback to Stereo Mix, queue overflow eviction, anti-clipping bounds, StreamDiagnostics. |
| `tests/test_vad.py` | `VADResult` dataclass, `SileroVAD` initialization, start/stop lifecycle, speech/silence processing, model loading fallback, multi-rate support, error handling. |
| `tests/test_device_detection.py` | Out-of-bounds requested IDs (9999, -1), 0-channel device fallback, Application startup device resolution. |
| `tests/test_mic_capture.py` | Real microphone capture execution, RMS level calculation, VAD threshold (0.45) validation. |
| `tests/test_loopback_headphones.py` | WASAPI headphone loopback & Stereo Mix native sample rate stream testing. |
| `tests/test_real_audio_capture.py` | Hardware device enumeration, real 2s mic capture, real 2s loopback capture, dual mic+loopback capture. |
| `tests/test_bidirectional.py` | Multi-panel bidirectional routing and per-panel speaker toggle gating. |
| `tests/test_pipeline.py` | E2E async pipeline workers (`_vad_worker`, `_stt_worker`, `_translation_worker`, `_tts_worker`) integration. |

### Execution Commands
- Run all unit and integration tests: `pytest`
- Run Audio & VAD specific tests:
  `pytest tests/test_audio_input.py tests/test_audio_stream_reliability.py tests/test_vad.py tests/test_device_detection.py tests/test_mic_capture.py tests/test_loopback_headphones.py`
- Run direct test scripts:
  `python tests/test_device_detection.py`
  `python tests/test_mic_capture.py`
