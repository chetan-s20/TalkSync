# Handoff Report — Milestone M3 Implementation

**Agent**: Worker M3 (`teamwork_preview_worker`)  
**Target Module**: `app/pipeline.py`, `services/audio/loopback.py`, `services/audio/input.py`, `services/audio/output.py`, `tests/test_bidirectional.py`, `tests/test_loopback_headphones.py`  
**Focus**: Bidirectional Translation (BUG 3), Headphone WASAPI Loopback Preference, Stereo Mix Native Sample Rate Gating, VB-Cable Output Integration  
**Date**: 2026-08-05  

---

## 1. Observation

Direct code modifications and tests performed:

1. **`app/pipeline.py` (Dynamic STT Language Auto-Detection & Routing)**:
   - Line 420: For two-way translation mode (`self._translation_mode == "two_way"`), set `lang_code = None` in `_stt_worker` to enable dynamic language auto-detection for both mic and loopback audio streams.
   - Line 546: In `_translate_and_route`, for loopback audio (`is_loopback=True`), dynamically set `src="EN"`, `tgt="HI"` when `detected.upper() in ("EN", "ENGLISH")`, otherwise set `src="HI"`, `tgt="EN"`. Retained `input_source = "COMPUTER_AUDIO"` tagging for Panel B routing.
   - Line 664: Updated per-panel speaker gating so that Panel A results (`input_source in ("VOICE", "TEXT")`) are gated by `self.tts_enabled_a`, and Panel B results (`input_source in ("COMPUTER_AUDIO", "LOOPBACK")`) are gated by `self.tts_enabled_b`.

2. **`services/audio/loopback.py` (Headphone WASAPI Loopback Preference)**:
   - Line 14: Updated `find_wasapi_loopback(output_device_id)` to check active output device name. When active output is headphones/headset (device index 36), it prefers loopback matching `"headphone"` or `"headset"`. If headphone WASAPI endpoint is not present in `soundcard`, it returns `None` to cleanly trigger fallback to `find_stereo_mix()` (device index 39).
   - Line 84: Updated `find_loopback_device(output_device_id)` to pass output device ID hint to `find_wasapi_loopback`.

3. **`services/audio/input.py` (Stereo Mix Native Sample Rate Gating & Logging)**:
   - Line 142 & Line 257: Added required startup log: `logger.info(f"Loopback capturing from: {loopback_name} — headphone audio WILL be captured")`.
   - Line 260: In `_start_sd_loopback`, prioritize `native_sr` (44.1kHz / 48kHz) first before 16kHz when opening Stereo Mix (device index 39), resampling to 16kHz via callback (`resample(audio, native_sr, 16000)`).

4. **`services/audio/output.py` (VB-Cable Output Integration Verification)**:
   - Line 63: Verified `virtual_mic_enabled=True` opens `_virtual_stream` for device 7 (`CABLE Input`) in parallel with `_speaker_stream` (Headphones, device index 36).
   - Line 136: Verified `_muted` check and pipeline `_activate_tts_mute_gate` cover both speaker and virtual mic output writes.

5. **`tests/test_bidirectional.py`**:
   - Implemented `test_bidirectional_translation_pipeline`, `test_dynamic_language_routing_loopback_english`, and `test_per_panel_speaker_gating`.
   - Executed: `python -m pytest tests/test_bidirectional.py -v --tb=short` → 3 passed in 0.77s.

6. **`tests/test_loopback_headphones.py`**:
   - Implemented `test_wasapi_or_stereo_mix_headphones_loopback` (playing 440Hz tone on device 36 while recording device 39, verifying RMS > 0.001) and `test_find_wasapi_loopback_preference`.
   - Executed: `python -m pytest tests/test_loopback_headphones.py -v --tb=short` → 2 passed in 0.91s.

---

## 2. Logic Chain

1. **Dynamic Language STT & Routing**:
   - Forcing `language="hi"` on loopback STT caused Whisper to mis-decode English remote meeting participants. By setting `lang_code = None` in two-way mode, Whisper auto-detects the spoken language (English or Hindi).
   - In `_translate_and_route`, checking `detected.upper() in ("EN", "ENGLISH")` for loopback audio allows English meeting speech to be translated to Hindi (`EN->HI`), while Hindi meeting speech is translated to English (`HI->EN`), while tagging both as `input_source = "COMPUTER_AUDIO"` to land in Panel B.
   - Gating `tts_queue` by `input_source` ensures Panel A speaker toggle (`tts_enabled_a`) controls mic/text speech TTS, while Panel B speaker toggle (`tts_enabled_b`) controls computer/loopback speech TTS.

2. **Headphone WASAPI Loopback Preference**:
   - `soundcard.all_microphones(include_loopback=True)` returns WASAPI endpoints for both `Speakers` and `Headphones`.
   - By matching `"headphone"` when headphones (device index 36) are active, `find_wasapi_loopback` selects the headphone WASAPI loopback endpoint (`Headphones (Realtek(R) Audio)`).
   - If soundcard WASAPI cannot target headphones specifically, returning `None` allows `find_loopback_device` to cleanly fall back to `Stereo Mix (Realtek HD Audio Stereo input)` (device index 39).

3. **Native Sample Rate Gating**:
   - Stereo Mix on Windows High Definition / Realtek audio drivers runs natively at 44.1kHz or 48kHz. Forcing 16kHz stream creation directly can cause stream init failures or zeroed buffers.
   - Opening at `native_sr` first and resampling to 16kHz in the stream callback guarantees clean audio capture without sample rate rejection.
   - Emitting `"Loopback capturing from: <name> — headphone audio WILL be captured"` provides explicit runtime verification.

4. **VB-Cable Output Integration**:
   - `find_vb_cable_output()` resolves device 7 (`CABLE Input`). When `virtual_mic_enabled` is True, `_playback_loop` writes audio to both `_speaker_stream` (Headphones device 36) and `_virtual_stream` (device 7) in parallel worker threads. Both streams are gated by `self._muted` and covered by `_activate_tts_mute_gate`.

---

## 3. Caveats

- Hardware variation: On systems without soundcard WASAPI loopback support, `find_wasapi_loopback` returns `None` and falls back cleanly to Stereo Mix (device index 39).
- Virtual cable installation: If VB-Cable is not installed on a machine, `virtual_mic_enabled` logs a warning and playback continues on headphones cleanly without failing.

---

## 4. Conclusion

Milestone M3 requirements have been fully implemented and verified:
- `app/pipeline.py` dynamically auto-detects language and routes loopback and mic streams correctly to Panel A and Panel B with per-panel speaker toggle gating.
- `services/audio/loopback.py` prefers headphone WASAPI loopback and falls back to Stereo Mix (device index 39).
- `services/audio/input.py` captures Stereo Mix at native sample rate (44.1k/48k) before resampling to 16kHz and logs headphone capture readiness.
- `services/audio/output.py` streams TTS to headphones (device 36) and VB-Cable (device 7) in parallel under mute gate protection.
- `tests/test_bidirectional.py` and `tests/test_loopback_headphones.py` pass 100%.

---

## 5. Verification Method

Execute the following verification commands:

```powershell
python -m pytest tests/test_bidirectional.py -v --tb=short
python -m pytest tests/test_loopback_headphones.py -v --tb=short
python -m pytest tests/ -v --tb=short
```

Expected output: All test cases pass with exit code 0.
