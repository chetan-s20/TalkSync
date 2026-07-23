# Deep Technical Analysis: Audio Capture, Output & Thread Lifecycle Stability

**Target Modules**: `services/audio/input.py`, `services/audio/output.py`, `services/audio/loopback.py`, `services/stt/faster_whisper.py`, `app/pipeline.py`, `ui/main_window.py`

---

## Executive Summary
This audit evaluated the stability, device resolution, resource management, thread safety, and event loop lifecycles of TalkSync AI's audio capture, output, and background pipeline tasks.

Nine critical architectural vulnerabilities were identified that directly impact system stability, audio device access, memory consumption, and GUI responsiveness. Detailed evidence chains, line-by-line analyses, and precise remediation patches are documented below.

---

## Detailed Audit Findings & Evidence Chains

### Finding 1: Invalid Event Loop Lookup in Sounddevice Callback Thread (Silent Audio Drop)
- **Location**: `services/audio/input.py:50-57`
- **Severity**: High
- **Observation**:
  ```python
  loop = asyncio.get_event_loop()
  if loop is not None and not loop.is_closed():
      try:
          loop.call_soon_threadsafe(q.put_nowait, chunk)
      except RuntimeError:
          pass
  ```
- **Logic Chain**:
  1. `sd.InputStream` invokes `_cb` on PortAudio's dedicated internal OS thread.
  2. Calling `asyncio.get_event_loop()` inside a non-main thread in Python 3.10+ raises `RuntimeError("There is no current event loop in thread 'PyAudioCallbackThread'")`.
  3. The enclosing `try...except Exception: pass` silently catches the `RuntimeError`, causing all audio chunks to be silently discarded without reaching `self._queue`.
- **Recommended Code Modification**:
  Bind `loop` at `SoundDeviceInput.start()` time or pass `loop` as an argument to `_make_callback`:
  ```python
  def _make_callback(self, native_sr: int, source: str, loop: asyncio.AbstractEventLoop):
      target_sr = self.settings.sample_rate
      q = self._loopback_queue if source == "loopback" else self._queue

      def _cb(indata, frames, time_info, status):
          if status:
              logger.debug(f"Audio {source} status: {status}")
          if not self._running:
              return
          try:
              ...
              if loop is not None and not loop.is_closed():
                  loop.call_soon_threadsafe(q.put_nowait, chunk)
          except Exception as e:
              logger.error(f"Callback error: {e}")
      return _cb
  ```

---

### Finding 2: Missing Native WASAPI Loopback & VB-Cable Output Channel Crash
- **Location**: `services/audio/input.py:78-97`, `services/audio/loopback.py:21-28,31-39`
- **Severity**: High
- **Observation**:
  `_start_loopback()` only attempts `find_stereo_mix()` and `find_vb_cable()`.
- **Logic Chain**:
  1. On modern Windows 10/11, "Stereo Mix" is disabled by default in sound settings.
  2. If VB-Cable is also not installed, `_start_loopback()` raises `RuntimeError("No loopback device found (Stereo Mix or VB-Cable)")`. PortAudio/WASAPI natively supports loopback capture on output devices on Windows without third-party drivers.
  3. `find_vb_cable()` in `loopback.py:25` checks `has_channels = max_input_channels > 0 or max_output_channels > 0`. If it selects a VB-Cable playback endpoint (where `max_input_channels == 0`), passing it to `sd.InputStream` (input.py:89) crashes with `PortAudioError: Invalid input device`.
- **Recommended Code Modification**:
  Require `max_input_channels > 0` in `find_vb_cable()`, and add native WASAPI loopback device discovery:
  ```python
  def find_vb_cable() -> Optional[int]:
      devices = sd.query_devices()
      for i, d in enumerate(devices):
          name = (d.get("name", "") or "").lower()
          if d.get("max_input_channels", 0) > 0 and ("cable" in name or "vb-audio" in name):
              return i
      return None
  ```

---

### Finding 3: Stream Resource Leaks on Re-initialization or Partial Failure
- **Location**: `services/audio/input.py:60-76,98-100`, `services/audio/output.py:35-54`
- **Severity**: Medium
- **Observation**:
  `SoundDeviceInput.start()` overwrites `self._mic_stream` and `self._loopback_stream` without calling `stop()` on pre-existing streams.
- **Logic Chain**:
  1. Calling `start()` repeatedly without calling `stop()` orphans prior `sd.InputStream` / `sd.OutputStream` handles in memory.
  2. If `_start_loopback()` succeeds on line 95, but `_start_mic()` fails on line 99, `self._loopback_stream` is left active and running while `self._running` is set to `False` and an exception is raised.
- **Recommended Code Modification**:
  In `SoundDeviceInput.start()`, always call `await self.stop()` before starting new streams, and wrap creation in `try...finally`:
  ```python
  async def start(self, device_id: Optional[int] = None, loopback: bool = False, capture_mic: bool = True) -> None:
      await self.stop()
      self._queue = asyncio.Queue(maxsize=256)
      self._loopback_queue = asyncio.Queue(maxsize=256) if loopback else None
      self._running = True
      ...
  ```

---

### Finding 4: Incorrect Device Index Mapping in `list_devices()`
- **Location**: `services/audio/output.py:145-162`, `services/audio/input.py:180-191`
- **Severity**: High
- **Observation**:
  `list_devices()` calls `sd.query_devices(kind="output")` and returns device ID as `i` from `enumerate(devices)`.
- **Logic Chain**:
  1. `sd.query_devices(kind="output")` returns a filtered list of only output devices.
  2. `enumerate()` assigns 0, 1, 2... based on position within the filtered sub-list.
  3. `sd.OutputStream(device=dev_id)` expects `dev_id` to be the global PortAudio index from `sd.query_devices()`.
  4. Selecting output device #1 from UI passes `device_id=1` to PortAudio, which opens global device #1 (which might be an input mic or invalid device), causing silent audio failures or device opening crashes.
- **Recommended Code Modification**:
  Query all devices and preserve original indices:
  ```python
  async def list_devices(self) -> list[dict]:
      all_devs = sd.query_devices()
      result = []
      for i, device in enumerate(all_devs):
          if isinstance(device, dict) and device.get("max_output_channels", 0) > 0:
              result.append({
                  "id": i,
                  "name": device.get("name", f"Device {i}"),
                  "channels": device.get("max_output_channels", 0),
                  "sample_rate": int(device.get("default_samplerate", 44100)),
              })
      return result
  ```

---

### Finding 5: Playback Thread Race Condition & C-Level Crash Risk on Shutdown
- **Location**: `services/audio/output.py:38-42,76-88,114-127`
- **Severity**: High
- **Observation**:
  `stop()` sets `self._running = False`, calls `self._play_thread.join(timeout=1.5)`, then calls `st.close()` on output streams.
- **Logic Chain**:
  1. `_playback_loop` executes `stream.write(out_audio)` on a background OS thread.
  2. PortAudio `stream.write()` blocks until audio buffer space is available.
  3. If `join(timeout=1.5)` times out while `_playback_loop` is inside `stream.write()`, `stop()` proceeds to call `st.stop()` and `st.close()`.
  4. Closing a PortAudio stream while another thread is executing `write()` triggers an Access Violation / Segmentation Fault C crash.
  5. Also, `stop()` does not enqueue `None` to `_play_queue`, so `_playback_loop` remains blocked in `_play_queue.get(timeout=0.1)`.
- **Recommended Code Modification**:
  In `SoundDeviceOutput.stop()`, clear `_play_queue` and enqueue `None` sentinel, then ensure thread termination before closing streams:
  ```python
  async def stop(self) -> None:
      self._running = False
      try:
          while not self._play_queue.empty():
              self._play_queue.get_nowait()
      except Exception:
          pass
      self._play_queue.put((None, 0))

      if self._play_thread is not None and self._play_thread.is_alive():
          self._play_thread.join(timeout=2.0)
      self._play_thread = None

      for st in (self._speaker_stream, self._virtual_stream):
          if st is not None:
              try:
                  st.stop()
                  st.close()
              except Exception:
                  pass
      self._speaker_stream = None
      self._virtual_stream = None
  ```

---

### Finding 6: Omission of `Pipeline.stop()` on Session Stop in `MainWindow`
- **Location**: `ui/main_window.py:312-321, 322-341`
- **Severity**: Critical
- **Observation**:
  When user stops session via Play/Stop toggle button, `_toggle_session()` sets `self.pipeline.running = False`. `_run_pipeline_thread()` exits its while loop. `self.pipeline.stop()` is NEVER called.
- **Logic Chain**:
  1. `Pipeline.stop()` is responsible for cancelling `_tasks` (`_vad_worker`, `_stt_worker`, `_translation_worker`, `_tts_worker`, `_capture_worker`) and shutting down audio input/output streams and VAD/STT/TTS services.
  2. Because `pipeline.stop()` is skipped on session stop, all 5 worker tasks remain running/hanging on the abandoned event loop.
  3. Audio input and output streams remain open, holding hardware resources.
  4. When user clicks Play again, a new event loop and new set of workers/streams are spawned alongside the zombie tasks, leading to memory leaks, device locking, and duplicate queue processing.
- **Recommended Code Modification**:
  In `_run_pipeline_thread()`, execute `loop.run_until_complete(self.pipeline.stop())` inside a `finally:` block:
  ```python
  def _run_pipeline_thread(self) -> None:
      loop = asyncio.new_event_loop()
      asyncio.set_event_loop(loop)
      self.pipeline._loop = loop

      async def _task():
          await self.pipeline.start(
              source_lang=self._source_lang,
              target_lang=self._target_lang,
              loopback=self._loopback_enabled,
              text_mode=self._text_mode,
          )
          while self.pipeline.running:
              await asyncio.sleep(0.1)

      try:
          loop.run_until_complete(_task())
      except Exception as e:
          logger.error(f"Pipeline loop error: {e}")
      finally:
          try:
              loop.run_until_complete(self.pipeline.stop())
          except Exception as e:
              logger.error(f"Error stopping pipeline in thread: {e}")
          loop.close()
  ```

---

### Finding 7: Missing Window Close (`WM_DELETE_WINDOW`) Handler
- **Location**: `ui/main_window.py:39-67`
- **Severity**: Medium
- **Observation**:
  `MainWindow` does not register a handler for window close events (`WM_DELETE_WINDOW`).
- **Logic Chain**:
  1. Closing `MainWindow` destroys Tkinter widgets while `_run_pipeline_thread`, `Pipeline` workers, and sounddevice streams are active.
  2. Python process hangs or exits uncleanly with unclosed device handles.
- **Recommended Code Modification**:
  Register protocol handler in `MainWindow.__init__`:
  ```python
  self.protocol("WM_DELETE_WINDOW", self._on_window_close)

  def _on_window_close(self) -> None:
      self.pipeline.running = False
      self.destroy()
  ```

---

### Finding 8: Unbounded Memory Growth in `SoundDeviceInput._queue`
- **Location**: `services/audio/input.py:61`, `app/pipeline.py:211-213`
- **Severity**: Medium
- **Observation**:
  `SoundDeviceInput._queue` is created with `asyncio.Queue()` (unbounded `maxsize=0`).
- **Logic Chain**:
  1. When downstream processing slows down, `Pipeline.audio_queue` (maxsize=256) fills up.
  2. `_capture_worker` blocks on `await self.audio_queue.put(chunk)`.
  3. Meanwhile, sounddevice `_cb` continues putting chunks into `SoundDeviceInput._queue` via `put_nowait()`.
  4. Since `SoundDeviceInput._queue` has no maximum size limit, audio chunks accumulate boundlessly in memory during long sessions.
- **Recommended Code Modification**:
  Initialize queues with `maxsize=256` and handle `asyncio.QueueFull` in `_make_callback`:
  ```python
  self._queue = asyncio.Queue(maxsize=256)
  ```
  In `_make_callback`:
  ```python
  try:
      q.put_nowait(chunk)
  except asyncio.QueueFull:
      try:
          q.get_nowait() # Drop oldest
          q.put_nowait(chunk)
      except Exception:
          pass
  ```

---

### Finding 9: Synchronous STT Transcription Blocking Async Event Loop
- **Location**: `services/stt/faster_whisper.py:122-181`, `app/pipeline.py:268`
- **Severity**: High
- **Observation**:
  `FasterWhisperSTT.transcribe()` runs `_get_result()` synchronously on the current thread, then returns a completed coroutine.
- **Logic Chain**:
  1. When `_stt_worker` in `Pipeline` calls `await self._stt.transcribe(...)`, Whisper STT inference runs directly on the asyncio event loop thread.
  2. Inference takes 100ms - 2000ms, during which the asyncio event loop is frozen.
  3. VAD processing, latency tracking, and UI callbacks stall.
  4. `FasterWhisperSTT` initializes `self._executor = ThreadPoolExecutor(max_workers=2)`, but never uses it.
- **Recommended Code Modification**:
  Offload `_get_result()` to `self._executor` in `FasterWhisperSTT.transcribe()`:
  ```python
  async def transcribe(
      self,
      audio: Any,
      sample_rate: Any = 16000,
      is_final: bool = True,
      language: Optional[str] = None,
      initial_prompt: Optional[str] = None,
      **kwargs,
  ) -> Optional[TranscriptionSegment]:
      loop = asyncio.get_running_loop()
      return await loop.run_in_executor(
          self._executor,
          lambda: self._sync_transcribe(audio, sample_rate, is_final, language, initial_prompt)
      )
  ```
