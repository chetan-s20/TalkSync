# Handoff Report — Explorer 3 (Milestone 2: Requirement R1 — Meeting Audio Loopback to Panel B)

## 1. Observation

Direct examination of `talksync/app/pipeline.py`, `talksync/ui/main_window.py`, and `talksync/ui/widgets/transcript_panel.py` reveals the following exact code states:

### 1.1 `talksync/app/pipeline.py`
- **Lines 148–152**: Audio capture tasks launch separate workers for `"mic"` and `"loopback"`:
  ```python
  if should_capture:
      if not text_mode:
          tasks.append(asyncio.create_task(self._capture_worker("mic")))
      if loopback:
          tasks.append(asyncio.create_task(self._capture_worker("loopback")))
  ```
- **Line 198**: `_capture_worker` tags audio chunks with `chunk.source = source` (`"mic"` or `"loopback"`).
- **Line 286**: In `_stt_worker`, for final STT results, input source is mapped to string `"COMPUTER_AUDIO"` for loopback:
  ```python
  input_src = "COMPUTER_AUDIO" if job.source == "loopback" else "VOICE"
  ```
- **Lines 277–280**: In `_stt_worker`, `on_transcription(result)` callback receives `result` (`TranscriptionSegment`) **before** `job.source` (`"mic"` / `"loopback"`) or `input_src` is attached:
  ```python
  if self.on_transcription:
      try:
          self.on_transcription(result)
      except Exception:
          pass
  ```
  `result.input_source` remains defaulted to `"VOICE"`.
- **Lines 301–307**: In `_stt_worker`, partial STT results pass a hardcoded `input_source="VOICE"` to `on_translation`:
  ```python
  if self.on_translation:
      try:
          self.on_translation(TranslationResult(
              original_text=accumulated, translated_text="...",
              source_lang=self._source_lang, target_lang=self._target_lang,
              is_final=False, input_source="VOICE",
          ))
      except Exception:
          pass
  ```
- **Lines 334–335 & 383–388**: In `_translate_and_route`:
  ```python
  src = self._source_lang
  tgt = self._target_lang
  ```
  Translation direction defaults to `source_lang -> target_lang` regardless of whether input source is `"mic"` or `"COMPUTER_AUDIO"` (loopback), unless two-way language detection succeeds in swapping them.

### 1.2 `talksync/ui/main_window.py`
- **Line 460**: `_on_transcription` is an unhandled stub:
  ```python
  def _on_transcription(self, segment) -> None:
      pass
  ```
- **Lines 463–472**: `_on_translation` performs routing based on string comparison `str(src).upper() == "LOOPBACK"`:
  ```python
  def _on_translation(self, result) -> None:
      orig = getattr(result, "original_text", "")
      trans = getattr(result, "translated_text", "")
      src = getattr(result, "input_source", "VOICE")

      if str(src).upper() == "LOOPBACK":
          self.after(0, lambda: self.panel_b.append_message(original=orig, translated=trans, input_source=src))
      else:
          self.after(0, lambda: self.panel_a.append_message(original=orig, translated=trans, input_source=src))
  ```
  Because `pipeline.py` outputs `input_source = "COMPUTER_AUDIO"`, `str("COMPUTER_AUDIO").upper() == "LOOPBACK"` evaluates to `False`. Thus, loopback messages are incorrectly sent to `self.panel_a` (Panel A) instead of `self.panel_b` (Panel B).

### 1.3 `talksync/ui/widgets/transcript_panel.py`
- **Lines 146–158**: `append_message` signature and implementation:
  ```python
  def append_message(self, original: str, translated: str, input_source: str = "VOICE", timestamp: str = "") -> None:
      raw_text = self.textbox._textbox

      if not timestamp:
          from datetime import datetime
          timestamp = datetime.now().strftime("%M:%S")

      raw_text.insert("end", f"{timestamp}\n", "timestamp")
      if original:
          raw_text.insert("end", f"{original}\n\n", "original")
      if translated:
          raw_text.insert("end", f"{translated}\n\n", "translated")
      self.textbox.see("end")
  ```
  - `input_source` parameter is received but unused; no badge or visual indicator is rendered in the card.
  - No mechanism exists to update/replace streaming in-progress text (`is_final=False`), leading to redundant entries if partial translations are appended.

---

## 2. Logic Chain

1. **Routing Failure to Panel B**:
   - `_capture_worker("loopback")` sets `chunk.source = "loopback"`.
   - `_vad_worker` creates an `SttJob` with `job.source = "loopback"`.
   - `_stt_worker` converts `job.source == "loopback"` to `input_src = "COMPUTER_AUDIO"` for `TranscriptionSegment`.
   - `_translation_worker` forwards `result.input_source = "COMPUTER_AUDIO"`.
   - `MainWindow._on_translation` evaluates `if str(src).upper() == "LOOPBACK":`.
   - Since `"COMPUTER_AUDIO" != "LOOPBACK"`, the condition is NEVER met.
   - **Conclusion**: All loopback audio (remote meeting participant speech) is routed to **Panel A** (Left Card) instead of **Panel B** (Right Card).

2. **Partial/Streaming Speech Routing Bug**:
   - In `_stt_worker` (line 306), partial results pass `input_source="VOICE"` to `on_translation`.
   - As a result, even if loopback routing logic in `MainWindow` is fixed, partial loopback speech will still be routed to Panel A during active speech.

3. **Translation Language Direction Bug for Loopback**:
   - Microphone audio represents local user speech (`source_lang` -> `target_lang`).
   - Loopback audio represents remote meeting participants speaking the target/remote language (`target_lang` -> `source_lang`).
   - `_translate_and_route` defaults to `self._source_lang -> self._target_lang` for all segments. Loopback speech is thus translated in the wrong direction unless two-way auto-detection overrides it.

4. **Transcript Rendering Gaps**:
   - `TranscriptPanel.append_message` ignores `input_source`, omitting source visual badges (`[MIC]`, `[LOOPBACK]`, `[TEXT]`).
   - Absence of a partial text update method causes streaming partial updates to append stacked lines into the UI text box.

---

## 3. Caveats

- `test_pipeline.py` explicitly tests `input_source == "COMPUTER_AUDIO"`. Therefore, changing `pipeline.py` string output from `"COMPUTER_AUDIO"` to `"LOOPBACK"` would break existing unit tests. The ideal fix is for `MainWindow._on_translation` to check `str(src).upper() in ("LOOPBACK", "COMPUTER_AUDIO")` or normalize `input_source` handling across the application.
- Two-way translation mode (`self._translation_mode == "two_way"`) uses `LanguageValidator` and speech detection, which can dynamically adjust language pairs. However, explicit source-based default directions (`mic`: `source` -> `target`; `loopback`: `target` -> `source`) ensure deterministic behavior when language detection is disabled or uncertain.

---

## 4. Conclusion & Recommended Code Modifications

### 4.1 Fix Pipeline Routing (`talksync/app/pipeline.py`)

1. **Attach correct `input_source` before calling `on_transcription`** (Line 277):
   ```python
   # Line 277 in _stt_worker:
   input_src = "COMPUTER_AUDIO" if job.source == "loopback" else "VOICE"
   result.input_source = input_src
   if self.on_transcription:
       try:
           self.on_transcription(result)
       except Exception:
           pass
   ```

2. **Fix partial translation input source** (Line 306):
   ```python
   # Line 306 in _stt_worker:
   input_src = "COMPUTER_AUDIO" if job.source == "loopback" else "VOICE"
   if self.on_translation:
       try:
           self.on_translation(TranslationResult(
               original_text=accumulated, translated_text="...",
               source_lang=self._source_lang, target_lang=self._target_lang,
               is_final=False, input_source=input_src,
           ))
       except Exception:
           pass
   ```

3. **Set loopback translation direction defaults** in `_translate_and_route` (Lines 334–337):
   ```python
   # In _translate_and_route:
   if segment.input_source in ("COMPUTER_AUDIO", "LOOPBACK"):
       src = self._target_lang
       tgt = self._source_lang
   else:
       src = self._source_lang
       tgt = self._target_lang
   ```

### 4.2 Fix MainWindow Routing & Callbacks (`talksync/ui/main_window.py`)

1. **Fix `_on_translation` condition to handle `"COMPUTER_AUDIO"` & `"LOOPBACK"`** (Line 468):
   ```python
   def _on_translation(self, result) -> None:
       orig = getattr(result, "original_text", "")
       trans = getattr(result, "translated_text", "")
       src = str(getattr(result, "input_source", "VOICE")).upper()
       is_final = getattr(result, "is_final", True)

       if src in ("LOOPBACK", "COMPUTER_AUDIO"):
           self.after(0, lambda: self.panel_b.append_message(original=orig, translated=trans, input_source=src))
       else:
           self.after(0, lambda: self.panel_a.append_message(original=orig, translated=trans, input_source=src))

       if self.subtitle_overlay.is_visible:
           self.subtitle_overlay.update_text(orig, trans)
   ```

2. **Implement `_on_transcription` for live preview routing** (Line 460):
   ```python
   def _on_transcription(self, segment) -> None:
       text = getattr(segment, "text", "")
       src = str(getattr(segment, "input_source", "VOICE")).upper()
       if not text:
           return
       if src in ("LOOPBACK", "COMPUTER_AUDIO"):
           self.after(0, lambda: self.panel_b.update_streaming_text(original=text))
       else:
           self.after(0, lambda: self.panel_a.update_streaming_text(original=text))
   ```

### 4.3 Enhance TranscriptPanel Rendering (`talksync/ui/widgets/transcript_panel.py`)

1. **Render `input_source` badge in `append_message`** (Line 146):
   ```python
   def append_message(self, original: str, translated: str, input_source: str = "VOICE", timestamp: str = "") -> None:
       raw_text = self.textbox._textbox
       if not timestamp:
           from datetime import datetime
           timestamp = datetime.now().strftime("%H:%M:%S")

       badge_text = f"[{input_source.upper()}] " if input_source else ""
       raw_text.insert("end", f"{timestamp} {badge_text}\n", "timestamp")
       if original:
           raw_text.insert("end", f"{original}\n\n", "original")
       if translated:
           raw_text.insert("end", f"{translated}\n\n", "translated")
       self.textbox.see("end")
   ```

2. **Add `update_streaming_text` method** for active partial transcription updates.

---

## 5. Verification Method

1. **Unit Test Verification**:
   - Run existing unit tests:
     `pytest talksync/tests/test_pipeline.py`
     `pytest talksync/tests/test_translation.py`
2. **Integration Verification Command**:
   - Run test suite covering pipeline & callbacks:
     `pytest talksync/tests/`
3. **Manual / Mock Callback Verification**:
   - Instantiate `MainWindow` with a mock pipeline emitting `TranslationResult(..., input_source="COMPUTER_AUDIO")`.
   - Assert `panel_b.textbox.get("1.0", "end")` contains the translated text and `panel_a.textbox.get("1.0", "end")` remains empty.
