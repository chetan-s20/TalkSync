# Task Dispatch — worker_m4

**Identity**: `worker_m4` (`teamwork_preview_worker`)  
**Working Directory**: `d:\talksync\talksync\.agents\worker_m4`  
**Scope**: Milestone M4: Diagnostics Report & Full Test Suite Execution  
**Original Request Path**: `d:\talksync\talksync\.agents\orchestrator\ORIGINAL_REQUEST.md`  

## Objectives

1. Produce `d:\talksync\talksync\DIAGNOSTICS_REPORT.md` covering all 6 required sections:
   - **Echo suppression**: before/after analysis, mute window duration (TTS + 500ms), queue gating mechanism, VB-Cable coverage.
   - **Mic RMS levels**: measured RMS from device 35, noise floor evaluation, VAD threshold tuning (0.45), AGC target RMS (0.2), gate threshold (0.0003).
   - **Bidirectional routing**: EN->HI (Panel A) and HI->EN (Panel B) translation pipelines, source tagging (`VOICE` vs `COMPUTER_AUDIO`), TTS routing, speaker toggle flags.
   - **Device auto-detection**: startup device checking, fallback handling, score-based selection, startup logging.
   - **Latency per stage**: breakdown for VAD, OpenAI STT (`gpt-4o-transcribe`), DeepL, TTS, total E2E latency.
   - **All files changed & remaining issues**: complete table of modified files with exact rationale and recommendations.

2. Execute full test suite:
   - Command: `python -m pytest tests/ -v --tb=short`
   - Verify all tests pass cleanly without errors or tracebacks.

## Mandatory Integrity Warning
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.
