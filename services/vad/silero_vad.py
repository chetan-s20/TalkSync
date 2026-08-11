from __future__ import annotations

import time
from typing import AsyncIterator, Optional

import numpy as np
import torch

from app.interfaces import AudioChunk, VADResult, BaseVAD
from config.settings import VADSettings
from utils.logger import get_logger

logger = get_logger("vad")

# Default RMS noise floor — rejects silent chunks before VAD
RMS_GATE_THRESHOLD = 0.0003


class VADSpeechOutcome(tuple):
    """Tuple subclass representing (is_speech: bool, confidence: float) that also behaves cleanly as boolean."""
    def __new__(cls, is_speech: bool, confidence: float):
        return super().__new__(cls, (bool(is_speech), float(confidence)))

    @property
    def is_speech(self) -> bool:
        return self[0]

    @property
    def confidence(self) -> float:
        return self[1]

    def __bool__(self) -> bool:
        return self[0]


class SileroVAD(BaseVAD):
    def __init__(self, settings: VADSettings):
        self.settings = settings
        self._model = None
        self._running = False

    async def start(self) -> None:
        try:
            self._model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                trust_repo=True,
                onnx=False,
            )
            self._running = True
            self._model.eval()
            logger.info("Silero VAD loaded")
            # Quick sanity check: run VAD on synthetic speech-like signal (exactly 512 samples as required by model)
            try:
                sr = 16000
                n = 512  # Silero VAD requires exactly 512 samples at 16kHz
                t = np.arange(n)
                d = (0.4 * np.sin(2*np.pi*400*t/sr) + 0.3 * np.sin(2*np.pi*1200*t/sr) + 0.2 * np.sin(2*np.pi*2400*t/sr)).astype(np.float32)
                d *= 0.3
                rms_test = float(np.sqrt(np.mean(d**2)))
                t_tensor = torch.from_numpy(d).float().unsqueeze(0)
                with torch.no_grad():
                    test_prob = float(self._model(t_tensor, sr).item())
                logger.info(f"[DIAG] VAD_SANITY: RMS={rms_test:.4f} → prob={test_prob:.4f}")
                if test_prob < 0.001:
                    logger.warning("[DIAG] VAD_SANITY: model returned near-zero for synthetic audio — may be broken")
            except Exception as e:
                logger.warning(f"[DIAG] VAD_SANITY: check failed: {e}")
        except Exception as e:
            logger.error(f"Silero VAD failed to load: {e}")
            self._model = None
            self._running = True

    async def stop(self) -> None:
        self._running = False
        self._model = None

    def _eval_512_frame(self, frame_512: np.ndarray) -> float:
        """Evaluate a single 512-sample audio frame with Silero VAD model."""
        if self._model is None:
            return 0.0
        try:
            audio_writable = np.ascontiguousarray(frame_512, dtype=np.float32)
            tensor = torch.from_numpy(audio_writable).float().unsqueeze(0)
            with torch.no_grad():
                prob = float(self._model(tensor, 16000).item())
            return prob
        except Exception as e:
            logger.debug(f"Silero VAD frame eval error: {e}")
            return 0.0

    def is_speech(self, audio: np.ndarray) -> VADSpeechOutcome:
        """Analyze audio numpy array for speech presence using 512-sample frame windowing and noise floor gate."""
        if audio is None or len(audio) == 0:
            return VADSpeechOutcome(False, 0.0)

        # Ensure float32 array and clean NaNs
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        audio = np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)

        rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
        noise_floor_rms = getattr(self.settings, "rms_gate_threshold", 0.0003)
        if noise_floor_rms <= 0.0:
            noise_floor_rms = 0.0003

        # 1. Noise floor gate check: RMS < threshold mutes silent static intervals
        if rms < noise_floor_rms:
            return VADSpeechOutcome(False, 0.0)

        # Fallback heuristic mode if Silero VAD model is not loaded
        if self._model is None:
            is_sp = bool(np.mean(np.abs(audio)) > 0.01 and rms >= noise_floor_rms)
            prob = 0.8 if is_sp else 0.2
            return VADSpeechOutcome(is_sp, prob)

        threshold = getattr(self.settings, "threshold", 0.5)

        # 2. 512-sample frame iterator / sliding window for chunk sizes > 512
        chunk_len = len(audio)
        frame_probs = []

        if chunk_len < 512:
            # Short chunk: pad to 512 samples
            padded = np.pad(audio, (0, 512 - chunk_len))
            frame_probs.append(self._eval_512_frame(padded))
        else:
            # Chunk > 512 samples: process in 512-sample window frames
            step = 512
            for i in range(0, chunk_len, step):
                frame = audio[i : i + 512]
                if len(frame) < 512:
                    frame = np.pad(frame, (0, 512 - len(frame)))
                prob = self._eval_512_frame(frame)
                frame_probs.append(prob)

        max_prob = float(max(frame_probs)) if frame_probs else 0.0
        is_speech_bool = max_prob >= threshold
        return VADSpeechOutcome(is_speech_bool, max_prob)


    async def process(self, chunk: AudioChunk) -> AsyncIterator[VADResult]:
        if not self._running:
            return
        try:
            audio = np.frombuffer(chunk.data, dtype=np.float32).copy()
            outcome = self.is_speech(audio)

            yield VADResult(
                is_speech=outcome.is_speech,
                speech_start=None,
                speech_end=None,
                confidence=outcome.confidence,
                chunk=chunk,
            )
        except Exception as e:
            logger.error(f"VAD process error: {e}", exc_info=True)
            yield VADResult(is_speech=False, confidence=0.0, chunk=chunk)

