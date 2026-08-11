# Handoff Report — Milestone 1: Audio DSP, Echo Suppression, Queue Purging & Latency Fixes

## 1. Observation

- **Initial Prompt Sanitization (`services/stt/faster_whisper.py` line 56, `app/pipeline.py` line 435)**:
  - In `services/stt/faster_whisper.py`: Line 56 previously defaulted `_initial_prompt` to `"TalkSync AI speech translation transcription."` when `initial_prompt` was `None`. Removed hardcoded prompt default so it defaults to `None`.
  - In `app/pipeline.py`: In `_stt_worker` (line 435), sanitized `initial_prompt` construction so generic prompt words `"TalkSync AI speech translation transcription"` are excluded, defaulting to `None` unless custom context/keywords are configured in settings.

- **TTS Mute Gate & Queue Purging (`app/pipeline.py` lines 244-288, line 731, line 736)**:
  - In `app/pipeline.py`: `_activate_tts_mute_gate(duration_s)` calculates `mute_until = now + duration_s + 0.5` and updates `_ignore_loopback_until` and `_ignore_mic_until`, followed by `_purge_loopback_queues()` clearing `_state.get_buffer("loopback")`, `audio_queue`, `stt_queue`, and resetting speech tracker.
  - Called `_activate_tts_mute_gate(duration_s)` BEFORE calling `await self._audio_output.play(...)` in `_tts_worker`.
  - Calculated duration for SAPI5 fallback text: `est_duration_s = len(est_text) * 0.06 + 0.5` and triggered `_activate_tts_mute_gate(est_duration_s)` on fallback.

- **Dynamic Language Detection & Routing in Two-Way Mode (`app/pipeline.py` line 424, line 563)**:
  - In `app/pipeline.py` (`_stt_worker` line 424): In `two_way` mode for loopback jobs, set `lang_code = None` to allow dynamic language auto-detection in STT.
  - In `_translate_and_route` (line 563): Dynamically set `src, tgt` based on detected language (`EN -> HI` if English, `HI -> EN` if Hindi). Retained `input_source = "COMPUTER_AUDIO"` tagging for UI Panel B routing.

- **Sarvam TTS Connection Pooling & Latency Fix (`services/tts/sarvam.py` lines 63, 67, 74, 133)**:
  - Refactored `SarvamTTS` to instantiate a single persistent `httpx.AsyncClient` with TCP connection pooling (`max_keepalive_connections=20, max_connections=50`) in `start()` / `_get_client()`, closing it in `stop()`.
  - Removed single-request `httpx.AsyncClient` context manager overhead and removed the `1.0s` sleep delay in the retry loop.

- **Eager TTS Router Engine Initialization (`services/tts/router.py` line 54)**:
  - Updated `MultilingualTTSRouter.start()` to eagerly initialize `_piper` and `_sarvam` sub-engines via `asyncio.gather(self._get_piper(), self._get_sarvam(), return_exceptions=True)` during startup, eliminating first-utterance latency spikes.

- **Test Suite Execution**:
  - Ran command: `python -m pytest tests/test_pipeline.py tests/test_audio_input.py tests/test_tts.py tests/test_bidirectional.py -v`
  - Output: `102 passed in 8.19s` with 0 failures or regressions.

## 2. Logic Chain

1. **Initial Prompt Sanitization**: Generic prompt words in Whisper's `initial_prompt` cause hallucination loops when audio input is silent or quiet. Sanitizing the prompt to default to `None` prevents Whisper from generating hallucinated text based on static prompt words.
2. **TTS Mute Gate & Queue Purging**: Loopback audio capture picks up synthesized speaker output. Setting the mute gate window *before* audio playback begins and purging queued loopback items ensures self-echo feedback loops are completely suppressed.
3. **Dynamic Two-Way Language Routing**: Loopback streams in two-way translation mode can contain either English or Hindi depending on who is speaking on the remote end. Auto-detecting the language in STT (`lang_code = None`) and dynamically mapping `EN -> HI` or `HI -> EN` ensures correct translation direction while preserving `"COMPUTER_AUDIO"` source tagging for UI Panel B.
4. **Sarvam Connection Pooling & Latency**: Instantiating new HTTP clients per synthesis request creates TLS handshake overhead and connection setup delay. A persistent `httpx.AsyncClient` with connection pooling and no artificial 1s retry delay reduces synthesis latency significantly.
5. **Eager TTS Router Warmup**: Lazily initializing Piper and Sarvam models on the first utterance causes a multi-second delay. Initializing them inside `router.start()` ensures engines are warm and ready prior to processing the first audio segment.

## 3. Caveats

- Hardware-dependent loopback device capture (e.g. Stereo Mix vs. VB-Audio Cable) relies on system audio settings, but audio DSP gates and queue purging operate deterministically on all incoming PCM streams.

## 4. Conclusion

All Milestone 1 requirements for Audio DSP, echo suppression, queue purging, dynamic two-way language routing, Sarvam connection pooling, and eager TTS engine warmup have been implemented, validated, and verified with 100% green test passes across 102 unit/integration tests.

## 5. Verification Method

To independently verify:

1. Run the test suite:
   ```bash
   python -m pytest tests/test_pipeline.py tests/test_audio_input.py tests/test_tts.py tests/test_bidirectional.py -v
   ```
2. Inspect the modified files:
   - `app/pipeline.py`
   - `services/stt/faster_whisper.py`
   - `services/tts/sarvam.py`
   - `services/tts/router.py`
