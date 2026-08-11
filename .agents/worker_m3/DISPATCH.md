## 2026-08-05T16:30:00Z

Task Objective: Implement Milestone M3 — Bidirectional Translation (BUG 3), Headphone WASAPI Loopback, and VB-Cable Output Integration.

Refer to:
- `d:\talksync\talksync\.agents\ORIGINAL_REQUEST.md`
- `d:\talksync\talksync\.agents\orchestrator\DISPATCH.md`
- `d:\talksync\talksync\.agents\explorer_survey_1\handoff.md`

Specific Changes to Make:
1. **Dynamic Language STT & Routing in `app/pipeline.py`**:
   - In `_stt_worker`, for two-way mode (`self._translation_mode == "two_way"`), set `lang_code = None` to enable dynamic language auto-detection for both mic and loopback audio streams (instead of forcing `language="hi"` on loopback).
   - In `_translate_and_route`, perform dynamic language routing based on detected language:
     - If `is_loopback`:
       - If `detected.upper() in ("EN", "ENGLISH")`: set `src="EN"`, `tgt="HI"`
       - Else: set `src="HI"`, `tgt="EN"`
     - Retain `input_source = "COMPUTER_AUDIO"` tagging so UI routes translated text to Panel B.
   - Verify per-panel speaker toggles (`tts_enabled_a` / `tts_enabled_b`) gate TTS queue insertion correctly.
2. **Headphone WASAPI Loopback Preference in `services/audio/loopback.py`**:
   - Update `find_wasapi_loopback()` to prefer the WASAPI loopback endpoint corresponding to the ACTIVE output device (headphones = device index 36).
   - Fall back cleanly to Stereo Mix (device index 39) if WASAPI loopback cannot target headphones specifically.
3. **Native Sample Rate Gating in `services/audio/input.py`**:
   - In `_start_sd_loopback`, when opening Stereo Mix (device 39), open it at its native sample rate (44.1kHz / 48kHz) first, then resample to 16kHz. Do NOT force 16kHz capture directly on Stereo Mix if native rate differs.
   - Add startup log: `logger.info(f"Loopback capturing from: {loopback_name} — headphone audio WILL be captured")`.
4. **VB-Cable Output Integration Verification (`services/audio/output.py`)**:
   - Verify that when `virtual_mic_enabled=True`, TTS audio is played through both Headphones (device 36) and VB-Cable Input (device 7) in parallel. Ensure mute gate covers VB-Cable writes.
5. **Test Script `tests/test_bidirectional.py` (`d:\talksync\talksync\tests\test_bidirectional.py`)**:
   - Write a test script feeding synthetic English audio (mic) and synthetic Hindi audio (loopback) into the pipeline, verifying Panel A produces `TranslationResult` (`VOICE`, EN->HI, text != "") and Panel B produces `TranslationResult` (`COMPUTER_AUDIO`, HI->EN, text != ""). Exits code 0.
6. **Test Script `tests/test_loopback_headphones.py` (`d:\talksync\talksync\tests\test_loopback_headphones.py`)**:
   - Write a test script that simulates playing a 440Hz tone on device 36 (headphones) while recording device 39 (Stereo Mix loopback / WASAPI loopback) and verifies recorded RMS > 0.001. Exits code 0.

Verification:
- Run test commands:
  `python -m pytest tests/test_bidirectional.py -v --tb=short`
  `python -m pytest tests/test_loopback_headphones.py -v --tb=short`
  `python -m pytest tests/ -v --tb=short`
- Document test commands and outputs in your handoff report at `d:\talksync\talksync\.agents\worker_m3\handoff.md`.
