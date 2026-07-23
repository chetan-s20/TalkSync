## 2026-07-23T10:31:37Z
You are Worker 2 executing Milestone 2: Dual Audio Capture & Auto Language Detection (Requirement R1) for TalkSync AI.
Your working directory is `d:/talksync/talksync/.agents/teamwork_preview_worker_m2`.
Please create your working directory if needed.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your Tasks for Milestone 2 (Requirement R1):

1. **Dual Audio Capture & Loopback Service (`services/audio/input.py`, `services/audio/loopback.py`)**:
   - In `services/audio/loopback.py`: Add robust resolution for system audio loopback devices (WASAPI Loopback, Stereo Mix, VB-Cable) with clean fallback and descriptive error messages if no loopback device is found.
   - In `services/audio/input.py`: Log warnings on queue overflow instead of silent `pass`. Ensure audio chunks carry `source: str = "mic"` or `"loopback"`.

2. **Whisper Automatic Language Detection (`services/stt/faster_whisper.py`, `app/interfaces.py`, `core/interfaces.py`)**:
   - In `services/stt/faster_whisper.py`:
     - Normalize language argument `"auto"`/`"AUTO"`/`"automatic"` to `None` when passing to `WhisperModel.transcribe()`.
     - Extract `info.language` and `info.language_probability`.
     - Populate `TranscriptionSegment` with `language=detected_lang`, `language_probability=lang_prob`, and `confidence=lang_prob`.
   - In `app/interfaces.py` and `core/interfaces.py`:
     - Add `language_probability: float = 0.0` to `TranscriptionSegment` dataclass.

3. **Pipeline Queue Routing & Panel B Loopback (`app/pipeline.py`, `ui/main_window.py`, `ui/widgets/transcript_panel.py`)**:
   - In `app/pipeline.py`:
     - In `_stt_worker`: Attach `result.input_source = input_src` (`"COMPUTER_AUDIO"` if `job.source == "loopback"` else `"VOICE"`) **before** invoking `self.on_transcription(result)`.
     - In partial STT translation callback, pass `input_source=input_src` instead of hardcoded `"VOICE"`.
     - In `_translate_and_route()`:
       - When `self._source_lang == "AUTO"`, resolve `src` dynamically from Whisper's `detected_lang` (e.g. `"EN"`, `"HI"`).
       - When `segment.input_source in ("COMPUTER_AUDIO", "LOOPBACK")`, set default translation direction `src = target_lang`, `tgt = source_lang` (e.g., remote speech translated into user's language).
   - In `ui/main_window.py`:
     - In `_on_translation(self, result)`: Check `if src in ("LOOPBACK", "COMPUTER_AUDIO"):` and route to `self.panel_b.append_message(original=orig, translated=trans, input_source=src)`, else `self.panel_a.append_message(...)`.
     - In `_on_transcription(self, segment)`: Route live transcription updates to `self.panel_b.update_streaming_text(...)` or `self.panel_a.update_streaming_text(...)`.
   - In `ui/widgets/transcript_panel.py`:
     - In `append_message`: Render timestamp and input source badge (e.g. `[MIC]`, `[LOOPBACK]`, `[TEXT]`).
     - Implement `update_streaming_text(self, original: str, translated: str = "")` to support live in-progress streaming updates without duplicating text entries.

4. **Verification & Tests**:
   - Run `pytest` and ensure all unit tests pass.
   - Write a detailed `handoff.md` report in `d:/talksync/talksync/.agents/teamwork_preview_worker_m2/handoff.md` detailing implemented changes, line numbers, test outputs, and verification.

Keep your message brief and point to your `handoff.md` report.
