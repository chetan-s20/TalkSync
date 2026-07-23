# Project: TalkSync AI Real-Time Speech-to-Speech Translation

## Architecture
TalkSync AI is a real-time speech-to-speech translation desktop application designed for online meetings (Google Meet, Zoom, Teams).
- **GUI**: CustomTkinter desktop interface (`ui/main_window.py`, `ui/widgets/`, `ui/dialogs/`) branded as **TalkSync AI**.
- **Pipeline Orchestrator**: `app/pipeline.py` managing audio queues, STT queue, translation queue, TTS queue, audio loopbacks, and UI event callbacks.
- **Audio Capture & Output**: `services/audio/input.py` (Dual capture: User mic + WASAPI Loopback / System Audio) and `services/audio/output.py` (System speakers + VB-Cable Virtual Mic).
- **Speech Recognition (STT)**: `services/stt/faster_whisper.py` with automatic language detection (`en`, `hi`, etc.).
- **Translation**: `services/translation/argos.py` & `deepl.py` with context engine (`services/translation/context_engine.py`).
- **TTS Engine Routing**: `services/tts/router.py` routing Hindi/Indic to Sarvam AI TTS (`hi-IN`) with local/SAPI5 fallback, and English to Piper TTS (`en_US-lessac-medium` / Kokoro) or SAPI5.
- **Visual Display**: Dual-panel setup (Panel A left for `en → hi >` user mic/text, Panel B right for `hi → en >` remote meeting speech), subtitle overlay, and header controls.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | App Stability & Branding Foundation | R5: App branding as TalkSync AI, clean imports, zero tracebacks, sounddevice stream safety, thread lifecycle cleanup | None | DONE |
| M2 | Dual Audio Capture & Auto Language Detection | R1: Mic + WASAPI Loopback / Stereo Mix dual capture, Whisper auto language detection (`en`, `hi`), routing meeting audio loopback to Panel B | M1 | IN_PROGRESS |
| M3 | Speech-to-Speech TTS Routing & Virtual Mic | R2: Sarvam AI TTS for Indic with local/SAPI5 fallback, Piper/Kokoro/SAPI5 for English, streaming to VB-Cable Virtual Mic | M1 | PLANNED |
| M4 | Dual-Panel Display & Text Input Control System | R3 & R4: Panel A (`en → hi >`) & Panel B (`hi → en >`) screenshot format with timestamps (`00:03`), text input mode bypass, live meter, header toolbar controls | M2, M3 | PLANNED |
| M5 | E2E Testing, Adversarial Hardening & Forensic Audit | Full verification across all requirements, E2E test suite validation (Tiers 1-5), and Forensic Integrity Audit | M4 | PLANNED |

## Code Layout
- `app/`
  - `pipeline.py`: Real-time pipeline processing loop and queues
  - `application.py`: Application container & settings manager
- `ui/`
  - `main_window.py`: CustomTkinter main GUI branded TalkSync AI
  - `widgets/`: `transcript_panel.py` (Dual Panel A & B), `top_meter.py`, etc.
  - `dialogs/`: Audio settings, AI assistant, Speaker options, Diagnostics, History viewer
- `services/`
  - `audio/`: `input.py` (mic + WASAPI loopback), `output.py` (speaker + virtual mic)
  - `stt/`: `faster_whisper.py` (Whisper STT with language detection)
  - `translation/`: `argos.py`, `deepl.py`, `context_engine.py`
  - `tts/`: `router.py`, `sarvam.py`, `piper.py`, `sapi.py`
  - `history/`: `database.py` SQLite CRUD
  - `diagnostics/`: `monitor.py` GPU VRAM & latency metrics
