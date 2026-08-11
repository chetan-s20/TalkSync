# Review & Handoff Report — Milestone M3 Implementation

**Reviewer**: `teamwork_preview_reviewer` (Reviewer M3-2)  
**Roles**: Reviewer, Critic  
**Working Directory**: `d:\talksync\talksync\.agents\reviewer_m3_2`  
**Date**: 2026-08-05  

---

## Verdict: APPROVE

---

## 1. Observation

Direct file inspection and test execution results:

1. **WASAPI Loopback Headphone Preference & Fallback (`services/audio/loopback.py`)**:
   - Lines 20-56: `find_wasapi_loopback(output_device_id)` queries active output device metadata via `sd.query_devices(output_device_id)`. When active output is headphones/headset (device index 36), `target_keyword` is set to `"headphone"`. If a headphone WASAPI loopback endpoint is not available via `soundcard`, `find_wasapi_loopback` returns `None`.
   - Lines 126-136: In `find_loopback_device`, returning `None` cleanly triggers step 2: `find_stereo_mix()`, which resolves device index 39 (`Stereo Mix (Realtek HD Audio Stereo input)`).

2. **Native Sample Rate Gating & Startup Logging (`services/audio/input.py`)**:
   - Lines 146 & 260: Added required startup log: `logger.info(f"Loopback capturing from: {loopback_name} — headphone audio WILL be captured")` in both WASAPI and sounddevice paths.
   - Lines 263-288: In `_start_sd_loopback`, the stream opener queries `dev_info.get("default_samplerate", 44100)` and tries `native_sr` (44.1kHz/48kHz) before target 16kHz rate. `_make_callback` performs downsampling from `native_sr` to 16kHz (`resample(audio, native_sr, target_sr)`).

3. **Bidirectional Translation & Panel Routing (`app/pipeline.py`)**:
   - Line 420: For two-way mode (`self._translation_mode == "two_way"`), `lang_code` is set to `None` in `_stt_worker`, enabling dynamic Whisper language auto-detection for both mic and loopback audio streams.
   - Lines 549-556: In `_translate_and_route`, for loopback audio (`is_loopback=True`), when detected language is English (`"EN"`, `"ENGLISH"`), routing sets `src="EN"`, `tgt="HI"`; otherwise `src="HI"`, `tgt="EN"`. Segment retains `input_source = "COMPUTER_AUDIO"` tagging to populate Panel B.
   - Lines 672-690: TTS queue gating checks `input_source`: Panel A (`VOICE`, `TEXT`) is gated by `self.tts_enabled_a`, and Panel B (`COMPUTER_AUDIO`, `LOOPBACK`) is gated by `self.tts_enabled_b`.

4. **VB-Cable Output Integration (`services/audio/output.py`)**:
   - Lines 63-70: When `settings.virtual_mic_enabled` is True, `find_vb_cable_output()` opens `_virtual_stream` for device index 7 (`CABLE Input`) in parallel with `_speaker_stream` (headphones, device index 36). Both streams are covered by `_muted` and pipeline `_activate_tts_mute_gate`.

5. **Integrity & Code Quality Audit**:
   - Source files (`app/pipeline.py`, `services/audio/loopback.py`, `services/audio/input.py`, `services/audio/output.py`) contain clean production logic without hardcoded test values, dummy stubs, or bypasses.
   - Tests in `tests/test_bidirectional.py` and `tests/test_loopback_headphones.py` exercise actual pipeline routing, WASAPI preference, and fallback mechanisms.

6. **Test Suite Verification**:
   - Executed: `python -m pytest tests/ -v --tb=short`
   - Result: **140 passed in 23.36s** (exit code 0).

---

## 2. Logic Chain

1. **Headphone WASAPI Loopback Selection & Fallback**:
   - When headphones (device index 36) are active, `find_wasapi_loopback` prioritizes WASAPI endpoints matching `"headphone"` or `"headset"`.
   - If `soundcard` does not expose a headphone-specific loopback endpoint, returning `None` allows `find_loopback_device` to cleanly fall back to `find_stereo_mix()` (device index 39). This prevents selecting an incorrect speaker WASAPI loopback while user wears headphones.

2. **Native Sample Rate Gating**:
   - High Definition Realtek audio chips enforce hardware sample rates at 44.1kHz or 48kHz. Direct stream opening at 16kHz on Stereo Mix can fail or output silent frames.
   - Opening Stereo Mix at its native rate first and resampling to 16kHz inside the callback guarantees clean signal capture. The explicit startup log confirms headphone loopback readiness to the user.

3. **Bidirectional Translation & Speaker Gating**:
   - Auto-detecting spoken language per audio segment (`lang_code = None`) allows meeting audio (Panel B) and mic audio (Panel A) to be accurately transcribed regardless of speaker language.
   - Dynamic direction assignment in `_translate_and_route` routes English meeting participant speech to Hindi (`EN->HI`) and Hindi participant speech to English (`HI->EN`).
   - Independent speaker toggle flags (`tts_enabled_a`, `tts_enabled_b`) ensure user preferences for audio playback per panel are respected.

---

## 3. Caveats

- **Hardware Variation**: If a system has neither soundcard WASAPI loopback nor Stereo Mix enabled in Windows Sound Settings, `find_loopback_device` will return `None` and log an explicit warning requesting the user to enable Stereo Mix.
- **VB-Cable Optionality**: If VB-Cable driver is not installed on the system, virtual mic output gracefully logs a warning and continues playback to headphones without breaking pipeline operation.

---

## 4. Conclusion

The Milestone M3 implementation is complete, robust, and meets all functional and integrity standards:
- WASAPI loopback correctly targets active headphones (36) with clean fallback to Stereo Mix (39).
- Stereo Mix captures at native sample rate (44.1k/48k) before resampling to 16kHz with the required startup log.
- Full bidirectional translation and per-panel speaker toggle gating function correctly.
- Test suite passes 100% (140/140 tests).

---

## 5. Verification Method

To independently verify this review:

```powershell
# Run the specific M3 unit tests
python -m pytest tests/test_bidirectional.py -v --tb=short
python -m pytest tests/test_loopback_headphones.py -v --tb=short

# Run the complete test suite
python -m pytest tests/ -v --tb=short
```

Expected result: All tests pass with exit code 0.
