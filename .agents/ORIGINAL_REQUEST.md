# Original User Request

## Initial Request — 2026-07-22T16:23:52Z

TalkSync Pro is a real-time speech translation desktop app (Python 3.11, CustomTkinter, CUDA GPU). The pipeline backend works (Whisper STT, Argos Translate, Piper/Sarvam TTS, Silero VAD) but the UI was recently rebuilt and most components are dead shells — they render visually but don't communicate with the pipeline. The goal is to wire every UI component to the live pipeline, fix all bugs, and deliver a fully working translator app.

Working directory: d:/talksync/talksync
Integrity mode: development

## Requirements

### R1. Wire All UI Dialogs to Pipeline Backend

The following dialogs must be connected to the live pipeline via proper callbacks. All pipeline APIs already exist — no new pipeline features need to be created.

**Audio Settings Dialog** (`ui/dialogs/audio_settings.py`):
- `MainWindow._show_audio_settings()` must pass `on_update_callback` when opening the dialog.
- Device selection must update `settings.audio.input_device_id` / `output_device_id` by resolving device names via `sounddevice.query_devices()`.
- The callback must be stored and invoked inside the dialog.

**AI Assistant Dialog** (`ui/dialogs/ai_assistant.py`):
- `on_save_callback` must be stored in `self.on_save_callback` and called when saving.
- Text fields must pre-fill from `settings.keywords` and `settings.context` instead of hardcoded placeholders.
- On save, must update `settings.keywords`, `settings.context`, and call `pipeline.context_engine.set_seed_context(context)` if available.

**Speaker Options Dialog** (`ui/dialogs/speaker_options.py`):
- `on_update_callback` must be stored and called when sliders/dropdowns change.
- Volume slider → `pipeline.set_volume(volume)`.
- Playback delay slider → `pipeline.set_delay(delay)`.
- Pre-fill from `settings.audio.volume`, `settings.audio.playback_delay_s`, `settings.tts.voice`.

**Diagnostics Dialog** (`ui/dialogs/diagnostics.py`):
- Remove all hardcoded metrics. Accept `pipeline` as constructor arg.
- Use `DiagnosticsMonitor` from `services/diagnostics/monitor.py` to collect live GPU VRAM, latency, model info.
- Refresh every 1000ms via `self.after(1000, self._refresh)`.
- Fix the broken `toggle()` stub (missing `self` parameter).

**History Viewer** (`ui/dialogs/history_viewer.py`):
- Remove all hardcoded mock session/transcript fallback data.
- Show clean "No sessions recorded yet" empty state when DB returns empty.
- Fix `_generate_summary()` to produce a real extractive summary from transcript text.

### R2. Live Audio Level Meter

- Add `on_audio_level: Optional[Callable[[float], None]]` callback to `Pipeline` class in `app/pipeline.py`.
- In `_capture_worker()`, compute RMS level (`np.sqrt(np.mean(audio**2))`) after processing each chunk, and call `on_audio_level(rms)`.  
- In `MainWindow`, register callback and update `self.top_meter.set_level(level)` on the main thread via `self.after(0, ...)`.

### R3. Translation Pipeline Must Work End-to-End

- When the user clicks Play (▶) and speaks into the mic, the full pipeline must execute: Mic → RNNoise → VAD → Whisper STT → Language Validator → Context Engine → Argos Translate → TTS → Speaker Output.
- The source transcript must appear in Panel A (left card) and the translated text must appear in Panel B (right card).
- The subtitle overlay must update with both original and translated text.
- Status bar must show live status ("Listening...", "Processing...", "Translating...", "Speaking...") and latency.

### R4. Text Input Mode Must Work

- When the user enables the text mode checkbox and types text in the input box, clicking Send must:
  1. Display the typed text in Panel A with a `[TEXT]` badge.
  2. Route text through `pipeline.process_text_input()` which bypasses VAD/STT and goes directly to translation.
  3. Display the translated result in Panel B.
  4. Play the translated text via TTS.

### R5. Fix All Import Errors and Runtime Bugs

- Run `python main.py` and fix every crash, traceback, import error, or runtime exception.
- Verify all `__init__.py` exports are correct across all packages.
- Verify all widget classes don't override `CTkFrame._draw()` (rename any `_draw` methods to avoid collision with CustomTkinter internals).
- Verify all Tkinter Canvas widgets use valid color strings (not `"transparent"`).

### R6. Cleanup Dead Code

- Delete unused widget files that are never imported: `control_bar.py`, `latency_badge.py`, `sidebar.py`, `status_indicator.py`, `waveform.py` from `ui/widgets/`.

## Key Technical Context

- **Pipeline class** is at `app/pipeline.py` (488 lines). It has async workers for each stage connected by `asyncio.Queue`s.
- **Pipeline callbacks**: `on_transcription`, `on_translation`, `on_status`, `on_latency` — already registered by MainWindow.
- **Pipeline methods available**: `set_volume()`, `set_delay()`, `set_translation_mode()`, `mute_mic()`, `process_text_input()`.
- **MainWindow** runs pipeline on a background daemon thread with its own asyncio event loop. UI updates use `self.after(0, callback)` to marshal to Tkinter main thread.
- **Settings** is Pydantic BaseSettings with nested sub-settings (AudioSettings, VADSettings, STTSettings, TranslationSettings, TTSSettings, SubtitleSettings, HistorySettings).
- **Context Engine** at `services/translation/context_engine.py` has `set_seed_context()`, `add_segment()`, `build_context_prompt()`.
- **DiagnosticsMonitor** at `services/diagnostics/monitor.py` has `collect() -> dict` returning GPU/VRAM/latency stats.
- **HistoryDatabase** at `services/history/database.py` has full CRUD: `save_session()`, `list_sessions()`, `load_session()`, `delete_session()`, `get_session_segments()`.
- **PROMPT.md** at `d:/talksync/talksync/PROMPT.md` (813 lines) contains the full specification.
- The app runs on Windows with Python 3.11, CUDA GPU (RTX 4060), and uses CustomTkinter for the GUI.

## Acceptance Criteria

### Pipeline Integration
- [ ] App launches with `python main.py` without any errors or tracebacks
- [ ] Clicking Play starts the pipeline; clicking Stop halts it
- [ ] Text typed in the input box (with text mode enabled) appears in Panel A and its translation appears in Panel B
- [ ] Status bar updates with live pipeline status text
- [ ] Audio level meter in the header animates when mic is active

### Dialog Wiring
- [ ] Audio Settings: selecting a different input device updates `settings.audio.input_device_id`
- [ ] AI Assistant: saving keywords/context updates `settings.keywords` and `settings.context`
- [ ] Speaker Options: moving the volume slider calls `pipeline.set_volume()`
- [ ] Diagnostics: shows live GPU VRAM and latency metrics that update every second
- [ ] History Viewer: shows real sessions from SQLite DB or clean empty state

### Code Quality
- [ ] No unused widget files remain in `ui/widgets/`
- [ ] No `_draw()` method conflicts with CTkFrame internals
- [ ] All imports resolve cleanly across all packages
- [ ] `python -c "from ui.main_window import MainWindow; print('OK')"` succeeds

## Manual User Edits — 2026-07-22T16:52:00Z

The user has made manual edits to the following files. Do NOT overwrite these changes — incorporate them into your work:

1. `d:/talksync/talksync/translation/__init__.py` — Removed the NLLB translator provider option (lines 13-15 deleted).

2. `d:/talksync/talksync/ui/main_window.py` — `_send_text_input()` method (around line 385) now properly uses `asyncio.run_coroutine_threadsafe()` to schedule `pipeline.process_text_input()` on the pipeline's async event loop. It also checks for a `submit_text_input` sync method first.

3. `d:/talksync/talksync/ui/main_window.py` — `_on_status()` callback (around line 453) now accepts `(self, message: str, category: str = "info")` signature. `_on_latency()` callback now handles both `float` and `dict` latency data formats.

## Follow-up — 2026-07-23T04:50:32Z

TalkSync AI is a real-time speech-to-speech translation desktop application designed for online meetings (Google Meet, Zoom, Teams). It captures both microphone audio (user) and computer audio (remote meeting participants), automatically recognizes spoken languages, translates speech in real time, and synthesizes natural audio output using Sarvam AI (for Hindi/Indic) and Piper/Kokoro (for English).

Working directory: d:/talksync/talksync
Integrity mode: development

## Requirements

### R1. Online Meeting Computer Audio Capture & Language Recognition

- **Dual Audio Capture**: Capture microphone input (user) and computer system audio (remote meeting participants via WASAPI Loopback / Stereo Mix / VB-Cable).
- **Auto Language Detection**: Utilize Whisper STT automatic language detection to identify spoken language per audio segment (`en`, `hi`, etc.).
- **Meeting Audio Loopback**: When remote participants speak in a Google Meet or Zoom call, their audio is processed, recognized, translated into the user's language, and displayed in **Panel B (Right Card)**.

### R2. Speech-to-Speech TTS Engine Routing

- **Hindi / Indic Target Speech**: Synthesize speech using Sarvam AI TTS API (`sarvam_voice`, `hi-IN`). If offline or without API key, fallback seamlessly to local TTS or SAPI5.
- **English Target Speech (Hindi -> English Translation)**: Synthesize high-quality English speech using local Piper TTS (`en_US-lessac-medium` / Kokoro) or SAPI5.
- **Virtual Microphone Output**: Stream translated audio into VB-Cable / Virtual Microphone so meeting software participants can hear the broadcasted voice.

### R3. Dual-Panel Real-Time Visual Display

- **Panel A (Left Card — My Side)**: Renders user's microphone speech and typed text input in screenshot format:
  - Timestamp (`00:03`) at top left
  - User's original text
  - Target translated text directly below it
- **Panel B (Right Card — Other Person / Meeting Participant)**: Renders remote meeting speech:
  - Timestamp (`00:03`) at top left
  - Remote speaker's original text
  - User translated text directly below it

### R4. Text Input Mode & Control System

- Typed text in the bottom input panel bypasses ASR/VAD, translates immediately, synthesizes TTS audio, and displays in Panel A.
- Header toolbar controls (Audio Source popup, Keywords/AI Assistant, CC Subtitles, History Dashboard, Play/Stop toggle) are fully operational.

### R5. Complete App Stability & Zero Traceback Guarantee

- Zero runtime exceptions, thread deadlocks, or unhandled logging errors.
- Ensure all Python imports, sounddevice streams, and background threads start and stop cleanly.

## Key Technical Context

- **Main entry point**: `main.py` launching `MainWindow(pipeline, settings)`.
- **Pipeline backend**: `app/pipeline.py` managing `audio_queue`, `stt_queue`, `translation_queue`, `tts_queue`.
- **Audio Services**: `services/audio/input.py` (mic + loopback capture), `services/audio/output.py` (speaker + virtual mic output).
- **STT**: `services/stt/faster_whisper.py` (`Systran/faster-whisper-small` CUDA float16).
- **Translation**: `services/translation/argos.py` & `deepl.py`.
- **TTS**: `services/tts/piper.py` (Piper English) and `services/tts/sarvam.py` (Sarvam Indic) routed by `services/tts/router.py`.

## Acceptance Criteria

### Meeting Translation & Audio
- [ ] App captures computer audio (system loopback) and translates remote speaker audio into Panel B
- [ ] User speech (mic) and typed text translate into target language and render in Panel A
- [ ] English translations are synthesized via Piper TTS / Kokoro / SAPI5
- [ ] Hindi/Indic translations are synthesized via Sarvam TTS (with graceful local fallback)

### UI & Branding
- [ ] Window title and branding displayed as **TalkSync AI**
- [ ] Panel A tag shows `en → hi >` and Panel B tag shows `hi → en >`
- [ ] Audio level meter animates live with microphone input


