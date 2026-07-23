## 2026-07-23T10:23:15Z
<USER_REQUEST>
You are Worker 1 executing Milestone 1: App Stability & Branding Foundation (R5 & R6) for TalkSync AI.
Your working directory is `d:/talksync/talksync/.agents/teamwork_preview_worker_m1`.
Please create your working directory if needed.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your Tasks for Milestone 1:

1. **App Branding (R5)**:
   - Update window title and branding text across `main.py`, `app/application.py`, `ui/main_window.py` to **TalkSync AI**.

2. **Dead Code Cleanup (R6)**:
   - Delete the 5 unused widget files in `ui/widgets/`:
     - `ui/widgets/control_bar.py`
     - `ui/widgets/latency_badge.py`
     - `ui/widgets/sidebar.py`
     - `ui/widgets/status_indicator.py`
     - `ui/widgets/waveform.py`
   - Verify `__init__.py` in `ui/widgets/` exports only active widgets.

3. **UI Callbacks & Text Input Wiring**:
   - In `ui/main_window.py`:
     - Update `_on_status(self, message: str, category: str = "info")` to accept 2 arguments.
     - Update `_on_latency` to handle both float and dict latency payloads (`dict` with `"avg_ms"` or `float`).
     - Update `_send_text_input()` to schedule `pipeline.process_text_input()` using `asyncio.run_coroutine_threadsafe(..., self.pipeline.loop)`.

4. **Audio Services & Thread Lifecycle Safety (R1, R2, R5 foundation)**:
   - In `services/audio/input.py`:
     - Store event loop (`loop = asyncio.get_running_loop()`) at `start()` time, and use `loop.call_soon_threadsafe(q.put_nowait, chunk)` in the sounddevice callback.
     - Set `SoundDeviceInput._queue` maxsize to 100 to prevent unbounded memory growth.
     - Stop existing input/loopback streams in `start()` before opening new streams.
   - In `services/audio/output.py`:
     - Preserve global PortAudio device indices in `list_devices()`.
     - In `stop()`, enqueue sentinel `None` to `_play_queue`, drain queue, and ensure `_play_thread.join(timeout=2.0)` completes before closing `_speaker_stream`.
   - In `services/audio/loopback.py`:
     - Gracefully fallback if Stereo Mix or VB-Cable is unavailable; check `max_input_channels > 0` for input streams.
   - In `services/stt/faster_whisper.py`:
     - Offload synchronous Whisper `transcribe()` inference to `self._executor` via `loop.run_in_executor(self._executor, ...)` so it does not freeze the asyncio event loop.
   - In `ui/main_window.py` & `app/pipeline.py`:
     - Ensure session toggle (`_toggle_session()`) invokes `pipeline.stop()` via `asyncio.run_coroutine_threadsafe(self.pipeline.stop(), self.pipeline.loop).result()` or similar cleanly.
     - Register `self.protocol("WM_DELETE_WINDOW", self._on_close)` in `MainWindow` to stop pipeline and close window gracefully.

5. **Translation Factory Resiliency**:
   - Wrap Argos `update_package_index()` in `services/translation/argos.py` in try/except Exception block so it doesn't crash in offline environments.
   - In `services/translation/factory.py`, fallback to Dummy/Mock translator if Argos and DeepL are both unavailable.

6. **Verification & Tests**:
   - Run build/test verification (e.g. `pytest`) to verify all unit tests pass.
   - Verify `python -c "from ui.main_window import MainWindow; print('OK')"` succeeds.
   - Write a detailed `handoff.md` report in `d:/talksync/talksync/.agents/teamwork_preview_worker_m1/handoff.md` with file changes, test outputs, and verification results.
</USER_REQUEST>
