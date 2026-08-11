# Project: TalkSync AI (Follow-Up Sprint)

## Overview
TalkSync AI is a real-time speech-to-speech translation desktop application.
Sprint Focus: DeepL socket check optimization, headphone audio device auto-detection, OpenAI STT end-to-end verification, pipeline latency profiling, and QA report generation.

## Feature Inventory
| # | Feature | Description | Target File(s) | Status |
|---|---------|-------------|----------------|--------|
| 1 | DeepL Fast Startup | Fast 1s socket check before fallback to direct connection | `services/translation/deepl.py` | PLANNED |
| 2 | Audio Device Auto-Detection | Prefer headphones/headsets, handle fallback for index 37, log selected devices | `services/audio/input.py`, `services/audio/loopback.py` | PLANNED |
| 3 | OpenAI STT Verification | Verify `gpt-4o-transcribe` in `.env`, `app/application.py`, and run `test_openai_stt.py` | `app/application.py`, `tests/test_openai_stt.py` | PLANNED |
| 4 | Latency Profiling | Profile VAD, STT queueing, DeepL latency, Sarvam TTS latency | `QA_REPORT.md` | PLANNED |
| 5 | QA Report & Pytest | Run `pytest tests/test_pipeline_accuracy.py`, produce `QA_REPORT.md` | `QA_REPORT.md` | PLANNED |

## Code Layout
- `services/translation/deepl.py`: DeepL translation provider with proxy & direct connectivity logic.
- `services/audio/input.py`: Microphone audio capture & device query/selection.
- `services/audio/loopback.py`: WASAPI loopback audio capture & device query/selection.
- `app/application.py`: Main application setup and STT engine initialization.
- `tests/test_openai_stt.py`: Integration test for OpenAI STT.
- `tests/test_pipeline_accuracy.py`: Full pipeline accuracy pytest suite.
- `QA_REPORT.md`: Comprehensive QA documentation.
