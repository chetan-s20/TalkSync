import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from app.pipeline import Pipeline
from config.settings import Settings
from app.pipeline_state import SttJob
from app.interfaces import BaseAudioInput, BaseVAD, BaseSTT, BaseTranslator, BaseTTS, BaseAudioOutput

@pytest.mark.asyncio
async def test_language_filtering_in_stt_worker():
    """Verify that STT segments in unselected languages are dropped in the stt_worker loop."""
    settings = Settings()
    settings.source_lang = "EN"
    settings.target_lang = "HI"
    
    # Mock services
    audio_input = MagicMock(spec=BaseAudioInput)
    vad = MagicMock(spec=BaseVAD)
    stt = MagicMock(spec=BaseSTT)
    translator = MagicMock(spec=BaseTranslator)
    tts = MagicMock(spec=BaseTTS)
    audio_output = MagicMock(spec=BaseAudioOutput)
    
    pipeline = Pipeline(
        audio_input=audio_input,
        vad=vad,
        stt=stt,
        translator=translator,
        tts=tts,
        audio_output=audio_output,
        settings=settings,
    )
    pipeline.running = True
    
    # Enqueue a job into stt_queue
    job = SttJob(
        source="mic",
        audio=b"fakeaudio",
        sample_rate=16000,
        is_final=True,
    )
    
    # 1. Test case: German (de) - should be dropped since allowed are en and hi
    mock_segment_de = MagicMock()
    mock_segment_de.text = "Guten Tag"
    mock_segment_de.language = "de"
    mock_segment_de.confidence = 0.95
    
    stt.transcribe = AsyncMock(return_value=mock_segment_de)
    
    # Run the worker for one iteration
    await pipeline.stt_queue.put(job)
    
    task = asyncio.create_task(pipeline._stt_worker())
    await asyncio.sleep(0.1) # Let the worker process
    
    # Verify that translation queue is empty (dropped)
    assert pipeline.translation_queue.qsize() == 0
    
    # 2. Test case: English (en) - should be kept
    mock_segment_en = MagicMock()
    mock_segment_en.text = "Hello there"
    mock_segment_en.language = "en"
    mock_segment_en.confidence = 0.95
    
    stt.transcribe = AsyncMock(return_value=mock_segment_en)
    
    await pipeline.stt_queue.put(job)
    await asyncio.sleep(0.1) # Let the worker process
    
    # Verify translation queue has 1 segment (kept)
    assert pipeline.translation_queue.qsize() == 1
    segment = pipeline.translation_queue.get_nowait()
    assert segment.text == "Hello there"
    
    # Clean up
    pipeline.running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
