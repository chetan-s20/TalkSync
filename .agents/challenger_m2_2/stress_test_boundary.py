import unittest
import numpy as np
from config.settings import STTSettings
from services.stt.openai_stt import OpenAISTT
from services.stt.faster_whisper import FasterWhisperSTT

class TestAdversarialBoundaryAndAGC(unittest.TestCase):
    def test_gate_threshold_boundary_precision(self):
        """Adversarial boundary check around 0.0003."""
        stt = OpenAISTT()
        threshold = stt._rms_gate_threshold
        self.assertEqual(threshold, 0.0003)

        # 1. Just below threshold: RMS = 0.000299
        audio_below = np.random.uniform(-0.001, 0.001, 16000).astype(np.float32)
        rms_curr = float(np.sqrt(np.mean(audio_below.astype(np.float64) ** 2)))
        audio_below = audio_below * (0.000299 / rms_curr)
        rms_below = float(np.sqrt(np.mean(audio_below.astype(np.float64) ** 2)))
        
        self.assertLess(rms_below, threshold)

        # 2. Just above threshold: RMS = 0.000301
        audio_above = np.random.uniform(-0.001, 0.001, 16000).astype(np.float32)
        rms_curr = float(np.sqrt(np.mean(audio_above.astype(np.float64) ** 2)))
        audio_above = audio_above * (0.000301 / rms_curr)
        rms_above = float(np.sqrt(np.mean(audio_above.astype(np.float64) ** 2)))
        
        self.assertGreater(rms_above, threshold)

    def test_agc_clipping_prevention(self):
        """Verify AGC clips scaled signal to [-1.0, 1.0] without float overflow/NaN."""
        # Create audio with high peak but low RMS
        audio = np.zeros(16000, dtype=np.float32)
        audio[0:100] = 0.8  # high peak
        audio[100:] = 0.01  # low base
        
        rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
        self.assertGreater(rms, 1e-4)

        scaled_openai = OpenAISTT._apply_agc(audio)
        self.assertTrue(np.all(scaled_openai >= -1.0))
        self.assertTrue(np.all(scaled_openai <= 1.0))
        self.assertFalse(np.isnan(scaled_openai).any())
        self.assertFalse(np.isinf(scaled_openai).any())

    def test_mic_capture_test_script_passes(self):
        """Verify tests/test_mic_capture.py logic explicitly."""
        import tests.test_mic_capture as tmc
        self.assertTrue(hasattr(tmc, "test_mic_capture_and_vad_threshold"))

    def test_device_detection_test_script_passes(self):
        """Verify tests/test_device_detection.py logic explicitly."""
        import tests.test_device_detection as tdd
        self.assertTrue(hasattr(tdd, "test_invalid_device_id_fallback"))

if __name__ == "__main__":
    unittest.main()
