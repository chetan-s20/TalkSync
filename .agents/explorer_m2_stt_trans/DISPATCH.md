## 2026-08-07T10:25:33Z
You are Explorer for Milestone 2 (STT & Translation Execution Pipeline).
Working directory: d:\talksync\talksync\.agents\explorer_m2_stt_trans
Read d:\talksync\talksync\.agents\ORIGINAL_REQUEST.md, d:\talksync\talksync\PROJECT.md, and d:\talksync\talksync\.agents\explorer_stt_trans\handoff.md.

Task:
Formulate a precise implementation plan and fix strategy for Milestone 2: STT & Translation Execution Pipeline.

Analyze and plan fixes for:
1. Persistent Asyncio Loop in `app/bridge.py`:
   - Inspect `ApiBridge.start_session()` and `_run_async()`. Explain how to replace the temporary loop creation and immediate `loop.close()` with a persistent background event loop or thread-decoupled loop that keeps background worker tasks alive.
2. DeepL Init Exception & Fallback in `services/translation/deepl.py` and `services/translation/factory.py`:
   - Fix `DeepLTranslator.start()` so that invalid API keys or connection failures raise an exception, allowing `TranslationFactory.create()` to fall back to `ArgosTranslator`.
3. OpenAI STT Fallback in `services/stt/factory.py` & `services/stt/openai_stt.py`:
   - Ensure `STTFactory.create()` catches OpenAI initialization/key errors and falls back to `FasterWhisperSTT`.
4. Test execution verification commands:
   - Identify tests in `tests/test_stt.py`, `tests/test_openai_stt.py`, `tests/test_translation.py`, `tests/unit/test_partial_translation.py`, `tests/unit/test_translation_queue_pruning.py`, `tests/integration/test_full_pipeline.py`.

Write your analysis report to d:\talksync\talksync\.agents\explorer_m2_stt_trans\analysis.md and handoff report to d:\talksync\talksync\.agents\explorer_m2_stt_trans\handoff.md. Do NOT modify source code files directly.
