# Code Review & Handoff Report: Milestone 2 Pipeline Routing & Dual Panel Display

**Reviewer**: Reviewer 2 (Instance 2)
**Date**: 2026-07-23
**Target Files Reviewed**:
- `talksync/app/pipeline.py`
- `talksync/ui/main_window.py`
- `talksync/ui/widgets/transcript_panel.py`

---

## Verdict: REQUEST_CHANGES (FAIL)

### Verdict Rationale
While 5 out of 6 core feature requirements passed code inspection and 229 out of 231 unit/integration tests passed, **pytest execution failed for 2 tests**:
1. `talksync/tests/test_milestone2.py::test_dynamic_auto_target`
2. `talksync/tests/test_milestone2.py::test_dynamic_auto_target_french`

The failure occurs because `_translate_and_route()` in `talksync/app/pipeline.py` only resolves dynamic `"AUTO"` language codes when `src.upper() == "AUTO"`, but fails to resolve `tgt` when `target_lang` (or `tgt`) is set to `"AUTO"`.

---

## 1. Observation

### Test Results
- **Command executed**: `pytest` in `d:/talksync`
- **Result**: `229 passed, 2 failed in 23.36s`
- **Failing Tests**:
  - `talksync/tests/test_milestone2.py:165`: `AssertionError: assert 'AUTO' == 'HI'` in `test_dynamic_auto_target`
  - `talksync/tests/test_milestone2.py:188`: `AssertionError: assert 'AUTO' == 'FR'` in `test_dynamic_auto_target_french`

### Detailed File Observations

1. **`talksync/app/pipeline.py`**:
   - **Line 277-285**: `input_src = "COMPUTER_AUDIO" if job.source == "loopback" else "VOICE"`; `result.input_source = input_src` is assigned **prior** to calling `self.on_transcription(result)`. (PASS)
   - **Line 306-310**: Partial STT updates instantiate `TranslationResult` with `input_source=input_src`. (PASS)
   - **Line 340-345**: Loopback audio (`"COMPUTER_AUDIO"` / `"LOOPBACK"`) flips language direction: `src = self._target_lang`, `tgt = self._source_lang`. User voice defaults to `src = self._source_lang`, `tgt = self._target_lang`. (PASS)
   - **Line 347-353**: Dynamic `"AUTO"` resolution logic:
     ```python
     if src.upper() == "AUTO":
         if detected:
             from utils.languages import get_language_code
             det_code = (get_language_code(detected) or detected).upper()
             src = det_code
         else:
             src = "EN"
     ```
     *Bug*: If `tgt.upper() == "AUTO"` (e.g. when `target_lang` is set to `"AUTO"`), `tgt` remains `"AUTO"` and is never resolved to the detected STT language code. (FAIL)

2. **`talksync/ui/main_window.py`**:
   - **Line 460-466 (`_on_transcription`)**: Inspects `segment.input_source`. If `src in ("LOOPBACK", "COMPUTER_AUDIO")`, routes streaming text to `self.panel_b`. Otherwise routes to `self.panel_a`. (PASS)
   - **Line 468-476 (`_on_translation`)**: Inspects `result.input_source`. If `src in ("LOOPBACK", "COMPUTER_AUDIO")`, appends message to `self.panel_b`. Otherwise appends message to `self.panel_a`. (PASS)

3. **`talksync/ui/widgets/transcript_panel.py`**:
   - **Line 134-142 (`_setup_tags`)**: Configures text tags for `timestamp`, `badge_mic` (orange), `badge_loopback` (purple), `badge_text` (blue), `streaming` (italic slate), `original`, and `translated`. (PASS)
   - **Line 150-165 (`update_streaming_text`)**: Handles in-place streaming text by deleting prior `"streaming"` tagged text before inserting updated `⚡ {display_text}\n`. (PASS)
   - **Line 166-196 (`append_message`)**: Clears streaming text, formats timestamp (`HH:MM:SS`), formats source badge (`[MIC]`, `[LOOPBACK]`, `[TEXT]`), and appends original/translated blocks. (PASS)

---

## 2. Logic Chain

1. Requirements state:
   - Verify dynamic `"AUTO"` language code resolution in `_translate_and_route()`.
   - Run `pytest` to confirm tests pass.
2. Code inspection of `talksync/app/pipeline.py` at line 347 reveals that dynamic resolution checks `if src.upper() == "AUTO":`, but does NOT perform equivalent resolution for `if tgt.upper() == "AUTO":`.
3. When tests in `test_milestone2.py` set `pipeline._target_lang = "AUTO"` with detected language `"Hindi"` or `"French"`, `src` is `"EN"` and `tgt` is `"AUTO"`. Since line 347 only checks `src`, `tgt` is passed directly to `translator.translate` as `"AUTO"`, causing assertions `assert mock_translator.last_tgt == "HI"` and `assert mock_translator.last_tgt == "FR"` to fail.
4. Pytest execution confirms the exact failures observed in step 3.
5. Per protocol, since tests fail due to a defect in the implementation, the review verdict must be `REQUEST_CHANGES` (FAIL).

---

## 3. Caveats

- All other requirements (input_source assignment ordering, partial STT input_source propagation, loopback default direction swapping, dual panel routing in main window, and transcript panel badge styling/in-place streaming) were verified and found fully compliant.
- No integrity violations (hardcoded test cheats or facade implementations) were found in the codebase.

---

## 4. Conclusion

- **Verdict**: **REQUEST_CHANGES (FAIL)**
- **Required Fix**: Update `_translate_and_route()` in `talksync/app/pipeline.py` to also resolve `tgt` when `tgt.upper() == "AUTO"` (or when `target_lang` is set to `"AUTO"`), resolving `detected` language to its language code.

---

## 5. Verification Method

To independently verify this finding:
1. Run `pytest talksync/tests/test_milestone2.py` from `d:/talksync`.
2. Observe 2 test failures in `test_dynamic_auto_target` and `test_dynamic_auto_target_french`.
3. Inspect `talksync/app/pipeline.py` lines 347-354 and verify the absence of `tgt.upper() == "AUTO"` resolution.
