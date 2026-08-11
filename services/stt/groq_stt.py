"""Groq LPU Cloud STT provider for sub-100ms Whisper transcription."""
from __future__ import annotations

import io
import time
import wave
import numpy as np
import httpx
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from app.interfaces import BaseSTT
from utils.logger import get_logger

logger = get_logger("groq_stt")


@dataclass
class STTResult:
    text: str
    language: str = "en"
    confidence: float = 1.0
    is_final: bool = True
    duration_ms: float = 0.0


class GroqSTT(BaseSTT):
    """Ultra-low latency STT engine utilizing Groq's LPU cloud endpoint."""

    GROQ_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

    def __init__(
        self,
        settings: Optional[Any] = None,
        api_key: Optional[str | list[str]] = None,
        loopback_api_key: Optional[str | list[str]] = None,
        model: str = "whisper-large-v3-turbo",
    ) -> None:
        self.root_settings = settings
        self.settings = getattr(settings, "stt", settings) if settings else None
        
        raw_key = api_key or (getattr(settings, "groq_api_key", "") if settings else "") or ""
        if hasattr(settings, "groq") and getattr(settings.groq, "api_key", None):
            raw_key = settings.groq.api_key
        
        loopback_key = loopback_api_key or (getattr(settings, "groq_loopback_api_key", "") if settings else "") or ""
        if hasattr(settings, "groq") and getattr(settings.groq, "loopback_api_key", None):
            loopback_key = settings.groq.loopback_api_key
            
        mic_keys_raw = [k.strip() for k in (raw_key if isinstance(raw_key, list) else str(raw_key).split(",")) if k.strip()]
        loopback_keys_raw = [k.strip() for k in (loopback_key if isinstance(loopback_key, list) else str(loopback_key).split(",")) if k.strip()]

        # Dedicated key pools: mic starts with Key A, loopback starts with Key B
        self.mic_keys = mic_keys_raw + [k for k in loopback_keys_raw if k not in mic_keys_raw]
        self.loopback_keys = loopback_keys_raw + [k for k in mic_keys_raw if k not in loopback_keys_raw]
        
        if not self.mic_keys:
            self.mic_keys = [""]
        if not self.loopback_keys:
            self.loopback_keys = [""]

        self.mic_index = 0
        self.loopback_index = 0
        self.model = model
        self.sample_rate = 16000
        self._mic_client: Optional[httpx.AsyncClient] = None
        self._loopback_client: Optional[httpx.AsyncClient] = None
        self.is_initialized = False
        self._fallback_stt = None
        logger.info(
            f"GroqSTT initialized: mic_keys={len(self.mic_keys)}, loopback_keys={len(self.loopback_keys)}, model='{self.model}'"
        )

    async def initialize(self) -> None:
        if self._mic_client is None or self._mic_client.is_closed:
            key = self.mic_keys[self.mic_index]
            self._mic_client = httpx.AsyncClient(
                timeout=httpx.Timeout(5.0, connect=2.0),
                headers={"Authorization": f"Bearer {key}"},
            )
        if self._loopback_client is None or self._loopback_client.is_closed:
            key = self.loopback_keys[self.loopback_index]
            self._loopback_client = httpx.AsyncClient(
                timeout=httpx.Timeout(5.0, connect=2.0),
                headers={"Authorization": f"Bearer {key}"},
            )
        self.is_initialized = True

    async def _rotate_key(self, source: str = "mic") -> str:
        """Rotate to next available API key in key pool for given audio source."""
        if source == "loopback":
            keys = self.loopback_keys
            self.loopback_index = (self.loopback_index + 1) % len(keys)
            next_key = keys[self.loopback_index]
            if self._loopback_client and not self._loopback_client.is_closed:
                await self._loopback_client.aclose()
            self._loopback_client = httpx.AsyncClient(
                timeout=httpx.Timeout(5.0, connect=2.0),
                headers={"Authorization": f"Bearer {next_key}"},
            )
            logger.warning(f"GroqSTT [loopback]: HTTP 429 rate limit hit — rotated to key #{self.loopback_index + 1}")
            return next_key
        else:
            keys = self.mic_keys
            self.mic_index = (self.mic_index + 1) % len(keys)
            next_key = keys[self.mic_index]
            if self._mic_client and not self._mic_client.is_closed:
                await self._mic_client.aclose()
            self._mic_client = httpx.AsyncClient(
                timeout=httpx.Timeout(5.0, connect=2.0),
                headers={"Authorization": f"Bearer {next_key}"},
            )
            logger.warning(f"GroqSTT [mic]: HTTP 429 rate limit hit — rotated to key #{self.mic_index + 1}")
            return next_key

    async def start(self, language: Optional[str] = None) -> None:
        await self.initialize()

    async def stop(self) -> None:
        await self.close()

    async def transcribe(
        self,
        audio: bytes | np.ndarray,
        is_final: bool = True,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        **kwargs,
    ) -> STTResult:
        source = kwargs.get("source", "mic")
        client = self._loopback_client if (source == "loopback" and self._loopback_client) else self._mic_client
        keys_pool = self.loopback_keys if source == "loopback" else self.mic_keys

        if not client or client.is_closed:
            await self.initialize()
            client = self._loopback_client if (source == "loopback" and self._loopback_client) else self._mic_client

        # Convert numpy audio float32 [-1, 1] array to WAV bytes
        if isinstance(audio, np.ndarray):
            audio_data = audio
        else:
            audio_data = np.frombuffer(audio, dtype=np.float32)

        if len(audio_data) == 0:
            return STTResult(text="", confidence=0.0, is_final=is_final)

        # Apply RMS gate
        rms = float(np.sqrt(np.mean(audio_data.astype(np.float64) ** 2)))
        rms_gate = getattr(self.settings, "rms_gate_threshold", 0.0003) if self.settings else 0.0003
        if rms < rms_gate:
            return STTResult(text="", confidence=0.0, is_final=is_final)

        wav_bytes = self._audio_to_wav_bytes(audio_data, self.sample_rate)
        
        form_data = {
            "model": self.model,
            "response_format": "verbose_json",
            "temperature": "0.0",
        }
        if language:
            lang_clean = language.lower().split("-")[0]
            if lang_clean not in ("auto", "automatic"):
                form_data["language"] = lang_clean
        if initial_prompt:
            form_data["prompt"] = initial_prompt

        files = {
            "file": ("audio.wav", wav_bytes, "audio/wav")
        }

        max_attempts = max(1, len(keys_pool))
        for attempt in range(max_attempts):
            t_start = time.perf_counter()
            curr_client = self._loopback_client if (source == "loopback" and self._loopback_client) else self._mic_client
            try:
                resp = await curr_client.post(self.GROQ_API_URL, data=form_data, files=files)
                duration_ms = (time.perf_counter() - t_start) * 1000.0

                if resp.status_code == 429:
                    curr_idx = self.loopback_index if source == "loopback" else self.mic_index
                    logger.warning(f"Groq API HTTP 429 (Rate Limit) [{source}] on key #{curr_idx + 1}")
                    if len(keys_pool) > 1 and attempt < max_attempts - 1:
                        await self._rotate_key(source=source)
                        continue
                    # Fallback to OpenAI STT if available
                    return await self._fallback_transcribe(audio, is_final, language, initial_prompt)

                if resp.status_code != 200:
                    logger.error(f"Groq API error HTTP {resp.status_code}: {resp.text}")
                    return STTResult(text="", confidence=0.0, is_final=is_final)

                data = resp.json()
                text = (data.get("text") or "").strip()
                detected_lang = data.get("language") or language or "en"
                
                segments = data.get("segments", [])
                conf = 0.95
                if segments:
                    avg_logprob = sum(seg.get("avg_logprob", -0.2) for seg in segments) / len(segments)
                    conf = max(0.1, min(1.0, float(np.exp(avg_logprob))))

                logger.info(f"Groq STT [{source}] transcribed in {duration_ms:.1f}ms: '{text[:60]}' (lang={detected_lang})")
                return STTResult(
                    text=text,
                    language=detected_lang,
                    confidence=conf,
                    is_final=is_final,
                    duration_ms=duration_ms,
                )
            except Exception as e:
                logger.error(f"Groq STT [{source}] transcription failed: {e}")
                return await self._fallback_transcribe(audio, is_final, language, initial_prompt)

        return STTResult(text="", confidence=0.0, is_final=is_final)

    async def _fallback_transcribe(
        self,
        audio: Any,
        is_final: bool,
        language: Optional[str],
        initial_prompt: Optional[str],
    ) -> STTResult:
        """Fallback transparently to OpenAISTT when all Groq rate limits are exhausted."""
        try:
            if self._fallback_stt is None:
                from services.stt.openai_stt import OpenAISTT
                self._fallback_stt = OpenAISTT(self.root_settings or self.settings)
                await self._fallback_stt.start()
            res = await self._fallback_stt.transcribe(audio, is_final=is_final, language=language, initial_prompt=initial_prompt)
            if res and res.text:
                logger.info(f"Groq Fallback (OpenAI STT): '{res.text[:60]}'")
                return STTResult(text=res.text, language=res.language, confidence=res.confidence, is_final=is_final)
        except Exception as fb_err:
            logger.warning(f"Groq STT fallback to OpenAI failed: {fb_err}")
        return STTResult(text="", confidence=0.0, is_final=is_final)

    async def stream(self, audio: Any) -> AsyncIterator[Any]:
        res = await self.transcribe(audio, is_final=False)
        yield res

    def _audio_to_wav_bytes(self, audio_data: np.ndarray, sample_rate: int = 16000) -> bytes:
        int16_data = (np.clip(audio_data, -1.0, 1.0) * 32767.0).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(int16_data.tobytes())
        return buf.getvalue()

    async def close(self) -> None:
        if self._mic_client and not self._mic_client.is_closed:
            await self._mic_client.aclose()
            self._mic_client = None
        if self._loopback_client and not self._loopback_client.is_closed:
            await self._loopback_client.aclose()
            self._loopback_client = None
        self.is_initialized = False
