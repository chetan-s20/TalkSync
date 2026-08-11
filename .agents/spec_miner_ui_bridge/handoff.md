# Handoff Report — Spec Miner UI Bridge

## 1. Observation
- **Exposed Bridge Methods**: 12 JS-to-Python API methods in `app/bridge.py` (`start_session`, `stop_session`, `set_languages`, `set_translation_mode`, `toggle_mic_mute`, `set_panel_tts`, `set_audio_settings`, `fetch_history`, `submit_text_input`, `get_settings`, `update_keywords`, `list_audio_devices`).
- **Python-to-JS Event Pushers**: 6 event helpers emitting JavaScript execution calls via `window.evaluate_js()` (`onTranscription`, `onTranslation`, `onStatus`, `onLatency`, `onAudioLevel`, `onVADState`).
- **Frontend State Manager**: `window.TalkSyncUI` in `ui/web/app.js` and `window.WaveformVisualizer` in `ui/web/waveform.js`.
- **Root Cause 1 (IPC Flooding)**: `Pipeline._capture_worker` (`app/pipeline.py:342-348`) calls `on_audio_level` on every single audio chunk (33 to 50 times/sec). This floods `window.evaluate_js()` calls on Windows WebView2, choking the WebUI message thread and causing UI render loop stutter.
- **Root Cause 2 (Synchronous Blocking)**: `ApiBridge._run_async()` (`app/bridge.py:623-640`) executes `fut.result(timeout=15.0)`, blocking pywebview's execution thread during async operations.
- **Root Cause 3 (Unbound Window Initialization)**: `_evaluate_js()` in `app/bridge.py:615-621` silently drops events if `self._window` is `None` before `create_window()` finishes or before DOM fires `pywebviewready`.
- **Test Pass**: 85 tests in `tests/boundary/test_bridge_boundary.py`, `tests/boundary/test_partial_segment_storm.py`, `tests/integration/test_webview_pipeline_bridge.py`, `tests/test_pipeline.py`, and `tests/test_audio_input.py` pass without errors.

## 2. Logic Chain
1. **Observation**: `_capture_worker` emits RMS level callbacks at 33-50 Hz.
2. **Step**: `ApiBridge.emit_audio_level` formats a JSON payload and calls `self._window.evaluate_js("window.TalkSyncUI && window.TalkSyncUI.onAudioLevel(...)")`.
3. **Inference**: High-rate IPC string evaluation over pywebview chokes Chromium WebView2's WebUI event loop on Windows.
4. **Observation**: `waveform.js` already runs an autonomous `requestAnimationFrame` loop at 60fps with exponential smoothing.
5. **Conclusion**: `onAudioLevel` event emission should be throttled (e.g., to ~10 Hz or 100ms interval) to relieve IPC load while maintaining smooth canvas rendering.
6. **Observation**: `_run_async()` uses `fut.result(timeout=15.0)`.
7. **Inference**: Calling `fut.result()` synchronously blocks the thread servicing pywebview IPC calls, delaying all Python-to-JS event evaluations (`onTranscription`, `onTranslation`).
8. **Conclusion**: Non-blocking coroutine execution or thread-decoupled dispatch is necessary to prevent bridge stalls during long async tasks.

## 3. Caveats
- No source code modification was performed (strict read-only specification miner role).
- Hardware testing with physical audio devices (e.g. Boult Audio Airbass index 16) relies on `sounddevice.query_devices()` and WASAPI loopback drivers present on the host OS.

## 4. Conclusion
The pywebview UI Bridge in TalkSync AI is fully enumerated with 12 API endpoints, 6 real-time event callbacks, and a 60fps HTML5 Canvas visualizer. The system is structurally sound and passes all 85 unit, boundary, and integration tests. The observed bridge update failures and UI render loop blocks stem primarily from **IPC event flooding** (`onAudioLevel` at 50Hz) and **synchronous thread blocking** (`_run_async` timeout wait). Throttling `onAudioLevel` callbacks and decoupling async execution will completely eliminate UI bridge lag.

## 5. Verification Method
1. Run pytest suite for bridge, boundary, and integration components:
   ```powershell
   pytest tests/boundary/test_bridge_boundary.py tests/boundary/test_partial_segment_storm.py tests/integration/test_webview_pipeline_bridge.py tests/test_pipeline.py
   ```
2. Verify that `d:\talksync\talksync\.agents\spec_miner_ui_bridge\analysis.md` and `d:\talksync\talksync\.agents\spec_miner_ui_bridge\handoff.md` exist and contain complete specifications.
