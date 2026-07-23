# Handoff Report — Dual Audio Capture (Requirement R1) Audit

## 1. Observation

### Codebase Architecture & Key Files
- `services/audio/input.py`: Implements `SoundDeviceInput(BaseAudioInput)` managing simultaneous dual audio streams (`_mic_stream` and `_loopback_stream`).
- `services/audio/loopback.py`: Provides helper functions (`find_stereo_mix()`, `find_vb_cable()`, `find_loopback_device()`, `find_vb_cable_output()`) to discover computer audio loopback capture devices.
- `config/settings.py`: Defines `AudioSettings` (lines 11–24) and `Settings` (lines 98–121) managing audio parameters (sample rate, chunk duration, device IDs, names).
- `app/interfaces.py`: Defines `AudioChunk` dataclass (lines 9–16) with `source: str = "mic"`.
- `app/pipeline.py`: Orchestrates parallel capture workers (`_capture_worker("mic")` and `_capture_worker("loopback")`, lines 148–153), tagging chunks, and routing them to `self.audio_queue` for per-source VAD processing (`PipelineState`, `app/pipeline_state.py`).

### Verbatim Observations & Code Locations

#### A. Dual Stream Initialization & Management (`services/audio/input.py`)
- **Class Attributes** (lines 20–28):
  ```python
  self._mic_stream: Optional[sd.InputStream] = None
  self._loopback_stream: Optional[sd.InputStream] = None
  self._queue: Optional[asyncio.Queue[AudioChunk]] = None
  self._loopback_queue: Optional[asyncio.Queue[AudioChunk]] = None
  ```
- **Stream Lifecycle** (lines 61–105):
  - `start(device_id, loopback, capture_mic)` initializes `_queue` (maxsize=100) and `_loopback_queue` (maxsize=100 if `loopback=True`).
  - When `loopback=True`, `_start_loopback(device_id, capture_mic)` resolves the loopback input device via `find_loopback_device()`.
  - `_loopback_stream` is started as `sd.InputStream` with native sample rate and channels (lines 94–100).
  - If `capture_mic=True` (non-text mode), `_start_loopback` invokes `_start_mic(None)` (line 104) to simultaneously initialize `_mic_stream` on the microphone input device.
- **Stream Stop** (lines 142–164):
  `stop()` iterates over `(self._mic_stream, self._loopback_stream)`, calling `.stop()` and `.close()` on both, and pushes `None` sentinel values to both queues.

#### B. Audio Chunk Formatting, Tagging, and Enqueueing (`services/audio/input.py`, `app/interfaces.py`, `app/pipeline.py`)
- **AudioChunk Structure** (`app/interfaces.py`, lines 9–16):
  ```python
  @dataclass
  class AudioChunk:
      data: bytes
      sample_rate: int
      channels: int
      timestamp: datetime
      duration_ms: float
      source: str = "mic"
  ```
- **PortAudio Callback & Resampling** (`services/audio/input.py`, lines 29–59):
  - `_make_callback(native_sr, source)` handles channel downmixing to mono:
    `audio = np.mean(audio, axis=1)` (line 41).
  - Performs sample rate conversion if `native_sr != target_sr` via `resample(audio, native_sr, target_sr)` (line 45, using linear interpolation in `services/audio/resampler.py`).
  - Instantiates `AudioChunk` tagged with `source=source` (`"mic"` vs `"loopback"`):
    ```python
    chunk = AudioChunk(
        data=audio.tobytes(), sample_rate=target_sr, channels=1,
        timestamp=datetime.now(), duration_ms=dur_ms, source=source,
    )
    ```
  - Thread-safe queueing into internal service queue: `loop.call_soon_threadsafe(q.put_nowait, chunk)` (line 54).
- **Pipeline Consumption & Worker Architecture** (`app/pipeline.py`, lines 148–218):
  - Launching parallel workers:
    ```python
    if not text_mode:
        tasks.append(asyncio.create_task(self._capture_worker("mic")))
    if loopback:
        tasks.append(asyncio.create_task(self._capture_worker("loopback")))
    ```
  - `_capture_worker(source)` pulls from `_audio_input.stream()` (mic) or `_audio_input.stream_loopback()` (loopback).
  - Mic chunks are suppressed during active TTS playback via `_should_ignore_mic()` (line 196).
  - Explicitly ensures `chunk.source = source` (line 198) and enqueues into `self.audio_queue` (`asyncio.Queue[AudioChunk]`, maxsize=256).
- **Per-Source VAD Buffering** (`app/pipeline.py` & `app/pipeline_state.py`):
  - In `_vad_worker()` (lines 227–230), `PipelineState` looks up source-specific audio buffers:
    `buf = self._state.get_buffer(chunk.source)`
    `tracker = self._state.get_speech_tracker(chunk.source)`
  - When speech ends, `SttJob` carries `job.source` ("mic" or "loopback"), which `_stt_worker` maps to `input_source = "COMPUTER_AUDIO"` (if loopback) or `"VOICE"` (if mic) (line 286).

#### C. Dynamic Device Selection & Resolution (`services/audio/loopback.py`, `services/audio/input.py`)
- **Microphone Device Resolution** (`services/audio/input.py`, lines 106–140):
  - Prioritizes user-specified `device_id` (`settings.input_device_id`).
  - Queries device capabilities with `sd.query_devices(device_id)`.
  - Fallback list: `[(device_id, native_sr, native_ch), (None, settings.sample_rate, settings.channels)]`.
- **Loopback Device Resolution** (`services/audio/loopback.py`, lines 12–52):
  - `find_stereo_mix()` scans input devices for `"stereo mix"` in device name (line 21).
  - `find_vb_cable()` scans input devices for `"cable"` or `"vb-audio"` in device name (line 36).
  - `find_loopback_device()` tries `Stereo Mix` first, then `VB-Cable`. Returns tuple `(dev_id, desc)` or `None`.
  - If `None`, `_start_loopback` raises `RuntimeError("No loopback device found (Stereo Mix or VB-Cable)")`.

---

## 2. Logic Chain

1. **Simultaneous Capture**:
   - `SoundDeviceInput` spawns two separate, concurrent `sd.InputStream` instances (`_mic_stream` and `_loopback_stream`) on host audio threads.
   - Each stream invokes `_make_callback` with its designated `source` identifier (`"mic"` or `"loopback"`).
   - This ensures both user microphone input and computer output audio are captured simultaneously without blocking each other.

2. **Source Separation & Chunk Tagging**:
   - `AudioChunk` carries the `source` field explicitly.
   - In `Pipeline`, `_capture_worker` preserves `chunk.source` and pushes chunks into `self.audio_queue`.
   - `_vad_worker` uses `chunk.source` to retrieve isolated `PerSourceAudioBuffer` and `SpeechTracker` instances in `PipelineState`.
   - This prevents mic audio and system audio from colliding in VAD buffers or triggering false sentence breaks across streams.
   - Upon VAD completion, the source propagates through `SttJob` into `TranscriptionSegment.input_source` (`"VOICE"` vs `"COMPUTER_AUDIO"`).

3. **Device Selection & Resolution**:
   - Mic device resolution relies on explicit `device_id` fallback to system default (`None`).
   - Loopback resolution dynamically identifies virtual loopback interfaces (`Stereo Mix` or `VB-Cable`).
   - The current resolution relies on string pattern matching in device names (`"stereo mix"`, `"cable"`, `"vb-audio"`).

---

## 3. Caveats

1. **WASAPI Loopback Support**: Windows native WASAPI loopback capture (capturing default output endpoint directly without needing Stereo Mix or VB-Cable installed) is not explicitly implemented via PortAudio/SoundDevice hostapi flags. If neither Stereo Mix nor VB-Cable driver is active, loopback initialization fails with a `RuntimeError`.
2. **Queue Drop Exceptions**: In `_make_callback` (line 55), `loop.call_soon_threadsafe(q.put_nowait, chunk)` catches `asyncio.QueueFull` with `pass`. Heavy load will drop audio chunks silently without logging.
3. **Legacy File Coexistence**: Legacy module `talksync/audio/input.py` exists alongside active module `talksync/services/audio/input.py`. Active pipeline references `services.audio.input.SoundDeviceInput`.
4. **Resampling Quality**: `services/audio/resampler.py` uses linear interpolation (`np.interp`). While fast and adequate for 16kHz speech, high-ratio sample rate conversions (e.g. 48kHz to 16kHz) may produce slight aliasing artifacts compared to polyphase resampling (e.g., `scipy.signal.resample_poly` or `samplerate`).

---

## 4. Conclusion

The dual audio capture system in TalkSync AI provides clean end-to-end separation between microphone audio (`"mic"`) and computer system audio (`"loopback"`). Streams run simultaneously via callback-driven `sd.InputStream` objects, tag individual `AudioChunk` instances, and feed isolated VAD pipelines in `PipelineState`.

### Recommended Code Modifications

1. **Queue Overflow Logging / Metrics** (`services/audio/input.py:55`):
   - Replace `except (RuntimeError, asyncio.QueueFull): pass` with debug logging or a dropped frame counter so buffer pressure can be monitored.
2. **Enhanced Loopback Device Resolution & WASAPI Direct Capture** (`services/audio/loopback.py`):
   - Add direct WASAPI host API loopback detection for Windows, allowing direct capture of default output speakers without requiring user configuration of Stereo Mix or third-party software.
   - Improve fallback error messaging when no loopback device is found, guiding the user to enable Stereo Mix or VB-Cable in Windows settings.
3. **Seamless Dynamic Device Hot-Swapping**:
   - Add a `switch_input_device(device_id)` method to `SoundDeviceInput` and `Pipeline` so users can change microphone devices during an active translation session without a full pipeline restart.
4. **Deprecate Unused Legacy Input Module**:
   - Remove or add deprecation warning to `talksync/audio/input.py` to prevent developer confusion with `talksync/services/audio/input.py`.

---

## 5. Verification Method

To independently verify these findings:

1. **Inspect Code Files**:
   - `services/audio/input.py`: lines 20–105 (`SoundDeviceInput` dual streams & callback), lines 165–189 (`stream()` / `stream_loopback()`).
   - `services/audio/loopback.py`: lines 12–52 (`find_stereo_mix`, `find_vb_cable`, `find_loopback_device`).
   - `config/settings.py`: lines 11–24 (`AudioSettings`).
   - `app/interfaces.py`: lines 9–16 (`AudioChunk`).
   - `app/pipeline.py`: lines 148–153 & 190–254 (`_capture_worker`, `_vad_worker`, `self.audio_queue`).
2. **Execute Diagnostic Test**:
   - Run Python test script instantiating `SoundDeviceInput` and listing devices via `list_devices()`.
   - Verify `find_loopback_device()` behavior on test machine.
3. **Invalidation Conditions**:
   - If `AudioChunk` source field is removed or unified into a single queue without source tags, dual audio stream separation is invalidated.
