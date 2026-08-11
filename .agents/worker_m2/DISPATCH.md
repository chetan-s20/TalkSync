## 2026-08-06T06:58:15Z
<USER_REQUEST>
You are worker_m2, an implementation worker subagent.
Your working directory is `d:\talksync\talksync\.agents\worker_m2`. Create your directory and `progress.md` before starting.
Read `d:\talksync\talksync\.agents\ORIGINAL_REQUEST.md`, `d:\talksync\talksync\PROJECT.md`, and `d:\talksync\talksync\.agents\explorer_survey_2\handoff.md` for full context.

DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your Task (Milestone 2 — UI State Management, OpenAI STT Language Filtering & Standalone Script):
1. **Prevent Duplicate Window Spawning (AC-2)**:
   - Inspect `ui/main_window.py` and `ui/dialogs/`.
   - Update `SessionSummaryDialog` and all modal dialog launchers (e.g. `_show_summary_dialog()`, `_open_settings()`, `_open_about()`) to maintain single-instance tracking (`self._summary_dialog`, `self._settings_dialog`, etc.) and check `if self._dialog and self._dialog.winfo_exists(): self._dialog.focus(); return`.
2. **Play Button Loading State `⏳` (AC-3)**:
   - In `ui/main_window.py` (`_restart_pipeline()`, `_start_pipeline()`, `_stop_pipeline()`): Ensure `btn_play` state is set to disabled (`state="disabled"`) and text is set to `"⏳"` during pipeline initialization/re-initialization until initialization completes, then restored to `"▶"` / active state.
3. **OpenAI STT Allowed Language Filtering (AC-4)**:
   - In `services/stt/openai_stt.py`: Change `response_format` in OpenAI API calls from `"json"` to `"verbose_json"` so the API returns the detected `language` field in transcription results.
   - Update `OpenAISTT` and `app/pipeline.py`: Populate `segment.language` with the detected language string and verify `detected_lang` against `allowed_languages` set (e.g. {"en", "hi", "english", "hindi"}). If the detected language is not in allowed languages, drop the audio segment and log `Dropped audio segment in un-allowed language: {detected_lang}`.
4. **Dark Mode Theme Consistency & UI Fixes**:
   - Fix hardcoded light hex values (`#FFFFFF`, `#F3F4F6`) across dialogs in `ui/dialogs/` to use dynamic theme color tuples or dark-mode compatible hex codes.
   - Clean up un-commanded `btn_model` button in `LanguageSelectorDialog`.
5. **Standalone Verification Script (AC-5)**:
   - Create/update `scripts/verify_mic_and_routing.py` to programmatically test mic level audio capture and bidirectional audio routing, outputting explicit status logs.
6. **Verification & Execution**:
   - Run pytest suite (`python -m pytest tests/ -v`).
   - Write your handoff report to `d:\talksync\talksync\.agents\worker_m2\handoff.md` detailing all exact file modifications and passing test outputs.
   - Send a completion message referencing `handoff.md`.
</USER_REQUEST>
