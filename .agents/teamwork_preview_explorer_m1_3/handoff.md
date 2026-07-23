# Handoff Report: Explorer 3 - STT, Translation, TTS Services & Test Suite Baseline (R1, R2, R5 Foundation)

**Agent**: Explorer 3  
**Milestone**: Milestone 1  
**Working Directory**: `d:/talksync/talksync/.agents/teamwork_preview_explorer_m1_3`  
**Date**: 2026-07-23  

---

## 1. Observation

### Observation 1.1: STT Auto Language Detection & Execution (`services/stt/faster_whisper.py`)
- **Location**: `services/stt/faster_whisper.py`, lines 87–90 & 136–147:
  ```python
  87: async def start(self, language: Optional[str] = None) -> None:
  ...
  90:     self._language = language
  ...
  136: lang = language if language is not None else self._language
  138: segments_gen, info = self._model.transcribe(
  ...
  141:     language=lang,
  ```
  When `language="auto"` is passed, `lang` remains `"auto"`. The underlying `faster_whisper.WhisperModel.transcribe` method expects `language=None` for auto-detection. Passing `"auto"` directly causes `faster_whisper` to raise `ValueError: Invalid language code 'auto'`.
  *(In contrast, root `stt/faster_whisper.py:31` handles this correctly via `lang = None if language == "auto" else language`.)*
- **Main-Thread Blocking Execution**:
  In `services/stt/faster_whisper.py`, lines 122–193:
  ```python
  122: def transcribe(self, audio: Any, ...):
  181:     segment = _get_result()  # Ran synchronously on calling thread!
  188:     if loop is not None and loop.is_running():
  189:         async def _async_res():
  190:             return segment
  191:         return _async_res()
  ```
  `_get_result()` executes CPU/GPU-heavy Whisper transcription synchronously on the asyncio event loop thread before returning an async coroutine, blocking the entire event loop.
  *(In contrast, root `stt/faster_whisper.py:102` correctly executes `run_in_executor(self._executor, _run)`.)*

### Observation 1.2: Missing STT Manager (`services/stt/manager.py`)
- **Query**: Search for `services/stt/manager.py` or any file named `manager.py`.
- **Result**: `services/stt/manager.py` does NOT exist in the repository. (The only manager file is `core/pipeline_manager.py`).

### Observation 1.3: TTS Sarvam AI Indic TTS Implementation (`services/tts/sarvam.py`)
- **Location**: `services/tts/sarvam.py`, lines 45 & 56–57:
  ```python
  45: headers={"Authorization": f"Bearer {self._api_key}"}
  ...
  56: sr = 24000
  57: audio = np.frombuffer(audio_bytes, dtype=np.float32)
  ```
  1. **Header Authentication**: Sarvam AI API endpoints expect `api-subscription-key: <API_KEY>` or `api-key: <API_KEY>`, not `Authorization: Bearer <API_KEY>`. Using `Authorization: Bearer` produces HTTP 401/403 errors.
  2. **Audio Byte Decoding**: Sarvam AI returns base64-encoded WAV (or 16-bit PCM integer) data. Calling `np.frombuffer(audio_bytes, dtype=np.float32)` directly assumes float32 binary format. If `len(audio_bytes)` is not a multiple of 4, numpy raises `ValueError: buffer size must be a multiple of element size`. Even if divisible by 4, parsing 16-bit integer PCM or WAV container bytes as `float32` produces corrupted noise.

### Observation 1.4: Missing SAPI5 Service File (`services/tts/sapi.py`)
- **Query**: Search for `services/tts/sapi.py` or any file matching `*sapi*.py`.
- **Result**: `services/tts/sapi.py` does NOT exist. SAPI5 fallback is implemented inline within `services/tts/router.py` lines 90–98 (`_sapi_speak`) using PowerShell `System.Speech.Synthesis.SpeechSynthesizer`.

### Observation 1.5: Multilingual TTS Router Audio Buffer Inspection (`services/tts/router.py`)
- **Location**: `services/tts/router.py`, lines 79–84:
  ```python
  79: res = await eng.synthesize(text, lang)
  80: arr = np.frombuffer(res.audio_data, dtype=np.float32)
  81: if len(arr) > 0 and not np.all(arr == 0):
  82:     return res
  ```
  If `res.audio_data` byte length is not divisible by 4, `np.frombuffer` raises `ValueError: buffer size must be a multiple of element size`, which is caught by `except Exception as e:` at line 83, marking the engine as failed and aborting valid fallback output.

### Observation 1.6: Package `__init__.py` Audit
- **Files inspected**:
  - `services/__init__.py`: Empty (0 bytes)
  - `services/stt/__init__.py`: Empty (0 bytes)
  - `services/tts/__init__.py`: Empty (0 bytes)
  - `services/translation/__init__.py`: Empty (0 bytes)
  - `app/__init__.py`: Empty (0 bytes)
  - `ui/__init__.py`: Empty (0 bytes)
  - `ui/dialogs/__init__.py`: Empty (0 bytes)
  - `ui/widgets/__init__.py`: Empty (0 bytes)
  - `stt/__init__.py`: Empty (0 bytes)
  - `tts/__init__.py`: Empty (0 bytes)
  - `translation/__init__.py`: Contains `from translation.translation_factory import TranslationFactory` and `create_translator()`, missing `__all__`.
- **Namespace Duplication**: Dual directory structures exist for STT, TTS, and Translation (`stt/`, `tts/`, `translation/` vs `services/stt/`, `services/tts/`, `services/translation/`). `app/pipeline.py` imports from `services.translation.*` while other modules import from `stt.*` or `tts.*`.

### Observation 1.7: Unit Test Baseline Execution (`pytest`)
- **Command executed**: `C:\Users\Chetan Sharma\AppData\Local\Programs\Python\Python311\python.exe -m pytest -v`
- **Result**:
  - Total Tests: **222**
  - Passed: **221**
  - Failed: **1**
  - Time: 68.03 seconds
- **Verbatim Failure Output**:
  ```
  FAILED tests/test_tts.py::TestTTSRouter::test_router_fallback_chain_on_failure
  
  AssertionError: assert b'\x00\x00\x0...0\x00\x00\x00' == b'sarvam'
  
  Captured log call:
  WARNING  tts_router:router.py:84 TTS 'piper' failed: Piper failed
  WARNING  tts_router:router.py:84 TTS 'sarvam' failed: buffer size must be a multiple of element size
  INFO     tts_router:router.py:86 Falling back to Windows SAPI5 TTS for text: Hello
  ```

---

## 2. Logic Chain

1. **Auto-Language Detection Bug in STT**:
   - *From Observation 1.1*: `services/stt/faster_whisper.py:141` passes `language="auto"` directly to `self._model.transcribe()`.
   - `faster_whisper` raises an invalid language code error when `"auto"` string is supplied instead of `None`.
   - *Inference*: `language = None if lang == "auto" else lang` must be applied before calling `self._model.transcribe()`.

2. **Event Loop Freeze in STT**:
   - *From Observation 1.1*: `services/stt/faster_whisper.py:181` invokes `_get_result()` synchronously on the main thread before returning a coroutine wrapper.
   - *Inference*: Heavy model execution blocks the event loop. It must be offloaded to `self._executor` using `await loop.run_in_executor()`, as is done in `stt/faster_whisper.py`.

3. **Sarvam AI API & Audio Decoding Bugs**:
   - *From Observation 1.3*: `services/tts/sarvam.py:45` uses `Authorization: Bearer`, causing HTTP 401/403 against Sarvam AI endpoints.
   - *From Observation 1.3 & 1.7*: `services/tts/sarvam.py:57` and `services/tts/router.py:80` call `np.frombuffer` directly on base64-decoded WAV data or byte buffers without verifying length alignment or WAV format headers.
   - When a mock or real audio byte buffer length is not a multiple of 4 bytes (e.g., `b"sarvam"` = 6 bytes), numpy raises `ValueError: buffer size must be a multiple of element size`.
   - *Inference*: `router.py` catches this `ValueError` as an engine failure, discarding Sarvam output and falling back to SAPI5 silence. This directly causes the test failure in `TestTTSRouter.test_router_fallback_chain_on_failure`.

4. **Missing Modules**:
   - *From Observations 1.2 & 1.4*: `services/stt/manager.py` and `services/tts/sapi.py` are absent from the filesystem. SAPI5 is currently an inline function inside `services/tts/router.py`.

5. **Export & Architecture Cleanliness**:
   - *From Observation 1.6*: All core `__init__.py` files across `services/`, `ui/`, `app/`, `stt/`, `tts/` are empty (0 bytes).
   - Package structure is split between root packages (`stt/`, `tts/`, `translation/`) and nested service packages (`services/stt/`, `services/tts/`, `services/translation/`).
   - *Inference*: `__init__.py` files must define explicit `__all__` exports, and the codebase should standardize on `services/` as the single package namespace.

---

## 3. Caveats

- **Network Mode Restriction**: The agent operated in `CODE_ONLY` mode, so live Sarvam AI API endpoints could not be called over HTTP during this run. Findings are based on static analysis, contract specifications, and unit test execution.
- **Python Environment**: `d:\talksync\.venv` lacked `pytest` and `pip`. The test suite was executed using the system's Python 3.11 environment (`C:\Users\Chetan Sharma\AppData\Local\Programs\Python\Python311\python.exe`), which has all required dependencies (`pytest`, `torch`, `numpy`, `faster_whisper`, `onnxruntime`, `anyio`).

---

## 4. Conclusion

1. **Test Suite Baseline**: **221 out of 222 tests pass**. The single test failure (`test_router_fallback_chain_on_failure`) is directly caused by `np.frombuffer` buffer-alignment errors on `audio_data` inside `services/tts/router.py:80`.
2. **STT Service Recommendations**:
   - In `services/stt/faster_whisper.py`, add `lang = None if lang == "auto" else lang` in `transcribe()`.
   - Refactor `services/stt/faster_whisper.py:transcribe()` to run model inference asynchronously using `await loop.run_in_executor(self._executor, _run)`.
3. **TTS Service Recommendations**:
   - In `services/tts/sarvam.py`, update header to `api-subscription-key` and decode WAV audio using `io.BytesIO` / `wave` / `soundfile` to produce normalized float32 arrays.
   - In `services/tts/router.py`, safely handle raw byte buffers in `_select_engine` / `synthesize` so `np.frombuffer` does not raise `ValueError` on unaligned bytes.
   - Optionally extract SAPI5 fallback from `services/tts/router.py` into a dedicated `services/tts/sapi.py` module.
4. **Export Consistency**: Populate `__init__.py` files across `services/stt/`, `services/tts/`, `services/translation/`, `app/`, `ui/` with clean `__all__` exports and resolve root vs nested `services/` package duplication.

---

## 5. Verification Method

To verify test execution and findings independently:

1. **Run full pytest suite**:
   ```powershell
   & "C:\Users\Chetan Sharma\AppData\Local\Programs\Python\Python311\python.exe" -m pytest -v
   ```
2. **Run TTS router unit tests specifically**:
   ```powershell
   & "C:\Users\Chetan Sharma\AppData\Local\Programs\Python\Python311\python.exe" -m pytest tests/test_tts.py -k "TestTTSRouter" -v
   ```
3. **Inspect target files**:
   - `services/stt/faster_whisper.py` (lines 87–90, 136–141, 180–193)
   - `services/tts/sarvam.py` (lines 45, 56–57)
   - `services/tts/router.py` (lines 79–88)
   - `services/__init__.py`, `services/stt/__init__.py`, `services/tts/__init__.py`, `services/translation/__init__.py`
