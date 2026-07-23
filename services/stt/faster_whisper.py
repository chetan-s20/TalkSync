from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, AsyncIterator, Optional

import numpy as np

from app.interfaces import TranscriptionSegment
from utils.logger import get_logger

logger = get_logger("stt")


class FasterWhisperSTT:
    def __init__(
        self,
        settings: Any = None,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        beam_size: Optional[int] = None,
        vad_filter: bool = True,
        no_speech_threshold: Optional[float] = None,
        compression_ratio_threshold: Optional[float] = None,
        log_prob_threshold: Optional[float] = None,
        initial_prompt: Optional[str] = None,
        **kwargs,
    ):
        if settings is not None:
            stt_settings = getattr(settings, "stt", settings)
        else:
            try:
                from config.settings import STTSettings
                stt_settings = STTSettings()
            except Exception:
                stt_settings = None

        self.settings = stt_settings
        self._model_name = model_name or getattr(stt_settings, "model", "Systran/faster-whisper-small")
        self._device = device or getattr(stt_settings, "device", "cpu")
        self._beam_size = beam_size if beam_size is not None else getattr(stt_settings, "beam_size", 1)
        self._vad_filter = vad_filter
        self._no_speech_threshold = no_speech_threshold if no_speech_threshold is not None else getattr(stt_settings, "no_speech_threshold", 0.7)
        self._compression_ratio_threshold = compression_ratio_threshold if compression_ratio_threshold is not None else getattr(stt_settings, "compression_ratio_threshold", 2.4)
        self._log_prob_threshold = log_prob_threshold if log_prob_threshold is not None else getattr(stt_settings, "log_prob_threshold", -1.0)
        self._initial_prompt = initial_prompt if initial_prompt is not None else getattr(stt_settings, "initial_prompt", None)

        self._model = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="stt")
        self._loaded = False
        self._language: Optional[str] = None

        try:
            from faster_whisper import WhisperModel
            compute_type = "float16" if self._device == "cuda" else "int8"
            self._model = WhisperModel(self._model_name, device=self._device, compute_type=compute_type)
            self._loaded = True
        except Exception:
            pass

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def beam_size(self) -> int:
        return self._beam_size

    @property
    def vad_filter(self) -> bool:
        return self._vad_filter

    @property
    def no_speech_threshold(self) -> float:
        return self._no_speech_threshold

    @property
    def compression_ratio_threshold(self) -> float:
        return self._compression_ratio_threshold

    @property
    def log_prob_threshold(self) -> float:
        return self._log_prob_threshold

    async def start(self, language: Optional[str] = None) -> None:
        if isinstance(language, str) and language.strip().lower() in ("auto", "automatic"):
            language = None
        if self._model is None:
            from faster_whisper import WhisperModel
            self._language = language
            logger.info(f"Loading STT model: {self._model_name}")
            t0 = time.perf_counter()
            try:
                self._model = WhisperModel(
                    self._model_name, device="cuda", compute_type="float16",
                )
                self._loaded = True
                logger.info(f"STT model loaded in {time.perf_counter() - t0:.1f}s")
            except Exception as e:
                logger.error(f"CUDA load failed: {e}")
                try:
                    self._model = WhisperModel(self._model_name, device="cpu", compute_type="int8")
                    self._loaded = True
                    logger.warning("STT falling back to CPU int8")
                except Exception as cpu_e:
                    logger.error(f"CPU fallback failed: {cpu_e}")
                    raise RuntimeError("STT model init failed") from cpu_e
        else:
            self._language = language
            self._loaded = True

    async def stop(self) -> None:
        self._loaded = False
        self._executor.shutdown(wait=False)
        self._model = None

    async def stream(self, audio: Any) -> AsyncIterator[TranscriptionSegment]:
        segment = await self.transcribe(audio, is_final=True)
        if segment and segment.text:
            yield segment

    def transcribe(
        self,
        audio: Any,
        sample_rate: Any = 16000,
        is_final: bool = True,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        **kwargs,
    ) -> Any:
        # VAD sends raw bytes; convert to writable float32 numpy array for faster-whisper
        if isinstance(audio, bytes):
            audio = np.frombuffer(audio, dtype=np.float32).copy()

        def _get_result():
            if self._model is None:
                return None

            try:
                lang = language if language is not None else self._language
                if isinstance(lang, str) and lang.strip().lower() in ("auto", "automatic"):
                    lang = None
                prompt = initial_prompt if initial_prompt is not None else self._initial_prompt
                segments_gen, info = self._model.transcribe(
                    audio,
                    beam_size=self._beam_size,
                    language=lang,
                    vad_filter=self._vad_filter,
                    no_speech_threshold=self._no_speech_threshold,
                    log_prob_threshold=self._log_prob_threshold,
                    compression_ratio_threshold=self._compression_ratio_threshold,
                    initial_prompt=prompt,
                )
                text_parts = []
                max_logprob = -999.0
                for seg in segments_gen:
                    def _to_float(v, default):
                        return float(v) if isinstance(v, (int, float)) else default

                    avg_lp = _to_float(getattr(seg, "avg_logprob", None), 0.0)
                    no_speech = _to_float(getattr(seg, "no_speech_prob", None), 0.0)
                    comp_ratio = _to_float(getattr(seg, "compression_ratio", None), 0.0)
                    if avg_lp < self._log_prob_threshold:
                        continue
                    if no_speech > self._no_speech_threshold:
                        continue
                    if comp_ratio > self._compression_ratio_threshold:
                        continue
                    text_parts.append(seg.text)
                    if avg_lp > max_logprob:
                        max_logprob = avg_lp
                text = " ".join(text_parts).strip()
                if not text:
                    return None

                detected_lang = getattr(info, "language", "") or ""
                lang_prob = float(getattr(info, "language_probability", 0.0) or 0.0)
                return TranscriptionSegment(
                    text=text, is_final=is_final,
                    start_time=datetime.now(), end_time=datetime.now(),
                    language=detected_lang, confidence=lang_prob,
                    language_probability=lang_prob,
                )
            except Exception as e:
                logger.error(f"STT error: {e}")
                return None

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            return loop.run_in_executor(self._executor, _get_result)
        else:
            return _get_result()
