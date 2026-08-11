# TalkSync AI — Milestone 3: Dynamic UI Bridge Integration Plan & Technical Analysis

## Executive Summary

This report provides the detailed technical analysis and implementation strategy for **Milestone 3: Dynamic UI Bridge Integration** in TalkSync AI.

The PyWebView JS-Python IPC Bridge acts as the real-time communication layer between the Python audio processing pipeline (`app/pipeline.py`) and the Web UI frontend (`ui/web/app.js`, `ui/web/waveform.js`). Our investigation identified three critical architectural bottlenecks and edge-case vulnerabilities in the current bridge implementation:

1. **IPC Event Flooding (`onAudioLevel`)**: `Pipeline._capture_worker` emits RMS audio levels on every audio chunk (33–50 Hz), causing Windows Chromium WebView2 IPC message queue congestion and UI render stuttering.
2. **Synchronous Thread Blocking (`_run_async`)**: `ApiBridge._run_async()` invokes `fut.result(timeout=15.0)`, synchronously blocking pywebview's execution thread during async operations and preventing dynamic UI event updates.
3. **Unbound Window Startup Race Condition**: Python-to-JS event callbacks drop early status and transcription events if emitted before `create_window()` or `set_window()` completes.

This document outlines precise, production-grade fix strategies to resolve all three issues, preserve full feature functionality, and ensure 100% test suite passing.

---

## 1. `onAudioLevel` IPC Throttling (`app/bridge.py` & `app/pipeline.py`)

### Problem Analysis
In `app/pipeline.py:342-348`, `_capture_worker` captures PCM audio chunks from `sounddevice` at 20–30ms intervals. For every captured microphone chunk:
```python
if self.on_audio_level and source == "mic":
    try:
        audio_array = np.frombuffer(chunk.data, dtype=np.float32)
        rms = float(np.sqrt(np.mean(audio_array ** 2)))
        self.on_audio_level(rms)
    except Exception:
        pass
```
This calls `ApiBridge.on_audio_level()` -> `ApiBridge.emit_audio_level()` -> `_evaluate_js("onAudioLevel", payload)` up to 50 times per second.

On Windows WebView2, evaluating JavaScript strings at 50 Hz causes IPC queue flooding. This chokes the Chromium WebUI rendering thread, leading to dropped UI frames and delayed transcript card updates.

Crucially, `ui/web/waveform.js` already runs an autonomous HTML5 Canvas animation loop via `requestAnimationFrame` at 60fps. It uses exponential decay (`targetLevel *= 0.88`) to smooth transitions. Updating `onAudioLevel` at **10 Hz (100ms interval)** is optimal for visual responsiveness while reducing IPC traffic by **80%**.

### Proposed Fix Strategy
Implement a dual-layer throttling mechanism:

1. **Bridge-Level Throttling (`app/bridge.py`)**:
   Add a timestamp tracker `self._last_audio_level_time: float = 0.0` in `ApiBridge.__init__`.
   In `ApiBridge.emit_audio_level()`:
   ```python
   def emit_audio_level(self, level: float, rms: float = 0.0, source: str = "mic", force: bool = False) -> dict:
       payload = {
           "level": round(level, 4),
           "rms": round(rms, 4),
           "source": source,
       }
       now = time.time()
       if force or (now - self._last_audio_level_time >= 0.10):  # 100ms interval (max 10 Hz)
           self._last_audio_level_time = now
           self._evaluate_js("onAudioLevel", payload)
       return payload
   ```

2. **Pipeline-Level Throttling (`app/pipeline.py`)**:
   In `Pipeline._capture_worker()`, add `self._last_audio_level_time: float = 0.0`.
   Only compute RMS and fire `self.on_audio_level(rms)` if `(time.time() - self._last_audio_level_time) >= 0.10`.

---

## 2. Non-blocking Dynamic UI Event Emission

### Problem Analysis
`ApiBridge._run_async` in `app/bridge.py:646-666` executes coroutines using:
```python
def _run_async(self, coro_or_func: Any) -> Any:
    ...
    fut = asyncio.run_coroutine_threadsafe(coro_or_func, loop)
    return fut.result(timeout=15.0)  # Blocks calling thread!
```
When frontend JS calls bridge API methods like `start_session()`, `stop_session()`, or `submit_text_input()`, pywebview executes the call on its IPC worker thread. `fut.result(timeout=15.0)` blocks this thread synchronously while waiting for pipeline setup, model loading, or TTS synthesis.

While the thread is blocked, incoming `evaluate_js()` calls from background workers (`onTranscription`, `onTranslation`, `onStatus`, `onVADState`, `onLatency`) cannot be evaluated by pywebview. This causes the UI to freeze and queue up event updates until `fut.result()` finishes.

### Proposed Fix Strategy
1. **Decouple Asynchronous API Dispatch**:
   Modify `_run_async` to offer non-blocking execution when called from synchronous pywebview IPC context, or schedule coroutines asynchronously via `asyncio.run_coroutine_threadsafe(coro, loop)` without blocking on `fut.result()`.
2. **Thread-Safe Non-Blocking Event Pushers**:
   Ensure `_evaluate_js()` dispatches JavaScript calls safely without waiting for DOM evaluation returns.

```python
def _run_async(self, coro_or_func: Any, block: bool = False) -> Any:
    if not asyncio.iscoroutine(coro_or_func):
        return coro_or_func

    try:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        loop = self._get_or_create_loop()

        if running_loop is not None and running_loop is loop:
            return asyncio.create_task(coro_or_func)

        fut = asyncio.run_coroutine_threadsafe(coro_or_func, loop)
        if block:
            return fut.result(timeout=15.0)
        return fut  # Return Future immediately without blocking IPC thread!
    except Exception as err:
        logger.warning(f"Async execution error: {err}")
        return None
```

This ensures `onTranscription`, `onTranslation`, `onStatus` ("Listening...", "Processing...", "Speaking..."), `onLatency`, and `onVADState` callbacks update pywebview dynamically without stalling the frontend UI rendering loop.

---

## 3. Unbound Window Protection & Event Queuing

### Problem Analysis
During application initialization or early session startup:
- `Pipeline` workers may start emitting events (`onStatus("Starting services...")`, `on_vad_state()`) before `WebviewWindowManager.create_window()` calls `api_bridge.set_window(window)`.
- If `self._window` is `None`, calling `self._window.evaluate_js()` raises an `AttributeError` or drops the event silently. Early status indicators and initialization updates are permanently lost.

### Proposed Fix Strategy
1. **Defensive Window Guard**:
   In `_evaluate_js()`:
   Check `if self._window is not None and hasattr(self._window, "evaluate_js"):`.

2. **Pending Event Queue for Critical Events**:
   Add `self._pending_events: list[tuple[str, dict]] = []` in `ApiBridge.__init__`.
   - When `_evaluate_js(callback_name, payload)` is called and `self._window` is `None`:
     - If `callback_name` is critical (`onStatus`, `onTranscription`, `onTranslation`), append `(callback_name, payload)` to `self._pending_events` (max 50 events).
     - Transient telemetry (`onAudioLevel`, `onVADState`) can be dropped safely.
   - In `set_window(window)`:
     - Assign `self._window = window`.
     - Drain and flush all `_pending_events` to `window.evaluate_js()`.

```python
def set_window(self, window: Any) -> None:
    """Bind window and flush any queued pending event callbacks."""
    self._window = window
    if self._window and self._pending_events:
        logger.info(f"Flushing {len(self._pending_events)} pending event callbacks to pywebview")
        for cb_name, payload in self._pending_events:
            self._evaluate_js(cb_name, payload)
        self._pending_events.clear()

def _evaluate_js(self, callback_name: str, payload: dict) -> None:
    if self._window and hasattr(self._window, "evaluate_js"):
        js_val = json.dumps(payload)
        js_str = f"window.TalkSyncUI && window.TalkSyncUI.{callback_name}({js_val})"
        try:
            self._window.evaluate_js(js_str)
        except Exception as err:
            logger.warning(f"Error evaluating JS callback '{callback_name}': {err}")
    else:
        # Queue critical state events when window is unbound
        if callback_name in ("onStatus", "onTranscription", "onTranslation"):
            if len(self._pending_events) < 50:
                self._pending_events.append((callback_name, payload))
```

---

## 4. Implementation Specification & Diff Patch Strategy

Below are the exact proposed changes to `app/bridge.py` and `app/pipeline.py`.

### Proposed Patch for `app/bridge.py`:
```python
# In ApiBridge.__init__:
self._last_audio_level_time: float = 0.0
self._pending_events: list[tuple[str, dict]] = []

# In set_window:
def set_window(self, window: Any) -> None:
    self._window = window
    if self._window and hasattr(self._window, "evaluate_js") and self._pending_events:
        for cb_name, payload in self._pending_events:
            self._evaluate_js(cb_name, payload)
        self._pending_events.clear()

# In emit_audio_level:
def emit_audio_level(self, level: float, rms: float = 0.0, source: str = "mic", force: bool = False) -> dict:
    payload = {
        "level": round(level, 4),
        "rms": round(rms, 4),
        "source": source,
    }
    now = time.time()
    if force or (now - self._last_audio_level_time >= 0.10):
        self._last_audio_level_time = now
        self._evaluate_js("onAudioLevel", payload)
    return payload

# In _evaluate_js:
def _evaluate_js(self, callback_name: str, payload: dict) -> None:
    if self._window and hasattr(self._window, "evaluate_js"):
        js_val = json.dumps(payload)
        js_str = f"window.TalkSyncUI && window.TalkSyncUI.{callback_name}({js_val})"
        try:
            self._window.evaluate_js(js_str)
        except Exception as err:
            logger.warning(f"Error evaluating JS callback '{callback_name}': {err}")
    else:
        if callback_name in ("onStatus", "onTranscription", "onTranslation"):
            if len(self._pending_events) < 50:
                self._pending_events.append((callback_name, payload))

# In _run_async:
def _run_async(self, coro_or_func: Any, block: bool = False) -> Any:
    if not asyncio.iscoroutine(coro_or_func):
        return coro_or_func
    try:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        loop = self._get_or_create_loop()

        if running_loop is not None and running_loop is loop:
            return asyncio.create_task(coro_or_func)

        fut = asyncio.run_coroutine_threadsafe(coro_or_func, loop)
        if block:
            return fut.result(timeout=15.0)
        return fut
    except Exception as err:
        logger.warning(f"Async execution error: {err}")
        return None
```

### Proposed Patch for `app/pipeline.py`:
```python
# In Pipeline.__init__:
self._last_audio_level_time: float = 0.0

# In Pipeline._capture_worker():
now = time.time()
if self.on_audio_level and source == "mic" and (now - self._last_audio_level_time >= 0.10):
    self._last_audio_level_time = now
    try:
        audio_array = np.frombuffer(chunk.data, dtype=np.float32)
        rms = float(np.sqrt(np.mean(audio_array ** 2)))
        self.on_audio_level(rms)
    except Exception:
        pass
```

---

## 5. Verification Commands & Execution Matrix

To verify the fixes independently after implementation, execute the following test suites:

### Primary Milestone 3 Verification Suite
```powershell
pytest tests/boundary/test_bridge_boundary.py tests/boundary/test_partial_segment_storm.py tests/integration/test_webview_pipeline_bridge.py tests/test_webview.py tests/test_m3_adversarial.py
```
*Expected Result*: 50 passed in < 1.0s.

### Full Pipeline & Unit Bridge Verification
```powershell
pytest tests/unit/test_bridge_api.py tests/test_pipeline.py tests/test_audio_input.py
```
*Expected Result*: 52 passed in < 2.0s.

### Complete System Regression Test
```powershell
pytest tests/
```
*Expected Result*: All collected tests pass with 0 failures.
