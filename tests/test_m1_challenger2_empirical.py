from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.interfaces import AudioChunk
from config.settings import AudioSettings, VADSettings
from services.audio.input import SoundDeviceInput
from services.diagnostics.stream_diagnostics import StreamDiagnostics
from services.vad.silero_vad import SileroVAD as ServicesSileroVAD
from vad.silero_vad import SileroVAD as DirectSileroVAD


def generate_audio_with_exact_rms(desired_rms: float, num_samples: int = 960, frequency: float = 440.0, sample_rate: int = 16000) -> np.ndarray:
    """Helper to generate a sine wave array scaled precisely to desired_rms."""
    t = np.arange(num_samples) / float(sample_rate)
    sine = np.sin(2.0 * np.pi * frequency * t).astype(np.float64)
    current_rms = np.sqrt(np.mean(sine ** 2))
    if current_rms == 0:
        return np.zeros(num_samples, dtype=np.float32)
    scaled = sine * (desired_rms / current_rms)
    return scaled.astype(np.float32)


# ============================================================================
# 1. EMPIRICAL CHALLENGE: Noise Floor Gating Threshold (0.0049 vs 0.0051 RMS)
# ============================================================================
class TestEmpiricalNoiseFloorGating:
    
    @pytest.mark.parametrize("vad_cls", [ServicesSileroVAD, DirectSileroVAD])
    def test_noise_floor_below_threshold_0049_is_gated(self, vad_cls):
        """Verify static/audio with RMS 0.0049 (< 0.005) is gated immediately without calling VAD model."""
        settings = VADSettings(threshold=0.5, rms_gate_threshold=0.005)
        vad = vad_cls(settings)
        vad._model = MagicMock()
        vad._running = True

        audio_0049 = generate_audio_with_exact_rms(0.0049, num_samples=960)
        actual_rms = float(np.sqrt(np.mean(audio_0049.astype(np.float64) ** 2)))
        assert actual_rms == pytest.approx(0.0049, abs=1e-5)
        assert actual_rms < 0.005

        with patch.object(vad, "_eval_512_frame") as mock_eval:
            outcome = vad.is_speech(audio_0049)
            
            # Gating assertion: Model evaluation must NOT be invoked
            assert mock_eval.call_count == 0
            
            # Gating outcome assertion: must evaluate to non-speech with 0.0 confidence
            if isinstance(outcome, tuple):
                is_sp, conf = outcome[0], outcome[1]
            else:
                is_sp, conf = outcome.is_speech, outcome.confidence
            
            assert is_sp is False
            assert conf == 0.0

    @pytest.mark.parametrize("vad_cls", [ServicesSileroVAD, DirectSileroVAD])
    def test_noise_floor_above_threshold_0051_passes_gate(self, vad_cls):
        """Verify audio with RMS 0.0051 (>= 0.005) passes noise gate and invokes VAD model evaluation."""
        settings = VADSettings(threshold=0.5, rms_gate_threshold=0.005)
        vad = vad_cls(settings)
        vad._model = MagicMock()
        vad._running = True

        audio_0051 = generate_audio_with_exact_rms(0.0051, num_samples=960)
        actual_rms = float(np.sqrt(np.mean(audio_0051.astype(np.float64) ** 2)))
        assert actual_rms == pytest.approx(0.0051, abs=1e-5)
        assert actual_rms >= 0.005

        with patch.object(vad, "_eval_512_frame", return_value=0.82) as mock_eval:
            outcome = vad.is_speech(audio_0051)

            # Verification: Model evaluation WAS called (passed gate)
            assert mock_eval.call_count > 0

            if isinstance(outcome, tuple):
                is_sp, conf = outcome[0], outcome[1]
            else:
                is_sp, conf = outcome.is_speech, outcome.confidence

            assert is_sp is True
            assert conf == pytest.approx(0.82)

    @pytest.mark.parametrize("vad_cls", [ServicesSileroVAD, DirectSileroVAD])
    def test_noise_floor_exact_boundary(self, vad_cls):
        """Verify sharp transition boundary at RMS 0.00499 vs RMS 0.00501."""
        settings = VADSettings(threshold=0.5, rms_gate_threshold=0.005)
        vad = vad_cls(settings)
        vad._model = MagicMock()
        vad._running = True

        audio_sub = generate_audio_with_exact_rms(0.00499, num_samples=960)
        audio_super = generate_audio_with_exact_rms(0.00501, num_samples=960)

        with patch.object(vad, "_eval_512_frame", return_value=0.7) as mock_eval:
            # Below boundary -> gated
            outcome_sub = vad.is_speech(audio_sub)
            assert mock_eval.call_count == 0
            is_sp_sub = outcome_sub[0] if isinstance(outcome_sub, tuple) else outcome_sub.is_speech
            assert is_sp_sub is False

            # Above boundary -> passes gate
            outcome_super = vad.is_speech(audio_super)
            assert mock_eval.call_count > 0
            is_sp_super = outcome_super[0] if isinstance(outcome_super, tuple) else outcome_super.is_speech
            assert is_sp_super is True

    @pytest.mark.parametrize("vad_cls", [ServicesSileroVAD, DirectSileroVAD])
    def test_noise_floor_fallback_heuristic_when_model_is_none(self, vad_cls):
        """Verify noise floor gating in fallback heuristic mode when _model is None."""
        settings = VADSettings(threshold=0.5, rms_gate_threshold=0.005)
        vad = vad_cls(settings)
        vad._model = None  # Force fallback heuristic mode
        vad._running = True

        audio_0049 = generate_audio_with_exact_rms(0.0049, num_samples=960)
        audio_0051 = generate_audio_with_exact_rms(0.0051, num_samples=960)

        # 0.0049 RMS should be False
        outcome_0049 = vad.is_speech(audio_0049)
        is_sp_0049 = outcome_0049[0] if isinstance(outcome_0049, tuple) else outcome_0049.is_speech
        assert is_sp_0049 is False

        # 0.0051 RMS with mean abs > 0.01 should be True in heuristic mode
        audio_loud = generate_audio_with_exact_rms(0.02, num_samples=960)
        outcome_loud = vad.is_speech(audio_loud)
        is_sp_loud = outcome_loud[0] if isinstance(outcome_loud, tuple) else outcome_loud.is_speech
        assert is_sp_loud is True


# ============================================================================
# 2. EMPIRICAL CHALLENGE: Device Candidate Fallback Logic & WASAPI Loopback
# ============================================================================
class TestEmpiricalDeviceCandidateFallback:

    @pytest.mark.asyncio
    async def test_mic_candidate_fallback_sequence_on_specified_device_failure(self):
        """Verify _start_mic falls back through candidate list when specified device fails."""
        settings = AudioSettings(input_device_id=99, sample_rate=16000, channels=1)
        audio_input = SoundDeviceInput(settings)
        audio_input._running = True
        audio_input._loop = asyncio.get_running_loop()

        # Querying device 99 fails
        def mock_query_devices(dev=None):
            if dev == 99:
                raise Exception("PortAudio device 99 query error")
            if dev is None:
                return [{"name": f"Device {i}", "max_input_channels": 2, "default_samplerate": 44100} for i in range(100)]
            return {"default_samplerate": 44100, "max_input_channels": 2}

        # InputStream succeeds only when device=None (default fallback)
        def mock_input_stream(**kwargs):
            if kwargs.get("device") == 99:
                raise Exception("Cannot open device 99")
            stream_mock = MagicMock()
            return stream_mock

        with patch("sounddevice.query_devices", side_effect=mock_query_devices):
            with patch("sounddevice.InputStream", side_effect=mock_input_stream):
                await audio_input._start_mic(device_id=99)

                # Mic stream initialized via fallback
                assert audio_input._mic_stream is not None
                # Init error logged for specified device query failure
                assert len(audio_input._device_init_errors) == 1
                assert "Query specified mic device 99 failed" in audio_input._device_init_errors[0]

    @pytest.mark.asyncio
    async def test_mic_all_candidates_failed_raises_runtime_error(self):
        """Verify RuntimeError is raised and error recorded when all mic candidates fail."""
        settings = AudioSettings(input_device_id=1, sample_rate=16000, channels=1)
        audio_input = SoundDeviceInput(settings)
        audio_input._running = True
        audio_input._loop = asyncio.get_running_loop()

        with patch("sounddevice.query_devices", return_value={"default_samplerate": 48000, "max_input_channels": 1}):
            with patch("sounddevice.InputStream", side_effect=Exception("PortAudio total device failure")):
                with pytest.raises(RuntimeError) as exc_info:
                    await audio_input._start_mic(device_id=1)

                assert "Mic fallbacks failed" in str(exc_info.value)
                assert len(audio_input._device_init_errors) >= 1

    @pytest.mark.asyncio
    async def test_wasapi_loopback_fallback_to_stereo_mix(self):
        """Verify WASAPI failure invokes _start_fallback_loopback to Stereo Mix."""
        settings = AudioSettings(sample_rate=16000)
        audio_input = SoundDeviceInput(settings)

        with patch("services.audio.input.find_loopback_device", return_value=("Realtek WASAPI", "WASAPI")):
            with patch.object(audio_input, "_start_wasapi_loopback", side_effect=Exception("WASAPI initialization error")):
                with patch("services.audio.input.find_stereo_mix", return_value=3):
                    with patch.object(audio_input, "_start_sd_loopback", new_callable=AsyncMock) as mock_sd_loopback:
                        with patch.object(audio_input, "_start_mic", new_callable=AsyncMock):
                            await audio_input.start(loopback=True, capture_mic=False)
                            mock_sd_loopback.assert_called_once_with(3, "Stereo Mix")
                            assert len(audio_input._device_init_errors) == 1
                            assert "WASAPI loopback failed" in audio_input._device_init_errors[0]

    @pytest.mark.asyncio
    async def test_wasapi_loopback_fallback_to_vb_cable_when_no_stereo_mix(self):
        """Verify WASAPI failure falls back to VB-Cable Output if Stereo Mix is unavailable."""
        settings = AudioSettings(sample_rate=16000)
        audio_input = SoundDeviceInput(settings)

        with patch("services.audio.input.find_loopback_device", return_value=("WASAPI Dev", "WASAPI")):
            with patch.object(audio_input, "_start_wasapi_loopback", side_effect=Exception("WASAPI error")):
                with patch("services.audio.input.find_stereo_mix", return_value=None):
                    with patch("services.audio.input.find_vb_cable", return_value=7):
                        with patch.object(audio_input, "_start_sd_loopback", new_callable=AsyncMock) as mock_sd_loopback:
                            with patch.object(audio_input, "_start_mic", new_callable=AsyncMock):
                                await audio_input.start(loopback=True, capture_mic=False)
                                mock_sd_loopback.assert_called_once_with(7, "VB-Cable Output")

    @pytest.mark.asyncio
    async def test_wasapi_loopback_total_fallback_failure_raises_runtime_error(self):
        """Verify RuntimeError is raised when WASAPI fails and no fallback loopback device exists."""
        settings = AudioSettings(sample_rate=16000)
        audio_input = SoundDeviceInput(settings)

        with patch("services.audio.input.find_loopback_device", return_value=("WASAPI Dev", "WASAPI")):
            with patch.object(audio_input, "_start_wasapi_loopback", side_effect=Exception("WASAPI error")):
                with patch("services.audio.input.find_stereo_mix", return_value=None):
                    with patch("services.audio.input.find_vb_cable", return_value=None):
                        with pytest.raises(RuntimeError) as exc_info:
                            await audio_input.start(loopback=True, capture_mic=False)

                        assert "WASAPI loopback failed and no sounddevice fallback loopback device found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_wasapi_capture_thread_exception_records_device_init_error(self):
        """Verify background WASAPI capture thread error appends to _device_init_errors."""
        settings = AudioSettings(sample_rate=16000, chunk_duration_ms=30)
        audio_input = SoundDeviceInput(settings)
        audio_input._loop = asyncio.get_running_loop()
        audio_input._loopback_queue = asyncio.Queue()

        mock_loop_dev = MagicMock()
        mock_recorder = MagicMock()
        mock_recorder.__enter__.return_value = mock_recorder
        mock_recorder.record.side_effect = Exception("Hardware stream disconnected")
        mock_loop_dev.recorder.return_value = mock_recorder

        mock_sc = MagicMock()
        mock_mic = MagicMock()
        mock_mic.isloopback = True
        mock_mic.name = "Speakers (Loopback)"
        mock_sc.all_microphones.return_value = [mock_mic]

        with patch.dict("sys.modules", {"soundcard": mock_sc}):
            with patch.object(mock_mic, "recorder", return_value=mock_recorder):
                await audio_input._start_wasapi_loopback("Speakers (Loopback)")
                # Give background thread time to execute
                await asyncio.sleep(0.1)

                assert len(audio_input._device_init_errors) >= 1
                assert any("WASAPI capture error: Hardware stream disconnected" in err for err in audio_input._device_init_errors)
                await audio_input.stop()


# ============================================================================
# 3. EMPIRICAL CHALLENGE: StreamDiagnostics Assertions under Clean vs Fault Conditions
# ============================================================================
class TestEmpiricalStreamDiagnostics:

    def test_stream_diagnostics_clean_stream_assertions_pass(self):
        """Verify assert_stream_reliability passes for single and global diagnostics on clean stream."""
        diag = StreamDiagnostics()

        clean_stream = MagicMock()
        clean_stream.get_diagnostics.return_value = {
            "running": True,
            "overflow_count": 0,
            "underflow_count": 0,
            "total_chunks": 500,
            "device_init_errors": [],
        }

        diag.register_stream("mic", clean_stream)

        status = diag.get_stream_status("mic")
        assert status["registered"] is True
        assert status["overflow_count"] == 0

        global_status = diag.get_all_diagnostics()
        assert global_status["is_reliable"] is True
        assert global_status["stream_count"] == 1

        # Must not raise any AssertionError
        diag.assert_stream_reliability("mic")
        diag.assert_stream_reliability()

    def test_stream_diagnostics_buffer_overflow_fault_injection(self):
        """Verify assert_stream_reliability raises AssertionError when buffer overflow occurs."""
        diag = StreamDiagnostics()

        faulty_stream = MagicMock()
        faulty_stream.get_diagnostics.return_value = {
            "running": True,
            "overflow_count": 5,
            "underflow_count": 0,
            "total_chunks": 200,
            "device_init_errors": [],
        }

        diag.register_stream("loopback", faulty_stream)

        # Query assertion
        status = diag.get_all_diagnostics()
        assert status["is_reliable"] is False
        assert status["total_overflows"] == 5

        # Stream specific assertion
        with pytest.raises(AssertionError) as exc_mic:
            diag.assert_stream_reliability("loopback")
        assert "buffer overflows: 5" in str(exc_mic.value)

        # Global assertion
        with pytest.raises(AssertionError) as exc_global:
            diag.assert_stream_reliability()
        assert "Global audio stream reliability assertion failed: overflows=5" in str(exc_global.value)

    def test_stream_diagnostics_buffer_underflow_fault_injection(self):
        """Verify assert_stream_reliability raises AssertionError when buffer underflow occurs."""
        diag = StreamDiagnostics()

        faulty_stream = MagicMock()
        faulty_stream.get_diagnostics.return_value = {
            "running": True,
            "overflow_count": 0,
            "underflow_count": 3,
            "total_chunks": 150,
            "device_init_errors": [],
        }

        diag.register_stream("mic", faulty_stream)

        with pytest.raises(AssertionError) as exc:
            diag.assert_stream_reliability("mic")
        assert "buffer underflows: 3" in str(exc.value)

    def test_stream_diagnostics_device_init_error_fault_injection(self):
        """Verify assert_stream_reliability raises AssertionError when device init errors exist."""
        diag = StreamDiagnostics()

        faulty_stream = MagicMock()
        faulty_stream.get_diagnostics.return_value = {
            "running": False,
            "overflow_count": 0,
            "underflow_count": 0,
            "total_chunks": 0,
            "device_init_errors": ["WASAPI loopback failed (Speakers): Device unavailable"],
        }

        diag.register_stream("wasapi_loopback", faulty_stream)

        with pytest.raises(AssertionError) as exc:
            diag.assert_stream_reliability("wasapi_loopback")
        assert "device errors: ['WASAPI loopback failed" in str(exc.value)

    def test_stream_diagnostics_unregistered_stream_assertion_fails(self):
        """Verify asserting reliability on an unregistered stream raises AssertionError."""
        diag = StreamDiagnostics()
        with pytest.raises(AssertionError) as exc:
            diag.assert_stream_reliability("unregistered_stream_name")
        assert "Stream 'unregistered_stream_name' is not registered for reliability assertion" in str(exc.value)

    def test_stream_diagnostics_mixed_multi_stream_reliability(self):
        """Verify global reliability fails if any one stream in a multi-stream setup has faults."""
        diag = StreamDiagnostics()

        clean_stream = MagicMock()
        clean_stream.get_diagnostics.return_value = {
            "overflow_count": 0, "underflow_count": 0, "device_init_errors": []
        }

        flaky_stream = MagicMock()
        flaky_stream.get_diagnostics.return_value = {
            "overflow_count": 0, "underflow_count": 1, "device_init_errors": []
        }

        diag.register_stream("mic", clean_stream)
        diag.register_stream("loopback", flaky_stream)

        # Stream-specific check on mic passes
        diag.assert_stream_reliability("mic")

        # Stream-specific check on loopback fails
        with pytest.raises(AssertionError):
            diag.assert_stream_reliability("loopback")

        # Global check fails
        with pytest.raises(AssertionError):
            diag.assert_stream_reliability()
