"""Faster-Whisper STT implementation with dedicated executor."""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncIterator, Optional

import numpy as np

from core.interfaces import TranscriptionSegment
from config.settings import STTSettings
from utils.logger import get_logger

logger = get_logger("stt")


class FasterWhisperSTT:
    def __init__(self, settings):
        self.settings = getattr(settings, "stt", settings)
        self._model = None
        self._executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="stt"
        )
        self._loaded = False
        self._language: Optional[str] = None

    async def start(self, language: str = "auto") -> None:
        try:
            from faster_whisper import WhisperModel
            lang = None if language == "auto" else language
            self._language = lang
            model_name = getattr(self.settings, "model", "Systran/faster-whisper-small")
            beam = getattr(self.settings, "beam_size", 2)
            logger.info(f"Loading STT model: {model_name}")
            t0 = time.perf_counter()
            self._model = WhisperModel(
                model_name,
                device="cuda",
                compute_type="float16",
            )
            elapsed = time.perf_counter() - t0
            self._loaded = True
            logger.info(f"STT model loaded in {elapsed:.1f}s")
        except Exception as e:
            logger.error(f"STT model failed to load: {e}")
            try:
                from faster_whisper import WhisperModel
                model_name = getattr(self.settings, "model", "Systran/faster-whisper-small")
                self._model = WhisperModel(model_name, device="cpu", compute_type="int8")
                self._loaded = True
                logger.warning("STT falling back to CPU int8")
            except Exception as cpu_e:
                logger.error(f"CPU fallback also failed: {cpu_e}")
                raise RuntimeError("Unable to initialize STT model") from cpu_e

    async def stop(self) -> None:
        self._loaded = False
        self._executor.shutdown(wait=False)
        self._model = None

    async def stream(self, audio: Any) -> AsyncIterator[TranscriptionSegment]:
        segment = await self.transcribe(audio, is_final=True)
        if segment.text:
            yield segment

    async def transcribe(self, audio: Any, is_final: bool = True, **kwargs) -> TranscriptionSegment:
        if not self._loaded or self._model is None:
            return TranscriptionSegment(
                text="", is_final=is_final,
                start_time=__import__("datetime").datetime.now(),
                end_time=__import__("datetime").datetime.now(),
                language="", confidence=0.0,
            )

        # VAD sends raw bytes; convert to float32 numpy array for faster-whisper
        if isinstance(audio, bytes):
            audio = np.frombuffer(audio, dtype=np.float32)

        def _run():
            segments_gen, info = self._model.transcribe(
                audio,
                beam_size=getattr(self.settings, "beam_size", 2),
                language=self._language,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=getattr(
                        getattr(self.settings, "vad", None),
                        "min_silence_duration_ms",
                        550,
                    ) if hasattr(self.settings, "vad") else 550
                ),
                word_timestamps=False,
            )
            text_parts = []
            language = ""
            confidence = 0.0
            for seg in segments_gen:
                text_parts.append(seg.text)
                language = getattr(info, "language", language) or language
                confidence = max(confidence, getattr(seg, "avg_logprob", 0.0) * -1)
            joined = " ".join(text_parts).strip()
            return joined, language, confidence

        try:
            text, language, confidence = await asyncio.get_running_loop().run_in_executor(
                self._executor, _run
            )
        except Exception as e:
            logger.error(f"STT transcribe error: {e}")
            return TranscriptionSegment(
                text="", is_final=is_final,
                start_time=__import__("datetime").datetime.now(),
                end_time=__import__("datetime").datetime.now(),
                language="", confidence=0.0,
            )

        return TranscriptionSegment(
            text=text,
            is_final=is_final,
            start_time=__import__("datetime").datetime.now(),
            end_time=__import__("datetime").datetime.now(),
            language=language,
            confidence=confidence,
        )
