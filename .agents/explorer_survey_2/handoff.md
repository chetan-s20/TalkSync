# Handoff Report — explorer_survey_2

**Agent**: explorer_survey_2  
**Role**: Read-Only Exploration Agent  
**Working Directory**: `d:\talksync\talksync\.agents\explorer_survey_2`  
**Date**: 2026-08-06  

---

## 1. Observation

### Observation 1: Double Window Spawning & UI Controls
- `ui/main_window.py:382`: `SessionSummaryDialog` is instantiated directly inside an `after()` callback: `self.after(500, lambda b=blocks: SessionSummaryDialog(self, b))`. It is not stored in an instance variable (e.g. `self._session_summary_dialog`) nor checked with `winfo_exists()`.
- `ui/main_window.py:578-612`: In `_restart_pipeline()`, when `not self.pipeline.running`, `_run_pipeline_thread()` is launched via a thread without updating `self.btn_play.configure(text="⏳", state="disabled", text_color="#94A3B8")`.
- `ui/dialogs/language_selector.py:186`: `btn_model` (`⚙ TalkSync AI >`) is defined without a `command=` parameter.
- `ui/dialogs/audio_settings.py:211`: `lbl_view` has `cursor="hand2"` but no `<Button-1>` event binding.

### Observation 2: OpenAI STT Language Filtering Bypass
- `services/stt/openai_stt.py:271-284`: `_call_api()` sets `response_format="json"`. Standard OpenAI API `json` response format returns `{"text": "..."}` without the `language` field.
- `services/stt/openai_stt.py:199`: `detected_lang = getattr(result, "language", "") or language or ""`. Because `result` lacks `language` attribute, `detected_lang` returns `""` when `language` is `None` or `"auto"`.
- `app/pipeline.py:461`: `if det_lang and det_lang.strip().lower() not in ("", "unknown"):`. Because `det_lang` is `""`, `pipeline.py` skips language checking, allowing audio segments transcribed in non-allowed languages to bypass filtering.

### Observation 3: Translation & TTS Stage Latency Bottlenecks
- `services/tts/router.py:29-47`: `_get_piper()` and `_get_sarvam()` initialize TTS engines lazily on the first synthesis request rather than during `start()`, causing a 1–3 second initial synthesis delay.
- `services/tts/sarvam.py:148-154`: `client = _httpx.AsyncClient(...)` and `async with client:` are executed inside `synthesize()`, instantiating and closing a new client for every request.
- `services/tts/sarvam.py:143`: `for attempt, cfg in enumerate(connection_configs * 2):` loops up to 4 times with `await _asyncio.sleep(1.0)` between attempts.
- `services/tts/router.py:97-106`: `_sapi_speak` executes `subprocess.Popen(["powershell", "-NoProfile", "-Command", cmd], ...)`, incurring 200–500ms process startup overhead per utterance.

---

## 2. Logic Chain

1. **Session Summary Window Spawning**:
   - *Observation*: Line 382 of `ui/main_window.py` executes `SessionSummaryDialog(self, b)` directly without checking `winfo_exists()`.
   - *Reasoning*: Every invocation of `_toggle_session()` when stopping a session creates a new top-level window. Rapid user interaction or multiple stop triggers spawn duplicate modal dialogs.
   - *Conclusion*: Single-instance tracking is missing for `SessionSummaryDialog`.

2. **Play Button Loading State during Restart**:
   - *Observation*: Lines 356-359 of `_toggle_session()` set `btn_play` to `⏳` disabled, but `_restart_pipeline()` in lines 578-612 launches `_run_pipeline_thread()` without disabling `btn_play` or showing `⏳`.
   - *Reasoning*: During routing configuration changes (e.g. toggling computer audio or virtual mic), `_restart_pipeline()` leaves the play button interactive in `▶` state while pipeline initialization and model warmup are running.
   - *Conclusion*: Pipeline restart state management is incomplete.

3. **OpenAI STT Allowed Language Filter Bypass**:
   - *Observation*: `_call_api()` in `openai_stt.py` requests `response_format="json"`, which omits the `language` field in the API response object.
   - *Reasoning*: `getattr(result, "language", "")` returns `""`. When auto-detecting language, `detected_lang` becomes `""`. `app/pipeline.py:461` checks `if det_lang`, which evaluates to `False` for `""` and skips the allowed language validation.
   - *Conclusion*: Non-allowed language audio segments transcribed by OpenAI STT are never dropped.

4. **TTS Synthesis Latency Bottlenecks**:
   - *Observation*: `MultilingualTTSRouter` uses lazy initialization (`_get_piper()`, `_get_sarvam()`), `SarvamTTS` creates a new `httpx.AsyncClient` on every request, and `_sapi_speak` spawns PowerShell subprocesses.
   - *Reasoning*: Lazy loading forces the first TTS request to bear model loading overhead. Re-creating `AsyncClient` prevents TCP connection pooling. Spawning PowerShell adds 200-500ms per fallback sentence.
   - *Conclusion*: TTS synthesis suffers avoidable startup and per-request latency penalties.

---

## 3. Caveats

- Investigation was strictly read-only. No source files were modified outside of agent report files in `.agents/explorer_survey_2/`.
- Actual API response timings for OpenAI STT and Sarvam TTS depend on external network latency and active API keys.

---

## 4. Conclusion

1. **UI State Management**: Single-instance tracking must be added to `SessionSummaryDialog`, `_restart_pipeline()` must set `btn_play` to `⏳` disabled during restart, and dead controls must be wired up.
2. **OpenAI STT Language Filtering**: `OpenAISTT` must use `response_format="verbose_json"` so the API returns the detected language, and internal filtering should be added to ensure audio segments not in allowed languages are dropped.
3. **Translation & TTS Latencies**: `MultilingualTTSRouter` should pre-load TTS engines on `start()`, `SarvamTTS` should reuse a persistent `httpx.AsyncClient`, and Windows SAPI5 fallback should avoid spawning PowerShell subprocesses.

---

## 5. Verification Method

- **Files to Inspect**:
  - `ui/main_window.py` (lines 380–385, 578–612)
  - `services/stt/openai_stt.py` (lines 199, 271–284)
  - `app/pipeline.py` (lines 459–470)
  - `services/tts/router.py` (lines 29–47, 97–106)
  - `services/tts/sarvam.py` (lines 138–196)

- **Verification Commands**:
  - Run existing test suite to verify baseline functionality:
    `python -m pytest tests/`
  - Inspect analysis details in `d:\talksync\talksync\.agents\explorer_survey_2\analysis.md`.

