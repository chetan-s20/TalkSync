# Master Project Plan: TalkSync Issue Resolution & Hardening

## Overview
Orchestrate diagnosis, fix, unit testing, and E2E verification of speech-to-text (STT), computer audio loopback capture, translation pipeline, and pywebview UI bridge in TalkSync.

## Phase 0: Survey & Scope Mapping (Parallel Track Initializer)
- [ ] Dispatch 3 Explorers / Spec Miners to map codebase architecture, entry points, dependencies, audio pipelines (sounddevice/soundcard/wasapi), VAD, STT workers, translation workers, pywebview JS-Python bridge, and test suite layout.
- [ ] Create `PROJECT.md` with Feature Inventory, Architecture, Code Layout, and Milestones.
- [ ] Create `TEST_INFRA.md` for parallel E2E testing track.

## Phase 1: Milestone Decomposition & Parallel Track Execution
- [ ] Track A (E2E Testing Track): Develop multi-tiered test suite (Tiers 1-4) per requirements in `ORIGINAL_REQUEST.md`. Publish `TEST_READY.md`.
- [ ] Track B (Implementation Track):
  - [ ] Milestone 1: Audio Capture & VAD Reliability (Microphone + WASAPI Loopback stream initialization, Silero VAD event loop, device index 16 verification).
  - [ ] Milestone 2: STT & Translation Pipeline Execution (Transcription trigger, queue non-blocking flow, API key handling, async event loop safety).
  - [ ] Milestone 3: Dynamic UI Bridge Integration (pywebview JS-Python event emission, transcript/translation state updates, non-blocking UI render loop).

## Phase 2: Final Integration & Coverage Hardening
- [ ] Pass 100% E2E test suite (Tiers 1-4).
- [ ] Tier 5 Adversarial Coverage Hardening (Challenger stress testing, edge case handling, zero crash guarantee).
- [ ] Forensic Audit & Gate Verification.
- [ ] Final Handoff and Sentinel Notification.
