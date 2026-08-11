"""Empirical Verification & Stress Test Harness for Milestone 2.
Run by Challenger 1 to independently verify claims and check for subtle edge-case bugs.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import MagicMock

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.bridge import ApiBridge
from app.pipeline import Pipeline
from app.interfaces import (
    BaseAudioInput, BaseVAD, BaseSTT, BaseTranslator, BaseTTS, BaseAudioOutput,
    AudioChunk, TranscriptionSegment, TranslationResult, VADResult, SynthesisResult
)
from services.translation.factory import TranslationFactory
from services.translation.argos import ArgosTranslator
from services.stt.factory import STTFactory
from services.stt.faster_whisper import FasterWhisperSTT


class MockAudioInput(BaseAudioInput):
    async def start(self, device_id: int | None = None, loopback: bool = False, capture_mic: bool = True, **kwargs) -> None:
        self.started = True
    async def stop(self) -> None:
        self.started = False
    async def stream(self):
        yield AudioChunk(data=b"\x00" * 640, sample_rate=16000, channels=1, timestamp=time.time(), duration_ms=20.0)
    async def stream_loopback(self):
        yield AudioChunk(data=b"\x00" * 640, sample_rate=16000, channels=1, timestamp=time.time(), duration_ms=20.0)
    async def list_devices(self):
        return []

class MockVAD(BaseVAD):
    def __init__(self):
        self.settings = MagicMock(threshold=0.5)
    async def start(self) -> None: pass
    async def stop(self) -> None: pass
    async def process(self, chunk: AudioChunk):
        yield VADResult(confidence=0.1, is_speech=False)

class MockSTT(BaseSTT):
    async def start(self, language: str | None = None) -> None: pass
    async def stop(self) -> None: pass
    async def transcribe(self, audio, **kwargs): return None
    async def stream(self, audio): yield None

class MockTranslator(BaseTranslator):
    async def start(self) -> None: pass
    async def stop(self) -> None: pass
    async def translate(self, text: str, source_lang: str, target_lang: str, context: str = None) -> TranslationResult:
        return TranslationResult(original_text=text, translated_text=f"Trans[{text}]", source_lang=source_lang, target_lang=target_lang, is_final=True)

class MockTTS(BaseTTS):
    async def start(self) -> None: pass
    async def stop(self) -> None: pass
    async def synthesize(self, text: str, lang: str = "en") -> SynthesisResult:
        return SynthesisResult(audio_data=b"\x00"*10, sample_rate=16000, duration_ms=10)
    async def synthesize_stream(self, text_stream, lang: str = "en"):
        yield SynthesisResult(audio_data=b"\x00"*10, sample_rate=16000, duration_ms=10)
    async def set_voice(self, voice_id: str) -> None: pass
    async def set_speed(self, speed: float) -> None: pass

class MockAudioOutput(BaseAudioOutput):
    async def start(self, device_id: int | None = None, **kwargs) -> None: pass
    async def stop(self) -> None: pass
    async def play(self, chunk: AudioChunk) -> None: pass
    async def list_devices(self): return []


def verify_requirement_2_event_loop_task_lifetime():
    """Verify worker tasks in Pipeline.start() remain alive on ApiBridge's persistent event loop."""
    print("=== Test 2: ApiBridge persistent event loop & Pipeline task lifetime ===")
    mock_app = MagicMock()
    mock_app.settings = MagicMock()
    mock_app.settings.source_lang = "EN"
    mock_app.settings.target_lang = "HI"
    mock_app.settings.translation_mode = "two_way"
    mock_app.settings.loopback_enabled = False
    mock_app.settings.vad = MagicMock(threshold=0.5)
    mock_app.settings.stt = MagicMock(rms_gate_threshold=0.0003, model="small")
    mock_app.settings.audio = MagicMock(input_device_id=None, output_device_id=None, virtual_mic_enabled=False)

    pipeline = Pipeline(
        audio_input=MockAudioInput(),
        vad=MockVAD(),
        stt=MockSTT(),
        translator=MockTranslator(),
        tts=MockTTS(),
        audio_output=MockAudioOutput(),
    )
    mock_app.pipeline = pipeline

    bridge = ApiBridge(application=mock_app)
    
    # Start session
    res = bridge.start_session(source="EN", target="HI", text_mode=True)
    assert res["status"] == "ok"
    
    # Check that event loop thread is alive and tasks are running
    assert bridge._loop_thread is not None
    assert bridge._loop_thread.is_alive()
    assert bridge._loop is not None
    assert bridge._loop.is_running()
    
    # Inspect pipeline worker tasks
    tasks = pipeline._tasks
    assert len(tasks) > 0, "No tasks launched in pipeline"
    
    # Wait a bit and confirm tasks are still active (not done/killed)
    time.sleep(0.5)
    active_tasks = [t for t in tasks if not t.done()]
    print(f"Total pipeline tasks: {len(tasks)}, Active tasks after 0.5s: {len(active_tasks)}")
    assert len(active_tasks) == len(tasks), f"Expected all {len(tasks)} tasks alive, but {len(tasks)-len(active_tasks)} ended!"

    # Stop session
    stop_res = bridge.stop_session()
    assert stop_res["status"] == "ok"
    time.sleep(0.3)
    
    # Verify loop thread is STILL running (persistent across sessions)
    assert bridge._loop_thread.is_alive(), "Event loop thread was destroyed after stop_session!"
    assert bridge._loop.is_running(), "Event loop stopped running after stop_session!"
    
    # Start second session to ensure re-usability
    res2 = bridge.start_session(source="EN", target="HI", text_mode=True)
    assert res2["status"] == "ok"
    tasks2 = pipeline._tasks
    assert len(tasks2) > 0
    time.sleep(0.3)
    active_tasks2 = [t for t in tasks2 if not t.done()]
    assert len(active_tasks2) == len(tasks2)
    
    bridge.stop_session()
    print("[OK] Requirement 2 PASSED: Worker tasks remain alive on persistent event loop across multiple sessions.")


def verify_requirement_3_deepl_fallback():
    """Verify DeepLTranslator.start() failure triggers clean fallback to ArgosTranslator."""
    print("\n=== Test 3: DeepL start failure -> ArgosTranslator fallback ===")
    
    # Case A: Missing API key
    settings_missing_key = MagicMock()
    settings_missing_key.provider = "deepl"
    settings_missing_key.deepl_api_key = ""
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        translator = loop.run_until_complete(TranslationFactory.create(settings_missing_key))
        print(f"Fallback translator type (missing key): {type(translator).__name__}")
        assert isinstance(translator, ArgosTranslator), f"Expected ArgosTranslator fallback, got {type(translator)}"
    finally:
        loop.close()

    # Case B: Invalid API key (network/auth failure)
    settings_invalid_key = MagicMock()
    settings_invalid_key.provider = "deepl"
    settings_invalid_key.deepl_api_key = "INVALID_KEY_99999_XYZ"
    
    loop2 = asyncio.new_event_loop()
    asyncio.set_event_loop(loop2)
    try:
        translator2 = loop2.run_until_complete(TranslationFactory.create(settings_invalid_key))
        print(f"Fallback translator type (invalid key): {type(translator2).__name__}")
        assert isinstance(translator2, ArgosTranslator), f"Expected ArgosTranslator fallback, got {type(translator2)}"
    finally:
        loop2.close()

    print("[OK] Requirement 3 PASSED: DeepL init failures fall back cleanly to ArgosTranslator.")


def verify_requirement_4_openai_stt_fallback():
    """Verify STTFactory.create() falls back from OpenAISTT to FasterWhisperSTT when OpenAI key is invalid."""
    print("\n=== Test 4: STTFactory fallback from OpenAISTT to FasterWhisperSTT on invalid key ===")
    
    settings = MagicMock()
    settings.stt_engine = "openai"
    settings.openai = MagicMock(api_key="sk-invalid-fake-key-12345", stt_model="gpt-4o-transcribe", proxy_url=None)
    settings.stt = MagicMock()
    settings.stt.model = "small"
    settings.stt.rms_gate_threshold = 0.0003
    settings.stt.min_word_count = 1
    settings.stt.refinement = True
    settings.stt.device = "cpu"
    settings.stt.compute_type = "int8"
    settings.stt.beam_size = 1
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        stt = loop.run_until_complete(STTFactory.create(settings))
        print(f"Fallback STT engine type: {type(stt).__name__}")
        assert isinstance(stt, FasterWhisperSTT), f"Expected FasterWhisperSTT fallback, got {type(stt)}"
    finally:
        loop.close()

    print("[OK] Requirement 4 PASSED: OpenAISTT invalid key falls back cleanly to FasterWhisperSTT.")


def run_adversarial_stress_checks():
    """Run adversarial edge-case stress tests."""
    print("\n=== Running Adversarial Edge-Case Stress Checks ===")
    
    # 1. Test ApiBridge thread-safety when start_session and stop_session are called rapidly
    print("Testing rapid start_session / stop_session concurrency...")
    mock_app = MagicMock()
    mock_app.pipeline = Pipeline(
        audio_input=MockAudioInput(), vad=MockVAD(), stt=MockSTT(),
        translator=MockTranslator(), tts=MockTTS(), audio_output=MockAudioOutput(),
    )
    bridge = ApiBridge(application=mock_app)
    
    for i in range(5):
        bridge.start_session(text_mode=True)
        bridge.stop_session()
    print("[OK] Rapid session toggle survived without deadlock or unhandled exception.")

    # 2. Test submitting text input when pipeline is inactive vs active
    print("Testing submit_text_input edge cases...")
    res_empty = bridge.submit_text_input("")
    assert res_empty["status"] == "error"
    res_space = bridge.submit_text_input("   ")
    assert res_space["status"] == "error"
    res_valid = bridge.submit_text_input("Hello world")
    assert res_valid["status"] == "ok"
    assert res_valid["original"] == "Hello world"
    print("[OK] submit_text_input edge cases handled correctly.")


if __name__ == "__main__":
    verify_requirement_2_event_loop_task_lifetime()
    verify_requirement_3_deepl_fallback()
    verify_requirement_4_openai_stt_fallback()
    run_adversarial_stress_checks()
    print("\nALL EMPIRICAL TESTS PASSED SUCCESSFULLY!")
