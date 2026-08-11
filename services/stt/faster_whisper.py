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
        best_of: Optional[int] = None,
        temperature: Optional[float] = None,
        vad_filter: Optional[bool] = None,
        no_speech_threshold: Optional[float] = None,
        compression_ratio_threshold: Optional[float] = None,
        log_prob_threshold: Optional[float] = None,
        condition_on_previous_text: Optional[bool] = None,
        initial_prompt: Optional[str] = None,
        rms_gate_threshold: Optional[float] = None,
        min_word_count: Optional[int] = None,
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
        self._beam_size = beam_size if beam_size is not None else getattr(stt_settings, "beam_size", 5)
        self._best_of = best_of if best_of is not None else getattr(stt_settings, "best_of", 5)
        self._temperature = temperature if temperature is not None else getattr(stt_settings, "temperature", 0.0)
        self._vad_filter = vad_filter if vad_filter is not None else getattr(stt_settings, "vad_filter", False)
        self._no_speech_threshold = no_speech_threshold if no_speech_threshold is not None else getattr(stt_settings, "no_speech_threshold", 0.75)
        self._compression_ratio_threshold = compression_ratio_threshold if compression_ratio_threshold is not None else getattr(stt_settings, "compression_ratio_threshold", 2.0)
        self._log_prob_threshold = log_prob_threshold if log_prob_threshold is not None else getattr(stt_settings, "log_prob_threshold", -1.0)
        self._condition_on_previous_text = condition_on_previous_text if condition_on_previous_text is not None else getattr(stt_settings, "condition_on_previous_text", False)
        self._initial_prompt = initial_prompt if initial_prompt is not None else getattr(stt_settings, "initial_prompt", None)
        self._rms_gate_threshold = rms_gate_threshold if rms_gate_threshold is not None else getattr(stt_settings, "rms_gate_threshold", 0.0003)
        self._min_word_count = min_word_count if min_word_count is not None else getattr(stt_settings, "min_word_count", 1)

        self._model = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="stt")
        self._loaded = False
        self._language: Optional[str] = None

        try:
            from faster_whisper import WhisperModel
            # Respect compute_type from settings, fallback to device-optimized default
            compute_type = getattr(stt_settings, "compute_type", None) or (
                "float16" if self._device == "cuda" else "int8"
            )
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

    @property
    def condition_on_previous_text(self) -> bool:
        return self._condition_on_previous_text

    @property
    def temperature(self) -> float:
        return self._temperature

    @property
    def best_of(self) -> int:
        return self._best_of

    @property
    def rms_gate_threshold(self) -> float:
        return self._rms_gate_threshold

    @property
    def min_word_count(self) -> int:
        return self._min_word_count

    async def start(self, language: Optional[str] = None) -> None:
        if isinstance(language, str) and language.strip().lower() in ("auto", "automatic"):
            language = None
        # Recreate executor in case it was shut down during previous stop()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="stt")
        if self._model is None:
            from faster_whisper import WhisperModel
            self._language = language
            logger.info(f"Loading STT model: {self._model_name}")
            t0 = time.perf_counter()
            try:
                # Respect compute_type from settings, fallback to device-optimized default
                compute_type = getattr(self.settings, "compute_type", None) or (
                    "float16" if self._device == "cuda" else "int8"
                )
                self._model = WhisperModel(
                    self._model_name,
                    device=self._device,
                    compute_type=compute_type,
                )
                self._loaded = True
                elapsed = time.perf_counter() - t0
                logger.info(f"STT model loaded in {elapsed:.1f}s")

                # Log GPU info if using CUDA
                if self._device == "cuda":
                    try:
                        import torch
                        if torch.cuda.is_available():
                            gpu_name = torch.cuda.get_device_name(0)
                            vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
                            logger.info(f"STT using GPU: {gpu_name}, VRAM: {vram_gb:.1f}GB, compute_type: {compute_type}")
                    except Exception:
                        pass
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
        if isinstance(audio, bytes):
            audio = np.frombuffer(audio, dtype=np.float32).copy()

        # 1. RMS Energy Gate: reject silent/low-energy audio before STT (run on raw signal)
        # 1. RMS Energy Gate: reject silent/low-energy noise audio before STT
        raw_rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
        gate_thresh = max(0.003, self._rms_gate_threshold)
        if raw_rms < gate_thresh:
            logger.debug(f"STT: RMS gate triggered ({raw_rms:.6f} < {gate_thresh}) — rejecting silence")
            return None

        # DSP Step 1: 100Hz Butterworth Highpass Filter to remove low-frequency rumble
        try:
            import scipy.signal
            nyq = 0.5 * 16000.0
            normal_cutoff = 100.0 / nyq
            b, a = scipy.signal.butter(2, normal_cutoff, btype='high', analog=False)
            audio = scipy.signal.lfilter(b, a, audio).astype(np.float32)
        except Exception as filter_err:
            logger.debug(f"STT [Filter]: Highpass filter skipped: {filter_err}")

        # DSP Step 2: Automatic Gain Control (AGC) - Normalize signal RMS to 0.2 (skipping sub-threshold noise)
        rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
        if rms >= 0.003:
            target_rms = 0.2
            gain = target_rms / rms
            if gain > 1.0:
                gain = min(gain, 6.0)  # limit amplification to 6.0x
                audio = np.clip(audio * gain, -1.0, 1.0)
                logger.info(f"STT [AGC]: Amplified signal (gain={gain:.2f}x, rms={rms:.4f} -> target={target_rms:.2f})")
            elif gain < 1.0:
                audio = audio * gain   # attenuate loud signals
                logger.info(f"STT [AGC]: Attenuated signal (gain={gain:.2f}x, rms={rms:.4f} -> target={target_rms:.2f})")

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
                    best_of=self._best_of,
                    temperature=self._temperature,
                    language=lang,
                    condition_on_previous_text=self._condition_on_previous_text,
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

                # 2. Minimum word count filter: reject single-word hallucinations
                words = text.split()
                if len(words) < self._min_word_count:
                    logger.debug(f"STT: min word count filter triggered ({len(words)} < {self._min_word_count}) — rejecting '{text[:60]}'")
                    return None

                detected_lang = getattr(info, "language", "") or ""
                lang_prob = float(getattr(info, "language_probability", 0.0) or 0.0)
                if lang is not None:
                    detected_lang = lang
                    lang_prob = 1.0
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
