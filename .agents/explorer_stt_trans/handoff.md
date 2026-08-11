# Handoff Report — Explorer 2 (stt_trans)

**Working Directory**: `d:\talksync\talksync\.agents\explorer_stt_trans`  
**Target Project Path**: `d:\talksync\talksync`  
**Date**: 2026-08-07  

---

## 1. Observation

### 1.1 Event Loop Destruction in PyWebView Bridge (`app/bridge.py`)
- **`app/bridge.py` (lines 117–118)**:
  ```python
  if hasattr(pipeline, "start") and callable(pipeline.start):
      self._run_async(pipeline.start(source, target, loopback=use_loopback, text_mode=text_mode))
  ```
- **`app/bridge.py` (lines 623–640)**:
  ```python
  def _run_async(self, coro_or_func: Any) -> Any:
      if not asyncio.iscoroutine(coro_or_func):
          return coro_or_func
      try:
          loop = asyncio.get_running_loop()
          fut = asyncio.run_coroutine_threadsafe(coro_or_func, loop)
          return fut.result(timeout=15.0)
      except RuntimeError:
          try:
              loop = asyncio.new_event_loop()
              res = loop.run_until_complete(coro_or_func)
              loop.close()  # <-- Event loop closed immediately after pipeline.start returns
              return res
          except Exception as err:
              logger.warning(f"Async execution error: {err}")
              return None
  ```
- **`app/pipeline.py` (lines 175–188)**:
  ```python
  tasks = [
      asyncio.create_task(self._vad_worker()),
      asyncio.create_task(self._stt_worker()),
      asyncio.create_task(self._translation_worker()),
      asyncio.create_task(self._tts_worker()),
      asyncio.create_task(self._stats_worker()),
  ]
  self._tasks = tasks
  logger.info(f"Pipeline workers launched")
  ```

### 1.2 DeepL Initialization Error Swallowing (`services/translation/deepl.py`)
- **`services/translation/deepl.py` (lines 60–62)**:
  ```python
  except Exception as e:
      logger.warning(f"DeepL init failed: {e}")
      self._client = None
  ```
- **`services/translation/factory.py` (lines 28–35)**:
  ```python
  for name, cls in engines:
      try:
          primary = cls(trans_settings)
          await primary.start()
          logger.info(f"Translation: {name} active as primary engine")
          return primary
      except Exception as e:
          logger.warning(f"Translation engine {name} unavailable: {e}")
  ```

### 1.3 OpenAI STT Startup Failure (`services/stt/openai_stt.py` & `.env`)
- **`.env` (lines 38 & 41)**:
  ```env
  openai_api_key=sk-proj-zqdMhwKly6zQV6oDet3...
  talksync_stt_engine=openai
  ```
- **`services/stt/openai_stt.py` (lines 88–91)**:
  ```python
  if not self._api_key:
      raise RuntimeError(
          "OpenAI API key not configured. Set OPENAI_API_KEY in your .env file."
      )
  ```

### 1.4 Speech Onset Clipping in SpeechTracker (`app/pipeline_state.py`)
- **`app/pipeline_state.py` (lines 21–32)**:
  ```python
  def update(self, is_speech: bool) -> bool:
      if is_speech:
          self._speech_frames += 1
          self._silence_frames = 0
          if not self._speech_active and self._speech_frames >= SPEECH_FRAMES_TO_ACTIVATE:
              self._speech_active = True
      else:
          ...
      return self._speech_active
  ```

---

## 2. Logic Chain

1. **PyWebView Bridge Invocation**: The PyWebView frontend calls `window.pywebview.api.start_session(...)`, which invokes `ApiBridge.start_session()` on a PyWebView thread.
2. **Event Loop Creation**: `ApiBridge.start_session()` calls `_run_async(pipeline.start(...))`. Because there is no active asyncio event loop on that thread, `_run_async()` catches `RuntimeError` and creates `loop = asyncio.new_event_loop()`.
3. **Pipeline Worker Creation**: `loop.run_until_complete(pipeline.start(...))` executes `Pipeline.start()`. `Pipeline.start()` initializes model references, creates asyncio queues (`audio_queue`, `stt_queue`, `translation_queue`, `tts_queue`), spawns 5 background tasks (`_vad_worker`, `_stt_worker`, `_translation_worker`, `_tts_worker`, `_stats_worker`) using `asyncio.create_task(...)` on `loop`, and returns `None`.
4. **Immediate Loop Destruction**: Upon `Pipeline.start()` returning, `loop.run_until_complete()` finishes immediately. `_run_async()` then executes `loop.close()`.
5. **Worker Task Termination**: `loop.close()` destroys the event loop. All background tasks (`_vad_worker`, `_stt_worker`, `_translation_worker`, `_tts_worker`, `_capture_worker`) created on that loop are killed instantly.
6. **Pipeline Breakdown**: When VAD or audio capture receives speech, chunks put into `audio_queue` or `stt_queue` are never processed because the event loop running the worker loops is closed. No transcription or translation events are ever generated or pushed to the UI.
7. **Secondary Translation Breakdown**: Even if the event loop were kept alive, `DeepLTranslator.start()` swallows initialization errors (e.g. bad API key or proxy failure) and returns without raising an exception. `TranslationFactory.create()` assumes DeepL initialized successfully, skipping fallback to `ArgosTranslator`. When `DeepLTranslator.translate()` runs, it sees `_client is None` and returns the untranslated original text.
8. **Secondary STT Breakdown**: If `stt_engine=openai` is enabled in `.env` with an invalid/expired key, `OpenAISTT.start()` raises during `Pipeline.start()`, aborting the pipeline start completely without falling back to local `FasterWhisperSTT`.

---

## 3. Caveats

- **Read-Only Scope**: This report is produced under read-only constraints. No source code modifications were made.
- **Environment Hardware Dependency**: Real-time microphone capture and speaker output tests require physical audio devices (e.g. Boult Audio Airbass index 16 or default system devices) active on the host machine.

---

## 4. Conclusion

The primary reason why transcription and translation are not triggered when VAD detects speech in TalkSync is that **`ApiBridge._run_async()` in `app/bridge.py` closes the asyncio event loop immediately after `Pipeline.start()` returns, killing all pipeline worker tasks (`_vad_worker`, `_stt_worker`, `_translation_worker`, `_tts_worker`, `_capture_worker`) on startup.**

Secondarily:
1. `DeepLTranslator.start()` swallows exceptions, bypassing fallback to `ArgosTranslator` in `TranslationFactory` and returning untranslated passthrough text.
2. `OpenAISTT.start()` raises on API key failure during `Pipeline.start()`, aborting session start without falling back to `FasterWhisperSTT`.
3. `SpeechTracker` discards frame 1 of speech during onset activation, truncating initial consonants.

---

## 5. Verification Method

### 5.1 Command Line Verification
Run pytest on the test suite from `d:\talksync\talksync`:
```bash
python -m pytest tests/test_stt.py tests/test_translation.py tests/integration/test_full_pipeline.py tests/integration/test_webview_pipeline_bridge.py -v
```

### 5.2 Code Inspection Locations
1. **Event Loop Bug**: `app/bridge.py` lines 117–118 & 623–640.
2. **Worker Creation**: `app/pipeline.py` lines 175–186.
3. **DeepL Swallowed Exception**: `services/translation/deepl.py` lines 60–62 & `services/translation/factory.py` lines 28–35.
4. **OpenAI STT Failure**: `services/stt/openai_stt.py` lines 86–122 & `app/application.py` lines 70–84.
5. **Speech Onset Truncation**: `app/pipeline_state.py` lines 21–32 & `app/pipeline.py` lines 386–393.
