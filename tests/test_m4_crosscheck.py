import pytest
import os
import time
from config.settings import Settings
from services.stt.openai_stt import OpenAISTT
from services.stt.faster_whisper import FasterWhisperSTT
from app.application import validate_and_resolve_audio_devices, Application
from app.pipeline import Pipeline
import numpy as np

def test_env_and_settings_crosscheck():
    """Verify settings and .env configurations match DIAGNOSTICS_REPORT.md claims."""
    settings = Settings()
    
    # 1. Check VAD threshold in .env / settings
    # Note: VADSettings env_prefix is "vad_", so vad_threshold=0.45 in .env populates settings.vad.threshold
    assert settings.vad.threshold == 0.45, f"Expected VAD threshold 0.45, got {settings.vad.threshold}"
    
    # 2. Check RMS gate threshold in settings
    assert settings.stt.rms_gate_threshold in (0.0, 0.0003), f"Expected RMS gate threshold 0.0 or 0.0003, got {settings.stt.rms_gate_threshold}"
    
    # 3. Check audio input/output device IDs in .env / settings
    assert settings.audio.input_device_id == 35, f"Expected input device ID 35, got {settings.audio.input_device_id}"
    assert settings.audio.output_device_id == 36, f"Expected output device ID 36, got {settings.audio.output_device_id}"
    
    # 4. Check STT engine selection
    assert settings.stt_engine == "openai", f"Expected STT engine 'openai', got {settings.stt_engine}"

def test_stt_engines_crosscheck():
    """Verify OpenAI STT and FasterWhisper STT configurations match report claims."""
    settings = Settings()
    
    openai_stt = OpenAISTT(settings)
    assert openai_stt._rms_gate_threshold in (0.0, 0.0003), f"OpenAI STT RMS gate threshold is {openai_stt._rms_gate_threshold}"
    
    # Test AGC normalization in OpenAISTT
    dummy_audio = np.ones(16000, dtype=np.float32) * 0.01  # Low amplitude audio
    amplified = OpenAISTT._apply_agc(dummy_audio)
    amplified_rms = float(np.sqrt(np.mean(amplified ** 2)))
    # AGC target_rms is 0.20, max gain 8.0x -> 0.01 * 8.0 = 0.08
    assert abs(amplified_rms - 0.08) < 0.01, f"AGC target failed: got RMS {amplified_rms}"
    
    fw_stt = FasterWhisperSTT(settings)
    assert fw_stt._rms_gate_threshold in (0.0, 0.0003), f"FasterWhisper STT RMS gate threshold is {fw_stt._rms_gate_threshold}"

def test_pipeline_mute_gate_logic():
    """Verify mute gate formula and buffer purging logic in Pipeline."""
    class DummyAudioInput:
        pass
    class DummyVAD:
        pass
    class DummySTT:
        pass
    class DummyTranslator:
        pass
    class DummyTTS:
        pass
    class DummyAudioOutput:
        pass

    pipeline = Pipeline(
        audio_input=DummyAudioInput(),
        vad=DummyVAD(),
        stt=DummySTT(),
        translator=DummyTranslator(),
        tts=DummyTTS(),
        audio_output=DummyAudioOutput(),
    )
    
    t0 = time.time()
    pipeline._activate_tts_mute_gate(1.0)
    # mute_until should be at least now + 1.0 + 0.5 = now + 1.5
    assert pipeline._ignore_loopback_until >= t0 + 1.5
    assert pipeline._ignore_mic_until >= t0 + 1.5

def test_device_resolution_logic():
    """Verify validate_and_resolve_audio_devices populates selected device names."""
    settings = Settings()
    validate_and_resolve_audio_devices(settings)
    assert isinstance(settings.selected_input_device_name, str)
    assert isinstance(settings.selected_output_device_name, str)
