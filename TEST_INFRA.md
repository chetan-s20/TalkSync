# E2E Test Infra: TalkSync AI

## Test Philosophy
- Opaque-box, requirement-driven testing. No dependency on private implementation design.
- Systematic 4-tier design: Category-Partition (Tier 1), Boundary Value Analysis (Tier 2), Pairwise Combinations (Tier 3), Real-World Application Workloads (Tier 4).

## Feature Inventory & Test Matrix
| # | Feature | Requirement | Tier 1 (Feature) | Tier 2 (Boundary) | Tier 3 (Pairwise) | Tier 4 (Scenario) |
|---|---------|-------------|:----------------:|:-----------------:|:-----------------:|:-----------------:|
| 1 | Audio Stream Initialization | ORIGINAL_REQUEST §R1 | 5 cases | 5 cases | ✓ | ✓ |
| 2 | Silero VAD & Onset Detection | ORIGINAL_REQUEST §R1 | 5 cases | 5 cases | ✓ | ✓ |
| 3 | STT Transcription Trigger | ORIGINAL_REQUEST §R2 | 5 cases | 5 cases | ✓ | ✓ |
| 4 | Translation & Fallback Handling | ORIGINAL_REQUEST §R2 | 5 cases | 5 cases | ✓ | ✓ |
| 5 | PyWebView UI Bridge Event Dispatch | ORIGINAL_REQUEST §R3 | 5 cases | 5 cases | ✓ | ✓ |

## Test Architecture
- Test runner: `pytest`
- Location: `tests/` directory (`tests/test_audio_input.py`, `tests/test_vad.py`, `tests/test_stt.py`, `tests/test_translation.py`, `tests/integration/`, `tests/boundary/`)
- Target minimum threshold: 50+ test cases across Tiers 1-4.

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Continuous Hindi/English Speech Stream | Mic Audio, VAD, STT, Translation, UI Bridge | High |
| 2 | Loopback Audio Playback Translation | Loopback Stream, VAD, STT, Translation, UI Log | High |
| 3 | Bluetooth Headset (Boult Airbass 16) Hotplug/Fallback | Device Auto-Detect, Mic Stream, VAD | Medium |
| 4 | DeepL API Key Failover to Argos | Translation Factory, Argos Fallback, UI Output | Medium |
| 5 | Rapid Session Start/Stop Toggle | UI Bridge Lifecycle, Event Loop Safety, Worker Cleanup | High |
