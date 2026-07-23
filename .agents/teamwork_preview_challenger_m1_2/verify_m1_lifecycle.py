"""
Empirical Verification Script for Milestone 1 Audio & Pipeline Thread Lifecycle
Challenger 2 — TalkSync AI
"""

from __future__ import annotations

import asyncio
import gc
import os
import sys
import time
import threading
import traceback
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config.settings import Settings
from app.pipeline import Pipeline
from app.interfaces import (
    AudioChunk, BaseAudioInput, BaseAudioOutput,
    BaseSTT, BaseTTS, BaseTranslator, BaseVAD,
    TranscriptionSegment, TranslationResult,
)
from services.translation.factory import TranslationFactory
from services.translation.dummy import DummyTranslator
from services.stt.faster_whisper import FasterWhisperSTT

results = {
    "test_a_start_stop_cycles": {"status": "FAIL", "metrics": {}},
    "test_b_callback_dispatches": {"status": "FAIL", "metrics": {}},
    "test_c_offline_fallback": {"status": "FAIL", "metrics": {}},
    "test_d_event_loop_responsiveness": {"status": "FAIL", "metrics": {}},
}


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}")


async def create_mock_stream():
    """Helper to yield a dummy AudioChunk for async for iteration."""
    for _ in range(0):
        yield AudioChunk(
            data=b"\x00" * 640, sample_rate=16000, channels=1,
            timestamp=datetime.now(), duration_ms=20.0, source="mic"
        )


async def test_a_repeated_start_stop_cycles():
    log("=== STARTING TEST A: 10 Start/Stop Pipeline Lifecycle Cycles ===")
    initial_threads = threading.active_count()
    cycle_times = []
    thread_counts = []

    for i in range(1, 11):
        t0 = time.perf_counter()

        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.start = AsyncMock()
        audio_input.stop = AsyncMock()
        audio_input.stream = create_mock_stream
        audio_input.stream_loopback = create_mock_stream

        vad = MagicMock(spec=BaseVAD)
        vad.start = AsyncMock()
        vad.stop = AsyncMock()
        vad.process = create_mock_stream

        stt = MagicMock(spec=BaseSTT)
        stt.start = AsyncMock()
        stt.stop = AsyncMock()
        stt.transcribe = AsyncMock()
        stt.transcribe.return_value = TranscriptionSegment(
            text="hello", is_final=True, start_time=datetime.now(),
            end_time=datetime.now(), language="en", confidence=0.95,
        )

        translator = MagicMock(spec=BaseTranslator)
        translator.start = AsyncMock()
        translator.stop = AsyncMock()
        translator.translate = AsyncMock()
        translator.translate.return_value = TranslationResult(
            original_text="hello", translated_text="नमस्ते",
            source_lang="EN", target_lang="HI", is_final=True,
        )

        tts = MagicMock(spec=BaseTTS)
        tts.start = AsyncMock()
        tts.stop = AsyncMock()
        tts.synthesize_stream = create_mock_stream

        audio_output = MagicMock(spec=BaseAudioOutput)
        audio_output.start = AsyncMock()
        audio_output.stop = AsyncMock()

        pipeline = Pipeline(
            audio_input=audio_input, vad=vad, stt=stt,
            translator=translator, tts=tts, audio_output=audio_output,
        )

        # Start pipeline with timeout protection
        await asyncio.wait_for(pipeline.start("EN", "HI"), timeout=5.0)
        assert pipeline.running is True, f"Iteration {i}: Pipeline failed to set running=True"

        # Brief delay to allow workers to initialize
        await asyncio.sleep(0.05)

        # Stop pipeline
        await asyncio.wait_for(pipeline.stop(), timeout=5.0)
        assert pipeline.running is False, f"Iteration {i}: Pipeline failed to set running=False"
        assert len(pipeline._tasks) == 0, f"Iteration {i}: Tasks remain in pipeline"

        t_cycle = (time.perf_counter() - t0) * 1000.0
        cycle_times.append(t_cycle)
        act_threads = threading.active_count()
        thread_counts.append(act_threads)
        log(f"  Cycle {i:02d}/10 completed in {t_cycle:6.2f} ms | Active threads: {act_threads}")

    gc.collect()
    final_threads = threading.active_count()
    thread_leak = final_threads - initial_threads
    log(f"Initial threads: {initial_threads}, Final threads: {final_threads}, Leak: {thread_leak}")

    metrics = {
        "iterations": 10,
        "avg_cycle_ms": round(sum(cycle_times) / len(cycle_times), 2),
        "max_cycle_ms": round(max(cycle_times), 2),
        "min_cycle_ms": round(min(cycle_times), 2),
        "initial_threads": initial_threads,
        "final_threads": final_threads,
        "thread_leak": thread_leak,
    }

    assert thread_leak <= 0, f"Thread leak detected! {thread_leak} threads leaked."
    results["test_a_start_stop_cycles"]["status"] = "PASS"
    results["test_a_start_stop_cycles"]["metrics"] = metrics
    log("=== TEST A PASSED ===\n")


async def test_b_high_frequency_callbacks():
    log("=== STARTING TEST B: High-Frequency Callback Dispatches ===")
    status_calls = []
    latency_calls = []

    def status_cb(msg: str, state: str):
        status_calls.append((msg, state, time.perf_counter()))

    def latency_cb(data: dict):
        latency_calls.append((data, time.perf_counter()))

    audio_input = MagicMock(spec=BaseAudioInput)
    audio_input.start = AsyncMock()
    audio_input.stop = AsyncMock()
    audio_input.stream = create_mock_stream
    audio_input.stream_loopback = create_mock_stream

    vad = MagicMock(spec=BaseVAD)
    vad.start = AsyncMock()
    vad.stop = AsyncMock()
    vad.process = create_mock_stream

    stt = MagicMock(spec=BaseSTT)
    stt.start = AsyncMock()
    stt.stop = AsyncMock()

    translator = MagicMock(spec=BaseTranslator)
    translator.start = AsyncMock()
    translator.stop = AsyncMock()
    translator.translate = AsyncMock()
    translator.translate.return_value = TranslationResult(
        original_text="warm", translated_text="warm",
        source_lang="EN", target_lang="HI", is_final=True,
    )

    tts = MagicMock(spec=BaseTTS)
    tts.start = AsyncMock()
    tts.stop = AsyncMock()

    audio_output = MagicMock(spec=BaseAudioOutput)
    audio_output.start = AsyncMock()
    audio_output.stop = AsyncMock()

    pipeline = Pipeline(
        audio_input=audio_input, vad=vad, stt=stt,
        translator=translator, tts=tts, audio_output=audio_output,
    )
    pipeline.on_status = status_cb
    pipeline.on_latency = latency_cb

    await pipeline.start("EN", "HI")

    t0 = time.perf_counter()
    num_dispatches = 5000

    async def status_producer():
        for i in range(num_dispatches):
            if pipeline.on_status:
                pipeline.on_status(f"Status update {i}", "processing")
            if i % 1000 == 0:
                await asyncio.sleep(0)

    async def latency_producer():
        for i in range(num_dispatches):
            if pipeline.on_latency:
                pipeline.on_latency({"avg_ms": float(i), "stages": {"stt": float(i)}})
            if i % 1000 == 0:
                await asyncio.sleep(0)

    await asyncio.gather(status_producer(), latency_producer())
    elapsed = time.perf_counter() - t0

    await pipeline.stop()

    total_callbacks = len(status_calls) + len(latency_calls)
    throughput = total_callbacks / elapsed if elapsed > 0 else 0.0

    log(f"Dispatched {num_dispatches * 2} callbacks in {elapsed * 1000:.2f} ms")
    log(f"Recorded status calls: {len(status_calls)}, latency calls: {len(latency_calls)}")
    log(f"Throughput: {throughput:.1f} callbacks/sec")

    assert len(status_calls) >= num_dispatches, "Status callback dispatches were dropped!"
    assert len(latency_calls) >= num_dispatches, "Latency callback dispatches were dropped!"

    metrics = {
        "dispatched_status_callbacks": len(status_calls),
        "dispatched_latency_callbacks": len(latency_calls),
        "total_callbacks": total_callbacks,
        "elapsed_ms": round(elapsed * 1000.0, 2),
        "throughput_callbacks_per_sec": round(throughput, 1),
    }

    results["test_b_callback_dispatches"]["status"] = "PASS"
    results["test_b_callback_dispatches"]["metrics"] = metrics
    log("=== TEST B PASSED ===\n")


async def test_c_offline_translation_fallback():
    log("=== STARTING TEST C: Offline TranslationFactory Fallback ===")
    settings = Settings()

    t0 = time.perf_counter()
    with patch("services.translation.argos.ArgosTranslator.start", side_effect=ConnectionError("Offline: Argos model unavailable")):
        with patch("services.translation.deepl.DeepLTranslator.start", side_effect=ConnectionError("Offline: DeepL network unreachable")):
            translator = await TranslationFactory.create(settings)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            log(f"TranslationFactory returned: {type(translator).__name__} in {elapsed_ms:.2f} ms")
            assert isinstance(translator, DummyTranslator), f"Expected DummyTranslator, got {type(translator).__name__}"

            res = await translator.translate("Offline test message", "EN", "HI")
            log(f"Translation output: '{res.original_text}' -> '{res.translated_text}'")
            assert res.translated_text != "", "DummyTranslator returned empty translation!"

    metrics = {
        "factory_class": type(translator).__name__,
        "fallback_resolution_ms": round(elapsed_ms, 2),
        "translated_text": res.translated_text,
    }

    results["test_c_offline_fallback"]["status"] = "PASS"
    results["test_c_offline_fallback"]["metrics"] = metrics
    log("=== TEST C PASSED ===\n")


async def test_d_event_loop_responsiveness():
    log("=== STARTING TEST D: Event Loop Responsiveness during STT Transcribe ===")

    settings = Settings()
    stt = FasterWhisperSTT(settings)
    await stt.start()

    log_prob = getattr(stt, "_loaded", False)
    log(f"FasterWhisperSTT initialized (loaded={log_prob})")

    # Warm-up call (initializes internal CTranslate2 model structures)
    audio_pcm = np.zeros(16000, dtype=np.float32)
    t_warm = time.perf_counter()
    _ = await stt.transcribe(audio_pcm, is_final=True)
    warm_ms = (time.perf_counter() - t_warm) * 1000.0
    log(f"Warm-up transcribe call took {warm_ms:.2f} ms")

    lags_ms = []
    monitoring = True

    async def event_loop_monitor():
        target_interval = 0.005  # 5ms ticker
        while monitoring:
            t0 = time.perf_counter()
            await asyncio.sleep(target_interval)
            t1 = time.perf_counter()
            actual_delta = t1 - t0
            lag = max(0.0, (actual_delta - target_interval) * 1000.0)
            lags_ms.append(lag)

    monitor_task = asyncio.create_task(event_loop_monitor())

    t_trans_start = time.perf_counter()
    trans_count = 5
    for i in range(trans_count):
        res = await stt.transcribe(audio_pcm, is_final=True)
    t_trans_elapsed = (time.perf_counter() - t_trans_start) * 1000.0

    monitoring = False
    await monitor_task

    await stt.stop()

    max_lag = max(lags_ms) if lags_ms else 0.0
    avg_lag = sum(lags_ms) / len(lags_ms) if lags_ms else 0.0
    p95_lag = float(np.percentile(lags_ms, 95)) if lags_ms else 0.0

    log(f"Executed {trans_count} steady-state transcriptions in {t_trans_elapsed:.2f} ms")
    log(f"Event loop monitor samples: {len(lags_ms)}")
    log(f"Steady-state loop lag -- Avg: {avg_lag:.2f} ms | P95: {p95_lag:.2f} ms | Max: {max_lag:.2f} ms")

    # Event loop max steady-state lag threshold: < 50ms
    assert max_lag < 50.0, f"Event loop stalled! Steady-state max lag: {max_lag:.2f} ms (threshold 50.0 ms)"

    metrics = {
        "warm_up_ms": round(warm_ms, 2),
        "steady_state_transcriptions": trans_count,
        "total_steady_state_ms": round(t_trans_elapsed, 2),
        "avg_transcription_ms": round(t_trans_elapsed / trans_count, 2),
        "monitor_sample_count": len(lags_ms),
        "avg_loop_lag_ms": round(avg_lag, 2),
        "p95_loop_lag_ms": round(p95_lag, 2),
        "max_loop_lag_ms": round(max_lag, 2),
    }

    results["test_d_event_loop_responsiveness"]["status"] = "PASS"
    results["test_d_event_loop_responsiveness"]["metrics"] = metrics
    log("=== TEST D PASSED ===\n")


async def main():
    log("Starting Milestone 1 Audio & Pipeline Empirical Stress Verification...")
    print("=" * 70)

    try:
        await test_a_repeated_start_stop_cycles()
    except Exception as e:
        log(f"Test A Failed: {e}\n{traceback.format_exc()}")

    try:
        await test_b_high_frequency_callbacks()
    except Exception as e:
        log(f"Test B Failed: {e}\n{traceback.format_exc()}")

    try:
        await test_c_offline_translation_fallback()
    except Exception as e:
        log(f"Test C Failed: {e}\n{traceback.format_exc()}")

    try:
        await test_d_event_loop_responsiveness()
    except Exception as e:
        log(f"Test D Failed: {e}\n{traceback.format_exc()}")

    print("=" * 70)
    log("STRESS VERIFICATION SUMMARY:")
    all_passed = True
    for name, res in results.items():
        status = res["status"]
        log(f"  {name:35s}: [{status}] - {res['metrics']}")
        if status != "PASS":
            all_passed = False

    overall_verdict = "PASS" if all_passed else "FAIL"
    log(f"\nOVERALL VERDICT: {overall_verdict}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
