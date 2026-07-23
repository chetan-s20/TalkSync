# Handoff Report — Whisper Automatic Language Detection (Milestone 2 Requirement R1)

## 1. Observation

### File 1: `services/stt/faster_whisper.py`
- **Lines 53, 90, 109**: `self._language` is initialized to `None` and assigned when `start(language)` is called.
- **Lines 122–130**: `transcribe()` signature:
  ```python
  def transcribe(self, audio: Any, sample_rate: Any = 16000, is_final: bool = True, language: Optional[str] = None, initial_prompt: Optional[str] = None, **kwargs) -> Any:
  ```
- **Line 136**: `lang = language if language is not None else self._language`
- **Line 138**: `segments_gen, info = self._model.transcribe(audio, beam_size=..., language=lang, ...)`
- **Lines 170–176**:
  ```python
  detected_lang = getattr(info, "language", "") or ""
  confidence = max(-max_logprob, 0.0) if max_logprob > -999 else 0.0
  return TranscriptionSegment(
      text=text, is_final=is_final,
      start_time=datetime.now(), end_time=datetime.now(),
      language=detected_lang, confidence=confidence,
  )
  ```
- **Key Findings in `faster_whisper.py`**:
  1. `faster-whisper` library's `WhisperModel.transcribe()` populates `info.language` (e.g. `'en'`, `'hi'`) and `info.language_probability` (float probability between `0.0` and `1.0`).
  2. When `language` or `self._language` is string `"auto"` or `"AUTO"`, it is passed directly to `WhisperModel.transcribe(language="auto")`. `faster-whisper` expects `language=None` to enable auto-detection. Passing `"auto"` string leads to invalid language lookup error or failure in `faster-whisper`.
  3. `getattr(info, "language", "")` is extracted, but `info.language_probability` is completely ignored. Instead, `confidence` is populated with `max(-max_logprob, 0.0)` (STT speech logprob), which is not the language detection probability.

### File 2: STT Manager Status (`services/stt/manager.py`)
- **Status**: `services/stt/manager.py` does not currently exist in the repository tree.
- **Current Architecture**: STT model initialization and transcription requests are currently handled directly within `Pipeline` (`app/pipeline.py`) or `PipelineManager` (`core/pipeline_manager.py`).
- **`core/pipeline_manager.py` Observation**:
  - Line 149: `await self.stt.start(language=None)` sets STT to auto-detect by default.
  - Lines 423–425: `result = await self.stt.transcribe(audio, is_final=is_final)` retrieves `TranscriptionSegment`.
  - Lines 497–516: In `_translate_and_route()`, `detected = (segment.language or "").strip()` and `confidence = getattr(segment, "confidence", 0.0)`.

### File 3: Data Structures (`app/interfaces.py` & `core/interfaces.py`)
- **`TranscriptionSegment`** (lines 20–28 in `app/interfaces.py` & lines 25–33 in `core/interfaces.py`):
  ```python
  @dataclass
  class TranscriptionSegment:
      text: str
      is_final: bool
      start_time: datetime
      end_time: datetime
      language: str
      confidence: float
      input_source: str = "VOICE"
  ```
- **Key Findings**:
  - The dataclass uses `language: str` to hold ISO codes (e.g., `'en'`).
  - Lacks an explicit `language_probability: float` field, causing `confidence` (speech logprob) to be mistakenly used by `LanguageValidator` for language confidence checks.

### File 4: `app/pipeline.py`
- **Line 91**: `self._source_lang = source_lang.upper()` (e.g. `"AUTO"` or `"EN"`).
- **Line 120**: `await self._stt.start()` is called without language parameter (defaulting to `None`).
- **Lines 256–296 (`_stt_worker`)**:
  - Line 268: `result = await self._stt.transcribe(job.audio, is_final=job.is_final)`
  - Line 286: `input_src = "COMPUTER_AUDIO" if job.source == "loopback" else "VOICE"`
  - Line 287–292: Constructs `TranscriptionSegment` with `language=result.language or ""`.
- **Lines 333–351 (`_translate_and_route`)**:
  ```python
  src = self._source_lang
  tgt = self._target_lang
  detected = (segment.language or "").strip()
  confidence = segment.confidence

  if self._translation_mode == "two_way" and detected:
      from utils.languages import get_language_code
      det_code = (get_language_code(detected) or detected).upper()
      src_code = self._source_lang.upper()
      tgt_code = self._target_lang.upper()
      if det_code in (src_code, tgt_code):
          validated = self._lang_validator.validate(
              detected_lang=det_code, confidence=confidence,
              source_lang=src_code, target_lang=tgt_code,
              context_engine=self._context_engine if is_final else None,
          )
          if validated == tgt_code:
              src, tgt = tgt_code, src_code
  ```
- **Key Findings in `app/pipeline.py`**:
  1. When `self._source_lang == "AUTO"`, `src_code` is `"AUTO"`. The condition `if det_code in ("AUTO", tgt_code)` evaluates to `False` for valid detected languages like `"EN"`.
  2. `src` remains `"AUTO"`, which is passed to `self._translator.translate(segment.text, "AUTO", tgt)`. Translation engines (Argos, Marian, etc.) fail when given `"AUTO"` as a source language string.
  3. Mic audio (`input_source="VOICE"`) and Meeting Loopback audio (`input_source="COMPUTER_AUDIO"`) are both transcribed per segment by `_stt_worker`, but per-segment detected language `det_code` is not resolved to `src` when `source_lang="AUTO"`.

---

## 2. Logic Chain

1. **Observation**: Faster-Whisper's `info` object contains `info.language` and `info.language_probability`.
   - **Reasoning**: `FasterWhisperSTT.transcribe()` must convert string `"auto"`/`"AUTO"` to `None` before invoking `self._model.transcribe(language=...)`.
   - **Reasoning**: `info.language_probability` must be captured and populated into `TranscriptionSegment` so `LanguageValidator.validate()` receives accurate probability metrics (0.3/0.6 thresholds) rather than speech logprob.

2. **Observation**: `TranscriptionSegment` definition in `app/interfaces.py` and `core/interfaces.py`.
   - **Reasoning**: Adding `language_probability: float = 0.0` explicitly preserves language confidence separate from acoustic segment confidence.

3. **Observation**: In `app/pipeline.py`, `_translate_and_route()` leaves `src = "AUTO"` when `self._source_lang == "AUTO"`.
   - **Reasoning**: Translation services require concrete ISO codes (`"EN"`, `"HI"`). When `self._source_lang == "AUTO"`, `src` must be dynamically resolved to `det_code` (Whisper's detected language).
   - **Reasoning**: For mic vs loopback audio, each audio chunk is independently processed by `_stt_worker` and assigned its own detected language, allowing simultaneous multi-lingual audio processing if `src` is dynamically updated per segment.

---

## 3. Caveats

- `services/stt/manager.py` is currently missing from the repository. The proposed modifications include specifications for creating this manager module.
- External translation engines (e.g. DeepL vs Argos) have varying ISO language code expectations (2-letter ISO 639-1 vs DeepL variants). `utils/languages.py` functions like `normalize_lang()` and `get_language_code()` should be used.
- All investigation was performed read-only without modifying non-agent files.

---

## 4. Conclusion

Whisper automatic language detection contains 4 main structural defects:
1. `services/stt/faster_whisper.py` does not convert `"auto"`/`"AUTO"` to `None` for `faster_whisper`.
2. `services/stt/faster_whisper.py` discards `info.language_probability`.
3. `app/interfaces.py` and `core/interfaces.py` `TranscriptionSegment` does not expose `language_probability`.
4. `app/pipeline.py` `_translate_and_route()` fails to resolve `src` from detected language when `source_lang="AUTO"`, passing string `"AUTO"` to translator.

---

## 5. Recommended Code Modifications

### A. Modify `services/stt/faster_whisper.py`
In `transcribe()` (lines 136–176):
```python
# 1. Normalize auto language string to None
lang_input = language if language is not None else self._language
if isinstance(lang_input, str) and lang_input.lower() in ("auto", "automatic"):
    lang = None
else:
    lang = lang_input

segments_gen, info = self._model.transcribe(
    audio,
    beam_size=self._beam_size,
    language=lang,
    vad_filter=self._vad_filter,
    no_speech_threshold=self._no_speech_threshold,
    log_prob_threshold=self._log_prob_threshold,
    compression_ratio_threshold=self._compression_ratio_threshold,
    initial_prompt=prompt,
)
...
# 2. Extract detected language and language_probability
detected_lang = getattr(info, "language", "") or ""
lang_prob = float(getattr(info, "language_probability", 0.0) or 0.0)

return TranscriptionSegment(
    text=text, is_final=is_final,
    start_time=datetime.now(), end_time=datetime.now(),
    language=detected_lang,
    confidence=lang_prob if lang is None else max(-max_logprob, 0.0),
    language_probability=lang_prob,
)
```

### B. Update Data Structures in `app/interfaces.py` & `core/interfaces.py`
Add `language_probability` field to `TranscriptionSegment`:
```python
@dataclass
class TranscriptionSegment:
    text: str
    is_final: bool
    start_time: datetime
    end_time: datetime
    language: str
    confidence: float
    input_source: str = "VOICE"
    language_probability: float = 0.0
```

### C. Update `app/pipeline.py`
In `_translate_and_route()` (lines 333–351):
```python
src = self._source_lang
tgt = self._target_lang
detected = (segment.language or "").strip()
confidence = getattr(segment, "language_probability", segment.confidence)

if detected:
    from utils.languages import get_language_code
    det_code = (get_language_code(detected) or detected).upper()
    
    # Handle explicit source_lang="AUTO"
    if src in ("AUTO", "AUTOMATIC"):
        if det_code:
            src = det_code
        else:
            src = "EN"  # Fallback default
    elif self._translation_mode == "two_way":
        src_code = self._source_lang.upper()
        tgt_code = self._target_lang.upper()
        if det_code in (src_code, tgt_code):
            validated = self._lang_validator.validate(
                detected_lang=det_code, confidence=confidence,
                source_lang=src_code, target_lang=tgt_code,
                context_engine=self._context_engine if is_final else None,
            )
            if validated == tgt_code:
                src, tgt = tgt_code, src_code
```

### D. Create `services/stt/manager.py` (New File Recommendation)
Create `STTManager` to wrap STT engines:
```python
from typing import Optional, Any
from app.interfaces import BaseSTT, TranscriptionSegment
from services.stt.faster_whisper import FasterWhisperSTT

class STTManager:
    def __init__(self, settings: Any = None):
        self._stt: BaseSTT = FasterWhisperSTT(settings=settings)
        
    async def start(self, language: Optional[str] = None) -> None:
        await self._stt.start(language=language)
        
    async def stop(self) -> None:
        await self._stt.stop()
        
    async def transcribe_segment(self, audio: Any, is_final: bool = True, language: Optional[str] = None) -> TranscriptionSegment:
        return await self._stt.transcribe(audio, is_final=is_final, language=language)
```

---

## 6. Verification Method

1. **Unit Tests Verification**:
   Execute `pytest tests/test_stt.py` using `run_command`.
2. **Inspection Verification**:
   Check that `info.language` and `info.language_probability` are correctly forwarded into `TranscriptionSegment`.
3. **Pipeline End-to-End Test**:
   Pass `source_lang="auto"` in `Pipeline.start("auto", "hi")` and verify `_translate_and_route` maps `src` to Whisper's detected language code (e.g. `"EN"`) rather than `"AUTO"`.
