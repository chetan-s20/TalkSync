# Milestone 2 Remediation Execution Report

## 1. Observation
- **File 1**: `services/audio/input.py`
  - In method `_make_callback()` (lines 33-59), `_cb()` dispatches audio chunks to `self._loop` via `loop.call_soon_threadsafe(q.put_nowait, chunk)`.
  - When `q` was full, `q.full()` was not checked inside `_cb()` prior to threadsafe scheduling, causing warnings to only occur asynchronously if `call_soon_threadsafe` failed, failing tests expecting warning logs during full queue callback execution.
- **File 2**: `app/pipeline.py`
  - In `_translate_and_route()` (lines 347-363), resolution for `src.upper() == "AUTO"` was present, but `tgt.upper() == "AUTO"` was not explicitly handled.
  - Added resolution for `tgt.upper() == "AUTO"` to resolve `tgt` to the detected language (if distinct from `src`) or default to `"HI"`/`"EN"`.
- **File 3**: `tests/test_milestone2.py`
  - Line 48: `SoundDeviceInput` was initialized with `mock_settings` (`Settings` object) instead of `mock_settings.audio` (`AudioSettings` object).
  - Line 124: `SttJob` was instantiated with `audio=np.zeros(...)`, `audio_id="123"` (an unknown keyword arg for `SttJob`), and missing `sample_rate=16000`.
- **Test Output**:
  - Ran `python -m pytest` in `d:/talksync/talksync`.
  - Command output log:
    ```
    collected 231 items

    tests\integration\test_full_pipeline.py ..........                       [  4%]
    tests\test_audio_input.py ...............                                [ 10%]
    tests\test_history.py ...........................................        [ 29%]
    tests\test_milestone2.py ........                                        [ 32%]
    tests\test_pipeline.py ................................................ [ 53%]
    ............................                                             [ 65%]
    tests\test_pipeline_state.py ....................                        [ 74%]
    tests\test_stt.py ..............                                         [ 80%]
    tests\test_subtitles.py .........                                        [ 84%]
    tests\test_translation.py ................................               [ 97%]
    tests\test_tts.py ......                                                 [100%]

    ============================= 231 passed in 23.36s =============================
    ```

## 2. Logic Chain
1. **Audio Input Queue Overflow Logging**: In `services/audio/input.py`, `_cb()` runs on the sounddevice audio thread. By checking `if q.full(): logger.warning(f"Audio input queue overflow for source '{source}'")` prior to calling `loop.call_soon_threadsafe(q.put_nowait, chunk)`, the warning log is immediately recorded on callback execution when the queue reaches capacity, satisfying `test_input_queue_overflow_logging`.
2. **Dynamic AUTO Language Resolution**: In `app/pipeline.py`, `_translate_and_route()` needs both `source_lang` and `target_lang` to be resolved to concrete 2-letter language codes before calling translation. Checking `if tgt.upper() == "AUTO":` alongside `src.upper() == "AUTO"` ensures both dynamic source and target language specifications resolve cleanly to valid target language codes or fallback defaults ("EN" / "HI").
3. **Milestone 2 Test Initializations**:
   - `SoundDeviceInput` requires `AudioSettings`. `mock_settings.audio` provides the `AudioSettings` object, fixing instantiation in `test_input_queue_overflow_logging`.
   - `SttJob` dataclass signature is `SttJob(source: str, audio: bytes, sample_rate: int, is_final: bool)`. Updating `test_stt_worker_attaches_input_source_and_prob` to pass `SttJob(source="loopback", audio=np.zeros(16000, dtype=np.float32).tobytes(), sample_rate=16000, is_final=True)` matches the dataclass contract cleanly.
4. **Verification**: Executing `pytest` verifies that all 231 test cases across the entire test suite pass with 100% success rate (231/231 passed).

## 3. Caveats
- No caveats. All changes strictly adhere to minimal changes required by the task prompt and contract specifications.

## 4. Conclusion
- Milestone 2 Remediation is complete. All 3 code files (`services/audio/input.py`, `app/pipeline.py`, `tests/test_milestone2.py`) were modified as requested and verified with genuine implementations.
- Test suite pass rate is 231/231 (100%).

## 5. Verification Method
- Execute the following command from `d:/talksync/talksync`:
  ```bash
  python -m pytest
  ```
- Confirm output reports `231 passed`.
