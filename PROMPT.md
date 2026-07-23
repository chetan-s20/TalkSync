# TalkSync Pro — Complete Rebuild Prompt

You are a team consisting of:

- Principal Software Architect
- Senior Python Engineer
- Real-Time Audio Systems Engineer
- AI/ML Engineer
- UI/UX Product Designer
- DevOps Engineer
- QA Lead

You are rebuilding TalkSync Pro completely from scratch.

This is NOT a rewrite of an existing repository. This is a new product that supersedes the previous implementation, informed by lessons from a failed attempt.

The goal is to build a production-quality desktop application capable of offline and hybrid real-time speech translation with a modern architecture and enterprise-grade code quality.

---

## ENVIRONMENT CONSTRAINTS (MUST FOLLOW)

These are hard constraints that the previous implementation failed to handle correctly:

1. **Corporate proxy at `192.168.0.1:8090`** blocks GitHub, HuggingFace, and most external AI model servers. Only cached HuggingFace assets (already downloaded to `~/.cache/huggingface/`) and the Argos translation model server work through the proxy. All network requests must use `{ "http": "http://192.168.0.1:8090", "https": "http://192.168.0.1:8090" }` or equivalent proxy configuration.

2. **GPU: RTX 4060 8GB VRAM** with CUDA 12.x. PyTorch CUDA is available. Device detection must use `torch.cuda.get_device_properties(0).total_memory` (note: `total_memory`, not `total_mem` — that attribute was renamed in newer PyTorch).

3. **Python 3.11** (not 3.12+). Use Python 3.11 compatible syntax throughout.

4. **Installed packages**: customtkinter, sounddevice, faster-whisper (CUDA), piper-tts v1.5.0 (NOTE: this version uses `PiperVoice.load(model_path, config_path, use_cuda=False)` — there is NO `piper.download` module), argostranslate, deepl, httpx, numpy, torch with CUDA, onnxruntime, pydantic, pydantic-settings.

5. **WASAPI loopback is NOT available** in the bundled PortAudio binary shipped with sounddevice. Loopback must use Stereo Mix (WDM-KS callback, no driver install needed — user enables via Windows Sound Settings → Recording → Show Disabled → Enable Stereo Mix) with VB-Cable as fallback.

6. **No local Hindi Piper voice**. The `hi_IN-medium` (~500MB) Piper voice is not cached and cannot be downloaded (HuggingFace blocked). Hindi TTS must route to **Sarvam cloud API** (`https://api.sarvam.ai/v1/text-to-speech`) with Piper as a fallback only for English. Sarvam adds 1-5s latency through the proxy.

7. **Argos Translate** is downloaded and works offline (~15ms warm, ~4s cold start). **DeepL** API works through the proxy (2-5s). Translation must have Argos as primary with DeepL fallback.

8. **Input audio**: Use `sounddevice.InputStream` with `dtype="float32"`, blocksize derived from `sample_rate * chunk_duration_ms / 1000`. Loopback from Stereo Mix device (`"stereo mix"` in device name, case-insensitive). Each stream gets its own callback that resamples to the target sample rate using `np.interp` if the native device rate differs.

9. **Output audio**: Use `sounddevice.OutputStream` with a fallback chain for sample rates `(24000, 44100, 48000, 16000)` × channels `(stereo (2), mono (1))` — try every combination. Some devices reject certain rate+channel combos. The speaker callback uses a thread-safe `queue.Queue` buffer filled by the async consumer loop.

10. **Silero VAD** is loaded via `torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad', force_reload=False, trust_repo=True)`. This model IS cached locally.

---

## LESSONS FROM PREVIOUS FAILURE

The previous implementation had these specific problems that MUST be avoided:

### Architecture Mistakes
- **File sprawl**: Previous app had 45+ files spread across `core/`, `audio/`, `stt/`, `tts/`, `translation/`, `vad/`, `utils/`, `config/`, `ui/`, `tests/` with no clear ownership boundaries. Every folder was flat with 5-10 files and no sub-module organization.
- **Duplicate VAD/STT workers**: Previous code had two nearly identical worker coroutines for mic and loopback (`_vad_worker` / `_vad_loopback_worker`, `_stt_worker` / `_stt_loopback_worker`). These must be unified with a `source` parameter.
- **Mixed concerns in pipeline manager**: `PipelineManager` handled restart logic, per-source state, worker lifecycle, translation routing, TTS routing, and text input. This was a god class.
- **Settings as a grab bag**: One `Settings` class with nested sub-settings but no validation, no environment variable loading for secrets, and no defaults documentation.
- **Implicit TTS routing**: The TTS router (`MultilingualTTSRouter`) guessed the engine based on language family string matching. Engine initialization was lazy and asynchronous with race conditions during restart.
- **`_fill()` method in AudioRouter** duplicated almost identically for speaker and virtual mic callbacks.

### Import & Runtime Bugs
- `stt/faster_whisper.py` imported `from config.settings import AppSettings` — a class that didn't exist (the class was named `Settings`).
- `ui/main_window.py:268` imported `from config.models_config import update_config` — a module that didn't exist at all.
- `tts/piper.py` tried `import piper.download` and called `piper.download.find_voice()` — neither exists in the installed `piper-tts` v1.5.0 package. The correct API is `PiperVoice.load(model_path, config_path, use_cuda=False)`.
- `tag_config()` calls in `customtkinter.CTkTextbox` included a `font` parameter, which customtkinter explicitly forbids (raises `AttributeError`). Font must be set on the widget itself, not on tags.
- `utils/device.py` used `torch.cuda.get_device_properties(0).total_mem` — this was renamed to `total_memory` in newer PyTorch versions.
- `translation/translation_factory.py` was duplicated by `translation/__init__.py` which also exported `TranslationFactory` — creating potential circular import paths.
- `audio/buffer.py` contained a `RingBuffer` class with only `extend` and `__len__` — never actually used anywhere in the pipeline.

### Design Flaws
- **No main entry point**: There was no `main.py`, `app.py`, `__main__.py`, or any other entry point. The app could not be launched.
- **No `delete_session()` in HistoryScreen**: Sessions could be saved, listed, and viewed but never deleted.
- **Tests directory was empty**: No test infrastructure existed at all.
- **No transcription display in UI**: `_on_transcription` callback was defined as a no-op (empty `pass`). The transcript panels showed nothing during speech.
- **GPU VRAM was never measured correctly**: The device utils silently returned `cpu` on `total_mem` attribute error, so the app defaulted to CPU despite having a CUDA GPU.
- **Piper voice fallback was missing**: When a Piper voice wasn't found locally, the code silently set `self._model = None` and every `synthesize()` call returned silence. There was no user-facing warning or fallback to another engine for the same language.

---

## PROJECT PHILOSOPHY

The project must be:

- **Production Ready** — handles errors gracefully, logs everything, no silent failures
- **Modular** — every module has a single responsibility, swappable implementations
- **Maintainable** — small files (<300 lines), clear naming, typed signatures
- **Scalable** — pipeline designed to handle multiple input sources without code duplication
- **Testable** — all services use abstract interfaces, dependency injection, no global state
- **Extensible** — providers (STT, TTS, translation, VAD) are hot-swappable behind interfaces

Every component must have a single responsibility. Nothing should depend directly on another module unless absolutely necessary. Prefer interfaces and dependency injection. Avoid global state. Avoid duplicate logic. Avoid giant files. Every feature must plug into the same processing pipeline.

---

## PRIMARY OBJECTIVE

Create a real-time multilingual communication platform capable of:

- Voice Translation (mic → STT → translate → TTS → speaker)
- Text Translation (typed text → translate → TTS)
- Live Meeting Translation (mic + loopback simultaneous, dual-direction)
- Floating Subtitles (always-on-top overlay)
- Virtual Microphone Translation (TTS output routed to virtual audio cable)
- Transcript Export (TXT, JSON, SRT)
- Session History (SQLite with CRUD)
- AI Context Assisted Translation (recent conversation history as prompt context)
- Diagnostics Dashboard (latency, GPU, queue sizes, FPS)

---

## CORE ARCHITECTURE

```
TalkSync/
├── app/
│   ├── __init__.py
│   ├── application.py          # App bootstrap, service wiring, DI container
│   ├── pipeline.py              # Single unified pipeline orchestrator
│   ├── pipeline_errors.py       # Custom error types
│   └── pipeline_state.py        # Per-source state machine (mic, loopback, text)
│
├── services/
│   ├── __init__.py
│   │
│   ├── audio/
│   │   ├── __init__.py
│   │   ├── base.py              # BaseAudioInput, BaseAudioOutput interfaces
│   │   ├── input.py             # SoundDeviceInput (mic + loopback dual-stream)
│   │   ├── output.py            # SoundDeviceOutput (speaker + virtual mic)
│   │   ├── loopback.py          # Stereo Mix / VB-Cable discovery
│   │   ├── resampler.py         # Sample rate conversion utility
│   │   └── fallback.py          # Rate × channel fallback combinator
│   │
│   ├── audio_processing/
│   │   ├── __init__.py
│   │   ├── base.py              # AudioProcessor interface (process(audio) -> audio)
│   │   ├── rnnoise.py           # RNNoise denoiser wrapper
│   │   ├── agc.py               # Automatic gain control
│   │   ├── normalizer.py        # Audio level normalization
│   │   └── echo_cancellation.py # Echo cancellation stub (interface only)
│   │
│   ├── stt/
│   │   ├── __init__.py
│   │   ├── base.py              # BaseSTT interface
│   │   ├── faster_whisper.py    # Faster-Whisper GPU implementation
│   │   └── models_config.py     # Model path resolution, cache management
│   │
│   ├── translation/
│   │   ├── __init__.py
│   │   ├── base.py              # BaseTranslator interface
│   │   ├── argos.py             # Argos Translate (offline, primary)
│   │   ├── deepl.py             # DeepL API (cloud, fallback through proxy)
│   │   ├── factory.py           # TranslationFactory (creates fallback chain)
│   │   ├── language_validator.py # Confidence-based language hysteresis
│   │   └── context_engine.py    # Conversation context window
│   │
│   ├── tts/
│   │   ├── __init__.py
│   │   ├── base.py              # BaseTTS interface
│   │   ├── piper.py             # Piper TTS (local, English)
│   │   ├── sarvam.py            # Sarvam AI API (cloud, Hindi through proxy)
│   │   ├── router.py            # Language → engine routing layer
│   │   └── voice_cache.py       # Voice file discovery
│   │
│   ├── context/
│   │   ├── __init__.py
│   │   ├── engine.py            # Conversation context window
│   │   └── keyword_processor.py # Keyword replacement
│   │
│   ├── history/
│   │   ├── __init__.py
│   │   ├── database.py          # SQLite CRUD (init, save, load, delete, list)
│   │   └── exporter.py          # TXT / JSON / SRT / WebVTT export
│   │
│   ├── subtitle/
│   │   ├── __init__.py
│   │   └── overlay.py           # Always-on-top floating subtitle window
│   │
│   └── diagnostics/
│       ├── __init__.py
│       └── monitor.py           # Live latency, GPU, queue, FPS monitoring
│
├── ui/
│   ├── __init__.py
│   ├── main_window.py           # Main application window
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── transcript_panel.py  # Bilingual transcript display
│   │   ├── control_bar.py       # Start/stop/mute buttons
│   │   ├── sidebar.py           # Navigation sidebar
│   │   ├── status_indicator.py  # GPU/language/connection status
│   │   └── latency_badge.py     # Live latency display
│   ├── dialogs/
│   │   ├── __init__.py
│   │   ├── audio_settings.py    # Device selection popup
│   │   ├── language_selector.py # Language pair and mode selection
│   │   ├── history_viewer.py    # Session history browser
│   │   ├── diagnostics.py       # Live diagnostics dashboard
│   │   ├── speaker_options.py   # Volume/mute/delay controls
│   │   └── about.py             # About / version dialog
│   └── assets/
│       ├── styles.py            # Theme colors, fonts, spacing constants
│       └── icons/               # SVG or PNG icons (optional)
│
├── config/
│   ├── __init__.py
│   ├── settings.py              # Pydantic settings models (all sub-settings)
│   └── defaults.json            # Default config values
│
├── utils/
│   ├── __init__.py
│   ├── logger.py                # Logging configuration
│   ├── device.py                # GPU/CPU detection (use total_memory, not total_mem)
│   ├── languages.py             # Language code ↔ name mapping
│   ├── latency.py               # Latency measurement decorators
│   └── proxy.py                 # Proxy-aware HTTP client factory
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Shared fixtures
│   ├── test_audio_input.py
│   ├── test_vad.py
│   ├── test_stt.py
│   ├── test_translation.py
│   ├── test_tts.py
│   ├── test_pipeline.py
│   ├── test_history.py
│   └── integration/
│       ├── __init__.py
│       └── test_full_pipeline.py
│
├── main.py                      # Entry point (argparse, bootstrap, app.mainloop)
├── pyproject.toml               # Project metadata, dependencies, tool config
├── README.md
└── PROMPT.md (this file)
```

### Key file size guidelines
- No file should exceed 400 lines. If it does, split into sub-modules.
- Exception: `ui/main_window.py` may be larger (complex layouts), but should aggregate widget classes rather than inline everything.
- Exception: `app/pipeline.py` is the orchestrator — keep it under 500 lines by delegating to smaller state/handler classes.

---

## UNIFIED PIPELINE

Everything must pass through ONE shared pipeline with pluggable stages.

### Voice Mode Flow
```
Microphone audio
  ↓
audio_processing chain (RNNoise → AGC → Normalizer → EchoCancellation stub)
  ↓
Silero VAD (single instance, tagged by source="mic"|"loopback")
  ↓
Per-source audio buffer (accumulates until speech segment complete or 10s timeout)
  ↓
Faster-Whisper STT (CUDA float16, beam_size=1, language auto-detect)
  ↓
Language Validator (confidence hysteresis, two-way mode swaps src/tgt)
  ↓
Conversation Context Engine (last 3 segments as prompt)
  ↓
Translation (Argos → DeepL fallback, 5s timeout)
  ↓
TTS Router (English → Piper, Hindi → Sarvam)
  ↓
Output Router (Speaker stream + Virtual Mic stream + Subtitles + History)
```

### Text Mode Flow
```
Text input (Ctrl+Enter)
  ↓
Language Validator (skips detection, uses configured source language)
  ↓
Conversation Context Engine
  ↓
Translation
  ↓
TTS Router
  ↓
Output Router (same as voice)
```

The only difference between voice and text is the input source. Everything after STT must be shared. The pipeline must not have duplicated translation, TTS, or output logic for different input sources.

### Source Tagging
Every `AudioChunk` must carry a `source` field: `"mic"`, `"loopback"`, `"text"`. This tag flows through the pipeline to the history/exporter layer so the user knows whether a transcript came from microphone, computer audio, or typed text.

### Dual-Source (Meeting Mode)
In meeting mode, two audio sources run simultaneously:
- Microphone: captures user's speech
- Loopback (Stereo Mix): captures remote meeting audio (Zoom, Teams, etc.)

Both sources share the same VAD instance, STT model, translation engine, and TTS engine. The only splitting is at the capture layer (two `InputStream`s) and the per-source audio buffer state. There must NOT be two copies of VAD/STT/translation workers — use a single generic worker that accepts a `source` parameter.

---

## INPUT SOURCES

Support these sources from day one:
1. **Microphone** — default system input device
2. **System Audio (Loopback)** — Stereo Mix (preferred) → VB-Cable (fallback)
3. **Typed Text** — Ctrl+Enter from text entry field
4. **Meeting Audio** — mic + loopback simultaneously

Future (interface only, no implementation needed):
- Phone Calls (interface ready)
- WebRTC (interface ready)
- Browser Extension (interface ready)

---

## AUDIO PROCESSING CHAIN

Implement a modular processing chain. Each processor implements:

```python
class AudioProcessor(ABC):
    @abstractmethod
    async def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        ...
```

Chain (in order):
1. **RNNoise** — denoising via `rnnoise` Python bindings (stub if not available, pass-through)
2. **Automatic Gain Control** — target RMS level normalization with attack/release
3. **Normalization** — peak normalization to [-1.0, 1.0]
4. **Echo Cancellation** — interface only, no-op implementation (future: use `sounddevice` loopback reference)

All processors should be swappable without changing pipeline code. The pipeline should accept a `list[AudioProcessor]`.

---

## VAD

**Silero VAD** loaded from local cache (not downloaded — use `force_reload=False, trust_repo=True`).

- Threshold: `0.6`
- Min speech duration: `250ms` (≈5 frames at 30ms)
- Min silence duration: `150ms` (≈5 frames)
- Speech active tracking: toggle on when speech_prob > 0.6 for 3+ consecutive frames; toggle off when speech_prob < 0.6 for 5+ consecutive frames
- Single instance shared across all input sources
- Return: `VADResult(is_speech, speech_start, speech_end, confidence)`

**Important**: VAD must not be per-source. A single VAD instance processes tagged chunks from both mic and loopback.

---

## STT

**Faster-Whisper** with CUDA float16.

- Model: `Systran/faster-whisper-small` (cached in `~/.cache/huggingface/`)
- Device: `cuda`, compute_type: `float16`
- Beam size: `1` (for speed over accuracy)
- Language: auto-detect (pass `None` to model, capture `info.language` from result)
- Initial prompt: `"This is a Hindi and English conversation."` (improves code-switching accuracy)
- `no_speech_threshold=0.7`, `log_prob_threshold=-1.0`, `compression_ratio_threshold=2.4`
- Filter segments with `avg_logprob > -0.5` for noise rejection

**Important**: `faster-whisper` always processes 30s windows internally regardless of audio length. Each STT call has a ~500-600ms baseline on RTX 4060. Account for this in latency expectations.

**Important config settings**:
```python
class STTSettings:
    model: str = "Systran/faster-whisper-small"
    beam_size: int = 1
```

---

## LANGUAGE VALIDATION

Whisper returns a detected language code and confidence probability. For two-way conversation:

```
Whisper prediction (detected_lang, confidence)
  ↓
If confidence < 0.3: use last validated language (hysteresis)
If detected_lang matches source or target:
  - If same as last validated: accept immediately
  - If different from last validated AND confidence > 0.6: flip
Otherwise: keep last validated language
```

This prevents flickering between EN and HI on short ambiguous utterances.

---

## CONTEXT ENGINE

Maintain a sliding window of the last 3 translation segments. When translating, prepend the recent history as context:

```
EN: Hello, how are you?
HI: नमस्ते, आप कैसे हैं?
---
EN: I am fine, thank you.
HI: मैं ठीक हूं, धन्यवाद।
```

This context is passed to the translation engine as a `context` parameter (if the engine supports it). For Argos (which doesn't), it's informational only but ready for future providers.

Additionally:
- Track source and target language per segment
- Support seed context (pre-set from settings)
- `clear()` method to reset for new session

---

## TRANSLATION

**Primary**: Argos Translate (offline, EN↔HI)
**Fallback**: DeepL API (via proxy)

### Provider Contract
```python
class BaseTranslator(ABC):
    async def start()
    async def stop()
    async def translate(text, source_lang, target_lang, context=None) -> TranslationResult
```

### Argos Implementation
- `argostranslate.package.update_package_index()` (works offline from cached index)
- Install `en_hi` and `hi_en` packages from available packages
- `get_translation_from_codes("en", "hi")` 
- Cold start: ~4s (first translation). Warm: ~15ms.
- Must handle `source_lang` and `target_lang` swap for two-way mode

### DeepL Implementation
- `deepl.Translator(api_key)` — API key from settings
- Uses `httpx` through proxy
- Timeout: 5s per request
- Fallback when Argos returns empty or raises exception

### Translation Result
```python
@dataclass
class TranslationResult:
    original_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    is_final: bool
    input_source: str = "VOICE"  # "VOICE" | "COMPUTER_AUDIO" | "TEXT"
```

### Two-Way Mode Logic
```python
if translation_mode == "two_way" and detected_lang:
    if detected_lang == target_lang:
        # Swap: user is speaking the target language
        # Translate TO source language
        source, target = target, source  # swap
    elif detected_lang == source:
        # Keep as configured
        pass
```

---

## TEXT-TO-SPEECH

### Routing
```
Language family → Engine
  English (en)     → Piper (local, ~50ms latency)
  Hindi (hi)       → Sarvam API (cloud, 1-5s latency through proxy)
  Other            → Fallback to Piper if available, otherwise synthesize silence + log warning
```

### Piper Implementation (piper-tts v1.5.0)
**CRITICAL**: The installed `piper-tts` version uses `PiperVoice.load(model_path, config_path, use_cuda=False)`. There is NO `piper.download` module.

```python
# CORRECT API for piper-tts v1.5.0:
import piper
voice = piper.PiperVoice.load(
    model_path="path/to/voice.onnx",
    config_path="path/to/voice.onnx.json",
    use_cuda=False,
)
audio_chunks: list[piper.voice.AudioChunk] = list(voice.synthesize(text))
# Each chunk has: .audio_float_array (np.float32), .sample_rate (int)
```

Voice file discovery should search these paths in order:
1. Current working directory
2. `./voices/` subdirectory
3. Project root's sibling `voices/` directory
4. `~/.local/share/piper/voices/`
5. Any path from `PIPER_VOICE_DIR` environment variable

### Sarvam Implementation
- Endpoint: `POST https://api.sarvam.ai/v1/text-to-speech`
- JSON body: `{"text": text, "voice": "shubh", "language": "hi-IN"}`
- Header: `Authorization: Bearer {api_key}`
- Response: `{"audio": "<base64-encoded-wav-or-raw>"}`
- Decode: `base64.b64decode(data["audio"])` → `np.frombuffer(audio_bytes, dtype=np.float32)`
- Sample rate: 24000 Hz
- Proxy: Use `httpx.AsyncClient(proxies={"http://": "http://192.168.0.1:8090", "https://": "http://192.168.0.1:8090"})`
- Timeout: 30s
- API key from settings (`tts.sarvam_api_key`)

### Fallback Chain
When the preferred engine fails, try the other engine even if it's the wrong language family. Some synthesis is better than silence. If both fail, log an error and return silent audio (not None — pipeline must not crash).

---

## OUTPUT ROUTER

### Speaker
- `sounddevice.OutputStream` with sample rate from `(24000, 44100, 48000, 16000)` × channels `(2, 1)` fallback
- Callback-based: `self._speaker_queue: queue.Queue` filled by async consumer
- Volume control: multiply samples by `self._volume` (0.0–1.0)
- Mute: skip playback entirely
- Delay: `await asyncio.sleep(self._delay_s)` before enqueuing (for lip-sync adjustment)

### Virtual Microphone
- Same structure as speaker but output to VB-Cable device
- Only active when `virtual_mic_enabled=True` in settings
- VB-Cable device detection: search for `"CABLE"` or `"VB-"` in device name with `max_output_channels > 0`

### Subtitles
- `customtkinter.CTkToplevel` with `overrideredirect(True)`, `attributes("-topmost", True)`
- Two labels: original (smaller, gray) + translated (larger, bold white)
- Draggable via `<Button-1>` + `<B1-Motion>`
- Close on main window destruction

### History Database
```sql
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    created_at TEXT,
    blocks TEXT  -- JSON array of segment objects
);
```

Required CRUD:
- `save_session(title, blocks)` → INSERT
- `list_sessions(limit=50)` → SELECT id, title, created_at
- `load_session(session_id)` → SELECT title, blocks
- `delete_session(session_id)` → DELETE (this was missing in the previous version)

---

## TEXT MODE

Typed text enters the pipeline after STT (i.e., it skips audio capture, VAD, and ASR). The translation + TTS path is identical.

```python
async def process_text_input(text: str, source_lang: str):
    segment = TranscriptionSegment(
        text=cleaned_text, is_final=True,
        language=source_lang, confidence=1.0,
        input_source="TEXT",
    )
    # Push to translation_queue — same queue as voice segments use
    await self.translation_queue.put(segment)
```

**No duplicated translation logic. No duplicated TTS logic.**

Features:
- `Ctrl+Enter` to send
- Unicode support (Hindi, English, emoji)
- Long paragraphs (up to 5000 chars, reject beyond)
- Disabled when not in an active session

---

## SESSION HISTORY & EXPORT

### SQLite Schema
```sql
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    created_at TEXT,
    duration_seconds REAL,
    blocks TEXT  -- JSON: [{time, original, translated, source_lang, target_lang, input_source, latency_ms, provider, tts_engine}]
);
```

### Export Formats
| Format | Extension | Content |
|--------|-----------|---------|
| Plain Text | `.txt` | `[HH:MM:SS] [VOICE] Original\nTranslated\n\n` |
| JSON | `.json` | Full block data structure |
| SRT | `.srt` | SubRip format with 3s per block |
| WebVTT | `.vtt` | WebVTT format with cue timing |

---

## FLOATING SUBTITLES

- Always on top (`"-topmost"`)
- Dark background (`"#1E293B"`)
- Original text: 16pt, gray (`"#94A3B8"`)
- Translated text: 20pt bold, white (`"#F8FAFC"`)
- Width: 600px, height: auto
- Draggable by mouse
- Update via `update_text(original, translated, source_lang, target_lang, is_final)`

Future (interface only):
- Opacity slider
- Font size selection
- Click-through mode (`attributes("-transparentcolor", ...)`)
- Auto-hide after N seconds of no update

---

## DIAGNOSTICS

Live dashboard displaying:
- **GPU**: Model name, VRAM used/total, CUDA version
- **Latency per stage**: STT, Translation, TTS — average, p95, count
- **Queue sizes**: audio_queue, stt_queue, translation_queue, tts_queue
- **VAD state**: active/idle, speech probability
- **Pipeline state**: running/stopped/error, uptime
- **FPS**: audio chunks processed per second

Update frequency: every 500ms via a `_stats_worker` coroutine.

---

## USER INTERFACE

### Design Language
- Modern, minimal, professional
- Dark theme (`#1E293B` background, `#F8FAFC` text, `#3B82F6` accent)
- Rounded cards (corner_radius=12)
- Soft shadows (tkinter doesn't support, approximate with colored frames)
- smooth animations (tkinter doesn't support well — use `after()` for timed updates)
- Responsive layout (`grid_rowconfigure` / `grid_columnconfigure` with weights)

### Layout

```
┌──────────────────────────────────────────────────────┐
│ █ Top Bar: Logo | Status | GPU | Lang | Theme | ≡    │
├────────┬─────────────────────────────────────────────┤
│        │  ┌─────────────────┬─────────────────┐      │
│ Side   │  │ Source Speech   │ Translation     │      │
│ Bar    │  │ [VOICE] 00:00   │ [VOICE] 00:00   │      │
│        │  │ Hello           │ नमस्ते           │      │
│ Voice  │  │                 │                  │      │
│ Text   │  │ [TEXT] 00:01    │ [TEXT] 00:01    │      │
│ Meeting│  │ How are you?    │ आप कैसे हैं?     │      │
│ History│  └─────────────────┴─────────────────┘      │
│ Diag   │                                             │
│        │  ┌──────────────────────────────────────┐   │
│        │  │ Type a message... (Ctrl+Enter)  [▶]  │   │
│        │  └──────────────────────────────────────┘   │
├────────┴─────────────────────────────────────────────┤
│ █ Mic █ Speaker █ V.Mic █ [0ms] █ ▶ Start █ ■ Stop  │
└──────────────────────────────────────────────────────┘
```

### Widgets
- **TranscriptPanel**: `CTkTextbox` with tags for timestamp (gray), badge (voice/text/computer), original (dark gray), translated (bold black), partial (gray italic). **No `font` parameter in `tag_config`** — set font on the widget itself.
- **ControlBar**: Start/Stop buttons, status pill (colored badge showing "Listening", "Processing", "Speaking", "Error")
- **Sidebar**: Navigation buttons for Voice, Text, Meeting, History, Diagnostics, Settings
- **StatusIndicator**: Shows GPU model, language pair, pipeline status
- **LatencyBadge**: Colored badge showing current end-to-end latency

---

## MEETING MODE

Active when both microphone AND loopback are capturing simultaneously.

- Two `sounddevice.InputStream` instances: one for mic, one for Stereo Mix
- Both feed the shared VAD → STT → Translation → TTS pipeline
- Source tagging (`"mic"` vs `"loopback"`) distinguishes speakers
- Floating subtitles show both sources in sequence
- Virtual mic output routes translated audio to meeting participants
- Echo suppression: when loopback is active, DO NOT suppress mic during TTS playback (the loopback is the remote audio, mic is local user — no echo to cancel)

---

## CODE QUALITY

### Standards
- Python 3.11 compatible syntax (no 3.12+ features)
- Strong typing everywhere (function signatures, dataclasses, generics where appropriate)
- Dataclasses for all data transfer objects
- `ABC` + `abstractmethod` for all service interfaces
- Dependency injection via constructor parameters (no service locators, no globals)
- Structured logging via `logging.getLogger(__name__)` with standard format
- No file longer than 400 lines (except `main_window.py` and `pipeline.py` which can be up to 500)
- No circular imports (use TYPE_CHECKING for type hints if needed)
- `async def` for all I/O-bound operations, `run_in_executor` for CPU-bound (STT, Piper)
- `finally` blocks for cleanup — services must be stoppable

### Logging Format
```
%(asctime)s | %(name)-30s | %(levelname)-8s | %(message)s
```

### Error Handling
- Services raise `ServiceError` (custom exception) on startup failure
- Pipeline catches and logs all worker exceptions, continues running other workers
- UI shows errors via status pill (colored badge), not modal dialogs
- Translation timeout: 5s, return empty result (don't crash pipeline)
- TTS failure: log error, return silent audio, continue

---

## TESTING

### Test Framework: pytest

### Coverage Areas
- Unit tests for each service in isolation (mock dependencies)
- Integration tests for the full pipeline (mock audio input, real VAD + STT + translation)
- Latency regression tests (ensure STT/translation/TTS stays within budget)
- Audio input tests (device enumeration, sample rate fallback)
- History database CRUD tests (especially `delete_session`)
- Pipeline restart tests (rapid start/stop/start cycles)
- Two-way translation tests (language flip detection)

### Test Structure
```
tests/
├── conftest.py              # Fixtures: mock audio, temp_db, settings override
├── test_audio_input.py      # Device discovery, stream start/stop, callback
├── test_vad.py              # Speech detection, silence timeout, edge cases
├── test_stt.py              # GPU availability, transcription, language detection
├── test_translation.py      # Argos + DeepL, two-way swap, context injection
├── test_tts.py              # Piper + Sarvam routing, fallback chain
├── test_pipeline.py         # Worker lifecycle, restart, source tagging
├── test_history.py          # CRUD, export formats, delete_session
└── integration/
    ├── __init__.py
    └── test_full_pipeline.py # End-to-end mock audio → transcript → history
```

---

## FUTURE EXTENSION POINTS

Design interfaces now for these future capabilities (no implementation required):

- **Voice Cloning**: `BaseTTS` extended with `clone_voice(audio_sample)` 
- **Speaker Diarization**: New `services/diarization/` module, pipeline emits speaker labels
- **AI Meeting Summary**: New `services/summary/` module, triggered on session end
- **Plugin System**: `app/plugin_manager.py` loads `.py` plugins from `~/.talksync/plugins/`
- **REST API**: `FastAPI` wrapper around `PipelineManager` for remote control
- **WebSocket API**: Real-time transcript streaming to web clients
- **Cloud Sync**: `HistoryDatabase` syncs to S3/Blob via `HistorySyncProvider` interface

---

## WORKFLOW

Do NOT start implementing immediately.

### Phase 1 — Design (current phase)
- [ ] Agree on architecture, folder structure, interfaces, dependency graph
- [ ] Document pipeline data flow (sources → queues → workers → sinks)
- [ ] Create UI wireframes (ASCII or tool)
- [ ] Review before proceeding

### Phase 2 — Core Engine
- [ ] `config/settings.py` — all pydantic settings models
- [ ] `core/interfaces.py` — all dataclasses and abstract base classes
- [ ] `app/pipeline.py` — unified pipeline orchestrator (worker factory, restart logic)
- [ ] `app/application.py` — DI container, service wiring

### Phase 3 — Audio Services
- [ ] `services/audio/input.py` — SoundDeviceInput (mic + loopback per source tagging)
- [ ] `services/audio/output.py` — OutputRouter (speaker + virtual mic with rate/channel fallback)
- [ ] `services/audio_processing/` — RNNoise, AGC, Normalizer chain
- [ ] `services/audio/loopback.py` — Stereo Mix / VB-Cable discovery

### Phase 4 — Translation Services
- [ ] `services/translation/argos.py` — offline EN↔HI
- [ ] `services/translation/deepl.py` — cloud fallback through proxy
- [ ] `services/translation/factory.py` — fallback chain
- [ ] `services/translation/language_validator.py` — hysteresis
- [ ] `services/translation/context_engine.py` — sliding window

### Phase 5 — TTS Services
- [ ] `services/tts/piper.py` — correct `PiperVoice.load()` API
- [ ] `services/tts/sarvam.py` — proxy-aware HTTP client
- [ ] `services/tts/router.py` — language → engine routing

### Phase 6 — UI
- [ ] `ui/main_window.py` — layout, sidebar, workspace, control bar
- [ ] `ui/widgets/` — transcript panel, status indicator, latency badge
- [ ] `ui/dialogs/` — audio settings, language selector, history viewer, diagnostics
- [ ] `services/subtitle/` — floating overlay

### Phase 7 — Remaining Services
- [ ] `services/history/database.py` — SQLite CRUD with `delete_session()`
- [ ] `services/history/exporter.py` — TXT/JSON/SRT/WebVTT
- [ ] `services/diagnostics/monitor.py` — live latency/GPU monitoring
- [ ] `services/stt/faster_whisper.py` — GPU whisper with proper settings

### Phase 8 — Testing
- [ ] Unit tests for every service
- [ ] Integration tests for full pipeline
- [ ] Latency regression tests
- [ ] Pipeline restart stress tests

**Never skip a phase. Never sacrifice architecture for speed.**

The final product should feel like a polished commercial Windows desktop application, not a prototype. Every error should be logged. Every edge case should be handled. Every service should be stoppable and restartable independently.
