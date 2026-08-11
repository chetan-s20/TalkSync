# STT and Translation Pipeline Analysis Report — TalkSync AI

**Working Directory**: `d:\talksync\talksync`  
**Explorer Agent**: Explorer 2 (`stt_trans`)  
**Date**: 2026-08-07  

---

## Executive Summary

This report presents a comprehensive investigation into the Speech-to-Text (STT) and Translation pipeline of TalkSync AI. The investigation identified the root cause of why transcription and translation are not triggered when VAD detects speech in the PyWebView UI, along with multiple contributing issues in event loop management, API key error handling, fallback engine selection, VAD frame buffering, and queue processing.

---

## 1. Analysis of Pipeline Workers (STT & Translation)

The processing pipeline in `app/pipeline.py` relies on 5 concurrent asyncio background workers launched during `Pipeline.start()` (lines 175–186):

```python
tasks = [
    asyncio.create_task(self._vad_worker()),
    asyncio.create_task(self._stt_worker()),
    asyncio.create_task(self._translation_worker()),
    asyncio.create_task(self._tts_worker()),
    asyncio.create_task(self._stats_worker()),
]
```

### 1.1 Audio Capture & VAD Worker (`_capture_worker` & `_vad_worker`)
- **`_capture_worker(source)`** (`app/pipeline.py:309-361`): Reads chunks from `SoundDeviceInput` (`mic` or `loopback`). Applies gain (`_MIC_GAIN=1.0`, `_LOOPBACK_GAIN=1.0`), runs noise gate filtering, computes RMS, emits `on_audio_level` callbacks for mic input, and pushes `AudioChunk` objects into `self.audio_queue` (`maxsize=1000`).
- **`_vad_worker()`** (`app/pipeline.py:363-425`): Consumes chunks from `audio_queue`. Passes audio to `SileroVAD.process(chunk)` (`vad/silero_vad.py:106`), which evaluates 512-sample frames. The result is passed to `SpeechTracker.update(is_speech)` (`app/pipeline_state.py:21`).
- **Buffer Finalization**: When speech ends (`tracker.just_deactivated`), or buffer reaches capacity (`buf.is_full`), or periodic interval elapses (`FEED_INTERVAL_S=0.3s`), `buf.finalize()` converts buffered audio to `SttJob` and enqueues it to `self.stt_queue` (`maxsize=256`).

### 1.2 STT Worker (`_stt_worker`)
- **`_stt_worker()`** (`app/pipeline.py:427-549`): Dequeues `SttJob` from `stt_queue`.
- **STT Engine Execution**: Calls `self._stt.transcribe(job.audio, is_final=job.is_final, language=lang_code, initial_prompt=custom_prompt)`.
- **Quality & Gating Filters**:
  1. *Language Enforcement Filter* (`app/pipeline.py:478-487`): Drops segment if detected language is not in allowed pair (`{source_lang, target_lang}`).
  2. *Confidence Gate* (`app/pipeline.py:494-495`): Drops segment if `result.confidence < 0.4`.
  3. *Minimum Word Count Filter* (`app/pipeline.py:498-502`): Drops segment if `len(words) < min_word_count`.
  4. *Duplicate Final Text Filter* (`app/pipeline.py:514-516`): Skips duplicate consecutive final transcriptions.
- **Callback & Enqueueing**: Invokes `self.on_transcription(result)`. If `job.is_final`, calls `_enqueue_translation_segment(segment)` (`app/pipeline.py:551`), which prunes obsolete partial segments and enqueues the segment into `self.translation_queue` (`maxsize=256`).

### 1.3 Translation Worker (`_translation_worker`)
- **`_translation_worker()`** (`app/pipeline.py:591-621`): Dequeues `TranscriptionSegment` from `translation_queue`. Checks if a partial segment has been superseded by a newer partial segment in the queue.
- **Routing & Execution (`_translate_and_route`)** (`app/pipeline.py:623-779`):
  1. Validates detected language using `LanguageValidator` (`services/translation/language_validator.py`).
  2. Applies domain keyword spelling corrections (`utils/keywords.py`) to original text before translation.
  3. Calls `self._translator.translate(orig_text, src, tgt, context=context)` with a 5.0s timeout (2.0s for partials).
  4. Applies AI assistant keyword post-processing on translated text.
  5. Appends segment to context engine history (`ContextEngine`).
  6. Invokes `self.on_translation(result)` callback.
  7. Persists history block to DB session (`self._db_blocks`).
  8. If `enqueue_tts` and speaker enabled (`tts_enabled_a`/`b`), puts `TranslationResult` into `self.tts_queue` (`maxsize=256`).

---

## 2. Root Cause Analysis: Why Transcription & Translation are Not Triggered on VAD Speech Detection

### 2.1 Primary Root Cause: Event Loop Lifecycle Destruction in PyWebView Bridge

- **File**: `app/bridge.py`
- **Location**: `ApiBridge.start_session()` (lines 117–118) and `ApiBridge._run_async()` (lines 623–640)

#### Mechanism of Failure:
1. When the PyWebView UI invokes `start_session()`, PyWebView executes the Python call on a separate worker thread managed by PyWebView.
2. `start_session()` calls `self._run_async(pipeline.start(source, target, loopback=use_loopback, text_mode=text_mode))`.
3. Inside `_run_async()`:
   ```python
   try:
       loop = asyncio.get_running_loop()
       fut = asyncio.run_coroutine_threadsafe(coro_or_func, loop)
       return fut.result(timeout=15.0)
   except RuntimeError:
       try:
           loop = asyncio.new_event_loop()
           res = loop.run_until_complete(coro_or_func)
           loop.close()  # <-- CRITICAL BUG!
           return res
       except Exception as err:
           ...
   ```
4. Because the PyWebView worker thread has no running asyncio event loop, `asyncio.get_running_loop()` raises `RuntimeError`.
5. `_run_async()` creates a temporary event loop (`loop = asyncio.new_event_loop()`) and calls `loop.run_until_complete(pipeline.start(...))`.
6. `Pipeline.start()` initializes model references, creates internal queues, and launches worker background tasks via `asyncio.create_task(...)`:
   ```python
   tasks = [
       asyncio.create_task(self._vad_worker()),
       asyncio.create_task(self._stt_worker()),
       asyncio.create_task(self._translation_worker()),
       asyncio.create_task(self._tts_worker()),
       asyncio.create_task(self._stats_worker()),
   ]
   self._tasks = tasks
   ```
   `Pipeline.start()` then returns `None`.
7. `loop.run_until_complete()` finishes immediately because `start()` has returned.
8. `_run_async()` immediately executes `loop.close()`.
9. **Closing the event loop cancels/destroys the event loop and kills all background worker tasks (`_vad_worker`, `_stt_worker`, `_translation_worker`, `_tts_worker`, `_capture_worker`) instantly.**
10. Consequently, when VAD detects speech and pushes audio jobs into `stt_queue`, there is **no running event loop and no active worker task** to dequeue from `stt_queue` or `translation_queue`. The pipeline is completely dead on arrival.

---

## 3. Subsystem Issues: Exceptions, Queue Stalls, API Keys, and Blocking

### 3.1 DeepL Failure Exception Swallowing & Fallback Bypass
- **Files**: `services/translation/deepl.py` (lines 60–62) and `services/translation/factory.py` (lines 28–35)
- **Problem**: In `DeepLTranslator.start()`:
  ```python
  except Exception as e:
      logger.warning(f"DeepL init failed: {e}")
      self._client = None
  ```
  `DeepLTranslator.start()` catches all initialization exceptions (e.g. invalid API key `0039cbf9-c4aa-48b5-b1c6-35c5c1e55abf:fx` in `.env` or unreachable proxy `http://192.168.0.1:8090`) and swallows them, setting `self._client = None` without re-raising.
- **Impact**: `TranslationFactory.create()` expects `start()` to raise an exception in order to trigger fallback to `ArgosTranslator`. Because `DeepLTranslator.start()` returns normally without error, `TranslationFactory` selects `DeepLTranslator` as primary. When `translate()` is called, `DeepLTranslator` sees `self._client is None` and returns `translated_text = original_text` (passthrough untranslated text). Local `ArgosTranslator` is never initialized as fallback, causing all translations to remain untranslated.

### 3.2 OpenAI STT Start Failure Prevents Pipeline Launch
- **Files**: `services/stt/openai_stt.py` (lines 86–122) and `app/application.py` (lines 70–84)
- **Problem**: In `.env`, `talksync_stt_engine=openai` and an invalid/expired key is set (`openai_api_key=sk-proj-...`). When `OpenAISTT` is selected, `OpenAISTT.start()` makes a network request to `self._client.models.list()`. If authentication fails or network is offline, `OpenAISTT.start()` raises `AuthenticationError`/`RuntimeError`.
- **Impact**: In `Pipeline.start()`:
  ```python
  for svc_name, svc in [("VAD", self._vad), ("STT", self._stt), ...]:
      await svc.start()
  ```
  `Pipeline.start()` catches this exception, logs `"Pipeline start failed"`, calls `await self.stop()`, and re-raises. The pipeline completely fails to start. There is no automatic runtime fallback from `OpenAISTT` to `FasterWhisperSTT` during `Pipeline.start()`.

### 3.3 VAD Speech Onset Truncation
- **Files**: `app/pipeline_state.py` (lines 25–26) and `app/pipeline.py` (lines 386–393)
- **Problem**: `SpeechTracker.update(is_speech)` requires `SPEECH_FRAMES_TO_ACTIVATE = 2` consecutive speech frames before `_speech_active` becomes `True`.
  On speech frame 1: `is_active = False` and `just_activated = False`.
  Therefore, audio frame 1 is **not appended to `buf`**.
- **Impact**: The initial 30ms–50ms onset of spoken speech (e.g. initial consonants / plosives) is dropped. In STT models (Whisper), dropping initial consonants causes misrecognition or dropped initial words.

### 3.4 Queue Stalls due to Sequential Blocking Translation
- **File**: `app/pipeline.py` (lines 591–714)
- **Problem**: `_translation_worker` dequeues segments sequentially and awaits `_translator.translate(...)`. For partial segments sent every 0.3s, if translation takes 0.5s–2.0s per request, partial segments accumulate in `translation_queue`. Although obsolete partials are pruned when dequeued, the sequential blocking await on prior partial translations delays the processing of the final transcript segment by multiple seconds.

---

## 4. Test Suite, Mock APIs, and Execution Entry Points

### 4.1 Entry Points
1. **PyWebView GUI Entry Point**: `main.py` -> `WebviewWindowManager.create_window()` -> `ApiBridge` -> `Application.build_pipeline()`.
2. **Tkinter GUI Entry Point**: `ui/main_window.py` -> `_run_pipeline_thread()` (spawns dedicated event loop thread).

### 4.2 Existing STT & Translation Test Files
- **`tests/test_stt.py`**: Unit tests for `BaseSTT`, `FasterWhisperSTT` (mocked `WhisperModel`, CPU fallback, beam size, prompt, VAD filter, logprob, word count filters).
- **`tests/test_openai_stt.py`**: Unit tests for `OpenAISTT` (mocked `AsyncOpenAI`, WAV encoding, highpass filter, AGC, retry logic, refinement).
- **`tests/test_stt_refinement.py`**: Unit tests for GPT-4o-mini post-processing refinement prompt.
- **`tests/test_translation.py`**: Unit tests for `BaseTranslator`, `ArgosTranslator` (mocked argostranslate, vocabulary mapping), `DeepLTranslator` (mocked deepl client, proxy checks), `TranslationFactory` (fallback chain), `LanguageValidator`, `ContextEngine`.
- **`tests/unit/test_partial_translation.py`**: Unit tests for partial segment translation routing.
- **`tests/unit/test_translation_queue_pruning.py`**: Unit tests for pruning obsolete partial segments in `translation_queue`.
- **`tests/integration/test_full_pipeline.py`**: Tier 3 integration test for complete audio-to-translation pipeline using mocks.
- **`tests/integration/test_webview_pipeline_bridge.py`**: Integration tests verifying PyWebView `ApiBridge` callbacks and state handling with mocked pipeline.

---

## 5. Summary of Findings & Recommended Fixes (Read-Only Proposal)

| Area | Current Bug / Weakness | Impact | Proposed Fix |
|---|---|---|---|
| **Event Loop** | `ApiBridge._run_async` runs `loop.close()` immediately after `pipeline.start()` returns | Kills all background workers (`_vad_worker`, `_stt_worker`, `_translation_worker`); pipeline is dead on arrival | Maintain a dedicated persistent asyncio event loop thread in `ApiBridge` / `Application` for PyWebView session lifecycle |
| **Translation Engine** | `DeepLTranslator.start()` catches all init errors, sets `_client=None` without raising | Bypasses `TranslationFactory` fallback to `ArgosTranslator`; returns untranslated text | Raise `RuntimeError` in `DeepLTranslator.start()` when init fails so `TranslationFactory` falls back to Argos/Dummy |
| **STT Engine** | `OpenAISTT.start()` raises on bad API key or offline network | Prevents `Pipeline.start()` from completing; no fallback to local Whisper | Catch init failure in `Application.build_pipeline()` or `Pipeline.start()` and fall back to `FasterWhisperSTT` |
| **VAD Buffering** | `SpeechTracker` skips frame 1 of speech before activation | Drops initial 30ms–50ms speech onset consonants | Include frame 1 when `is_speech` is detected or add pre-roll buffer ring |
