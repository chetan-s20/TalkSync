# Progress Log

Last visited: 2026-07-23T10:34:00Z

## Step 1: Context Recovery & Exploration
- Workspace and briefing initialized.
- Ran initial test suite (222 passed).

## Step 2: Implementation of Milestone 2 Tasks
- Dual Audio Capture & Loopback Service:
  - Updated `services/audio/loopback.py`: Added WASAPI loopback device discovery (`find_wasapi_loopback()`) and updated `find_loopback_device()` with logging and clear fallback/error handling.
  - Updated `services/audio/input.py`: Added warning logging on queue overflow instead of silent `pass` in `_make_callback()`, ensured audio chunks carry `source: str = "mic"` or `"loopback"`, updated loopback missing device error message.
- Whisper Automatic Language Detection:
  - Updated `app/interfaces.py` and `core/interfaces.py`: Added `language_probability: float = 0.0` to `TranscriptionSegment` dataclass.
  - Updated `services/stt/faster_whisper.py`: Normalized `"auto"`/`"AUTO"`/`"automatic"` language argument to `None` when invoking `WhisperModel.transcribe()`, extracted `info.language` and `info.language_probability`, and populated `TranscriptionSegment` with `language=detected_lang`, `language_probability=lang_prob`, and `confidence=lang_prob`.
- Pipeline Queue Routing & Panel B Loopback:
  - Updated `app/pipeline.py`: Attached `result.input_source = input_src` (`"COMPUTER_AUDIO"` if `job.source == "loopback"` else `"VOICE"`) before calling `on_transcription`, passed `input_source=input_src` in partial STT translation callback, resolved `src` dynamically from Whisper's `detected_lang` when `_source_lang == "AUTO"`, and set default translation direction for loopback audio (`COMPUTER_AUDIO`/`LOOPBACK`) as `src = target_lang`, `tgt = source_lang`.
  - Updated `ui/main_window.py`: Routed live streaming transcriptions and final translations with `src in ("LOOPBACK", "COMPUTER_AUDIO")` to `self.panel_b`, and mic/voice audio to `self.panel_a`.
  - Updated `ui/widgets/transcript_panel.py`: Rendered timestamp and input source badges (`[MIC]`, `[LOOPBACK]`, `[TEXT]`) in `append_message`, and implemented `update_streaming_text(self, original: str, translated: str = "")` to support live in-progress streaming updates without duplicating text entries.

## Step 3: Verification & Test Execution
- Added comprehensive unit tests in `tests/test_milestone2.py`.
- Ran `pytest` test suite: All 229 unit tests passed successfully.
- Written `handoff.md` report.
