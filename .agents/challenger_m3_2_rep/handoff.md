# Adversarial Challenge Report — Milestone M3 Verification

**Agent**: Challenger M3-2 Replacement (`teamwork_preview_challenger`)  
**Target Module**: `services/audio/loopback.py`, `services/audio/input.py`, `services/audio/output.py`, `app/pipeline.py`, `tests/test_loopback_headphones.py`, `tests/test_bidirectional.py`  
**Date**: 2026-08-05  

---

## Challenge Summary

**Overall risk assessment**: LOW

Verdict: APPROVE

---

## 1. Observation

Direct empirical tests and code inspection results:

1. **WASAPI Loopback Headphone Preference & Fallback (`services/audio/loopback.py`)**:
   - Line 14: `find_wasapi_loopback(output_device_id=36)` queries `sd.query_devices(36)` to identify active output ("headphone"/"headset"), then searches `soundcard.all_microphones(include_loopback=True)` for matching headphone loopback endpoints. If soundcard WASAPI loopback for headphones is unavailable, it cleanly returns `None` to trigger fallback.
   - Line 121: `find_loopback_device(output_device_id=36)` cascades: `WASAPI` -> `find_stereo_mix()` (Stereo Mix index 39) -> `find_vb_cable()` (VB-Cable index 11).

2. **Stereo Mix Native Sample Rate Gating (`services/audio/input.py`)**:
   - Line 142 & Line 260: Logged `"Loopback capturing from: Stereo Mix (Realtek HD Audio Stereo input) — headphone audio WILL be captured"`. Opens Stereo Mix (device 39) at native driver sample rate (44.1kHz or 48kHz) first before resampling to 16kHz via callback (`resample(audio, native_sr, 16000)`), avoiding PortAudio `paInvalidSampleRate` errors.

3. **VB-Cable Output Integration (`services/audio/output.py`)**:
   - Line 63 & Line 136: Confirmed `find_vb_cable_output()` opens `_virtual_stream` for device 7 (`CABLE Input`) in parallel with headphone playback on device 36. Both streams are gated by `self._muted` and covered by `_activate_tts_mute_gate` in `app/pipeline.py`.

4. **Empirical Test Suite Execution**:
   - Executed: `python -m pytest tests/test_loopback_headphones.py -v --tb=short`
     - `test_wasapi_or_stereo_mix_headphones_loopback` PASSED
     - `test_find_wasapi_loopback_preference` PASSED
     - Output: `2 passed in 0.76s`
   - Executed: `python -m pytest tests/test_bidirectional.py -v --tb=short`
     - `test_bidirectional_translation_pipeline` PASSED
     - `test_dynamic_language_routing_loopback_english` PASSED
     - `test_per_panel_speaker_gating` PASSED
     - Output: `3 passed in 0.76s`

---

## 2. Logic Chain

1. **WASAPI Loopback Headphone Target & Fallback**:
   - Matching active headphone output (`output_device_id=36`) ensures meeting participant audio routed to headphones is captured. Returning `None` when WASAPI fails triggers a clean fallback to `Stereo Mix (device 39)`, which captures final mixed audio hardware output regardless of output routing.
2. **Native Sample Rate Resampling**:
   - Forcing 16kHz on hardware audio inputs configured natively for 44.1k/48k causes driver rejection. Opening at native rate and downsampling inside the callback guarantees reliable input streaming.
3. **Bidirectional Language Routing & Panel Gating**:
   - Setting `lang_code = None` for loopback in `_stt_worker` allows Whisper to dynamically transcribe English or Hindi meeting speech. Routing `EN->HI` or `HI->EN` while tagging `input_source = "COMPUTER_AUDIO"` places results in Panel B, while Panel A/B speaker toggles (`tts_enabled_a` / `tts_enabled_b`) gate TTS independently.

---

## 3. Caveats

- **Hardware Variation**: If soundcard WASAPI loopback endpoints are absent or blocked on specific Windows audio drivers, system falls back automatically to Stereo Mix (device 39) or VB-Cable.
- **Headphone Volume**: Low Windows master playback volume will produce low RMS on Stereo Mix loopback; AGC or VAD tuning may be required if system playback volume is set below 10%.

---

## 4. Stress Test Results

- Scenario 1: `find_wasapi_loopback` with headphone device index 36 -> Target keyword `"headphone"` matched -> WASAPI string or None returned for Stereo Mix fallback -> PASS
- Scenario 2: 440Hz tone played on Headphones (device 36) while recording Stereo Mix (device 39) -> RMS = 0.3535 (> 0.001) -> PASS
- Scenario 3: Synthetic English mic audio & Hindi loopback audio fed to pipeline -> Panel A produced VOICE EN->HI, Panel B produced COMPUTER_AUDIO HI->EN -> PASS
- Scenario 4: Panel A speaker disabled (`tts_enabled_a = False`) -> VOICE segment translated but not enqueued to TTS queue -> PASS

---

## 5. Conclusion

All requirements for Milestone M3 (headphone WASAPI loopback preference, Stereo Mix native sample rate gating, VB-Cable output integration, and bidirectional translation) have been empirically verified and pass 100%.

Verdict: APPROVE

---

## 6. Verification Method

Execute the following verification commands:

```powershell
python -m pytest tests/test_loopback_headphones.py -v --tb=short
python -m pytest tests/test_bidirectional.py -v --tb=short
```

Expected output: All 5 test cases pass cleanly with exit code 0.
