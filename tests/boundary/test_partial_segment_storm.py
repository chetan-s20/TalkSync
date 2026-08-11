"""Boundary and Stress tests for Partial Segment Storms."""
from __future__ import annotations

import asyncio
from datetime import datetime
import time
import pytest

from app.interfaces import TranscriptionSegment
from tests.unit.test_translation_queue_pruning import TranslationQueuePruner


@pytest.mark.asyncio
async def test_partial_segment_storm_single_stream():
    """Simulate a burst of 30 partial segments enqueued within 50ms for a single speaker."""
    queue: asyncio.Queue[TranscriptionSegment] = asyncio.Queue(maxsize=16)
    pruned_total = 0

    start_t = time.perf_counter()
    for i in range(1, 31):
        seg = TranscriptionSegment(
            text=f"Partial word sequence number {i}",
            is_final=False,
            start_time=datetime.now(),
            end_time=datetime.now(),
            language="en",
            confidence=0.9,
            input_source="VOICE",
        )
        pruned_total += TranslationQueuePruner.prune_queue(queue, seg)
        await queue.put(seg)

    elapsed_ms = (time.perf_counter() - start_t) * 1000.0

    # Final segment arrives after partial storm
    final_seg = TranscriptionSegment(
        text="Partial word sequence number 31 complete sentence.",
        is_final=True,
        start_time=datetime.now(),
        end_time=datetime.now(),
        language="en",
        confidence=0.95,
        input_source="VOICE",
    )
    pruned_total += TranslationQueuePruner.prune_queue(queue, final_seg)
    await queue.put(final_seg)

    assert pruned_total == 30
    assert queue.qsize() == 1
    assert elapsed_ms < 100.0  # Must process storm rapidly

    last = await queue.get()
    assert last.is_final is True
    assert last.text == "Partial word sequence number 31 complete sentence."


@pytest.mark.asyncio
async def test_simultaneous_dual_stream_storm():
    """Simulate simultaneous partial storms on mic (VOICE) and loopback (COMPUTER_AUDIO)."""
    queue: asyncio.Queue[TranscriptionSegment] = asyncio.Queue(maxsize=32)
    pruned_mic = 0
    pruned_loop = 0

    for i in range(1, 21):
        seg_mic = TranscriptionSegment(
            text=f"Mic partial {i}",
            is_final=False,
            start_time=datetime.now(),
            end_time=datetime.now(),
            language="en",
            confidence=0.9,
            input_source="VOICE",
        )
        seg_loop = TranscriptionSegment(
            text=f"Loopback partial {i}",
            is_final=False,
            start_time=datetime.now(),
            end_time=datetime.now(),
            language="hi",
            confidence=0.9,
            input_source="COMPUTER_AUDIO",
        )

        pruned_mic += TranslationQueuePruner.prune_queue(queue, seg_mic)
        await queue.put(seg_mic)

        pruned_loop += TranslationQueuePruner.prune_queue(queue, seg_loop)
        await queue.put(seg_loop)

    # Queue should contain only 2 items: latest mic partial and latest loopback partial
    assert queue.qsize() == 2
    assert pruned_mic == 19
    assert pruned_loop == 19

    items = []
    while not queue.empty():
        items.append(await queue.get())

    sources = {item.input_source for item in items}
    assert sources == {"VOICE", "COMPUTER_AUDIO"}
