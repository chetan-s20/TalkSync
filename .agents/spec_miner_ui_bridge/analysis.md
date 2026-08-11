# TalkSync AI — PyWebView UI Bridge Specification & Vulnerability Analysis

## Executive Summary

This specification analysis documents the architecture, interface contracts, real-time event propagation pipeline, edge-case boundary behavior, and failure modes of the PyWebView JS-Python IPC Bridge in TalkSync AI (`d:\talksync\talksync`).

TalkSync uses `pywebview` with a Chromium/WebView2 frontend rendering engine, connected to a Python backend orchestrating asynchronous workers for Voice Activity Detection (Silero VAD), Speech-to-Text (FasterWhisper/OpenAI STT), Neural Translation (DeepL/NLLB/MBART), and Multilingual Text-to-Speech (EdgeTTS/Kokoro/SAPI5).

---

## Features Discovered

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|----------|---------|-------------|--------|---------|----------------|----------------|
| 1 | IPC API | `start_session` | Starts live audio capture/translation session and launches background pipeline workers. | `source: str = "EN"`, `target: str = "HI"`, `loopback: bool = False`, `text_mode: bool = False` | `{"status": "ok", "active": True, "source": str, "target": str}` | Returns error dictionary or stops pipeline cleanly on exception. | `app/bridge.py:84`, `ui/web/app.js:103` |
| 2 | IPC API | `stop_session` | Gracefully stops active pipeline workers and audio streams. | None | `{"status": "ok", "active": False}` | Safely handles unstarted or already stopped pipeline. | `app/bridge.py:122`, `ui/web/app.js:113` |
| 3 | IPC API | `set_languages` | Dynamically updates source and target translation language pair. | `source: str`, `target: str` (Valid: EN, HI, ES, FR, DE, ZH, JA, KO, AUTO) | `{"status": "ok", "source": str, "target": str}` | Returns `{"status": "error", "error": "Unsupported language pair: ..."}` for invalid language codes or non-strings. | `app/bridge.py:129`, `tests/boundary/test_bridge_boundary.py:30` |
| 4 | IPC API | `set_translation_mode` | Switches translation mode between 1-way (unidirectional) and 2-way (bidirectional). | `mode: str` ("1-way", "2-way", "one_way", "two_way") | `{"status": "ok", "mode": str}` | Returns `{"status": "error", "error": "Invalid translation mode: ..."}` if invalid mode string passed. | `app/bridge.py:156`, `tests/boundary/test_bridge_boundary.py:42` |
| 5 | IPC API | `toggle_mic_mute` | Mutes or unmutes microphone audio capture stream. | `muted: bool = True` | `{"status": "ok", "muted": bool}` | Safely casts input to boolean. | `app/bridge.py:171`, `ui/web/app.js:190` |
| 6 | IPC API | `set_panel_tts` | Enables or disables TTS audio playback for Panel A (Mic) or Panel B (Loopback). | `panel: str` ("A" or "B"), `enabled: bool` | `{"status": "ok", "panel": str, "enabled": bool}` | Returns `{"status": "error", "error": "Invalid panel: ..."}` for invalid panel strings. | `app/bridge.py:178`, `ui/web/app.js:198` |
| 7 | IPC API | `set_audio_settings` | Updates VAD threshold, RMS noise gate, audio device selection, loopback, and virtual mic. | `settings: dict` | `{"status": "ok", "settings": dict}` | Returns `{"status": "error", "error": "Settings must be a dictionary"}` for non-dict input. | `app/bridge.py:196`, `ui/web/app.js:536` |
| 8 | IPC API | `fetch_history` | Fetches historical transcription and translation blocks from SQLite database. | `limit: int = 50` | `list[dict]` (cards with timestamps and text) | Returns empty list `[]` for limit <= 0 or invalid input types. | `app/bridge.py:215`, `ui/web/app.js:558` |
| 9 | IPC API | `submit_text_input` | Translates submitted text string immediately and enqueues result for TTS. | `text: str`, `target_lang: str = "HI"` | `{"status": "ok", "original": str, "translated": str, ...}` | Returns `{"status": "error", "error": "Empty text input"}` if empty or whitespace string passed. | `app/bridge.py:304`, `ui/web/app.js:238` |
| 10 | IPC API | `get_settings` | Returns current application configuration state to UI frontend. | None | `dict` containing configuration parameters | Returns fallback settings dictionary if application instance is uninitialized. | `app/bridge.py:371`, `ui/web/app.js:57` |
| 11 | IPC API | `update_keywords` | Updates custom domain dictionary keywords list for STT and translation context. | `keywords: list[str]` | `{"status": "ok", "keywords": list[str]}` | Returns `{"status": "error", "error": "Keywords must be a list of strings"}` for non-list input. | `app/bridge.py:388`, `ui/web/app.js:538` |
| 12 | IPC API | `list_audio_devices` | Queries host system audio devices via `sounddevice` for active inputs/outputs. | None | `{"inputs": [...], "outputs": [...]}` | Returns empty lists on sounddevice query error. | `app/bridge.py:399`, `ui/web/app.js:440` |
| 13 | Event Push | `onTranscription` | Pushes streaming partial or final transcription text to frontend UI. | `text: str`, `is_final: bool`, `speaker: str`, `lang: str` | JS `TalkSyncUI.onTranscription({...})` | Ignored silently if window or `TalkSyncUI` unavailable. | `app/bridge.py:426`, `ui/web/app.js:289` |
| 14 | Event Push | `onTranslation` | Pushes live partial translation or final translated segment to frontend UI. | `original: str`, `translated: str`, `is_final: bool`, `speaker: str`, `source_lang: str`, `target_lang: str` | JS `TalkSyncUI.onTranslation({...})` | Appends segment card on final; updates live box on partial. | `app/bridge.py:444`, `ui/web/app.js:316` |
| 15 | Event Push | `onStatus` | Updates UI status badge ("LISTENING", "PROCESSING", "SPEAKING", "STOPPED"). | `status: str`, `active: bool` | JS `TalkSyncUI.onStatus({...})` | Updates status text and badge CSS indicator. | `app/bridge.py:466`, `ui/web/app.js:358` |
| 16 | Event Push | `onLatency` | Pushes breakdown of STT, translation, TTS, and total latency values in ms. | `stt_ms: float`, `translation_ms: float`, `tts_ms: float`, `total_ms: float` | JS `TalkSyncUI.onLatency({...})` | Updates latency performance pill on top header. | `app/bridge.py:472`, `ui/web/app.js:371` |
| 17 | Event Push | `onAudioLevel` | Pushes live microphone RMS audio level and amplitude. | `level: float`, `rms: float`, `source: str` | JS `TalkSyncUI.onAudioLevel({...})` | Triggers HTML5 Canvas waveform animation. | `app/bridge.py:489`, `ui/web/app.js:384` |
| 18 | Event Push | `onVADState` | Pushes Silero VAD state ("SPEECH DETECTED" vs "SILENCE"). | `is_speech: bool` | JS `TalkSyncUI.onVADState({...})` | Toggles VAD status pill active class and text. | `app/bridge.py:499`, `ui/web/app.js:394` |
| 19 | UI Component | `WaveformVisualizer` | 60fps HTML5 Canvas waveform visualizer with quadratic Bezier curves and glowing gradient. | `level: float`, `rms: float` | Rendered canvas frame | Uses exponential smoothing and decay when silent. | `ui/web/waveform.js:7` |
| 20 | UI Component | Dual Panel Grid | Side-by-side transcript cards for Speaker 1 (Mic/User) and Speaker 2 (Loopback/Remote). | Transcription and Translation events | Rendered segment cards & streaming boxes | Hides Panel B when translation mode is set to 1-way. | `ui/web/index.html:77`, `ui/web/app.js:162` |
| 21 | UI Component | Settings Modal | Drawer for configuring VAD threshold, RMS gate, audio devices, loopback, virtual mic, and keywords. | User input | Dispatched `set_audio_settings` & `update_keywords` | Validates range inputs before saving. | `ui/web/index.html:161`, `ui/web/app.js:412` |
| 22 | UI Component | History Modal | Drawer for fetching and viewing historical translation sessions. | `fetch_history` results | Rendered historical cards | Displays empty state message if no history found. | `ui/web/index.html:217`, `ui/web/app.js:482` |

---

## Edge Cases

| # | Feature | Input | Observed Behavior |
|---|---------|-------|-------------------|
| 1 | `set_languages` | Empty string `""`, `None`, invalid language code `"XYZ"`, or non-string integer `123`. | Returns `{"status": "error", "error": "..."}` without crashing or updating state. |
| 2 | `set_translation_mode` | Unsupported mode `"3-way"`, `None`, or empty string `""`. | Returns `{"status": "error", "error": "Invalid translation mode: ..."}`. |
| 3 | `set_panel_tts` | Invalid panel identifier `"C"`, `None`, or integer `123`. | Returns `{"status": "error", "error": "Invalid panel: ..."}`. |
| 4 | `fetch_history` | Negative integer `-10`, zero `0`, or non-integer string `"abc"`. | Returns empty list `[]`. |
| 5 | `set_audio_settings` | Non-dictionary input (string `"not_a_dict"`, integer `12345`, or list `[1, 2, 3]`). | Returns `{"status": "error", "error": "Settings must be a dictionary"}`. |
| 6 | `submit_text_input` | Empty string `""` or whitespace string `"   \n\t  "`. | Returns `{"status": "error", "error": "Empty text input"}`. |
| 7 | `update_keywords` | Non-list input (string `"keyword1, keyword2"`). | Returns `{"status": "error", "error": "Keywords must be a list of strings"}`. |
| 8 | Rapid Session Toggle | 50 rapid `start_session` and `stop_session` API calls within 1 second. | Handled cleanly; pipeline states transition without unhandled exceptions or thread leaks. |
| 9 | Partial Segment Storm | Burst of 30 VAD partial segments enqueued within 50ms for a single speaker. | `TranslationQueuePruner` prunes obsolete partial segments; queue size remains <= 1 and processing completes in < 100ms. |
| 10 | `onAudioLevel` Flooding | Audio capture worker emitting RMS audio levels 33 to 50 times per second. | Causes pywebview IPC evaluation queue backing up on Windows WebUI thread, resulting in UI render loop lag and frame drops. |
| 11 | Early Callback Emission | Python backend emitting events before `ApiBridge._window` is set or before `window.TalkSyncUI` is initialized in JS. | Events are silently dropped because `_evaluate_js` checks `if self._window and hasattr(self._window, "evaluate_js")`. |
| 12 | Synchronous `_run_async` | Invoking async pipeline methods from `ApiBridge` when event loop is running. | `fut.result(timeout=15.0)` blocks the calling thread synchronously, freezing pywebview JS-to-Python IPC execution for up to 15s. |

---

## PyWebView JS-Python Bridge Architecture

```
+-------------------------------------------------------------------------------+
|                             Python Backend Environment                        |
|                                                                               |
|  +--------------------+     Pipeline Events      +------------------------+  |
|  |     Pipeline       | -----------------------> |       ApiBridge        |  |
|  |  (VAD/STT/Trans)   |                          |     (app/bridge.py)    |  |
|  +--------------------+                          +------------------------+  |
|            ^                                                 |                |
|            | Pipeline API calls                              | evaluate_js()  |
|            v                                                 v                |
|  +--------------------+                          +------------------------+  |
|  |    Application     |                          | WebviewWindowManager   |  |
|  | (app/application.py)                          | (ui/webview_window.py) |  |
|  +--------------------+                          +------------------------+  |
+--------------------------------------------------------------|----------------+
                                                               | IPC Channel
+--------------------------------------------------------------v----------------+
|                        PyWebView Frontend Environment                         |
|                                                                               |
|  window.pywebview.api.<method>()  -------------> Exposed API Methods          |
|                                                                               |
|  window.TalkSyncUI.<callback>()   <------------- Pushed Event Callbacks       |
|                                                                               |
|  +--------------------+   +-------------------+   +------------------------+  |
|  | Dual Panel Cards   |   | Canvas Waveform   |   | Settings/History Modal |  |
|  | (Panel A / B)      |   | (waveform.js)     |   | (index.html/app.js)    |  |
|  +--------------------+   +-------------------+   +------------------------+  |
+-------------------------------------------------------------------------------+
```

### Bridge Initialization & Window Binding
1. `Application` initializes settings and builds the core `Pipeline`.
2. `ApiBridge` is instantiated with a reference to `Application` (`api_bridge = ApiBridge(application=app)`).
3. `WebviewWindowManager` creates the pywebview window:
   `webview.create_window(title="TalkSync AI", url=html_url, js_api=api_bridge, ...)`
4. `WebviewWindowManager` binds the window back to `ApiBridge` via `api_bridge.set_window(window)`.
5. On `start_session()`, `ApiBridge` binds its internal callback handlers (`on_transcription`, `on_translation`, `on_status`, `on_latency`, `on_audio_level`, `on_vad_state`) directly to the `Pipeline` instance.

---

## Real-Time Event Propagation & Frontend Rendering

### Event Flow Sequence
1. **Audio Capture & RMS Metering (`onAudioLevel`)**:
   - `Pipeline._capture_worker` reads float32 PCM chunks from `sounddevice` stream.
   - Calculates Root Mean Square (RMS): `rms = float(np.sqrt(np.mean(chunk ** 2)))`.
   - Calls `self.on_audio_level(rms)`.
   - `ApiBridge.on_audio_level` formats payload `{"level": round(level, 4), "rms": round(rms, 4), "source": "mic"}`.
   - Calls `_evaluate_js("onAudioLevel", payload)` -> Executes `window.TalkSyncUI.onAudioLevel(data)`.
   - `app.js` invokes `window.WaveformVisualizer.draw(level, rms)`.
   - `waveform.js` computes target level `targetLevel = Math.min(1.0, level * 4.0 + (rms * 10.0))` and renders dynamic Bezier curve on HTML5 `<canvas id="waveformCanvas">`.

2. **VAD Speech State (`onVADState`)**:
   - `SileroVAD` processes audio chunks and produces confidence scores.
   - Speech tracker updates state (`is_speech = confidence >= threshold`).
   - `Pipeline._vad_worker` invokes `self.on_vad_state(is_speech)`.
   - `ApiBridge.emit_vad_state` pushes `{"is_speech": bool}` to frontend.
   - `app.js` updates `#vad-indicator` class (`vad-pill active` vs `inactive`) and `#vad-text` ("SPEECH DETECTED" vs "SILENCE").

3. **Status Indicator (`onStatus`)**:
   - State changes in pipeline trigger `on_status("Listening...", "listening")`, `on_status("Processing...", "processing")`, `on_status("Speaking...", "speaking")`.
   - `ApiBridge.on_status` formats payload `{"status": status, "active": active}`.
   - `app.js` updates header status badge (`#status-text` and `#status-badge`).

4. **Speech Transcription (`onTranscription`)**:
   - `FasterWhisperSTT` or `OpenAISTT` transcribes speech.
   - Emit partial (`is_final=False`) or final (`is_final=True`) `TranscriptionSegment`.
   - `ApiBridge.on_transcription` formats payload `{"text": text, "is_final": is_final, "speaker": speaker, "lang": lang}`.
   - `app.js` routes speaker (`"mic"`/`"VOICE"` -> Panel A, `"loopback"`/`"COMPUTER_AUDIO"` -> Panel B).
   - Partial: Displays streaming original text in `#streaming-text-a/b`.
   - Final: Clears streaming box.

5. **Speech Translation (`onTranslation`)**:
   - `BaseTranslator` (DeepL/NLLB/MBART) translates transcribed text.
   - `Pipeline._translate_and_route` invokes `self.on_translation(result)`.
   - `ApiBridge.on_translation` formats payload `{"original": orig, "translated": trans, "is_final": is_final, "speaker": speaker, ...}`.
   - `app.js` routes to Panel A or Panel B.
   - Partial: Updates streaming box with live translation (`orig → trans`).
   - Final: Clears streaming box and prepends a `.segment-card` to `#history-list-a` or `#history-list-b` with formatted timestamp, original text, and translated text.

---

## Root Cause Analysis: UI Bridge Failures & Render Loop Blocks

Through code inspection and test execution, we identified four primary root causes for UI bridge updates failing to reach the frontend or blocking the UI render loop:

### Root Cause 1: High-Frequency IPC Event Flooding (`onAudioLevel`)
- **Location**: `app/pipeline.py` (lines 342-348) and `app/bridge.py` (lines 489-497, 613-621).
- **Mechanism**: The audio capture worker reads audio chunks every 20-30ms (~33 to 50 chunks/sec). For *every* chunk, it invokes `self.on_audio_level(rms)`, which calls `ApiBridge.emit_audio_level()`, executing `window.evaluate_js()` in pywebview.
- **Impact**: On Windows WebView2 (Chromium engine), calling `evaluate_js()` 50 times per second creates a massive IPC message bottleneck on the WebUI main thread. The JavaScript message queue backs up, causing noticeable rendering stutter, dropped UI frames, and frozen transcript updates.
- **Proof**: `waveform.js` already runs an independent 60fps `requestAnimationFrame` loop with exponential decay (`this.targetLevel *= 0.88`). High-frequency IPC calls are redundant and flood the IPC pipe.

### Root Cause 2: Synchronous Thread-Blocking in `_run_async`
- **Location**: `app/bridge.py` (lines 623-640).
- **Mechanism**:
  ```python
  def _run_async(self, coro_or_func: Any) -> Any:
      loop = asyncio.get_running_loop()
      fut = asyncio.run_coroutine_threadsafe(coro_or_func, loop)
      return fut.result(timeout=15.0)  # <-- Synchronous blocking call!
  ```
- **Impact**: When frontend JavaScript calls `start_session()`, `stop_session()`, or `submit_text_input()`, pywebview executes the Python method on its IPC thread. `fut.result(timeout=15.0)` blocks that thread synchronously while waiting for async model initialization, translator warmup, or TTS synthesis. While blocked, pywebview cannot evaluate incoming `evaluate_js()` calls, causing all real-time events (`onTranscription`, `onStatus`, `onTranslation`) to freeze until `fut.result()` completes or times out!

### Root Cause 3: Unhandled Startup Race Conditions
- **Location**: `app/bridge.py` (lines 615-621) and `ui/web/app.js` (lines 24-34).
- **Mechanism**: If pipeline events fire before pywebview completes `create_window()` or before the browser DOM fires `pywebviewready`, `self._window` is `None` or `window.TalkSyncUI` is `undefined`.
- **Impact**: In `_evaluate_js()`:
  ```python
  if self._window and hasattr(self._window, "evaluate_js"):
      ...
  ```
  If `self._window` is not yet bound, event calls fail silently without logging or queuing. Early status updates ("Starting services...", "Warming translator...") are permanently lost.

### Root Cause 4: Partial Segment Storms & Queue Congestion
- **Location**: `app/pipeline.py` (lines 551-590) and `tests/boundary/test_partial_segment_storm.py`.
- **Mechanism**: Rapid speech or low VAD thresholds emit frequent partial segments every 300ms. If translation workers fall behind or if JS evaluation blocks, `translation_queue` fills up.
- **Fix in place**: TalkSync implements `_enqueue_translation_segment` with `TranslationQueuePruner`, which prunes obsolete partial segments for the same input source. However, if pruning fails or if queues fill, partial segments are dropped or delay final segment delivery.

---

## User-Facing Requirements & UI State Machine

### User-Facing Requirements Mapping

| ID | Requirement | Authoritative Source | Implementation / Verification Status |
|---|-------------|----------------------|---------------------------------------|
| R1.1 | Clean mic input stream capture | `ORIGINAL_REQUEST.md:15` | Handled by `SoundDeviceInput` (`audio/input.py`). |
| R1.2 | Continuous loopback stream capture | `ORIGINAL_REQUEST.md:15` | Handled by `SoundDeviceInput.stream_loopback()` via Windows WASAPI loopback. |
| R1.3 | VAD speech detection | `ORIGINAL_REQUEST.md:15` | Handled by `SileroVAD` (`services/vad/silero_vad.py`). |
| R1.4 | Dynamic audio level indicator | `ORIGINAL_REQUEST.md:27` | Handled by `onAudioLevel` -> `WaveformVisualizer` canvas. |
| R1.5 | UI status indicators | `ORIGINAL_REQUEST.md:28` | Handled by `onStatus` -> `#status-badge` ("Listening...", "Processing...", "Speaking..."). |
| R2.1 | Speech transcription execution | `ORIGINAL_REQUEST.md:18,31` | Handled by `FasterWhisperSTT` / `OpenAISTT` -> `onTranscription`. |
| R2.2 | Neural text translation | `ORIGINAL_REQUEST.md:18,32` | Handled by `TranslationFactory` -> `onTranslation`. |
| R2.3 | Loopback audio capture & translation | `ORIGINAL_REQUEST.md:33` | Handled by `_capture_worker("loopback")` -> Panel B. |
| R3.1 | Non-blocking pywebview UI bridge updates | `ORIGINAL_REQUEST.md:21` | Requires throttling `onAudioLevel` and non-blocking `_run_async` handling. |

### UI State Machine

```
              +-----------------------------------+
              |              STOPPED              |
              |  (Badge: Gray/Red "STOPPED")      |
              |  (Button: "▶ START SESSION")      |
              +-----------------------------------+
                                |
                   start_session() API Call
                                v
              +-----------------------------------+
              |              STARTING             |
              | (Badge: Yellow "Starting...")     |
              | (Warming VAD, STT, Translator)    |
              +-----------------------------------+
                                |
                  Pipeline Ready / Input Active
                                v
              +-----------------------------------+
              |             LISTENING             |
              | (Badge: Green "RUNNING/LISTENING")|
              | (VAD: "SILENCE", Waveform Active) |
              +-----------------------------------+
                 /                             \
     Speech Detected (VAD)              Text Submitted (Keyboard)
                /                               \
               v                                 v
   +-----------------------+         +-----------------------+
   |      PROCESSING       |         |      TRANSLATING      |
   | (VAD: "SPEECH DET")   |         | (Badge: "Translating")|
   | (Status: "Processing")|         | (Live orig -> trans)  |
   +-----------------------+         +-----------------------+
               |                                 |
         STT Completed                     Translation Done
               |                                 |
               +----------------+----------------+
                                |
                                v
              +-----------------------------------+
              |             SPEAKING              |
              | (Status: "Speaking...")           |
              | (TTS Playback + Mute Gate Active) |
              +-----------------------------------+
                                |
                        TTS Playback Done
                                |
                                v
                      (Back to LISTENING)
```

---

## Verification & Test Results

The test suite was executed against the repository boundary and integration test suites:

```bash
pytest tests/boundary/test_bridge_boundary.py tests/integration/test_webview_pipeline_bridge.py
# Result: 32 passed in 0.69s

pytest tests/boundary/test_partial_segment_storm.py
# Result: 2 passed in 0.11s

pytest tests/test_pipeline.py tests/test_audio_input.py
# Result: 51 passed in 1.81s
```

All 85 bridge, boundary, pipeline, and audio input tests pass cleanly.

