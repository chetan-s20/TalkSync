## 2026-08-06T12:20:22Z
You are worker_m1, an implementation worker subagent.
Your working directory is `d:\talksync\talksync\.agents\worker_m1`. Create your directory and `progress.md` before starting.
Read `d:\talksync\talksync\.agents\ORIGINAL_REQUEST.md` and `d:\talksync\talksync\PROJECT.md` for full context.

DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your Task (Milestone 1 — Audio DSP, Echo Suppression, Queue Purging & Latency Fixes):
1. In `app/pipeline.py` (`_stt_worker`, line 381):
   - Sanitize `initial_prompt` by removing generic prompt words ("TalkSync AI speech translation transcription."). Default to empty prompt `[]` unless non-empty custom prompt is configured in settings.
2. In `app/pipeline.py`:
   - Implement `_activate_tts_mute_gate(duration_s: float)` and `_purge_loopback_queues()` helper functions.
   - `_activate_tts_mute_gate` updates `_ignore_loopback_until = max(_ignore_loopback_until, now + duration_s + 0.5)` and `_ignore_mic_until`, then drains pending loopback items from `audio_queue`, `stt_queue`, and VAD speech buffers (`_state.get_buffer("loopback").clear()`).
   - Call `_activate_tts_mute_gate(duration_s)` BEFORE calling `await self._audio_output.play()`.
   - Calculate duration for SAPI5 fallback text (~0.06s per character + 0.5s buffer) and trigger `_activate_tts_mute_gate` when SAPI5 speaks.
3. In `app/pipeline.py`:
   - In `two_way` translation mode, allow dynamic language auto-detection in STT (`lang_code = None`) for loopback, and dynamically set `src, tgt` in `_translate_and_route` based on detected language (`EN -> HI` if English, `HI -> EN` if Hindi). Retain `input_source = "COMPUTER_AUDIO"` tagging for UI Panel B routing.
4. In `services/tts/sarvam.py`:
   - Refactor `SarvamTTS` to reuse a single persistent `httpx.AsyncClient` with TCP connection pooling instead of instantiating `httpx.AsyncClient()` on every request. Remove the `1.0s` sleep delay in the retry loop.
5. In `services/tts/router.py`:
   - Eagerly warm up / initialize TTS engines during `MultilingualTTSRouter` initialization to eliminate first-utterance latency spikes.
6. Verification & Execution:
   - Run pytest for affected modules (`python -m pytest tests/test_pipeline.py tests/test_audio.py tests/test_tts.py -v`).
   - Write your handoff report to `d:\talksync\talksync\.agents\worker_m1\handoff.md` including exact code changes and passing test output.
   - Send a message when finished referencing `handoff.md`.
