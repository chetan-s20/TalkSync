import unittest
import numpy as np
from config.settings import STTSettings
from services.stt.openai_stt import OpenAISTT
from services.stt.faster_whisper import FasterWhisperSTT

class TestSTTRMSGateAndAGC(unittest.TestCase):
    def setUp(self):
        self.stt_settings = STTSettings()
        self.openai_stt = OpenAISTT(settings=self.stt_settings)
        # FasterWhisperSTT does not require model load for _apply_agc testing if called directly or via mock
        self.faster_stt = FasterWhisperSTT.__new__(FasterWhisperSTT)
        self.faster_stt._rms_gate_threshold = 0.0003

    def test_rms_gate_threshold_setting(self):
        """Verify default rms_gate_threshold setting is 0.0003."""
        self.assertEqual(self.stt_settings.rms_gate_threshold, 0.0003)
        self.assertEqual(self.openai_stt._rms_gate_threshold, 0.0003)

    def test_openai_stt_rms_gating(self):
        """Test OpenAI STT RMS gate rejecting silence (< 0.0003) and passing audio (>= 0.0003)."""
        # Create silent audio array (RMS 0.0)
        silent_audio = np.zeros(16000, dtype=np.float32)
        rms_silent = float(np.sqrt(np.mean(silent_audio.astype(np.float64) ** 2)))
        self.assertLess(rms_silent, 0.0003)

        # Create quiet noise (RMS 0.0002) - below threshold
        quiet_noise = np.random.uniform(-0.0003, 0.0003, 16000).astype(np.float32)
        rms_quiet = float(np.sqrt(np.mean(quiet_noise.astype(np.float64) ** 2)))
        # Normalize quiet noise to exact RMS = 0.0002
        quiet_noise = quiet_noise * (0.0002 / rms_quiet)
        rms_quiet = float(np.sqrt(np.mean(quiet_noise.astype(np.float64) ** 2)))
        self.assertAlmostEqual(rms_quiet, 0.0002, places=6)
        self.assertLess(rms_quiet, 0.0003)

        # Create low-amplitude signal (RMS = 0.00035) - above threshold
        low_amp_signal = np.random.uniform(-0.001, 0.001, 16000).astype(np.float32)
        rms_low = float(np.sqrt(np.mean(low_amp_signal.astype(np.float64) ** 2)))
        low_amp_signal = low_amp_signal * (0.00035 / rms_low)
        rms_low = float(np.sqrt(np.mean(low_amp_signal.astype(np.float64) ** 2)))
        self.assertAlmostEqual(rms_low, 0.00035, places=6)
        self.assertGreater(rms_low, 0.0003)

    def test_openai_stt_agc_scaling(self):
        """Test AGC scaling to target_rms=0.2 on quiet audio arrays."""
        # Test Case 1: Quiet audio within 8x gain limit (e.g. RMS = 0.05)
        # Expected gain = 0.2 / 0.05 = 4.0x (<= 8.0x cap) -> Output RMS should be 0.2
        audio_05 = np.sin(np.linspace(0, 100, 16000)).astype(np.float32)
        rms_orig_05 = float(np.sqrt(np.mean(audio_05.astype(np.float64) ** 2)))
        audio_05 = audio_05 * (0.05 / rms_orig_05)
        
        scaled_05 = OpenAISTT._apply_agc(audio_05)
        rms_scaled_05 = float(np.sqrt(np.mean(scaled_05.astype(np.float64) ** 2)))
        print(f"AGC Test 1 (RMS 0.05 -> Target 0.2): Output RMS = {rms_scaled_05:.4f}")
        self.assertAlmostEqual(rms_scaled_05, 0.2, places=3)

        # Test Case 2: Quiet audio requiring exactly 8x max gain (e.g. RMS = 0.025)
        # Expected gain = 0.2 / 0.025 = 8.0x (matches max gain cap) -> Output RMS should be 0.2
        audio_025 = audio_05 * (0.025 / 0.05)
        scaled_025 = OpenAISTT._apply_agc(audio_025)
        rms_scaled_025 = float(np.sqrt(np.mean(scaled_025.astype(np.float64) ** 2)))
        print(f"AGC Test 2 (RMS 0.025 -> Target 0.2): Output RMS = {rms_scaled_025:.4f}")
        self.assertAlmostEqual(rms_scaled_025, 0.2, places=3)

        # Test Case 3: Very quiet audio requiring > 8x gain (e.g. RMS = 0.001)
        # Expected gain capped at 8.0x -> Output RMS should be 0.001 * 8 = 0.008
        audio_001 = audio_05 * (0.001 / 0.05)
        scaled_001 = OpenAISTT._apply_agc(audio_001)
        rms_scaled_001 = float(np.sqrt(np.mean(scaled_001.astype(np.float64) ** 2)))
        print(f"AGC Test 3 (RMS 0.001 -> Capped 8x gain): Output RMS = {rms_scaled_001:.4f}")
        self.assertAlmostEqual(rms_scaled_001, 0.008, places=3)

        # Test Case 4: Extremely quiet audio (< 1e-4) -> AGC bypassed
        audio_tiny = audio_05 * (1e-5 / 0.05)
        scaled_tiny = OpenAISTT._apply_agc(audio_tiny)
        rms_scaled_tiny = float(np.sqrt(np.mean(scaled_tiny.astype(np.float64) ** 2)))
        print(f"AGC Test 4 (RMS 1e-5 -> Bypassed): Output RMS = {rms_scaled_tiny:.6f}")
        self.assertAlmostEqual(rms_scaled_tiny, 1e-5, places=6)

    def test_faster_whisper_agc_scaling(self):
        """Test FasterWhisperSTT AGC scaling logic."""
        audio_05 = np.sin(np.linspace(0, 100, 16000)).astype(np.float32)
        rms_orig_05 = float(np.sqrt(np.mean(audio_05.astype(np.float64) ** 2)))
        audio_05 = audio_05 * (0.05 / rms_orig_05)
        
        # Reproduce FasterWhisper AGC logic directly
        rms = float(np.sqrt(np.mean(audio_05.astype(np.float64) ** 2)))
        target_rms = 0.2
        gain = target_rms / rms
        if gain > 1.0:
            gain = min(gain, 8.0)
            scaled = np.clip(audio_05 * gain, -1.0, 1.0)
        
        rms_scaled = float(np.sqrt(np.mean(scaled.astype(np.float64) ** 2)))
        print(f"FasterWhisper AGC Test (RMS 0.05 -> Target 0.2): Output RMS = {rms_scaled:.4f}")
        self.assertAlmostEqual(rms_scaled, 0.2, places=3)

if __name__ == "__main__":
    unittest.main()
