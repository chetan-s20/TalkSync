# TalkSync AI — Test Suite Audit, Specification & Gap Analysis Report

**Agent**: `spec_miner_survey_3`  
**Date**: 2026-08-06  
**Target Repository**: `d:\talksync\talksync`  
**Scope**: Complete audit of existing test suite (53+ requirements baseline, 31 test files, 140+ executable test cases), test fixtures, standalone test scripts, gap analysis, and requirement-to-test mapping.

---

## 1. Executive Summary

TalkSync AI is a Python / `customtkinter` real-time bidirectional speech translation desktop application. A thorough inspection of the repository was performed to audit existing test files, test fixtures, test cases, and test runner execution paths.

### Key Audit Findings:
1. **Existing Test Suite**: The test suite under `tests/` contains **31 Python test files** plus **4 standalone runner scripts**, comprising **140+ executable test cases** covering audio capture, DSP normalizers, Silero VAD, FasterWhisper STT, OpenAISTT, Argos/DeepL translation, Piper/Sarvam TTS, SQLite history database, exporters, and UI transcript panels.
2. **Execution Results**: Running `pytest -v` completes successfully with functional accuracy and latency benchmarks passing (e.g. `test_english_pipeline_accuracy_and_latency` and `test_hindi_pipeline_accuracy_and_latency` PASS).
3. **Identified Coverage Gaps**:
   - **G1: LLM Refinement Retry Thresholds & Exception Recovery**: STT LLM refinement tests check success and hallucination filtering, but miss rate-limit (429) / timeout retry thresholds and raw fallback behavior.
   - **G2: Language Constraint Checks**: Only 1 test checks generic German dropping; missing configurable allowed language set validation and code-switching constraint checks.
   - **G3: UI Control State Transitions**: Mic mute toggle is tested, but Play, Stop, and Pipeline Initialize control transitions lack UI-level state machine tests.
   - **G4: Double Window Spawning Prevention**: ZERO existing tests verify that modal dialogs (Settings, History, About) or MainWindow cannot be spawned in duplicate.
   - **G5: Play Button Loading State `⏳`**: ZERO existing tests verify that clicking Play disables the button and sets the text to `⏳` during async pipeline initialization.
   - **G6: OpenAI STT Allowed Languages Filtering**: OpenAI STT tests cover silence RMS gating and API connection, but do not verify dropping segments in non-allowed languages at the service layer.
   - **G7: Standalone Script Verification**: Standalone scripts (`test_mic_capture.py`, `test_sarvam_network.py`, `test_openai_stt.py`) exist, but lack a non-interactive automated verifier script covering both mic level and bidirectional routing.

---

## 2. Test Suite Inventory

### 2.1 Test Files & Test Case Breakdown

| # | File Path | Test Class / Scope | Test Cases | Description / Purpose |
|---|-----------|-------------------|------------|-----------------------|
| 1 | `tests/conftest.py` | Pytest Fixtures | 11 Fixtures | Shared fixtures: `sample_audio`, `mock_settings`, `mock_pipeline`, `mock_device_list`, `temp_db_path`, etc. |
| 2 | `tests/fixtures/generate_fixtures.py` | Fixture Generator | 2 Functions | Generates synthetic 16kHz WAV audio samples (`english_sample.wav`, `hindi_sample.wav`) for benchmark tests. |
| 3 | `tests/integration/test_full_pipeline.py` | `TestFullPipeline` | 10 | End-to-end integration tests: audio-to-transcript flow, source tagging, 2-way translation, text input flow, pipeline restart, error recovery, latency measurement, multiple sources, history integration, SRT output. |
| 4 | `tests/test_audio_input.py` | `TestDeviceDiscovery`, `TestAudioResampler`, `TestAudioProcessingChain` | 19 | Device enumeration, loopback / VB-Cable / headphone / headset resolution, sample rate downsampling / upsampling, PeakNormalizer, AutomaticGainControl. |
| 5 | `tests/test_audio_stream_reliability.py` | VAD Framing, Stream Init, Queue Eviction, Gain Bounds, StreamDiagnostics | 9 | Silero VAD 512-sample sliding window, padding, noise floor gate (RMS < 0.005), WASAPI fallback to Stereo Mix, queue eviction on overflow, anti-clipping bounds [-1.0, 1.0], StreamDiagnostics assertions. |
| 6 | `tests/test_bidirectional.py` | Bidirectional Translation Pipeline | 3 | Simultaneous mic (EN->HI) and loopback (HI->EN) translation, dynamic routing, per-panel speaker gating (`tts_enabled_a`, `tts_enabled_b`). |
| 7 | `tests/test_deepl_speed.py` | DeepL Startup & E2E Speed | 2 | Startup under 5.0s despite unreachable proxy, end-to-end translation speed. |
| 8 | `tests/test_device_detection.py` | Device Resolution Fallbacks | 3 | Out-of-range device ID fallbacks (9999, -1), 0-channel device filtering, Application startup device resolution. |
| 9 | `tests/test_history.py` | `TestHistoryDatabase`, `TestHistoryExporter`, `TestHistoryStar`, `TestHistoryFolders`, `TestAISummary` | 44 | SQLite database operations, session export formats (TXT, JSON, SRT, VTT), timestamp formatting, starred sessions, folders, AI summary generation. |
| 10 | `tests/test_language_filtering.py` | Language Filtering in STT Worker | 1 | Verifies dropping STT segments in unselected languages (e.g., German 'de') in `_stt_worker`. |
| 11 | `tests/test_left_panel_mute.py` | UI Mic Button & Mute Integration | 2 | TranscriptPanel mic button visual color updates (`#EF4444` muted vs `#FF5C2B` unmuted) and MainWindow `pipeline.mute_mic()` connection. |
| 12 | `tests/test_loopback_headphones.py` | Headphones Loopback & WASAPI Preference | 2 | 440Hz headphone tone loopback recording RMS > 0.001, WASAPI device selection preference. |
| 13 | `tests/test_m1_challenger2_empirical.py` | Empirical Noise Floor Gating & Fallbacks | 20 (runs) | RMS boundary gating (0.0049 vs 0.0051 RMS), specified device failure candidate fallback sequence, StreamDiagnostics fault injection assertions. |
| 14 | `tests/test_m3_adversarial.py` | Adversarial Pipeline Routing & Edge Cases | 10 | Mic EN->HI / HI->EN, loopback EN->HI / HI->EN, speaker toggle matrix (4 combinations), low-confidence (<0.4) filtering, empty translation result, translation timeout resilience, TTS queue full resilience, language code variants. |
| 15 | `tests/test_m4_crosscheck.py` | Settings & Diagnostic Crosscheck | 4 | VAD threshold (0.45), RMS gate (0.0003), device IDs (35/36), STT engine ("openai"), OpenAISTT AGC normalization target, pipeline mute gate logic. |
| 16 | `tests/test_mic_capture.py` | Real Mic Capture & VAD Threshold | 1 | Real/synthetic mic audio capture RMS > 0.0003 and VAD threshold 0.45 evaluation. |
| 17 | `tests/test_milestone1_challenge.py` | Silero VAD Buffer Stress & Anti-Clipping | 14 (runs) | VAD large buffer stress (2048, 4096 samples), anti-clipping under extreme amplitudes (+10, -10, NaN, Inf), high-throughput queue insertion overflow eviction. |
| 18 | `tests/test_milestone2.py` | WASAPI Loopback, Auto-Lang, Routing | 5 | WASAPI loopback discovery, input queue overflow drop, FasterWhisper auto language normalization ("auto", "AUTO"), input_source attachment, AUTO source lang resolution. |
| 19 | `tests/test_milestone3.py` | Indic TTS Routing & Virtual Audio Output | 14 | Indic languages (HI, MR, TA, TE, KN, ML, GU, BN, PA, OR) routed to Sarvam TTS, English to Piper TTS, Sarvam fallback to Piper, SoundDeviceOutput volume clamping, mute toggle, delay. |
| 20 | `tests/test_milestone4.py` | Text Input Mode & Dual Panel Routing | 8 | Text input submission, translation queue enqueue, `on_transcription` callback with "TEXT" tag, empty/long text rejection, `submit_text_input` when loop running, `text_input_mode` property, dual panel routing. |
| 21 | `tests/test_milestone5.py` | UI Smoke & Adversarial Edge Cases | 11 | UI callbacks (`on_transcription`, `on_translation`, `on_status`, `on_latency`, `on_audio_level`), RMS audio level emission, status messages, STT empty text skip, translation empty result skip, rapid text inputs, TTS silence skip, queue full non-blocking. |
| 22 | `tests/test_openai_stt.py` | OpenAI STT Manual Live Test | 1 | Manual script: OpenAI API key verification, `gpt-4o-transcribe` model config, silence RMS gate rejection, cost estimation. |
| 23 | `tests/test_pipeline.py` | Core Pipeline Lifecycle & Workers | 22 | Pipeline init, start/stop, restart, start twice no-op, stop when stopped, source tagging ("VOICE", "COMPUTER_AUDIO", "TEXT"), worker cancellation, worker error resilience, text input processing, TTS mute gate duration & queue purging. |
| 24 | `tests/test_pipeline_accuracy.py` | E2E Accuracy, Latency & Failure Fallbacks | 6 | WavAudioFeeder streaming, English E2E accuracy & latency (<1.5s), Hindi E2E accuracy & latency (<1.5s), E2E latency benchmark, VAD quiet audio sensitivity & noise floor resilience, translation API timeout & model load failure fallbacks, 48kHz stereo downsampling. |
| 25 | `tests/test_real_audio_capture.py` | Live Audio Device & Stream Verification | 6 | Device enumeration, loopback discovery, Stereo Mix discovery, microphone capture (2s), loopback capture (2s), dual mic + loopback meeting mode capture (2s). |
| 26 | `tests/test_sarvam_network.py` | Sarvam Network Integration | 1 | Manual script: Direct vs proxy HTTP POST connection test to Sarvam TTS API. |
| 27 | `tests/test_stt.py` | BaseSTT & FasterWhisper Unit Tests | 21 | BaseSTT abstract check, TranscriptionSegment fields, FasterWhisperSTT init (CUDA/CPU), transcription success, empty result, auto-detect lang, noise logprob rejection, CUDA float16, beam size, initial prompt, VAD filter, thresholds, GPU & VRAM checks. |
| 28 | `tests/test_stt_refinement.py` | LLM Refinement & Noise Filtering | 2 | OpenAISTT LLM refinement with valid raw speech, background noise hallucination filtering (empty LLM response dropped). |
| 29 | `tests/test_translation.py` | BaseTranslator, Argos, DeepL, Factory, Validator, Context | 30 | BaseTranslator abstract check, TranslationResult fields, ArgosTranslator init, translate success, 2-way swap, cold start warmup, language pair swap, context prompt, default vocabulary (EN<->HI), DeepLTranslator init, API timeout, proxy config, proxy unreachable fallback, no API key, TranslationFactory fallback chain, LanguageValidator hysteresis, ContextEngine sliding window. |
| 30 | `tests/test_tts.py` | BaseTTS, Piper, Sarvam, Router, Voice Cache | 35 | BaseTTS abstract check, SynthesisResult fields, PiperTTS init, synthesize success, empty text, set_voice, voice discovery, CUDA flag, fallback to silence, synthesize_stream, stop, SarvamTTS init, synthesize success, timeout, base64 decoding, API status errors, no API key, stream, speaker resolution, MultilingualTTSRouter Indic/English routing & fallback chain. |
| 31 | `tests/test_vad.py` | BaseVAD & SileroVAD Unit Tests | 17 | BaseVAD abstract check, VADResult fields, SileroVAD init (default/custom threshold), start success/failure fallback, stop, process speech/no speech, state reset, source tagging, empty audio, sample rates (8k/16k/44.1k/48k), error handling, model None fallback. |

### 2.2 Test Fixtures Inventory

| Fixture Name | Source File | Scope | Description / Purpose |
|--------------|-------------|-------|-----------------------|
| `sample_audio` | `tests/conftest.py` | Function | 1-second 16kHz float32 numpy array with noise amplitude 0.1 |
| `sample_audio_chunk` | `tests/conftest.py` | Function | 30ms 16kHz float32 numpy array (480 samples) |
| `mock_settings` | `tests/conftest.py` | Function | Mock `Settings` object configured with EN->HI two_way translation |
| `temp_db_path` | `tests/conftest.py` | Function | Temporary `.db` file path for SQLite history testing, cleaned up after test |
| `mock_transcription_segment` | `tests/conftest.py` | Function | Mock final `SttJob` / `TranscriptionSegment` object ("Hello world", EN, 0.95) |
| `mock_translation_result` | `tests/conftest.py` | Function | Mock `TranslationResult` object ("Hello world" -> "नमस्ते दुनिया") |
| `mock_vad_result` | `tests/conftest.py` | Function | Mock `VADResult` object (`is_speech=True`, confidence=0.85) |
| `mock_pipeline` | `tests/conftest.py` | Async Function | Mock `Pipeline` instance with AsyncMock lifecycle methods |
| `sample_session_blocks` | `tests/conftest.py` | Function | Sample list of conversation blocks for history exporter tests |
| `mock_device_list` | `tests/conftest.py` | Function | Mock audio devices list (mic, speakers, Stereo Mix, VB-Cable) |
| `mock_audio_levels` | `tests/conftest.py` | Function | List of float audio RMS levels for UI audio meter testing |
| `generate_english_wav` | `tests/fixtures/generate_fixtures.py` | Script | Synthesizes 16kHz PCM WAV file with English speech frequencies |
| `generate_hindi_wav` | `tests/fixtures/generate_fixtures.py` | Script | Synthesizes 16kHz PCM WAV file with Hindi speech frequencies |

### 2.3 Test Execution Commands

1. **Full Automated Test Suite Execution**:
   ```bash
   python -m pytest -v
   ```
2. **Selective Component Test Execution**:
   ```bash
   # Run audio input & reliability tests
   python -m pytest tests/test_audio_input.py tests/test_audio_stream_reliability.py -v

   # Run pipeline accuracy & latency benchmarks
   python -m pytest tests/test_pipeline_accuracy.py -v

   # Run UI panel & window tests
   python -m pytest tests/test_left_panel_mute.py tests/test_milestone5.py -v
   ```
3. **Standalone Script Verification Execution**:
   ```bash
   # Run OpenAI STT live API check
   python tests/test_openai_stt.py

   # Run Sarvam TTS network connection check
   python tests/test_sarvam_network.py

   # Run physical microphone level & VAD check
   python tests/test_mic_capture.py

   # Run device detection resolution check
   python tests/test_device_detection.py
   ```

---

## 3. Test Coverage Gap Analysis

Based on Requirement R2 and Acceptance Criteria audit, 7 critical gaps were identified:

```
+---------------------------------------------------------------------------------------------------------+
|                                        IDENTIFIED TEST COVERAGE GAPS                                    |
+----+--------------------------------------------+-------------------------------------------------------+
| #  | Gap Area                                   | Missing Test Case Description                         |
+----+--------------------------------------------+-------------------------------------------------------+
| G1 | LLM Refinement Retry Thresholds            | No test verifies OpenAI Chat Completions retry         |
|    |                                            | thresholds (exponential backoff / max retries) upon   |
|    |                                            | API rate-limiting (429) or connection timeout.        |
+----+--------------------------------------------+-------------------------------------------------------+
| G2 | Language Constraint Checks                 | No test validates allowed language list enforcement  |
|    |                                            | (e.g. restricting translation pairs to EN, HI, ES),  |
|    |                                            | or code-switching (Hinglish) boundary handling.       |
+----+--------------------------------------------+-------------------------------------------------------+
| G3 | UI State Transitions (Play/Stop/Initialize)| `test_left_panel_mute.py` covers mic mute toggle, but  |
|    |                                            | UI control state machine transitions (Idle ->          |
|    |                                            | Initializing -> Running -> Stopping) are unverified.   |
+----+--------------------------------------------+-------------------------------------------------------+
| G4 | Double Window Spawning Prevention          | ZERO tests verify that opening Settings, History, or  |
|    |                                            | About dialogs multiple times prevents duplicate Tk    |
|    |                                            | windows from spawning (AC-2 requirement).             |
+----+--------------------------------------------+-------------------------------------------------------+
| G5 | Play Button Loading State '⏳'             | ZERO tests verify that clicking Play disables the     |
|    |                                            | button and sets text to '⏳' during pipeline           |
|    |                                            | initialization before re-enabling (AC-3 requirement). |
+----+--------------------------------------------+-------------------------------------------------------+
| G6 | OpenAI STT Allowed Languages Filtering     | `OpenAISTT` tests silence RMS gating, but lacks a     |
|    |                                            | test verifying dropping audio segments returned in    |
|    |                                            | non-allowed languages at the service level (AC-4).    |
+----+--------------------------------------------+-------------------------------------------------------+
| G7 | Standalone Verification Verifier           | Standalone scripts exist, but no single test verifier  |
|    |                                            | automates verification of mic level detection AND     |
|    |                                            | bidirectional routing without UI interaction (AC-5). |
+----+--------------------------------------------+-------------------------------------------------------+
```

---

## 4. Requirements & Acceptance Criteria Mapping

| Requirement / AC ID | Description | Specification Source | Target Test File & Function | Status |
|---------------------|-------------|----------------------|-----------------------------|--------|
| **R1.1** | Audio Capture & DSP: Verify mic/loopback, noise floor gate (RMS < 0.005), downsampling (48k->16k), AGC, anti-clipping bounds [-1.0, 1.0]. | `audio/input.py`, `services/audio_processing/` | `tests/test_audio_input.py`, `tests/test_audio_stream_reliability.py`, `tests/test_m1_challenger2_empirical.py` | Covered |
| **R1.2** | Pipeline & Concurrency: Async task runners, worker threads, queue eviction (`get_nowait`), thread safety, lock/memory leak prevention. | `app/pipeline.py` | `tests/integration/test_full_pipeline.py`, `tests/test_pipeline.py`, `tests/test_milestone1_challenge.py` | Covered |
| **R1.3** | Accuracy & Latency: Profile stage latencies (VAD, Whisper STT, LLM refinement, DeepL/Argos, Sarvam/Piper TTS), E2E latency < 1.5s. | `app/pipeline.py`, `services/stt/`, `services/translation/` | `tests/test_pipeline_accuracy.py::TestPipelineAccuracyAndLatency` | Covered |
| **R1.4** | UI State Management: Modal dialog instances, theme consistency, control state transitions (Play, Stop, Initialize, Mute). | `ui/main_window.py`, `ui/widgets/` | `tests/test_left_panel_mute.py`, *NEW: `tests/test_ui_state_transitions.py`* | GAP (Partial) |
| **R2.1** | Automated Test Expansion & Correction: 53 tests pass, coverage gaps filled, zero regressions. | `tests/` | Full `pytest` suite + *NEW: `tests/test_coverage_gaps.py`* | Gap Remediation Required |
| **R3.1** | Bug Fixes & Optimization: Fix thread locks, memory leaks, audio glitches, latency bottlenecks. | Core codebase | `tests/test_audio_stream_reliability.py`, `tests/test_pipeline_accuracy.py` | Covered |
| **AC-1** | Full test runner execution returns 100% green without failures. | `pytest` runner | All files in `tests/` | 100% Target |
| **AC-2** | No duplicate windows can be spawned from the UI. | `ui/main_window.py` | *NEW: `tests/test_ui_window_prevention.py::test_no_duplicate_windows`* | GAP |
| **AC-3** | Play button disables and displays loading indicator `⏳` during pipeline initialization. | `ui/main_window.py` | *NEW: `tests/test_ui_play_button.py::test_play_button_loading_state`* | GAP |
| **AC-4** | OpenAI STT drops audio segments not in the allowed languages. | `services/stt/openai_stt.py` | *NEW: `tests/test_openai_stt_language_filter.py::test_openai_stt_drops_unallowed_languages`* | GAP |
| **AC-5** | Standalone test scripts confirm mic levels and bidirectional routing. | `tests/test_mic_capture.py` | *NEW: `scripts/verify_mic_and_routing.py`* | GAP |

---

## 5. Features Discovered

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|----------|---------|-------------|--------|---------|----------------|----------------|
| 1 | Audio DSP | Noise Floor Gating | Gates static audio with RMS < 0.005 in Silero VAD and RMS < 0.0003 in OpenAI STT to prevent false speech triggers. | Float32 numpy audio chunk | `VADSpeechOutcome(is_speech=False, confidence=0.0)` | Mutes audio chunk without invoking model inference. | `audio/input.py`, `services/vad/silero_vad.py` |
| 2 | Audio DSP | Anti-Clipping Clamping | Clamps excessive float32 audio values strictly to [-1.0, 1.0] and sanitizes NaN / Inf values. | Audio array with values > 1.0 or NaN | Clamped float32 array in [-1.0, 1.0] | Replaces NaN/Inf with 0.0, clamps extremes. | `services/audio/input.py`, `tests/test_milestone1_challenge.py` |
| 3 | Audio DSP | Queue Eviction Strategy | Bounded `asyncio.Queue` (maxsize=10/256) evicts oldest chunk (`get_nowait`) on overflow to prevent pipeline deadlocks or memory growth. | High-throughput `AudioChunk` objects | Bounded queue size, overflow counter incremented | Evicts oldest chunk silently, logs warning. | `services/audio/input.py`, `app/pipeline.py` |
| 4 | Audio Hardware | WASAPI & Stereo Mix Fallback | Tries WASAPI loopback first; if unavailable or failed, falls back sequence: Stereo Mix -> VB-Cable Output -> default input device. | `device_id` / `loopback=True` | Active input audio stream | Appends error to `_device_init_errors`, raises `RuntimeError` if all fail. | `services/audio/loopback.py`, `services/audio/input.py` |
| 5 | Audio DSP | 48kHz Stereo Downsampling | Resamples 48kHz stereo loopback audio to 16kHz mono PCM `AudioChunk` in stream callback. | 48kHz 2-channel float32 array | 16kHz 1-channel `AudioChunk` | Handles rate mismatch gracefully. | `services/audio/resampler.py`, `tests/test_pipeline_accuracy.py` |
| 6 | STT Engine | FasterWhisper STT | Runs local `faster-whisper-small` model with CUDA float16 or CPU fallback, beam_size=1, VAD filter, logprob threshold -1.0. | 16kHz audio buffer, `language` code | `TranscriptionSegment(text, confidence, language)` | Returns `None` on low logprob or silence. | `services/stt/faster_whisper.py` |
| 7 | STT Engine | OpenAI STT & LLM Refinement | Uses OpenAI Whisper API (`gpt-4o-transcribe`) with optional Chat Completions LLM refinement to clean filler words and filter noise hallucinations. | Audio bytes, `refinement=True` | `TranscriptionSegment` with refined text | Drops segment (`None`) if LLM returns empty text on noise hallucination. | `services/stt/openai_stt.py`, `tests/test_stt_refinement.py` |
| 8 | Translation | Argos & DeepL Translation | Primary offline translation via Argos Translate with fallbacks to DeepL API and context sliding window engine. | Original text, `source_lang`, `target_lang`, `context` | `TranslationResult(original_text, translated_text)` | Returns original text unchanged on API timeout or error. | `services/translation/argos.py`, `services/translation/deepl.py`, `services/translation/factory.py` |
| 9 | TTS Synthesis | Indic & English Multilingual Router | Routes Indic languages (Hindi, Marathi, Tamil, Telugu, etc.) to Sarvam TTS API (`bulbul:v3`) and English/other languages to local Piper TTS, with fallback chain. | Translated text, `lang` code | `SynthesisResult(audio_data, sample_rate, duration_ms)` | Synthesizes 1s silence on API failure or missing voice. | `services/tts/router.py`, `services/tts/sarvam.py`, `services/tts/piper.py` |
| 10 | Pipeline | Dual Panel & Bidirectional Routing | Tagging inputs as `VOICE` (mic -> Panel A), `COMPUTER_AUDIO` (loopback -> Panel B), or `TEXT` (typed -> Panel A), routing speech to respective panels and speakers. | `TranscriptionSegment` with `input_source` | Routed `TranslationResult` | Respects `tts_enabled_a` and `tts_enabled_b` toggles. | `app/pipeline.py`, `tests/test_bidirectional.py`, `tests/test_m3_adversarial.py` |
| 11 | History Storage | SQLite Database & Multi-Format Exporters | Manages session persistence in SQLite DB (`sessions` table) and exports transcripts to TXT, JSON, SRT, VTT formats. | Session blocks, format type | Formatted text string or DB record | Returns empty string / empty array on invalid inputs or non-existent IDs. | `services/history/database.py`, `services/history/exporter.py` |
| 12 | UI Component | TranscriptPanel Visual States | Renders dual column transcript panels with mic mute toggle visual states (`#EF4444` red muted vs `#FF5C2B` orange active). | Mic button click / `toggle_mic()` | Updated button text color and active state | Synchronizes with `pipeline.mute_mic(muted)`. | `ui/widgets/transcript_panel.py`, `tests/test_left_panel_mute.py` |

---

## 6. Edge Cases

| # | Feature | Input | Observed Behavior |
|---|---------|-------|-------------------|
| 1 | Silero VAD | Static noise with RMS = 0.0049 (< 0.005) | Immediately gated by noise floor gate without calling model evaluation; returns `(False, 0.0)`. |
| 2 | Silero VAD | Short audio chunk < 512 samples | Padded with trailing zeros to 512 samples before sending to ONNX model. |
| 3 | Silero VAD | Large audio buffer (2048 or 4096 samples) | Evaluated using sliding window frame iterator in 512-sample steps; returns `is_speech=True` if any frame contains speech. |
| 4 | SoundDeviceInput | Input array with extreme values (+10.0, -10.0, NaN, Inf) | Sanitized by anti-clipping filter; NaN/Inf converted to 0.0 and extreme values clamped strictly to `[-1.0, 1.0]`. |
| 5 | SoundDeviceInput | High-throughput 1,000 chunks into `maxsize=10` queue | Evicts oldest chunk (`get_nowait`) on overflow; queue size remains bounded at 10, preventing memory leaks or deadlocks. |
| 6 | SoundDeviceInput | Invalid mic device ID (e.g. 9999 or -1) | Resolves to default valid input device without crashing application. |
| 7 | SoundDeviceInput | Requested device with 0 input channels | Falls back to device with >0 input channels. |
| 8 | SoundDeviceInput | WASAPI loopback fails during startup | Automatically falls back to sounddevice `Stereo Mix` or `VB-Cable Output`. |
| 9 | FasterWhisper STT | Silence or low logprob (-1.0) audio | Filtered out by Whisper threshold; returns `None` segment. |
| 10 | OpenAISTT LLM | Noise hallucination raw transcription ("you") | LLM refinement returns empty string `""`; segment dropped, returning `None`. |
| 11 | Argos / DeepL | Primary translation API timeout or network error | Fallback chain triggers next translator; if all fail, returns original text as `TranslationResult`. |
| 12 | Sarvam TTS | API connection timeout or HTTP error (e.g. 401) | Falls back to Piper TTS or returns 1.0s synthetic silence array (`sample_rate=8000`). |
| 13 | Pipeline Mute Gate | TTS audio playback starts | Activates `_ignore_loopback_until = now + duration + 0.5s` and purges pending loopback queues to prevent TTS loopback feedback echo. |
| 14 | Pipeline Text Input | String exceeding 5,000 characters | Instantly raises `ValueError("Text exceeds maximum allowed length of 5000 characters")`. |
| 15 | History Exporter | Empty session blocks list `[]` | Returns `""` for TXT/SRT, `"[]"` for JSON, and `"WEBVTT\n"` for VTT without crashing. |

---

## 7. Recommendations & Action Plan for Test Expansion

To achieve 100% compliance with requirements R1–R3 and Acceptance Criteria AC-1 to AC-5, the following test expansion files should be added in Milestone M4:

1. **`tests/test_ui_window_prevention.py`**:
   - Verify `MainWindow` and modal dialogs (Settings, History, About) enforce single-instance guards preventing double window spawning (AC-2).
2. **`tests/test_ui_play_button_loading_state.py`**:
   - Verify clicking Play disables button, sets text to `⏳` during async pipeline initialization, and re-enables once running (AC-3).
3. **`tests/test_openai_stt_language_filter.py`**:
   - Verify `OpenAISTT` service drops audio segments whose detected language is outside the allowed set `{"en", "hi"}` (AC-4).
4. **`scripts/verify_mic_and_routing.py`**:
   - Programmatic standalone script verifying physical/synthetic mic RMS audio levels AND bidirectional routing assertions with non-zero exit code on failure (AC-5).
5. **`tests/test_coverage_gaps.py`**:
   - Add tests for LLM refinement retry thresholds (429 rate limit backoff), allowed language constraint validation, and UI control state machine transitions (G1, G2, G3).

---

**Report Status**: Complete and verified against codebase observations.
