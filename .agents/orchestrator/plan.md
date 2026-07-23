# TalkSync AI Project Plan

## Overview
TalkSync AI is a real-time speech-to-speech translation desktop application for online meetings (Google Meet, Zoom, Teams).
This plan details the implementation strategy for Requirements R1 through R5 and all acceptance criteria.

## Requirements Mapping
- **R1: Online Meeting Computer Audio Capture & Language Recognition**
  - Dual audio capture: mic input (user) + WASAPI Loopback / System Audio / VB-Cable (remote meeting participants).
  - Auto language detection via Whisper STT per segment (`en`, `hi`, etc.).
  - Loopback processing: remote meeting speech translated to user language, rendered in Panel B.
- **R2: Speech-to-Speech TTS Engine Routing**
  - Hindi/Indic target speech -> Sarvam AI TTS (`sarvam_voice`, `hi-IN`), with local TTS / SAPI5 fallback.
  - English target speech -> Piper TTS (`en_US-lessac-medium` / Kokoro) or SAPI5 fallback.
  - Virtual Microphone Output via VB-Cable for broadcasting translated voice into meeting apps.
- **R3: Dual-Panel Real-Time Visual Display**
  - Window title and branding: **TalkSync AI**.
  - Panel A (Left Card - My Side): `en → hi >` header tag, timestamp (`00:03`), original mic/typed text + translated text.
  - Panel B (Right Card - Remote Participant): `hi → en >` header tag, timestamp (`00:03`), original remote text + translated text.
- **R4: Text Input Mode & Control System**
  - Text mode input bypasses ASR/VAD, translates immediately, plays TTS, updates Panel A.
  - Header toolbar controls (Audio Source popup, Keywords/AI Assistant, CC Subtitles, History Dashboard, Play/Stop toggle) fully operational.
- **R5: App Stability & Zero Traceback Guarantee**
  - Clean imports, thread lifecycle management, sounddevice streams clean start/stop, zero exceptions/deadlocks.

## Execution Strategy & Milestones

### Milestone 1: App Stability & Branding Foundation (R5)
- Verify `MainWindow` window title and branding are updated to **TalkSync AI**.
- Fix any remaining import errors, widget conflicts (`_draw()` collisions, invalid canvas colors), and sounddevice stream setup/cleanup logic.
- Ensure main application starts cleanly without tracebacks.

### Milestone 2: Dual Audio Capture & Auto Language Detection (R1)
- Enhance `services/audio/input.py` and `app/pipeline.py` to support simultaneous capture of user microphone and WASAPI loopback audio.
- Enable automatic language detection in `services/stt/faster_whisper.py`.
- Tag audio frames with source origin (Mic vs System Loopback) and detected language (`en`, `hi`, etc.).
- Direct system loopback translations to Panel B callback.

### Milestone 3: Speech-to-Speech TTS Engine Routing & Virtual Mic (R2)
- Configure `services/tts/router.py` for dynamic language routing:
  - Indic/Hindi (`hi`, `hi-IN`) -> `services/tts/sarvam.py` with local/SAPI5 fallback.
  - English (`en`, `en-US`) -> `services/tts/piper.py` / Kokoro / SAPI5 fallback.
- Stream synthesized audio to both physical speakers and VB-Cable Virtual Microphone in `services/audio/output.py`.

### Milestone 4: Dual-Panel Real-Time Visual Display & Header Controls (R3 & R4)
- Update `ui/widgets/transcript_panel.py` and `ui/main_window.py` to format cards with timestamps (`00:03`), tags (`en → hi >` for Panel A, `hi → en >` for Panel B), original text, and translated text.
- Connect live audio level meter to microphone RMS level.
- Complete text mode integration: typing text in bottom panel bypasses VAD/ASR and routes through translation + TTS into Panel A.
- Wire header toolbar controls (Audio Source, Keywords/AI Assistant, CC Subtitles, History, Play/Stop).

### Milestone 5: End-to-End Verification & Forensic Integrity Audit
- Run full test suite across all 5 tiers.
- Perform forensic integrity audit with `teamwork_preview_auditor`.
- Claim project victory and submit final report to Sentinel.
