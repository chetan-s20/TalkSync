# Handoff Report — Code Review for Milestone 2 (Audio Capture & Whisper Auto Language Detection)

**Reviewer**: Reviewer 1 (teamwork_preview_reviewer_m2_1)  
**Target Milestone**: Milestone 2 — Audio Capture & Whisper Auto Language Detection  
**Verdict**: **REQUEST_CHANGES (FAIL)**

---

## 1. Observation

### Verified Source Files
- `services/audio/loopback.py`
- `services/audio/input.py`
- `services/stt/faster_whisper.py`
- `app/interfaces.py`
- `core/interfaces.py`
- `tests/test_milestone2.py`

### Test Execution Command & Output
Command executed: `pytest tests/test_milestone2.py -v`
Exit status: **Exit Code 1 (FAILED)**

**Summary of test results**:
```
tests/test_milestone2.py::TestMilestone2AudioLoopback::test_find_wasapi_loopback PASSED
tests/test_milestone2.py::TestMilestone2AudioLoopback::test_find_loopback_device_wasapi_fallback PASSED
tests/test_milestone2.py::TestMilestone2AudioLoopback::test_find_loopback_device_not_found PASSED
tests/test_milestone2.py::TestMilestone2AudioLoopback::test_input_queue_overflow_logging FAILED
tests/test_milestone2.py::TestMilestone2WhisperAutoLang::test_auto_lang_normalization_and_prob_extraction PASSED
tests/test_milestone2.py::TestMilestone2PipelineRouting::test_stt_worker_attaches_input_source_and_prob FAILED
tests/test_milestone2.py::TestMilestone2PipelineRouting::test_translate_and_route_auto_language_resolution PASSED
tests/test_milestone2.py::TestMilestone2PipelineRouting::test_translate_and_route_loopback_default_direction PASSED
tests/test_milestone2.py::TestMilestone2TranscriptPanelWidget::test_transcript_panel_badges_and_streaming PASSED
```

### Direct Code Observations & Errors

#### Finding 1: Queue Overflow Warning Logging Flaw (CRITICAL)
- **Location**: `services/audio/input.py`, lines 52-56:
```python
loop = self._loop
if loop is not None and loop.is_running() and not loop.is_closed():
    try:
        loop.call_soon_threadsafe(q.put_nowait, chunk)
    except (RuntimeError, asyncio.QueueFull) as e:
        logger.warning(f"Audio input queue overflow for source '{source}': {e}")
```
- **Observed Behavior**: `loop.call_soon_threadsafe(q.put_nowait, chunk)` schedules `q.put_nowait` to execute on the main event loop thread asynchronously. The `call_soon_threadsafe` function call itself returns immediately without putting an item into `q` or throwing `asyncio.QueueFull`. When the main event loop executes `q.put_nowait(chunk)` later, if `q` is full, `QueueFull` is raised on the main loop thread inside asyncio's internal callback executor. Because it runs outside the `try... except` block in `_cb`, `logger.warning(...)` is **NEVER** called when a queue overflow occurs.
- **Verbatim Error Output**:
```
> assert any("overflow" in record.message.lower() for record in caplog.records)
E AssertionError: assert False
E  + where False = any(<generator object ...>)
```

#### Finding 2: Broken Milestone 2 Unit Test (CRITICAL)
- **Location**: `tests/test_milestone2.py`, line 124:
```python
job = SttJob(audio=np.zeros(16000, dtype=np.float32), is_final=True, source="loopback", audio_id="123")
```
- **Observed Behavior**: `SttJob` defined in `app/pipeline_state.py` (line 53) takes `(source: str, audio: bytes, sample_rate: int, is_final: bool, ...)` and does NOT accept an `audio_id` argument.
- **Verbatim Error Output**:
```
FAILED tests/test_milestone2.py::TestMilestone2PipelineRouting::test_stt_worker_attaches_input_source_and_prob - TypeError: SttJob.__init__() got an unexpected keyword argument 'audio_id'
```

#### Finding 3: WASAPI Loopback, Stereo Mix, and VB-Cable Fallback Resolution (PASS)
- **Location**: `services/audio/loopback.py`, lines 55-65.
- **Observed Behavior**: `find_loopback_device()` correctly checks for WASAPI Loopback, Stereo Mix, and VB-Cable in order and logs resolution:
```python
methods = [
    (find_wasapi_loopback(), "WASAPI Loopback"),
    (find_stereo_mix(), "Stereo Mix"),
    (find_vb_cable(), "VB-Cable"),
]
```

#### Finding 4: Whisper Auto-Language Normalization (PASS)
- **Location**: `services/stt/faster_whisper.py`, lines 88-89 & 138-140.
- **Observed Behavior**: Correctly normalizes `"auto"`, `"AUTO"`, `"automatic"` (case-insensitive) to `None`.

#### Finding 5: `language_probability` Extraction and Population (PASS)
- **Location**: `services/stt/faster_whisper.py` lines 174-181, `core/interfaces.py` line 32, `app/interfaces.py` line 27.
- **Observed Behavior**: `info.language_probability` is extracted and populated in `TranscriptionSegment.language_probability` and assigned as `confidence`.

---

## 2. Logic Chain

1. **Requirement Check: WASAPI loopback, Stereo Mix, and VB-Cable fallback resolution**
   - `services/audio/loopback.py` implements functions `find_wasapi_loopback()`, `find_stereo_mix()`, `find_vb_cable()`, and aggregates them in `find_loopback_device()`.
   - Priority sequence matches requirements: WASAPI Loopback -> Stereo Mix -> VB-Cable.
   - Tests `test_find_wasapi_loopback`, `test_find_loopback_device_wasapi_fallback`, and `test_find_loopback_device_not_found` in `tests/test_milestone2.py` PASS.

2. **Requirement Check: Queue overflow warning logging**
   - In `services/audio/input.py`, `_cb()` attempts to handle queue overflow by wrapping `loop.call_soon_threadsafe(q.put_nowait, chunk)` in a `try... except (RuntimeError, asyncio.QueueFull)`.
   - Reasoning: In `asyncio`, `call_soon_threadsafe` puts a callback onto the loop's queue and returns immediately. It does not invoke `q.put_nowait` synchronously inside `_cb`.
   - When `q.put_nowait` runs on the event loop, if full, `asyncio.QueueFull` is raised asynchronously in the loop's context, bypassing `_cb`'s `try-except` block.
   - Consequence: Queue overflow warning is never logged, and `test_input_queue_overflow_logging` fails. This is a logic defect in `services/audio/input.py`.

3. **Requirement Check: Whisper STT auto language normalization**
   - In `services/stt/faster_whisper.py`, `start()` and `transcribe()` inspect the string argument. If `lang.strip().lower() in ("auto", "automatic")`, `lang` is set to `None`.
   - WhisperModel receives `language=None`, triggering faster-whisper language identification.
   - Verified via `test_auto_lang_normalization_and_prob_extraction` (PASS).

4. **Requirement Check: `language_probability` extraction**
   - `services/stt/faster_whisper.py` extracts `lang_prob = float(getattr(info, "language_probability", 0.0) or 0.0)`.
   - `TranscriptionSegment` dataclass in both `core/interfaces.py` and `app/interfaces.py` includes `language_probability: float = 0.0`.
   - The field is correctly populated on segment creation.

5. **Requirement Check: `pytest` suite execution**
   - Running `pytest tests/test_milestone2.py` results in 2 failures (`test_input_queue_overflow_logging` and `test_stt_worker_attaches_input_source_and_prob`).
   - Per review protocol, a failing test suite invalidates submission approval and requires a verdict of `REQUEST_CHANGES`.

---

## 3. Caveats

- Physical audio hardware (WASAPI loopback endpoint, VB-Cable driver) was mocked during automated pytest execution.
- No other unexamined areas; all 5 scope items were fully checked against codebase and unit tests.

---

## 4. Conclusion

**Verdict**: **REQUEST_CHANGES (FAIL)**

**Required Action Items for Implementer**:
1. **Fix `services/audio/input.py` Queue Overflow Logging**:
   - Instead of relying on `try... except` around `loop.call_soon_threadsafe`, check if the queue is full before scheduling, or wrap the callback passed to `call_soon_threadsafe`:
   ```python
   if q.full():
       logger.warning(f"Audio input queue overflow for source '{source}'")
   else:
       try:
           loop.call_soon_threadsafe(q.put_nowait, chunk)
       except Exception as e:
           logger.warning(f"Audio input queue put error for source '{source}': {e}")
   ```
2. **Fix `tests/test_milestone2.py` Test Signature Mismatch**:
   - Update line 124 of `tests/test_milestone2.py` to match `SttJob`'s constructor:
   ```python
   job = SttJob(source="loopback", audio=b"\x00" * 32000, sample_rate=16000, is_final=True)
   ```

---

## 5. Verification Method

To independently verify:
1. Run `pytest tests/test_milestone2.py -v` from `d:/talksync/talksync`.
2. Inspect log output when `test_input_queue_overflow_logging` runs.
3. Confirm all 9 test cases in `tests/test_milestone2.py` PASS after fixes.
