"""Unit tests for Translation Queue Pruning algorithm."""
from __future__ import annotations

import asyncio
from datetime import datetime
import pytest

from app.interfaces import TranscriptionSegment


class TranslationQueuePruner:
    """Helper class or static utility for pruning obsolete partial segments from translation_queue."""

    @staticmethod
    def prune_queue(
        queue: asyncio.Queue[TranscriptionSegment],
        incoming_segment: TranscriptionSegment
    ) -> int:
        """Prune any non-final segments in the queue matching incoming_segment's input_source.
        Returns count of pruned obsolete segments.
        """
        if queue.empty():
            return 0

        kept_items: list[TranscriptionSegment] = []
        pruned_count = 0

        while not queue.empty():
            try:
                item = queue.get_nowait()
                # Prune if same input_source and item is non-final (obsolete partial)
                same_source = (item.input_source or "VOICE") == (incoming_segment.input_source or "VOICE")
                if same_source and not item.is_final:
                    pruned_count += 1
                else:
                    kept_items.append(item)
            except asyncio.QueueEmpty:
                break

        # Re-enqueue remaining items
        for item in kept_items:
            queue.put_nowait(item)

        return pruned_count


@pytest.mark.asyncio
async def test_prune_obsolete_partial_segments():
    """Verify enqueuing a newer partial segment prunes older pending partials."""
    queue: asyncio.Queue[TranscriptionSegment] = asyncio.Queue(maxsize=10)

    p1 = TranscriptionSegment("Hello", is_final=False, start_time=datetime.now(), end_time=datetime.now(), language="en", confidence=0.9, input_source="VOICE")
    p2 = TranscriptionSegment("Hello how", is_final=False, start_time=datetime.now(), end_time=datetime.now(), language="en", confidence=0.9, input_source="VOICE")

    await queue.put(p1)
    assert queue.qsize() == 1

    pruned = TranslationQueuePruner.prune_queue(queue, p2)
    await queue.put(p2)

    assert pruned == 1
    assert queue.qsize() == 1
    remaining = await queue.get()
    assert remaining.text == "Hello how"


@pytest.mark.asyncio
async def test_prune_all_partials_on_final_segment():
    """Verify enqueuing a final segment prunes all pending partial segments for that speaker."""
    queue: asyncio.Queue[TranscriptionSegment] = asyncio.Queue(maxsize=10)

    p1 = TranscriptionSegment("The weather", is_final=False, start_time=datetime.now(), end_time=datetime.now(), language="en", confidence=0.9, input_source="VOICE")
    p2 = TranscriptionSegment("The weather is nice", is_final=False, start_time=datetime.now(), end_time=datetime.now(), language="en", confidence=0.9, input_source="VOICE")
    f3 = TranscriptionSegment("The weather is nice today.", is_final=True, start_time=datetime.now(), end_time=datetime.now(), language="en", confidence=0.95, input_source="VOICE")

    await queue.put(p1)
    await queue.put(p2)
    assert queue.qsize() == 2

    pruned = TranslationQueuePruner.prune_queue(queue, f3)
    await queue.put(f3)

    assert pruned == 2
    assert queue.qsize() == 1
    remaining = await queue.get()
    assert remaining.text == "The weather is nice today."
    assert remaining.is_final is True


@pytest.mark.asyncio
async def test_multi_stream_source_isolation_during_pruning():
    """Verify pruning partials for VOICE (mic) does NOT discard partials for COMPUTER_AUDIO (loopback)."""
    queue: asyncio.Queue[TranscriptionSegment] = asyncio.Queue(maxsize=10)

    p_mic = TranscriptionSegment("Mic speaker text", is_final=False, start_time=datetime.now(), end_time=datetime.now(), language="en", confidence=0.9, input_source="VOICE")
    p_loop = TranscriptionSegment("Loopback speaker text", is_final=False, start_time=datetime.now(), end_time=datetime.now(), language="en", confidence=0.9, input_source="COMPUTER_AUDIO")

    await queue.put(p_mic)
    await queue.put(p_loop)
    assert queue.qsize() == 2

    new_mic = TranscriptionSegment("Mic speaker text updated", is_final=False, start_time=datetime.now(), end_time=datetime.now(), language="en", confidence=0.9, input_source="VOICE")

    pruned = TranslationQueuePruner.prune_queue(queue, new_mic)
    await queue.put(new_mic)

    assert pruned == 1  # Only p_mic pruned
    assert queue.qsize() == 2  # p_loop and new_mic remain
    items = []
    while not queue.empty():
        items.append(await queue.get())

    sources = [item.input_source for item in items]
    texts = [item.text for item in items]
    assert "COMPUTER_AUDIO" in sources
    assert "Loopback speaker text" in texts
    assert "Mic speaker text updated" in texts


@pytest.mark.asyncio
async def test_prune_empty_queue_graceful():
    """Verify pruning an empty queue causes zero errors and returns 0."""
    queue: asyncio.Queue[TranscriptionSegment] = asyncio.Queue(maxsize=10)
    p = TranscriptionSegment("Standalone", is_final=False, start_time=datetime.now(), end_time=datetime.now(), language="en", confidence=0.9, input_source="VOICE")

    pruned = TranslationQueuePruner.prune_queue(queue, p)
    assert pruned == 0
    assert queue.empty()
