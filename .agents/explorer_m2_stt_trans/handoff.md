# Handoff Report — Explorer for Milestone 2 (STT & Translation Execution Pipeline)

**Working Directory**: `d:\talksync\talksync\.agents\explorer_m2_stt_trans`  
**Target Project Path**: `d:\talksync\talksync`  
**Date**: 2026-08-07  

---

## 1. Observation

### 1.1 `app/bridge.py` Event Loop Destruction (Lines 623–640)
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
            loop.close()  # <-- Event loop closed immediately after pipeline.start() returns
            return res
        except Exception as err:
            logger.warning(f"Async execution error: {err}")
            return None
```
In `start_session()` (lines 117-118), calling `self._run_async(pipeline.start(...))` executes `pipeline.start()` on a temporary event loop. `Pipeline.start()` (lines 175-188) creates tasks `_vad_worker`, `_stt_worker`, `_translation_worker`, `_tts_worker`, `_stats_worker`, and `_capture_worker` on `loop`. As soon as `pipeline.start()` finishes, `loop.close()` destroys the loop, killing all worker tasks.

### 1.2 `services/translation/deepl.py` Swallowed Exception (Lines 22–24 & 60–62)
```python
if not api_key:
    logger.warning("DeepL API key not configured")
    return  # Swallows missing key condition

except Exception as e:
    logger.warning(f"DeepL init failed: {e}")
    self._client = None  # Swallows init/connection exception
```
`DeepLTranslator.start()` returns `None` without raising an exception when API keys are missing or connections fail. In `services/translation/factory.py` (lines 28–35), `TranslationFactory.create()` catches no exceptions and returns the broken `DeepLTranslator` with `_client = None`, causing `translate()` to return untranslated text.

### 1.3 Missing `services/stt/factory.py` & `services/stt/openai_stt.py` Exception Handling
- `services/stt/factory.py` is currently missing from the codebase.
- `OpenAISTT.start()` (lines 88–91 in `services/stt/openai_stt.py`) raises a `RuntimeError` on invalid/missing keys during `Pipeline.start()`. Without an `STTFactory` catching the error, `Pipeline.start()` crashes completely instead of falling back to local `FasterWhisperSTT`.

### 1.4 Test Suite File Locations
- `tests/test_stt.py`
- `tests/test_openai_stt.py`
- `tests/test_translation.py`
- `tests/unit/test_partial_translation.py`
- `tests/unit/test_translation_queue_pruning.py`
- `tests/integration/test_full_pipeline.py`

---

## 2. Logic Chain

1. **Observation 1.1 → Event Loop Destruction**: In `app/bridge.py`, PyWebView JS API calls run on separate non-asyncio threads. `ApiBridge.start_session()` invokes `_run_async(pipeline.start(...))`. Since no running loop exists on that thread, `_run_async()` creates a temporary event loop, runs `pipeline.start()`, and immediately calls `loop.close()`.
2. **Observation 1.1 → Worker Termination**: `Pipeline.start()` spawns 5–7 worker tasks using `asyncio.create_task(...)`. When `loop.close()` runs, all worker tasks are killed instantly. Any audio chunks queued into `audio_queue` or `stt_queue` are never processed.
3. **Logic Step → Persistent Background Loop Fix**: To prevent worker task death, `ApiBridge` must maintain a persistent background event loop thread (`_loop` and `_loop_thread`). `_run_async()` submits coroutines via `asyncio.run_coroutine_threadsafe(coro, self._loop)`.
4. **Observation 1.2 → DeepL Fallback Bypass**: In `services/translation/deepl.py`, `DeepLTranslator.start()` catches all errors and returns without raising. `TranslationFactory.create()` relies on `start()` raising an exception to trigger the `except Exception:` block and try `ArgosTranslator`. Because `DeepLTranslator.start()` doesn't raise, fallback is bypassed.
5. **Logic Step → DeepL Exception Fix**: `DeepLTranslator.start()` must raise `RuntimeError` when `api_key` is missing or when `deepl.Translator` / `get_usage` fails, allowing `TranslationFactory.create()` to fall back to `ArgosTranslator`.
6. **Observation 1.3 → OpenAI STT Fallback Defect**: `OpenAISTT.start()` raises on API key errors. Because `STTFactory` is missing and `OpenAISTT` is initialized/started directly in `Pipeline.start()`, initialization errors crash the pipeline instead of falling back.
7. **Logic Step → STTFactory Implementation**: Creating `services/stt/factory.py` with `STTFactory.create()` mirrors `TranslationFactory.create()`, attempting `OpenAISTT` first and falling back cleanly to `FasterWhisperSTT` upon exception.

---

## 3. Caveats

- **Read-Only Scope**: Analysis and plan formulated under strict read-only constraints; no source code files were edited directly.
- **Hardware API Key Testing**: Testing OpenAI STT or DeepL fallback without valid keys will trigger fallback paths as designed; full live API verification requires valid credentials in `.env`.

---

## 4. Conclusion

Milestone 2 issues stem from three primary defects:
1. `ApiBridge._run_async()` in `app/bridge.py` closing the temporary event loop immediately after `Pipeline.start()` finishes, killing worker tasks.
2. `DeepLTranslator.start()` swallowing exceptions, preventing `TranslationFactory.create()` from falling back to `ArgosTranslator`.
3. Absence of `STTFactory` in `services/stt/factory.py`, causing `OpenAISTT` startup errors to abort `Pipeline.start()` without falling back to `FasterWhisperSTT`.

Fixing these three areas with persistent background event loop management and factory-level exception propagation will restore full STT and translation execution flow.

---

## 5. Verification Method

### 5.1 Test Execution Verification Command
Execute the combined pytest command from `d:\talksync\talksync`:

```bash
python -m pytest tests/test_stt.py tests/test_openai_stt.py tests/test_translation.py tests/unit/test_partial_translation.py tests/unit/test_translation_queue_pruning.py tests/integration/test_full_pipeline.py -v
```

### 5.2 Files to Inspect for Verification
1. `app/bridge.py` lines 623–640 (`_run_async` persistent thread loop implementation).
2. `services/translation/deepl.py` lines 17–63 (Exception propagation in `start()`).
3. `services/translation/factory.py` lines 28–35 (Fallback loop to `ArgosTranslator`).
4. `services/stt/factory.py` (New file with `STTFactory.create()` fallback implementation).
5. `services/stt/openai_stt.py` lines 86–122 (`start()` idempotency & exception raising).
6. `app/application.py` lines 70–85 (`STTFactory.create()` integration).
