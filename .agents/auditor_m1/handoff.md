# Handoff & Forensic Audit Report — auditor_m1 (Milestone 1)

## Forensic Audit Verdict: CLEAN

**Work Product**: Milestone 1 Code Modifications (`app/pipeline.py`, `services/tts/sarvam.py`, `services/tts/router.py`, `services/stt/faster_whisper.py`)  
**Profile**: General Project / Integrity Forensics  
**Integrity Mode**: Development Mode  
**Verdict**: **CLEAN**

---

## 1. Observation

A comprehensive forensic audit of all modified files for Milestone 1 was conducted, verifying source code, runtime behavior, and test suite execution:

1. **Initial Prompt Sanitization (`services/stt/faster_whisper.py` line 56, `app/pipeline.py` lines 435–445)**:
   - In `services/stt/faster_whisper.py`: `_initial_prompt` defaults to `None` instead of hardcoded default strings (`"TalkSync AI speech translation transcription."`), eliminating hallucination triggers on quiet audio.
   - In `app/pipeline.py` (`_stt_worker`): Dynamically constructs prompt from settings context and keywords if configured, preventing injection of hardcoded generic strings.

2. **TTS Mute Gate & Queue Purging (`app/pipeline.py` lines 244–289, line 738, line 742)**:
   - `_activate_tts_mute_gate(duration_s)` calculates `mute_until = max(self._ignore_loopback_until, now) + duration_s + 0.5` and updates both `_ignore_loopback_until` and `_ignore_mic_until`.
   - `_purge_loopback_queues()` deterministically removes loopback items from `audio_queue` and `stt_queue`, and resets speech buffers/trackers in `_state`.
   - In `_tts_worker`: `_activate_tts_mute_gate(duration_s)` is invoked *before* calling `await self._audio_output.play(...)`, preventing loopback audio echo feedback loops. Fallback TTS paths calculate estimated duration (`est_duration_s = len(est_text) * 0.06 + 0.5`) to activate the gate prior to playback.

3. **Dynamic Two-Way Language Routing (`app/pipeline.py` line 425, line 567)**:
   - In `_stt_worker`: For `two_way` translation mode on `loopback` source jobs, `lang_code` is set to `None` to enable dynamic language auto-detection by Whisper.
   - In `_translate_and_route`: Dynamically sets `src`/`tgt` based on detected language (`EN -> HI` if English, `HI -> EN` if Hindi), preserving `input_source = "COMPUTER_AUDIO"` tagging for UI Panel B speaker output.

4. **Sarvam TTS Connection Pooling (`services/tts/sarvam.py` lines 68–77, line 84)**:
   - Refactored `SarvamTTS` to maintain a single persistent `httpx.AsyncClient` with TCP connection pooling (`max_keepalive_connections=20`, `max_connections=50`).
   - Removed single-request client creation overhead and removed the 1.0s artificial sleep delay in retry loops.

5. **Eager TTS Engine Initialization (`services/tts/router.py` lines 54–61)**:
   - Updated `MultilingualTTSRouter.start()` to eagerly initialize `_piper` and `_sarvam` sub-engines in parallel via `asyncio.gather(self._get_piper(), self._get_sarvam(), return_exceptions=True)`.

6. **Authenticity & Integrity Sweeps**:
   - Zero hardcoded return values, facade implementations, or mock bypasses were found in production code.
   - Zero dummy/fake test assertions (e.g. `assert True`) were found.

7. **Test Suite Execution**:
   - Executed M1 test suite: `pytest tests/test_pipeline.py tests/test_audio_input.py tests/test_tts.py tests/test_bidirectional.py -v` -> **102 passed** (8.08s).
   - Executed full test runner: `pytest tests/ -v` -> **387 passed** (0 failures, 0 regressions).

---

## 2. Logic Chain

1. **Prompt Sanitization**: Omitting fixed prompt defaults prevents Whisper from generating hallucinated text from static prompts when audio is silent or near noise floor.
2. **Mute Gate & Purging**: Activating the ignore window *before* output playback and clearing pending loopback queues ensures audio captured from speakers during synthesis does not re-trigger STT, stopping echo feedback loops.
3. **Dynamic Language Routing**: Auto-detecting loopback stream language (`lang_code = None`) enables two-way remote conversation translation (`EN->HI` or `HI->EN`) while correctly tagging output for UI rendering.
4. **Sarvam Connection Pooling**: Reusing `httpx.AsyncClient` eliminates per-request TLS handshake setup, while removing the artificial 1.0s sleep delay significantly lowers synthesis latency.
5. **Eager Initialization**: Pre-loading Piper and Sarvam models on pipeline start eliminates multi-second cold-start latency on the first translated utterance.
6. **Empirical Pass**: Verification confirmed that all 387 unit/integration tests pass cleanly without failures.

---

## 3. Caveats

- Hardware-dependent audio loopback (e.g., Stereo Mix vs. WASAPI Loopback vs. VB-Cable) depends on host OS audio drivers, but the software DSP gates, queue purging, and translation routing operate deterministically on all incoming audio streams.

---

## 4. Conclusion

All code modifications for Milestone 1 in `app/pipeline.py`, `services/tts/sarvam.py`, `services/tts/router.py`, and `services/stt/faster_whisper.py` are authentic, genuine, fully functional, and verified.
- **Verdict**: **CLEAN**
- **Test Results**: 100% Green Pass across all 387 tests.

---

## 5. Verification Method

To independently re-verify:

1. **Run direct M1 test suite**:
   ```bash
   pytest tests/test_pipeline.py tests/test_audio_input.py tests/test_tts.py tests/test_bidirectional.py -v
   ```
2. **Run full test runner**:
   ```bash
   pytest tests/ -v
   ```
3. **Inspect modified source files**:
   - `app/pipeline.py`
   - `services/stt/faster_whisper.py`
   - `services/tts/sarvam.py`
   - `services/tts/router.py`
