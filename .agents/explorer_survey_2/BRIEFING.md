# BRIEFING — 2026-08-06T12:18:05Z

## Mission
Investigate TalkSync AI UI State Management, OpenAI/Faster Whisper STT Language Filtering, and Translation & TTS Stage Latencies.

## 🔒 My Identity
- Archetype: explorer
- Roles: read-only explorer
- Working directory: d:\talksync\talksync\.agents\explorer_survey_2
- Original parent: fc8b1a40-6e52-42b4-a1df-f0f6350ca52d
- Milestone: exploration phase 2

## 🔒 Key Constraints
- Read-only investigation — do NOT implement code fixes in source tree
- Output reports to d:\talksync\talksync\.agents\explorer_survey_2\analysis.md and handoff.md

## Current Parent
- Conversation ID: fc8b1a40-6e52-42b4-a1df-f0f6350ca52d
- Updated: 2026-08-06T12:18:05Z

## Investigation State
- **Explored paths**: `ui/main_window.py`, `ui/dialogs/`, `ui/widgets/`, `app/application.py`, `app/pipeline.py`, `services/stt/openai_stt.py`, `services/stt/faster_whisper.py`, `services/translation/deepl.py`, `services/translation/argos.py`, `services/tts/`
- **Key findings**:
  1. UI State: Un-tracked `SessionSummaryDialog` spawns duplicates on quick session stop. `_restart_pipeline` omits `btn_play` `⏳` loading state. Hardcoded light-mode hex colors break dark appearance mode. Dead button `btn_model` in `LanguageSelectorDialog`.
  2. STT Language Filtering: `OpenAISTT` requests `response_format="json"`, which omits the `language` field in API responses, causing `detected_lang` to evaluate to `""` and bypassing `pipeline.py`'s allowed language validation filter.
  3. Latency: `MultilingualTTSRouter` lazy initialization causes 1-3s first-utterance latency. `SarvamTTS` creates a new `httpx.AsyncClient` on every request and has 1.0s sleep retry delays. SAPI5 fallback spawns PowerShell subprocesses (200-500ms per utterance).
- **Unexplored areas**: None (all assigned scope explored)

## Key Decisions Made
- Exploration complete. Published analysis.md and handoff.md.

## Artifact Index
- DISPATCH.md — Dispatch instructions log
- BRIEFING.md — Working memory index
- progress.md — Liveness heartbeat
- analysis.md — Detailed exploration analysis report
- handoff.md — 5-component handoff report
