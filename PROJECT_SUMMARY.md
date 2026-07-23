# TalkSync Pro — Project Summary

## Overview

Real-time bidirectional speech translation app (EN ↔ HI) built with Python, CustomTkinter GUI, faster-whisper STT, and Piper/Kokoro/Sarvam TTS.

## Architecture

Concurrent queue-based PipelineManager; stages: mic → VAD → STT → Translator → TTS → AudioRouter

## Tech Stack

- **UI**: CustomTkinter
- **Audio**: sounddevice (low-latency capture/playback), optional RNNoise
- **VAD**: Silero VAD
- **STT**: faster-whisper-small (GPU fp16, CUDA)
- **Translation**: Argos (offline primary) → DeepL (cloud fallback)
- **TTS**: Piper / Kokoro (offline), Sarvam AI (Indic cloud)

## Python Files

| Module | Key Implementation |
|--------|-----------------|
| `main.py` | Entry point, argparse, signal handling |
| `core/interfaces.py` | Data classes (AudioChunk, TranscriptionSegment, TranslationResult, SynthesisResult, VADResult) + ABCs |
| `core/pipeline_manager.py` | Async orchestration with 6 workers |
| `audio/input.py` | SoundDeviceInput — mic/loopback capture |
| `audio/router.py` | AudioRouter — playback, resampling, volume |
| `audio/buffer.py` | Ring buffer for streaming |
| `audio/denoiser.py` | Optional RNNoise wrapper |
| `audio/rnnoise_native.py` | ctypes RNNoise binding |
| `vad/silero_vad.py` | Silero VAD with tail silence |
| `stt/faster_whisper.py` | FasterWhisperSTT — dedicated executor |
| `stt/base.py` | BaseSTT ABC |
| `translation/deepl.py` | DeepL cloud translator |
| `translation/argos.py` | Argos offline translator |
| `translation/context_engine.py` | Conversation context for translation |
| `translation/language_validator.py` | Hysteresis-based language validator |
| `translation/translation_factory.py` | Fallback chain creation |
| `tts/piper.py` | Piper offline TTS |
| `tts/kokoro.py` | Kokoro ONNX TTS |
| `tts/sarvam.py` | Sarvam AI cloud TTS |
| `tts/router.py` | MultilingualTTSRouter |
| `ui/main_window.py` | Main GUI with device/language/speaker popups |
| `utils/logger.py` | Centralized logging |
| `utils/latency.py` | Latency tracking |
| `utils/languages.py` | Language code mappings |
| `utils/keywords.py` | Keyword replacement |
| `utils/device.py` | Audio device enumeration |

## Key Constraints

- Corporate proxy blocks internet model downloads; models must be pre-cached or transferred via USB
- Cached models: faster-whisper-small, Silero VAD, Piper en_US-lessac-medium
- No CPU torch in venv; CUDA torch linked via `.pth` file
- VB-Cable installed for loopback/computer audio

## Next Features

1. Virtual Microphone — route translated audio to VB-Cable
2. Meeting Notes Export
3. PiP Floating Subtitles
4. English → Hindi offline translation (NLLB-distilled-600M)
5. Adaptive noise suppression
6. Language auto-detection for two-way mode
7. Custom wake word / push-to-talk
8. Multi-language support (beyond EN/HI)
9. Dark theme
10. Audio waveform visualization
