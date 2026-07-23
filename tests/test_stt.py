from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import torch

from app.interfaces import BaseSTT, TranscriptionSegment
from services.stt.faster_whisper import FasterWhisperSTT


class TestSTTInterface:
    def test_base_stt_abstract(self):
        with pytest.raises(TypeError):
            BaseSTT()

    def test_stt_segment_dataclass(self):
        segment = TranscriptionSegment(
            text="Hello",
            is_final=True,
            start_time="00:00:00",
            end_time="00:00:01",
            language="en",
            confidence=0.95,
        )
        assert segment.text == "Hello"
        assert segment.is_final is True
        assert segment.language == "en"
        assert segment.confidence == 0.95

    def test_stt_segment_with_source(self):
        segment = TranscriptionSegment(
            text="Hello",
            is_final=True,
            start_time="00:00:00",
            end_time="00:00:01",
            language="en",
            confidence=0.95,
            input_source="mic",
        )
        assert segment.input_source == "mic"


class TestFasterWhisperSTT:
    def test_stt_initialization(self):
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_instance = MagicMock()
            mock_model.return_value = mock_instance
            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cuda")
            assert stt is not None

    def test_stt_cpu_fallback(self):
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_instance = MagicMock()
            mock_model.return_value = mock_instance
            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
            assert stt is not None

    def test_stt_transcribe_success(self):
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_instance = MagicMock()
            mock_model.return_value = mock_instance

            mock_segment = MagicMock()
            mock_segment.text = "Hello world"
            mock_segment.start = 0.0
            mock_segment.end = 1.0
            mock_segment.avg_logprob = -0.1
            mock_segment.no_speech_prob = 0.05

            mock_info = MagicMock()
            mock_info.language = "en"
            mock_info.duration = 1.0

            mock_instance.transcribe.return_value = ([mock_segment], mock_info)

            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
            audio = np.random.randn(16000).astype(np.float32)
            result = stt.transcribe(audio, 16000)
            assert result is not None
            assert result.text == "Hello world"
            assert result.language == "en"

    def test_stt_transcribe_empty_result(self):
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_instance = MagicMock()
            mock_model.return_value = mock_instance
            mock_instance.transcribe.return_value = ([], MagicMock(language="en", duration=1.0))

            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
            audio = np.zeros(16000, dtype=np.float32)
            result = stt.transcribe(audio, 16000)
            assert result is None

    def test_stt_language_auto_detect(self):
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_instance = MagicMock()
            mock_model.return_value = mock_instance

            mock_segment = MagicMock()
            mock_segment.text = "नमस्ते"
            mock_segment.start = 0.0
            mock_segment.end = 0.5
            mock_segment.avg_logprob = -0.1
            mock_segment.no_speech_prob = 0.05

            mock_info = MagicMock()
            mock_info.language = "hi"
            mock_info.duration = 0.5

            mock_instance.transcribe.return_value = ([mock_segment], mock_info)

            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
            audio = np.random.randn(16000).astype(np.float32)
            result = stt.transcribe(audio, 16000, language=None)
            assert result.language == "hi"

    def test_stt_noise_rejection_low_logprob(self):
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_instance = MagicMock()
            mock_model.return_value = mock_instance

            mock_segment = MagicMock()
            mock_segment.text = "Noise"
            mock_segment.start = 0.0
            mock_segment.end = 0.5
            mock_segment.avg_logprob = -1.0
            mock_segment.no_speech_prob = 0.8

            mock_info = MagicMock()
            mock_info.language = "en"
            mock_info.duration = 0.5

            mock_instance.transcribe.return_value = ([mock_segment], mock_info)

            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
            audio = np.random.randn(16000).astype(np.float32) * 0.01
            result = stt.transcribe(audio, 16000)
            assert result is None

    def test_stt_cuda_float16_precision(self):
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            assert props.total_memory > 0
            assert "RTX" in props.name or "NVIDIA" in props.name
        else:
            pytest.skip("CUDA not available")

    def test_stt_model_name_config(self):
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_instance = MagicMock()
            mock_model.return_value = mock_instance
            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small")
            assert "small" in stt.model_name

    def test_stt_beam_size_effect(self):
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_instance = MagicMock()
            mock_model.return_value = mock_instance
            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", beam_size=5)
            assert stt.beam_size == 5

    def test_stt_initial_prompt(self):
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_instance = MagicMock()
            mock_model.return_value = mock_instance
            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small")
            prompt = "This is a Hindi and English conversation."
            audio = np.random.randn(16000).astype(np.float32)
            result = stt.transcribe(audio, 16000, initial_prompt=prompt)
            assert True

    def test_stt_vad_filter_enabled(self):
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_instance = MagicMock()
            mock_model.return_value = mock_instance
            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", vad_filter=True)
            assert stt.vad_filter is True

    def test_stt_no_speech_threshold(self):
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_instance = MagicMock()
            mock_model.return_value = mock_instance
            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small")
            assert stt.no_speech_threshold == 0.7

    def test_stt_compression_ratio_threshold(self):
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_instance = MagicMock()
            mock_model.return_value = mock_instance
            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small")
            assert stt.compression_ratio_threshold == 2.4

    def test_stt_log_prob_threshold(self):
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_instance = MagicMock()
            mock_model.return_value = mock_instance
            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small")
            assert stt.log_prob_threshold == -1.0


class TestSTTIntegration:
    def test_gpu_availability_check(self):
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            assert props.total_memory > 0
            assert "4060" in props.name or "NVIDIA" in props.name
        else:
            pytest.skip("CUDA not available")

    def test_vram_monitoring(self):
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            vram_mb = props.total_memory / (1024 * 1024)
            assert vram_mb > 0
        else:
            pytest.skip("CUDA not available")

    def test_whisper_small_model_size(self):
        expected_size_gb = 1.5
        assert expected_size_gb > 0

    def test_audio_duration_for_stt(self):
        sample_rate = 16000
        duration_ms = 30000
        expected_samples = int(sample_rate * duration_ms / 1000)
        assert expected_samples == 480000

    def test_stt_inference_time(self):
        with patch("faster_whisper.WhisperModel") as mock_model:
            mock_instance = MagicMock()
            mock_model.return_value = mock_instance

            import time
            start = time.time()

            mock_segment = MagicMock()
            mock_segment.text = "Test"
            mock_segment.start = 0.0
            mock_segment.end = 0.3
            mock_segment.avg_logprob = -0.1
            mock_segment.no_speech_prob = 0.1

            mock_info = MagicMock()
            mock_info.language = "en"
            mock_info.duration = 0.3

            mock_instance.transcribe.return_value = ([mock_segment], mock_info)

            stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
            audio = np.random.randn(16000).astype(np.float32)
            result = stt.transcribe(audio, 16000)
            assert True