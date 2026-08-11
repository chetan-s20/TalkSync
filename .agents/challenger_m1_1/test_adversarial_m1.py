import asyncio
import time
from datetime import datetime
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.interfaces import (
    AudioChunk, BaseAudioInput, BaseAudioOutput,
    BaseSTT, BaseTTS, BaseTranslator, BaseVAD,
)
from app.pipeline import Pipeline
from app.pipeline_state import SttJob


def create_mock_pipeline():
    audio_input = MagicMock(spec=BaseAudioInput)
    vad = MagicMock(spec=BaseVAD)
    stt = MagicMock(spec=BaseSTT)
    translator = MagicMock(spec=BaseTranslator)
    tts = MagicMock(spec=BaseTTS)
    audio_output = MagicMock(spec=BaseAudioOutput)
    return Pipeline(
        audio_input=audio_input, vad=vad, stt=stt,
        translator=translator, tts=tts, audio_output=audio_output,
    )


@pytest.mark.asyncio
async def test_purge_empty_queues():
    p = create_mock_pipeline()
    assert p.audio_queue.empty()
    assert p.stt_queue.empty()
    p._purge_loopback_queues()
    assert p.audio_queue.empty()
    assert p.stt_queue.empty()


@pytest.mark.asyncio
async def test_purge_full_queues_mixed():
    p = create_mock_pipeline()
    # audio_queue maxsize = 1000
    for i in range(1000):
        src = "loopback" if i % 2 == 0 else "mic"
        chunk = AudioChunk(
            data=b"0" * 100, sample_rate=16000, channels=1,
            timestamp=datetime.now(), duration_ms=10.0, source=src,
        )
        p.audio_queue.put_nowait(chunk)

    # stt_queue maxsize = 256
    for i in range(256):
        src = "loopback" if i % 4 == 0 else "mic"
        job = SttJob(source=src, audio=b"0" * 100, sample_rate=16000, is_final=True)
        p.stt_queue.put_nowait(job)

    assert p.audio_queue.full()
    assert p.stt_queue.full()

    p._purge_loopback_queues()

    # Audio queue: 500 mic items retained
    assert p.audio_queue.qsize() == 500
    mic_audio_count = 0
    while not p.audio_queue.empty():
        item = p.audio_queue.get_nowait()
        assert item.source == "mic"
        mic_audio_count += 1
    assert mic_audio_count == 500

    # STT queue: 192 mic items retained (256 - 64 loopback)
    assert p.stt_queue.qsize() == 192
    mic_stt_count = 0
    while not p.stt_queue.empty():
        job = p.stt_queue.get_nowait()
        assert job.source == "mic"
        mic_stt_count += 1
    assert mic_stt_count == 192


@pytest.mark.asyncio
async def test_purge_all_loopback():
    p = create_mock_pipeline()
    for i in range(1000):
        chunk = AudioChunk(
            data=b"0" * 100, sample_rate=16000, channels=1,
            timestamp=datetime.now(), duration_ms=10.0, source="loopback",
        )
        p.audio_queue.put_nowait(chunk)

    assert p.audio_queue.full()
    p._purge_loopback_queues()
    assert p.audio_queue.empty()


@pytest.mark.asyncio
async def test_purge_all_mic():
    p = create_mock_pipeline()
    for i in range(1000):
        chunk = AudioChunk(
            data=b"0" * 100, sample_rate=16000, channels=1,
            timestamp=datetime.now(), duration_ms=10.0, source="mic",
        )
        p.audio_queue.put_nowait(chunk)

    assert p.audio_queue.full()
    p._purge_loopback_queues()
    assert p.audio_queue.qsize() == 1000


@pytest.mark.asyncio
async def test_purge_concurrent_access():
    p = create_mock_pipeline()
    stop_event = asyncio.Event()

    async def producer_audio():
        count = 0
        while not stop_event.is_set():
            src = "loopback" if count % 3 == 0 else "mic"
            chunk = AudioChunk(
                data=b"0" * 10, sample_rate=16000, channels=1,
                timestamp=datetime.now(), duration_ms=10.0, source=src,
            )
            try:
                p.audio_queue.put_nowait(chunk)
            except asyncio.QueueFull:
                pass
            count += 1
            await asyncio.sleep(0.001)

    async def producer_stt():
        count = 0
        while not stop_event.is_set():
            src = "loopback" if count % 2 == 0 else "mic"
            job = SttJob(source=src, audio=b"0" * 10, sample_rate=16000, is_final=True)
            try:
                p.stt_queue.put_nowait(job)
            except asyncio.QueueFull:
                pass
            count += 1
            await asyncio.sleep(0.001)

    async def purger():
        for _ in range(50):
            p._purge_loopback_queues()
            await asyncio.sleep(0.005)

    producer_a_task = asyncio.create_task(producer_audio())
    producer_s_task = asyncio.create_task(producer_stt())
    purger_task = asyncio.create_task(purger())

    await purger_task
    stop_event.set()
    await asyncio.gather(producer_a_task, producer_s_task)

    # Final purge check
    p._purge_loopback_queues()
    while not p.audio_queue.empty():
        item = p.audio_queue.get_nowait()
        assert item.source != "loopback"

    while not p.stt_queue.empty():
        job = p.stt_queue.get_nowait()
        assert job.source != "loopback"


@pytest.mark.asyncio
async def test_activate_tts_mute_gate_single():
    p = create_mock_pipeline()
    now = time.time()
    p._activate_tts_mute_gate(1.0)
    # Expected mute until now + 1.0 + 0.5 = now + 1.5
    assert p._ignore_loopback_until >= now + 1.45
    assert p._ignore_mic_until >= now + 1.45
    assert p._should_ignore_loopback() is True
    assert p._should_ignore_mic() is True


@pytest.mark.asyncio
async def test_activate_tts_mute_gate_rapid_stacking():
    p = create_mock_pipeline()
    now = time.time()
    # Rapid consecutive calls with 1.0s, 0.5s, 2.0s
    p._activate_tts_mute_gate(1.0)  # mute_until = now + 1.0 + 0.5 = now + 1.5
    first_mute = p._ignore_loopback_until

    p._activate_tts_mute_gate(0.5)  # mute_until = (now + 1.5) + 0.5 + 0.5 = now + 2.5
    second_mute = p._ignore_loopback_until

    p._activate_tts_mute_gate(2.0)  # mute_until = (now + 2.5) + 2.0 + 0.5 = now + 5.0
    third_mute = p._ignore_loopback_until

    assert second_mute > first_mute
    assert third_mute > second_mute
    assert third_mute >= now + 4.95
    assert p._should_ignore_loopback() is True
    assert p._should_ignore_mic() is True


@pytest.mark.asyncio
async def test_activate_tts_mute_gate_after_expiration():
    p = create_mock_pipeline()
    p._activate_tts_mute_gate(0.1)  # mute_until = now + 0.6
    await asyncio.sleep(0.7)
    assert p._should_ignore_loopback() is False
    assert p._should_ignore_mic() is False

    # Call again after expiration
    now2 = time.time()
    p._activate_tts_mute_gate(1.0)
    assert p._ignore_loopback_until >= now2 + 1.45
    assert p._should_ignore_loopback() is True


@pytest.mark.asyncio
async def test_purge_loopback_queues_with_unusual_items():
    p = create_mock_pipeline()
    # Add items missing 'source' attribute or string/dict items
    p.audio_queue.put_nowait("raw_string_item")
    p.audio_queue.put_nowait({"key": "val"})
    p.audio_queue.put_nowait(None)
    
    lb_chunk = AudioChunk(
        data=b"0" * 10, sample_rate=16000, channels=1,
        timestamp=datetime.now(), duration_ms=10.0, source="loopback",
    )
    p.audio_queue.put_nowait(lb_chunk)

    p._purge_loopback_queues()

    # 3 non-loopback items retained, 1 loopback chunk removed
    assert p.audio_queue.qsize() == 3
    assert p.audio_queue.get_nowait() == "raw_string_item"
    assert p.audio_queue.get_nowait() == {"key": "val"}
    assert p.audio_queue.get_nowait() is None
