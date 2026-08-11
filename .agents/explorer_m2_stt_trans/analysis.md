# Milestone 2 Analysis Report: STT & Translation Execution Pipeline

**Working Directory**: `d:\talksync\talksync\.agents\explorer_m2_stt_trans`  
**Target Directory**: `d:\talksync\talksync`  
**Date**: 2026-08-07  
**Author**: Explorer Agent (Milestone 2)

---

## 1. Executive Summary

This analysis provides a comprehensive fix strategy for **Milestone 2: STT & Translation Execution Pipeline**.
The investigation targeted four primary functional areas where execution failures, queue stalls, and missing fallbacks prevent real-time audio transcription and translation from executing reliably:

1. **Event Loop Destruction (`app/bridge.py`)**: `ApiBridge._run_async()` destroys the temporary event loop immediately after `Pipeline.start()` returns, killing all background worker tasks (`_vad_worker`, `_stt_worker`, `_translation_worker`, `_tts_worker`, `_stats_worker`, `_capture_worker`).
2. **DeepL Fallback Bypass (`services/translation/deepl.py` & `services/translation/factory.py`)**: `DeepLTranslator.start()` swallows initialization errors (missing key, invalid key, or network failure) and returns `None` without raising. `TranslationFactory.create()` assumes success and returns a broken `DeepLTranslator` instance that outputs untranslated passthrough text.
3. **OpenAI STT Pipeline Crash (`services/stt/factory.py` & `services/stt/openai_stt.py`)**: `STTFactory` is missing from `services/stt/`. `OpenAISTT.start()` raises directly during `Pipeline.start()` on missing/invalid API keys without a factory-level fallback to local `FasterWhisperSTT`.
4. **Pipeline & Partial Segment Integrity**: Verification of `test_partial_translation.py`, `test_translation_queue_pruning.py`, `test_stt.py`, `test_openai_stt.py`, `test_translation.py`, and `test_full_pipeline.py`.

---

## 2. Detailed Technical Findings & Proposed Fix Strategy

### 2.1 Component 1: Persistent Asyncio Loop in `app/bridge.py`

#### Observation & Code Locations
- **`app/bridge.py` lines 117–118**:
  ```python
  if hasattr(pipeline, "start") and callable(pipeline.start):
      self._run_async(pipeline.start(source, target, loopback=use_loopback, text_mode=text_mode))
  ```
- **`app/bridge.py` lines 623–640**:
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
              loop.close()  # <-- WORKER KILLED HERE IMMEDIATELY
              return res
          except Exception as err:
              logger.warning(f"Async execution error: {err}")
              return None
  ```

#### Root Cause Analysis
1. JS-to-Python invocations from PyWebView execute on worker threads without a running asyncio event loop (`asyncio.get_running_loop()` raises `RuntimeError`).
2. `_run_async()` falls into `except RuntimeError:`, creates a temporary event loop (`asyncio.new_event_loop()`), and calls `loop.run_until_complete(pipeline.start(...))`.
3. `pipeline.start()` initializes queues and spawns 5–7 long-running background tasks (`asyncio.create_task(...)` for `_vad_worker`, `_stt_worker`, `_translation_worker`, etc.) on `loop`.
4. Once `pipeline.start()` finishes returning `None`, `run_until_complete` finishes. `_run_async()` immediately executes `loop.close()`.
5. `loop.close()` destroys the event loop and terminates all background worker tasks instantly. Consequently, audio chunks placed into `audio_queue` or `stt_queue` are never picked up.

#### Fix Strategy & Implementation Design
Replace temporary loop creation and immediate closure with a persistent background event loop managed by `ApiBridge`:

```python
import threading

class ApiBridge:
    def __init__(self, application: Any = None, window: Any = None):
        ...
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None

    def _get_or_create_loop(self) -> asyncio.AbstractEventLoop:
        """Get or initialize the persistent background event loop thread."""
        if self._loop is None or self._loop.is_closed() or not self._loop.is_running():
            def _start_loop(loop: asyncio.AbstractEventLoop):
                asyncio.set_event_loop(loop)
                loop.run_forever()

            self._loop = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(
                target=_start_loop,
                args=(self._loop,),
                daemon=True,
                name="ApiBridge-EventLoop"
            )
            self._loop_thread.start()
        return self._loop

    def _run_async(self, coro_or_func: Any, timeout: float = 15.0) -> Any:
        """Execute a coroutine safely on the persistent background loop."""
        if not asyncio.iscoroutine(coro_or_func):
            return coro_or_func

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        target_loop = self._get_or_create_loop()

        # Prevent deadlock if called from within the background event loop itself
        if current_loop is target_loop:
            return asyncio.create_task(coro_or_func)

        fut = asyncio.run_coroutine_threadsafe(coro_or_func, target_loop)
        try:
            return fut.result(timeout=timeout)
        except Exception as err:
            logger.warning(f"Async execution error: {err}")
            return None
```

---

### 2.2 Component 2: DeepL Initialization Exception & Fallback

#### Observation & Code Locations
- **`services/translation/deepl.py` lines 22–24 & 60–62**:
  ```python
  if not api_key:
      logger.warning("DeepL API key not configured")
      return  # <-- Returns cleanly without exception when key is missing

  except Exception as e:
      logger.warning(f"DeepL init failed: {e}")
      self._client = None  # <-- Swallows exception and returns cleanly when key/network invalid
  ```
- **`services/translation/factory.py` lines 28–35**:
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

#### Root Cause Analysis
Because `DeepLTranslator.start()` swallows all exceptions and missing key conditions, it returns `None` without raising an exception. `TranslationFactory.create()` believes DeepL initialized successfully and returns `DeepLTranslator` with `_client = None`. During translation calls, `DeepLTranslator.translate()` sees `self._client is None` and returns the untranslated text.

#### Fix Strategy & Implementation Design
Update `DeepLTranslator.start()` in `services/translation/deepl.py` to raise explicit exceptions on failure:

```python
    async def start(self) -> None:
        import deepl
        import asyncio

        api_key = getattr(self.settings, "deepl_api_key", "") or ""
        if not api_key:
            self._client = None
            raise RuntimeError("DeepL API key not configured")

        proxy_dict = get_proxy_dict()
        proxy_url = getattr(self.settings, "proxy_url", None) or proxy_dict.get("https://")
        use_proxy = False

        if proxy_url:
            try:
                import socket
                from urllib.parse import urlparse
                url_to_parse = proxy_url if "://" in proxy_url else f"http://{proxy_url}"
                parsed = urlparse(url_to_parse)
                host = parsed.hostname
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                if host:
                    with socket.create_connection((host, port), timeout=1.0):
                        use_proxy = True
            except Exception as check_err:
                logger.debug(f"DeepL proxy check failed ({check_err}) — falling back to direct connection")

        if use_proxy:
            try:
                self._client = deepl.Translator(api_key, proxy=proxy_url)
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._client.get_usage)
                logger.info("DeepL API initialized (via proxy)")
                return
            except Exception as proxy_e:
                logger.warning(f"DeepL proxy connection failed: {proxy_e}. Falling back to direct connection.")

        try:
            self._client = deepl.Translator(api_key)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._client.get_usage)
            logger.info("DeepL API initialized (direct connection)")
        except Exception as e:
            self._client = None
            logger.warning(f"DeepL init failed: {e}")
            raise RuntimeError(f"DeepL init failed: {e}") from e
```

---

### 2.3 Component 3: OpenAI STT Fallback & Factory Pattern

#### Observation & Code Locations
- **`services/stt/`**: `services/stt/factory.py` is currently missing.
- **`services/stt/openai_stt.py` lines 86–122**:
  ```python
  async def start(self, language: Optional[str] = None) -> None:
      if not self._api_key:
          raise RuntimeError("OpenAI API key not configured. Set OPENAI_API_KEY in your .env file.")
      ...
  ```
- **`app/application.py` lines 70–84**:
  `Application.build_pipeline()` contains inline fallback logic, but does not invoke `stt.start()`, delaying the failure until `Pipeline.start()` executes `await self._stt.start()`.

#### Root Cause Analysis
Without `STTFactory`, `OpenAISTT` initialization errors are only thrown when `Pipeline.start()` executes `await self._stt.start()`. This causes `Pipeline.start()` to crash without falling back to local `FasterWhisperSTT`.

#### Fix Strategy & Implementation Design
1. Create `services/stt/factory.py`:
   ```python
   from __future__ import annotations

   from typing import Any
   from app.interfaces import BaseSTT
   from services.stt.faster_whisper import FasterWhisperSTT
   from services.stt.openai_stt import OpenAISTT
   from utils.logger import get_logger

   logger = get_logger("stt_factory")


   class STTFactory:
       @staticmethod
       async def create(settings: Any) -> Any:
           openai_key = getattr(getattr(settings, "openai", None), "api_key", "") or ""
           engine_pref = getattr(settings, "stt_engine", "local").lower()

           engines = []
           if bool(openai_key) and engine_pref in ("openai", "auto"):
               engines.append(("OpenAI STT", OpenAISTT))
               engines.append(("FasterWhisper", FasterWhisperSTT))
           else:
               engines.append(("FasterWhisper", FasterWhisperSTT))
               engines.append(("OpenAI STT", OpenAISTT))

           for name, cls in engines:
               try:
                   stt_instance = cls(settings)
                   await stt_instance.start()
                   logger.info(f"STT: {name} active as primary engine")
                   return stt_instance
               except Exception as e:
                   logger.warning(f"STT engine {name} unavailable: {e}")

           # Final safeguard fallback
           try:
               fallback = FasterWhisperSTT(settings)
               await fallback.start()
               return fallback
           except Exception as e:
               logger.error(f"Failed to initialize any STT engine: {e}")
               raise RuntimeError("No STT engine available") from e
   ```

2. Update `OpenAISTT.start()` in `services/stt/openai_stt.py` to be idempotent:
   ```python
   async def start(self, language: Optional[str] = None) -> None:
       if self._loaded and self._client is not None:
           return
       ...
   ```

3. Update `app/application.py` `build_pipeline()`:
   ```python
   if not self._services.get("stt"):
       from services.stt.factory import STTFactory
       stt = asyncio.run(STTFactory.create(self.settings))
   ```

---

### 2.4 Component 4: Test Execution Verification Commands

To verify all Milestone 2 fixes across STT, translation, queue pruning, partial segments, and pipeline execution, the following test suite commands must be executed:

```bash
# 1. STT Unit & Interface Tests
python -m pytest tests/test_stt.py -v

# 2. OpenAI STT Live / Integration Test
python -m pytest tests/test_openai_stt.py -v

# 3. Translation Engine & DeepL Fallback Tests
python -m pytest tests/test_translation.py -v

# 4. Partial Segment Translation & Side-Effect Isolation Tests
python -m pytest tests/unit/test_partial_translation.py -v

# 5. Translation Queue Pruning & Multi-Source Isolation Tests
python -m pytest tests/unit/test_translation_queue_pruning.py -v

# 6. E2E Full Pipeline Integration Tests
python -m pytest tests/integration/test_full_pipeline.py -v

# Consolidated Milestone 2 Verification Command
python -m pytest tests/test_stt.py tests/test_openai_stt.py tests/test_translation.py tests/unit/test_partial_translation.py tests/unit/test_translation_queue_pruning.py tests/integration/test_full_pipeline.py -v
```

---

## 3. Implementation Plan for Implementer Agent

| Step | Target File | Action / Modification |
|------|-------------|-----------------------|
| 1 | `app/bridge.py` | Implement `_get_or_create_loop()` and update `_run_async()` to use persistent background daemon loop thread `ApiBridge-EventLoop` and avoid deadlock when called internally. |
| 2 | `services/translation/deepl.py` | Update `DeepLTranslator.start()` to raise `RuntimeError` when API key is missing or initialization/connection fails, rather than swallowing exceptions. |
| 3 | `services/translation/factory.py` | Verify `TranslationFactory.create()` catches `DeepLTranslator.start()` exceptions and falls back cleanly to `ArgosTranslator`. |
| 4 | `services/stt/factory.py` | Create `STTFactory` with `create(settings)` method implementing candidate loop (`OpenAISTT` -> `FasterWhisperSTT`). |
| 5 | `services/stt/openai_stt.py` | Make `OpenAISTT.start()` idempotent (`if self._loaded and self._client: return`) and raise `RuntimeError` on invalid key/init failure. |
| 6 | `app/application.py` | Integrate `STTFactory.create(self.settings)` in `Application.build_pipeline()`. |
| 7 | Tests | Run verification test commands to confirm 100% test pass rate. |

