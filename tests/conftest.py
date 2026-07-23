from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import pytest_asyncio

from config.settings import Settings


@pytest.fixture
def sample_audio() -> np.ndarray:
    return np.random.randn(16000).astype(np.float32) * 0.1


@pytest.fixture
def sample_audio_chunk() -> np.ndarray:
    return np.random.randn(480).astype(np.float32) * 0.1


@pytest.fixture
def mock_settings() -> Settings:
    return Settings(
        source_lang="EN",
        target_lang="HI",
        translation_mode="two_way",
        audio={
            "input_device_id": None,
            "output_device_id": None,
            "sample_rate": 16000,
            "chunk_duration_ms": 30,
            "volume": 1.0,
            "playback_delay_s": 0.0,
        },
        stt={
            "model": "Systran/faster-whisper-small",
            "beam_size": 1,
        },
        translation={
            "primary": "argos",
            "fallback": "deepl",
            "deepl_api_key": "mock-key",
            "timeout_s": 5,
        },
        tts={
            "piper_voice_dir": "",
            "sarvam_api_key": "mock-sarvam-key",
            "default_voice": "default",
        },
    )


@pytest.fixture
def temp_db_path() -> Generator[str, None, None]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def mock_transcription_segment():
    from app.pipeline_state import SttJob
    return SttJob(
        text="Hello world",
        is_final=True,
        language="en",
        confidence=0.95,
        source="mic",
        audio_id=None,
    )


@pytest.fixture
def mock_translation_result():
    from dataclasses import dataclass

    @dataclass
    class TranslationResult:
        original_text: str
        translated_text: str
        source_lang: str
        target_lang: str
        is_final: bool
        input_source: str = "VOICE"

    return TranslationResult(
        original_text="Hello world",
        translated_text="\u0928\u092e\u0938\u094d\u0924\u0947 \u0926\u0941\u0928\u093f\u092f\u093e",
        source_lang="EN",
        target_lang="HI",
        is_final=True,
        input_source="VOICE",
    )


@pytest.fixture
def mock_vad_result():
    from dataclasses import dataclass

    @dataclass
    class VADResult:
        is_speech: bool
        speech_start: float | None = None
        speech_end: float | None = None
        confidence: float = 0.0

    return VADResult(is_speech=True, speech_start=0.0, speech_end=1.0, confidence=0.85)


@pytest_asyncio.fixture
async def mock_pipeline():
    from app.pipeline import Pipeline
    from unittest.mock import AsyncMock, MagicMock

    pipeline = MagicMock(spec=Pipeline)
    pipeline.start = AsyncMock()
    pipeline.stop = AsyncMock()
    pipeline.running = False
    pipeline.set_translation_mode = MagicMock()
    pipeline.set_volume = MagicMock()
    pipeline.mute_mic = MagicMock()
    pipeline.set_delay = MagicMock()
    pipeline.process_text_input = AsyncMock()
    return pipeline


@pytest.fixture
def sample_session_blocks() -> list[dict]:
    return [
        {
            "timestamp": "00:00",
            "original": "Hello, how are you?",
            "translated": "\u0928\u092e\u0938\u094d\u0924\u0947, \u0906\u092a \u0915\u0948\u0938\u0947 \u0939\u0948\u0902?",
            "input_source": "VOICE",
            "source_lang": "EN",
            "target_lang": "HI",
        },
        {
            "timestamp": "00:05",
            "original": "I am fine, thank you.",
            "translated": "\u092e\u0948\u0902 \u0920\u0940\u0915 \u0939\u0942\u0902, \u0927\u0928\u094d\u092f\u0935\u093e\u0926\u0964",
            "input_source": "VOICE",
            "source_lang": "EN",
            "target_lang": "HI",
        },
    ]


@pytest.fixture
def mock_device_list():
    return [
        {"name": "Microphone (Realtek Audio)", "index": 0, "max_input_channels": 1, "max_output_channels": 0, "default_samplerate": 48000},
        {"name": "Speakers (Realtek Audio)", "index": 1, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000},
        {"name": "Stereo Mix (Realtek Audio)", "index": 2, "max_input_channels": 2, "max_output_channels": 0, "default_samplerate": 48000},
        {"name": "CABLE Input (VB-Audio Cable)", "index": 3, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000},
    ]


@pytest.fixture
def mock_audio_levels() -> list[float]:
    return [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0, 0.8, 0.6, 0.4, 0.2, 0.0]
