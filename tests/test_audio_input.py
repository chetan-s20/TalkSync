from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from services.audio.loopback import find_loopback_device, find_vb_cable
from services.audio.resampler import resample
from services.audio.fallback import try_open_output
from services.audio_processing.normalizer import PeakNormalizer
from services.audio_processing.agc import AutomaticGainControl


class TestDeviceDiscovery:
    def test_find_loopback_device(self, mock_device_list):
        with patch("sounddevice.query_devices", return_value=mock_device_list):
            device = find_loopback_device()
            assert device is not None
            assert isinstance(device, tuple)
            assert len(device) == 2
            assert "Stereo Mix" in device[1]

    def test_find_loopback_device_no_stereo_mix(self):
        devices = [
            {"name": "Microphone", "index": 0, "max_input_channels": 1, "max_output_channels": 0},
            {"name": "Speakers", "index": 1, "max_input_channels": 0, "max_output_channels": 2},
        ]
        with patch("sounddevice.query_devices", return_value=devices):
            device = find_loopback_device()
            assert device is None

    def test_find_virtual_cable(self, mock_device_list):
        with patch("sounddevice.query_devices", return_value=mock_device_list):
            device = find_vb_cable()
            assert device is None  # CABLE Input doesn't match; need CABLE Output

    def test_find_virtual_cable_output(self):
        devices = [
            {"name": "CABLE Output (VB-Audio Virtual Cable)", "index": 0, "max_input_channels": 2, "max_output_channels": 0},
        ]
        with patch("sounddevice.query_devices", return_value=devices):
            device = find_vb_cable()
            assert device is not None
            assert isinstance(device, int)
            assert device == 0

    def test_find_virtual_cable_not_found(self):
        devices = [
            {"name": "Microphone", "index": 0, "max_input_channels": 1, "max_output_channels": 0},
        ]
        with patch("sounddevice.query_devices", return_value=devices):
            device = find_vb_cable()
            assert device is None

    def test_loopback_discovery_case_insensitive(self, mock_device_list):
        mock_device_list[2]["name"] = "stereo mix (realtek audio)"
        with patch("sounddevice.query_devices", return_value=mock_device_list):
            device = find_loopback_device()
            assert device is not None
            assert device[1] == "Stereo Mix"

    def test_find_working_output_config_success(self):
        with patch("sounddevice.OutputStream") as mock_stream:
            mock_stream_instance = MagicMock()
            mock_stream.return_value.__enter__.return_value = mock_stream_instance
            config = try_open_output(device_id=None)
            assert config is not None
            assert config[0] in (24000, 44100, 48000, 16000)
            assert config[1] in (1, 2)

    def test_find_working_output_config_all_fail(self):
        with patch("sounddevice.OutputStream", side_effect=Exception("Device rejected")):
            config = try_open_output(device_id=None)
            assert config == (None, None)


class TestAudioResampler:
    def test_resample_basic(self):
        audio = np.random.randn(16000).astype(np.float32)
        resampled = resample(audio, src_rate=16000, dst_rate=8000)
        expected_length = len(audio) * 8000 // 16000
        assert len(resampled) == expected_length

    def test_resample_upsample(self):
        audio = np.random.randn(8000).astype(np.float32)
        resampled = resample(audio, src_rate=8000, dst_rate=16000)
        expected_length = len(audio) * 16000 // 8000
        assert len(resampled) == expected_length

    def test_resample_same_rate(self):
        audio = np.random.randn(16000).astype(np.float32)
        resampled = resample(audio, src_rate=16000, dst_rate=16000)
        assert len(resampled) == len(audio)

    def test_resample_values(self):
        audio = np.sin(2 * np.pi * 440 * np.arange(16000) / 16000).astype(np.float32)
        resampled = resample(audio, src_rate=16000, dst_rate=8000)
        assert np.all(np.isfinite(resampled))
        assert np.max(np.abs(resampled)) <= 1.0


class TestAudioProcessingChain:
    def test_peak_normalizer_process(self):
        processor = PeakNormalizer()

        async def run():
            audio = np.random.randn(16000).astype(np.float32) * 0.5
            result = await processor.process(audio, 16000)
            assert len(result) == len(audio)
            assert np.max(np.abs(result)) <= 1.0

        import asyncio
        asyncio.run(run())

    def test_peak_normalizer_silence(self):
        processor = PeakNormalizer()

        async def run():
            audio = np.zeros(16000, dtype=np.float32)
            result = await processor.process(audio, 16000)
            assert np.allclose(result, np.zeros(16000))

        import asyncio
        asyncio.run(run())

    def test_agc_process(self):
        processor = AutomaticGainControl(target_rms=0.1, attack=0.01, release=0.1)
        audio = np.random.randn(16000).astype(np.float32)

        async def run():
            result = await processor.process(audio, 16000)
            assert len(result) == len(audio)
            assert np.all(np.isfinite(result))

        import asyncio
        asyncio.run(run())

    def test_audio_level_computation(self):
        audio = np.ones(16000, dtype=np.float32) * 0.5
        level = float(np.sqrt(np.mean(audio ** 2)))
        assert level == pytest.approx(0.5, rel=0.01)