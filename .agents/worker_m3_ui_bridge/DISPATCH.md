## 2026-08-07T16:10:38Z
You are Worker for Milestone 3: Dynamic UI Bridge Integration.
Working directory: d:\talksync\talksync\.agents\worker_m3_ui_bridge
Read d:\talksync\talksync\.agents\ORIGINAL_REQUEST.md, d:\talksync\talksync\PROJECT.md, and d:\talksync\talksync\.agents\explorer_m3_ui_bridge\handoff.md.

Task:
Implement the fixes for Milestone 3: Dynamic UI Bridge Integration as planned in explorer_m3_ui_bridge/handoff.md:

1. `app/bridge.py` (`ApiBridge.emit_audio_level`) & `app/pipeline.py` (`Pipeline._capture_worker`):
   - Implement dual-layer timestamp throttling checking `time.time() - self._last_audio_level_time >= 0.1` (100ms interval / 10 Hz max) so high-frequency PCM chunk evaluation (33-50Hz) does not flood pywebview's `window.evaluate_js()` IPC queue on Windows WebView2.

2. `app/bridge.py` (Non-blocking event callbacks & unbound window buffer):
   - Ensure `emit_transcription`, `emit_translation`, `emit_status` ("Listening...", "Processing...", "Speaking..."), `emit_latency`, and `emit_vad_state` dispatch Python-to-JS events dynamically without blocking pywebview's thread.
   - Implement `_pending_events` queue in `ApiBridge` to buffer critical events when `self._window` is `None` before `create_window()` or `set_window()` completes, and flush them automatically when `set_window()` is called.

3. Run test verification using pytest:
   - Run `pytest tests/boundary/test_bridge_boundary.py tests/boundary/test_partial_segment_storm.py tests/integration/test_webview_pipeline_bridge.py tests/test_webview.py tests/test_m3_adversarial.py`.
   - Run `pytest tests/unit/test_bridge_api.py tests/test_pipeline.py tests/test_audio_input.py`.
   - Run full pytest suite: `pytest`.
   - Report test execution output and results.

Write your changes summary and handoff report to d:\talksync\talksync\.agents\worker_m3_ui_bridge\handoff.md.
