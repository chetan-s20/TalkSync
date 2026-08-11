# Dispatch — worker_m4_remediation

**Role**: `teamwork_preview_worker`  
**Working Directory**: `d:\talksync\talksync\.agents\worker_m4_remediation`  
**Task**: Fix 3 specific issues identified by Challenger 1 for Milestone M4  
**Original Request Path**: `d:\talksync\talksync\.agents\orchestrator\ORIGINAL_REQUEST.md`  

## Objectives

Fix the following 3 issues identified during Challenger testing:

1. **`app/pipeline.py` Queue Gating Fix**:
   - In `app/pipeline.py` (around lines 678 & 687), `await self.tts_queue.put(result)` is inside `try...except asyncio.QueueFull`.
   - `await self.tts_queue.put(...)` blocks indefinitely when full rather than raising `asyncio.QueueFull`.
   - Change to `self.tts_queue.put_nowait(result)` (or use `try: self.tts_queue.put_nowait(result) except asyncio.QueueFull: ...`) so full queues drop or handle gracefully without hanging.

2. **`tests/test_openai_stt.py` Missing Decorator**:
   - Add `@pytest.mark.asyncio` decorator above `async def test_openai_stt()` in `tests/test_openai_stt.py`.

3. **`tests/test_pipeline_accuracy.py` Confidence & Language Handling**:
   - Fix `tests/test_pipeline_accuracy.py::TestPipelineAccuracyAndLatency::test_hindi_pipeline_accuracy_and_latency` so it passes reliably. Ensure audio fixture or language hints allow STT confidence >= 0.4.

4. **Run Test Suite**:
   - Execute `python -m pytest tests/ -v --tb=short` and verify all tests pass cleanly.

## Mandatory Integrity Warning

## 2026-08-05T17:12:27Z
Worker assignment: Fix the 3 issues identified by Challenger 1 for M4.

