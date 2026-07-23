from __future__ import annotations

import time
from typing import AsyncIterator, Optional

import numpy as np
import torch

from app.interfaces import AudioChunk, VADResult, BaseVAD
from config.settings import VADSettings
from utils.logger import get_logger

logger = get_logger("vad")


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

    async def process(self, chunk: AudioChunk) -> AsyncIterator[VADResult]:
        if not self._running:
            return
        try:
            audio = np.frombuffer(chunk.data, dtype=np.float32)
            threshold = self.settings.threshold

            if self._model is not None:
                # Silero VAD requires exactly 512 samples at 16kHz — pad or truncate
                if audio.shape[0] < 512:
                    audio = np.pad(audio, (0, 512 - audio.shape[0]))
                elif audio.shape[0] > 512:
                    audio = audio[:512]
                audio_writable = np.ascontiguousarray(audio)
                tensor = torch.from_numpy(audio_writable).float().unsqueeze(0)

                with torch.no_grad():
                    prob = float(self._model(tensor, 16000).item())
                is_speech = prob >= threshold
            else:
                is_speech = bool(np.mean(np.abs(audio)) > 0.01)
                prob = 0.8 if is_speech else 0.2

            yield VADResult(
                is_speech=is_speech,
                speech_start=None,
                speech_end=None,
                confidence=prob,
                chunk=chunk,
            )
        except Exception as e:
            logger.debug(f"VAD process error: {e}")
            yield VADResult(is_speech=False, confidence=0.0, chunk=chunk)
