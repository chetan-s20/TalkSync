"""
Real-time audio capture verification test.
Tests microphone and loopback audio capture without errors.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import numpy as np
import pytest
import sounddevice as sd

from config.settings import AudioSettings
from services.audio.input import SoundDeviceInput
from services.audio.loopback import find_loopback_device, find_stereo_mix


class TestRealAudioCapture:
    """Test suite for verifying real-time audio capture from mic and loopback."""

    def test_list_audio_devices(self):
        """Verify audio device enumeration works."""
        devices = sd.query_devices()
        assert len(devices) > 0, "No audio devices found"

        mic_devices = [d for d in devices if d['max_input_channels'] > 0]
        output_devices = [d for d in devices if d['max_output_channels'] > 0]

        print(f"\n=== Audio Devices Found ===")
        print(f"Input devices: {len(mic_devices)}")
        print(f"Output devices: {len(output_devices)}")

        assert len(mic_devices) > 0, "No microphone input devices found"
        assert len(output_devices) > 0, "No audio output devices found"

    def test_find_loopback_device(self):
        """Verify loopback device (Stereo Mix or VB-Cable) can be found."""
        loopback = find_loopback_device()

        if loopback is None:
            pytest.skip("No loopback device (Stereo Mix or VB-Cable) available")

        device, dev_type = loopback
        print(f"\n=== Loopback Device ===")
        print(f"Type: {dev_type}")
        print(f"Device: {device}")

        assert dev_type in ("WASAPI", "sounddevice")

    def test_find_stereo_mix(self):
        """Verify Stereo Mix device can be found."""
        stereo_mix_idx = find_stereo_mix()

        if stereo_mix_idx is None:
            pytest.skip("Stereo Mix not available (enable in Windows Sound Settings)")

        devices = sd.query_devices()
        stereo_mix = devices[stereo_mix_idx]

        print(f"\n=== Stereo Mix Device ===")
        print(f"Index: {stereo_mix_idx}")
        print(f"Name: {stereo_mix['name']}")
        print(f"Channels: {stereo_mix['max_input_channels']}")
        print(f"Sample Rate: {stereo_mix['default_samplerate']}")

        assert stereo_mix['max_input_channels'] > 0

    @pytest.mark.asyncio
    async def test_microphone_capture(self):
        """
        Test real-time microphone audio capture.
        Captures 2 seconds of mic audio and verifies:
        - Stream starts without errors
        - Audio chunks are received
        - No buffer overflows
        - Stream stops cleanly
        """
        settings = AudioSettings()
        audio_input = SoundDeviceInput(settings)

        try:
            await audio_input.start(loopback=False, capture_mic=True)

            chunks_received = []
            rms_levels = []
            start_time = time.time()

            async for chunk in audio_input.stream():
                chunks_received.append(chunk)

                # Calculate RMS level
                audio_data = np.frombuffer(chunk.data, dtype=np.float32)
                rms = float(np.sqrt(np.mean(audio_data ** 2)))
                rms_levels.append(rms)

                # Capture for 2 seconds
                if time.time() - start_time > 2.0:
                    break

            await audio_input.stop()

            print(f"\n=== Microphone Capture Results ===")
            print(f"Chunks received: {len(chunks_received)}")
            print(f"Average RMS: {np.mean(rms_levels):.6f}")
            print(f"Max RMS: {np.max(rms_levels):.6f}")
            print(f"Overflows: {audio_input._overflow_count}")
            print(f"Underflows: {audio_input._underflow_count}")
            print(f"Device errors: {audio_input._device_init_errors}")

            assert len(chunks_received) > 0, "No audio chunks received from microphone"
            assert audio_input._overflow_count < 10, f"Too many buffer overflows: {audio_input._overflow_count}"
            assert len(audio_input._device_init_errors) == 0, f"Device init errors: {audio_input._device_init_errors}"

        except Exception as e:
            await audio_input.stop()
            raise

    @pytest.mark.asyncio
    async def test_loopback_capture(self):
        """
        Test real-time loopback (computer audio) capture.
        Captures 2 seconds of loopback audio and verifies:
        - Stream starts without errors
        - Audio chunks are received
        - No buffer overflows
        - Stream stops cleanly

        Note: This test requires Stereo Mix to be enabled or VB-Cable installed.
        """
        loopback_device = find_loopback_device()
        if loopback_device is None:
            pytest.skip("No loopback device available (enable Stereo Mix or install VB-Cable)")

        settings = AudioSettings()
        audio_input = SoundDeviceInput(settings)

        try:
            await audio_input.start(loopback=True, capture_mic=False)

            chunks_received = []
            rms_levels = []
            start_time = time.time()

            async for chunk in audio_input.stream_loopback():
                chunks_received.append(chunk)

                # Calculate RMS level
                audio_data = np.frombuffer(chunk.data, dtype=np.float32)
                rms = float(np.sqrt(np.mean(audio_data ** 2)))
                rms_levels.append(rms)

                # Capture for 2 seconds
                if time.time() - start_time > 2.0:
                    break

            await audio_input.stop()

            print(f"\n=== Loopback Capture Results ===")
            print(f"Chunks received: {len(chunks_received)}")
            print(f"Average RMS: {np.mean(rms_levels):.6f}")
            print(f"Max RMS: {np.max(rms_levels):.6f}")
            print(f"Overflows: {audio_input._overflow_count}")
            print(f"Underflows: {audio_input._underflow_count}")
            print(f"Device errors: {audio_input._device_init_errors}")

            assert len(chunks_received) > 0, "No audio chunks received from loopback"
            assert audio_input._overflow_count < 10, f"Too many buffer overflows: {audio_input._overflow_count}"
            assert len(audio_input._device_init_errors) == 0, f"Device init errors: {audio_input._device_init_errors}"

        except Exception as e:
            await audio_input.stop()
            raise

    @pytest.mark.asyncio
    async def test_dual_capture_mic_and_loopback(self):
        """
        Test simultaneous microphone and loopback capture (meeting mode).
        Captures from both sources for 2 seconds and verifies:
        - Both streams start without errors
        - Audio chunks are received from both sources
        - Source tagging is correct
        - No conflicts between streams
        """
        loopback_device = find_loopback_device()
        if loopback_device is None:
            pytest.skip("No loopback device available (enable Stereo Mix or install VB-Cable)")

        settings = AudioSettings()
        audio_input = SoundDeviceInput(settings)

        try:
            await audio_input.start(loopback=True, capture_mic=True)

            mic_chunks = []
            loopback_chunks = []
            start_time = time.time()

            # Create tasks for both streams
            async def capture_mic():
                async for chunk in audio_input.stream():
                    mic_chunks.append(chunk)
                    if time.time() - start_time > 2.0:
                        break

            async def capture_loopback():
                async for chunk in audio_input.stream_loopback():
                    loopback_chunks.append(chunk)
                    if time.time() - start_time > 2.0:
                        break

            # Run both captures concurrently
            await asyncio.gather(
                capture_mic(),
                capture_loopback(),
            )

            await audio_input.stop()

            print(f"\n=== Dual Capture Results ===")
            print(f"Mic chunks: {len(mic_chunks)}")
            print(f"Loopback chunks: {len(loopback_chunks)}")
            print(f"Overflows: {audio_input._overflow_count}")
            print(f"Device errors: {audio_input._device_init_errors}")

            assert len(mic_chunks) > 0, "No mic chunks received"
            assert len(loopback_chunks) > 0, "No loopback chunks received"
            assert audio_input._overflow_count < 20, f"Too many overflows in dual capture: {audio_input._overflow_count}"

            # Verify source tagging
            assert all(c.source == "mic" for c in mic_chunks), "Mic chunks have incorrect source tag"
            assert all(c.source == "loopback" for c in loopback_chunks), "Loopback chunks have incorrect source tag"

        except Exception as e:
            await audio_input.stop()
            raise
