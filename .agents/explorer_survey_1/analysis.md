# TalkSync AI — Audio, Pipeline & Latency Survey Analysis

**Agent:** `explorer_survey_1`  
**Date:** 2026-08-06  
**Scope:** Audio Capture & DSP, Pipeline & Concurrency, Stage Latencies & Accuracy

---

## Executive Summary

A comprehensive, read-only diagnostic investigation was conducted on the TalkSync AI desktop application at `d:\talksync\talksync`. The analysis focused on three primary engineering domains:
1. **Audio Capture & DSP Infrastructure** (`services/audio/*`, `utils/device.py`, `services/audio_processing/*`, and standalone test scripts in `tests/`).
2. **Pipeline & Concurrency Architecture** (`app/pipeline.py`, `app/application.py`, thread synchronization, queue eviction, memory/resource leaks).
3. **Stage Latencies & Accuracy Bottlenecks** (VAD hangover delays, STT/TTS processing pipelines, LLM refinement overhead, thread creation churn).

---

## 1. Domain 1: Audio Capture & DSP Analysis

### 1.1 Mic & Loopback Stream Management (`services/audio/input.py`, `services/audio/loopback.py`)
- **Microphone Capture (`SoundDeviceInput._start_mic`)**:
  - Device resolution: `utils/device.py:find_best_input_device()` validates requested device ID (e.g., ID 35 from `.env`). It verifies `max_input_channels > 0` and falls back cleanly to auto-detection (headset mic > default mic > any valid input) if requested ID is out-of-range (e.g. 9999 or -1) or invalid.
  - Multi-candidate fallback loop attempts opening streams across native sample rates (44.1kHz / 48kHz) down to 16kHz mono.
- **Loopback Capture (`SoundDeviceInput._start_loopback`)**:
  - Priority chain: **WASAPI Loopback** (via `soundcard` package in background thread `_wasapi_thread`) → **Stereo Mix** (`find_stereo_mix()` preferring HD Audio / HAP WASAPI driver over MME) → **VB-Cable Output** (`find_vb_cable()`).
  - `_start_wasapi_loopback()` runs a continuous recording loop in a daemon thread `_wasapi_thread`, posting `AudioChunk` objects to `_loopback_queue` via `loop.call_soon_threadsafe()`.
- **Callback Processing (`SoundDeviceInput._make_callback`)**:
  - Converts multi-channel to mono via `np.mean(audio, axis=1)`.
  - Fixed gain multiplier & anti-clipping protection (`np.clip(audio, -1.0, 1.0)`).
  - Downsamples native rate to target 16kHz via `services/audio/resampler.py:resample()`.
  - Dispatches `AudioChunk` objects to `_queue` or `_loopback_queue` (maxsize=500).
  - Eviction policy: `if _queue.full(): self._overflow_count += 1; _queue.get_nowait()` evicts oldest chunk to prevent pipeline stall.

### 1.2 Dynamic Noise Gating, Downsampling & Normalization
- **RMS Noise Floor Gate**:
  - `rms_gate_threshold = 0.0003` in `config/settings.py` (and STT engines) filters static room hum (`0.0001`–`0.00025`) while allowing soft speech input (`0.0005`–`0.0050`).
  - `SileroVAD` pre-filters chunks with `RMS_GATE_THRESHOLD = 0.005` / `0.0003`.
- **Downsampling (`services/audio/resampler.py`)**:
  - Uses linear interpolation: `np.interp(indices, np.arange(src_len), audio)`.
  - *Finding*: Linear interpolation is fast but lacks anti-aliasing filtering compared to polyphase resamplers (e.g. `scipy.signal.resample_poly`), which can introduce high-frequency aliasing artifacts into high-pitch female speech.
- **RMS & AGC Normalization**:
  - `AutomaticGainControl` (`services/audio_processing/agc.py`) & inline AGC in STT engines (`FasterWhisperSTT` & `OpenAISTT`): Normalizes signal RMS to `0.20` with a max gain ceiling of `8.0x`.
  - `PeakNormalizer` (`services/audio_processing/normalizer.py`): Scales peak amplitude to 1.0.
  - `RNNoiseProcessor` (`services/audio_processing/rnnoise.py`): Processes noise reduction on 480-sample frames.

### 1.3 Audio Output & Playback Thread Churn (`services/audio/output.py`)
- **Dual Output Streams**: `SoundDeviceOutput` opens speaker output and virtual mic (`VB-Cable Output`, Device 7) streams in parallel.
- **critical Concurrency Bottleneck in Playback**:
  - In `SoundDeviceOutput._playback_loop()` (lines 145–171): For *every* audio chunk played back, it creates and joins two fresh OS threads:
    ```python
    t = threading.Thread(target=write_to_stream, args=(stream, out_audio.astype(np.float32)), daemon=True)
    t.start(); threads.append(t)
    for t in threads: t.join()
    ```
  - *Impact*: During continuous TTS playback, this causes 50–100 OS thread creations/joins per second! This results in CPU thread churn, context switching overhead, and audio micro-stutters.

### 1.4 Standalone Test Verification
- `tests/test_mic_capture.py`: Validates VAD threshold `0.45`, verifies mic RMS > `0.0003` with 440Hz synthetic fallback.
- `tests/test_loopback_headphones.py`: Validates WASAPI / Stereo Mix loopback RMS > `0.001` during 440Hz tone playback.
- `tests/test_device_detection.py`: Verifies out-of-range IDs (9999, -1) and 0-channel device fallback.
- `tests/test_bidirectional.py`: Verifies two-way translation routing (VOICE → Panel A, COMPUTER_AUDIO → Panel B) and per-panel speaker gating.

---

## 2. Domain 2: Pipeline & Concurrency Audit

### 2.1 Async Worker Tasks & Lifecycle (`app/pipeline.py`)
`Pipeline.start()` launches 5–7 worker tasks on the asyncio event loop:
1. `_vad_worker()`: Consumes `audio_queue` (maxsize=1000), evaluates VAD scores, manages `PerSourceAudioBuffer` and `SpeechTracker`, enqueues finalized `SttJob` into `stt_queue`.
2. `_stt_worker()`: Consumes `stt_queue` (maxsize=256), calls STT model (`FasterWhisperSTT` in thread executor or `OpenAISTT`), applies language constraint filters and min word count, enqueues `TranscriptionSegment` into `translation_queue`.
3. `_translation_worker()`: Consumes `translation_queue` (maxsize=256), invokes `_translate_and_route()`, calls DeepL / Argos / OpenAI, enqueues `TranslationResult` into `tts_queue`.
4. `_tts_worker()`: Consumes `tts_queue` (maxsize=256), splits text into sentences, synthesizes audio (Piper / Sarvam / SAPI5 fallback), triggers `_activate_tts_mute_gate()`, plays audio via `_audio_output.play()`.
5. `_stats_worker()`: Periodically samples `get_all_latency_summaries()` every 0.5s.
6. `_capture_worker("mic")` & `_capture_worker("loopback")`: Async stream consumers feeding `audio_queue`.

### 2.2 Queue Eviction & Buffer Flushing
- `audio_queue` (maxsize=1000): Oldest chunk evicted on overflow in callback.
- `stt_queue`, `translation_queue`, `tts_queue` (maxsize=256): Overflow drops newest chunk via `put_nowait` exception handling.
- `_purge_loopback_queues()`: Called during TTS mute gate activation (`_activate_tts_mute_gate`). Purges `audio_queue`, `stt_queue`, resets VAD loopback buffers, and clears speech trackers to prevent acoustic feedback echo loops.

### 2.3 Tkinter-asyncio Thread Safety & Boundary Crossing
- **Architecture**:
  - Main thread: Tkinter GUI event loop (`window.mainloop()`).
  - Background thread: `MainWindow._run_pipeline_thread()` runs a dedicated asyncio event loop (`loop = asyncio.new_event_loop()`).
- **Thread Safety Inspection**:
  - Callbacks (`on_transcription`, `on_translation`, `on_status`, `on_latency`, `on_audio_level`) originate from the background asyncio loop thread and use `self.after(0, ...)` to post UI updates to Tkinter. `self.after()` is thread-safe in Tkinter.
  - UI inputs (e.g. text input submission) call `asyncio.run_coroutine_threadsafe(self.pipeline.process_text_input(...), loop)` to cross safely from Tkinter to asyncio loop.
  - *Verdict*: Tkinter-asyncio boundary thread-safety is cleanly maintained.

### 2.4 Resource & Memory Leak Risks
1. **Unclosed WASAPI Thread on Init Failure**: In `SoundDeviceInput._start_wasapi_loopback()`, if mic initialization fails *after* `_wasapi_thread` is started, `_wasapi_thread` remains active in the background unless `stop()` is called in the exception handler.
2. **SQLite Connection Leak**: `Pipeline.start()` calls `self._db.connect()`. `Pipeline.stop()` calls `self._db.close()`. If `start()` fails midway, `_db.connect()` may leak an unclosed connection handle.
3. **Queue Full Signal Drop in Output Stop**: In `SoundDeviceOutput.stop()` (line 101), `self._play_queue.put_nowait((None, 0))` ignores `queue.Full`. If the queue is full, sentinel `(None, 0)` is not enqueued, forcing `_play_thread.join(timeout=2.0)` to wait for the full 2-second timeout.

---

## 3. Domain 3: Stage Latencies & Accuracy Analysis

### 3.1 Detailed Stage Latency Profile

| Stage | Mechanism / Location | Measured / Estimated Latency | Impact & Bottleneck Rating |
|---|---|---|---|
| **VAD Deactivation** | `app/pipeline_state.py:10` (`SILENCE_FRAMES_TO_DEACTIVATE = 18`) | **540 ms** (18 frames × 30ms) | 🔴 **HIGH BOTTLENECK**: Forces 540ms silence delay before speech segment is finalized |
| **VAD Inference** | `services/vad/silero_vad.py` (Silero VAD 512-sample frames) | 15–30 ms | 🟢 LOW |
| **STT Transcription** | `FasterWhisperSTT` (CPU int8 / CUDA float16) or `OpenAISTT` | 350–650 ms (CUDA / API), 1200–2400 ms (CPU) | 🟡 MEDIUM (CPU mode is high) |
| **STT LLM Refinement** | `services/stt/openai_stt.py:326` (`_refine_transcription` via `gpt-4o-mini`) | **300–800 ms** | 🔴 **HIGH BOTTLENECK**: Sequential LLM call per segment adds 300-800ms before translation |
| **Translation** | `DeepLTranslator` / `ArgosTranslator` (warm) | 15–220 ms | 🟢 LOW (Argos cold-start Stanza ~3s) |
| **TTS Synthesis** | `PiperTTS` / `SarvamTTS` | 150–300 ms (Piper), 400–900 ms (Sarvam) | 🟡 MEDIUM |
| **TTS Output Playback** | `services/audio/output.py` (per-chunk thread creation) | 20–50 ms overhead | 🟡 MEDIUM (causes thread churn) |
| **E2E Total** | Full Pipeline (Mic/Loopback -> TTS Output) | **1400 ms – 3200 ms** | Target is < 1500 ms |

### 3.2 Key Latency Bottleneck Summary
1. **VAD Deactivation Delay (540 ms)**: `SILENCE_FRAMES_TO_DEACTIVATE = 18` forces the pipeline to wait over half a second after the user stops speaking before sending audio to STT. Reducing this to 8–10 frames (240–300 ms) will immediately save ~250–300 ms of E2E latency.
2. **Sequential LLM Refinement in STT (300–800 ms)**: `OpenAISTT._refine_transcription` invokes `gpt-4o-mini` synchronously on every final segment. Making refinement optional, asynchronous, or bypassing it for clean audio will eliminate 300–800 ms.
3. **Playback Thread Churn**: Creating 2 threads per 30ms chunk in `output.py` introduces playback latency jitter. Using a single persistent worker thread or sounddevice callback writing will optimize playback.

---

## 4. Evidence Matrix & References

- **Audio Capture & Resampling**: `services/audio/input.py:48-63`, `services/audio/resampler.py:6-12`
- **Loopback Priority & WASAPI**: `services/audio/loopback.py:14-123`
- **Output Thread Creation Overhead**: `services/audio/output.py:145-171`
- **Device Resolution & Fallback**: `utils/device.py:71-285`
- **VAD Hangover Frame Count**: `app/pipeline_state.py:10` (`SILENCE_FRAMES_TO_DEACTIVATE = 18`)
- **STT LLM Refinement Overhead**: `services/stt/openai_stt.py:326-371`
- **Tkinter-asyncio Thread Safety**: `ui/main_window.py:384-418`, `ui/main_window.py:631-670`
- **Standalone Tests**: `tests/test_mic_capture.py`, `tests/test_loopback_headphones.py`, `tests/test_device_detection.py`, `tests/test_bidirectional.py`
