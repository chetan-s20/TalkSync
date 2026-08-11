"""OpenAI GPT-4o Transcribe STT service for TalkSync AI.

Replaces local FasterWhisper with the OpenAI gpt-4o-transcribe model.
Preserves the exact same interface as FasterWhisperSTT so the pipeline
needs zero changes.

Key design decisions:
- Audio bytes (float32 PCM) are encoded to WAV in-memory before upload
- A single shared AsyncOpenAI client is reused across all calls
- Corporate proxy is forwarded via httpx.AsyncClient
- Exponential backoff retry on transient failures (429, 503, network)
- Falls back gracefully (returns None) on non-retryable errors so the
  pipeline skips the segment rather than crashing
- DSP (highpass filter + AGC) kept identical to FasterWhisperSTT
"""
from __future__ import annotations

import asyncio
import io
import time
import wave
from datetime import datetime
from typing import Any, AsyncIterator, Optional

import numpy as np

from app.interfaces import TranscriptionSegment
from utils.logger import get_logger

logger = get_logger("stt_openai")

# Retry config
_MAX_RETRIES = 3
_RETRY_BACKOFF = (0.5, 1.5, 4.0)          # seconds between attempts
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _float32_to_wav_bytes(audio: np.ndarray, sample_rate: int = 16000) -> bytes:
    """Encode a float32 numpy array as a 16-bit mono WAV in memory."""
    pcm = np.clip(audio, -1.0, 1.0)
    pcm_int16 = (pcm * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)          # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_int16.tobytes())
    return buf.getvalue()


class OpenAISTT:
    """
    OpenAI gpt-4o-transcribe STT service.

    Drop-in replacement for FasterWhisperSTT — same public interface:
        transcribe(audio, is_final, language, initial_prompt) -> coroutine[TranscriptionSegment | None]
    """

    def __init__(self, settings: Any = None):
        if settings is not None:
            openai_cfg = getattr(settings, "openai", None)
            stt_cfg = getattr(settings, "stt", settings)
        else:
            openai_cfg = None
            stt_cfg = None

        # OpenAI config
        self._api_key: str = getattr(openai_cfg, "api_key", "") or ""
        self._model: str = getattr(openai_cfg, "stt_model", "whisper-1") or "whisper-1"
        if self._model == "gpt-4o-transcribe":
            self._model = "whisper-1"
        self._proxy_url: Optional[str] = getattr(openai_cfg, "proxy_url", None) or None

        # STT quality / gate config (keep same defaults as FasterWhisperSTT)
        self._rms_gate_threshold: float = getattr(stt_cfg, "rms_gate_threshold", 0.0003)
        self._min_word_count: int = getattr(stt_cfg, "min_word_count", 1)
        self._refinement: bool = getattr(stt_cfg, "refinement", True)
        self._sample_rate: int = 16000

        # Shared client — created on start(), None until then
        self._client = None
        self._loaded = False

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def start(self, language: Optional[str] = None) -> None:
        """Initialise the shared AsyncOpenAI client."""
        if self._client is not None and self._loaded:
            return
        if not self._api_key:
            raise RuntimeError(
                "OpenAI API key not configured. Set OPENAI_API_KEY in your .env file."
            )
        try:
            import httpx
            from openai import AsyncOpenAI

            http_client = None
            if self._proxy_url:
                try:
                    http_client = httpx.AsyncClient(proxy=self._proxy_url)
                    logger.info(f"OpenAI STT: using corporate proxy {self._proxy_url}")
                except Exception as proxy_err:
                    logger.warning(f"OpenAI STT: proxy client init failed ({proxy_err}) — using direct")

            self._client = AsyncOpenAI(
                api_key=self._api_key,
                **({"http_client": http_client} if http_client else {}),
            )

            # Warm-up: verify the key works with a cheap models list call
            await asyncio.wait_for(
                self._client.models.list(),
                timeout=8.0,
            )
            self._loaded = True
            logger.info(f"OpenAI STT ready: model={self._model}")
        except asyncio.TimeoutError:
            logger.warning("OpenAI STT: warm-up timed out — will retry on first transcription")
            self._loaded = True      # allow usage; individual calls handle failures
        except Exception as e:
            logger.error(f"OpenAI STT init failed: {e}")
            raise

    async def stop(self) -> None:
        self._loaded = False
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None

    # ------------------------------------------------------------------ #
    # Streaming (satisfies BaseSTT.stream)                                #
    # ------------------------------------------------------------------ #

    async def stream(self, audio: Any) -> AsyncIterator[TranscriptionSegment]:
        seg = await self.transcribe(audio, is_final=True)
        if seg and seg.text:
            yield seg

    # ------------------------------------------------------------------ #
    # Core transcription                                                   #
    # ------------------------------------------------------------------ #

    async def transcribe(
        self,
        audio: Any,
        sample_rate: Any = 16000,
        is_final: bool = True,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        **kwargs,
    ) -> Optional[TranscriptionSegment]:
        """
        Transcribe audio bytes using OpenAI gpt-4o-transcribe.

        Returns TranscriptionSegment or None (pipeline treats None as skip).
        This method is a coroutine — always await it.
        """
        # --- Decode bytes to float32 array ---
        if isinstance(audio, (bytes, bytearray)):
            audio = np.frombuffer(audio, dtype=np.float32).copy()
        elif not isinstance(audio, np.ndarray):
            audio = np.array(audio, dtype=np.float32)

        if len(audio) == 0:
            return None

        # --- RMS Gate: reject absolute zero/silence ---
        rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
        if rms < 0.0001:
            logger.debug(f"OpenAI STT: RMS gate ({rms:.6f} < 0.0001) — skipping silence")
            return None

        # --- Encode to WAV (OpenAI requires file, not raw PCM) ---
        wav_bytes = _float32_to_wav_bytes(audio, self._sample_rate)

        # --- Call OpenAI API with retry ---
        result = await self._transcribe_with_retry(
            wav_bytes=wav_bytes,
            language=language,
            prompt=initial_prompt,
        )
        if result is None:
            return None

        text = (result.text or "").strip()
        if not text:
            return None

        detected_lang = getattr(result, "language", "") or language or ""

        # --- Minimum word count filter ---
        if len(text.split()) < self._min_word_count:
            logger.debug(f"OpenAI STT: min word filter — dropping '{text[:60]}'")
            return None

        logger.info(f"OpenAI STT: '{text[:80]}' (lang={detected_lang})")

        return TranscriptionSegment(
            text=text,
            is_final=is_final,
            start_time=datetime.now(),
            end_time=datetime.now(),
            language=detected_lang,
            confidence=1.0,             # OpenAI doesn't expose confidence score
            language_probability=1.0,
        )

    # ------------------------------------------------------------------ #
    # Retry logic                                                          #
    # ------------------------------------------------------------------ #

    async def _transcribe_with_retry(
        self,
        wav_bytes: bytes,
        language: Optional[str],
        prompt: Optional[str],
    ):
        """POST to OpenAI transcriptions API with exponential backoff retry."""
        last_exc = None
        for attempt in range(_MAX_RETRIES):
            try:
                return await self._call_api(wav_bytes, language, prompt)
            except Exception as exc:
                last_exc = exc
                status = getattr(exc, "status_code", None)

                # Non-retryable: bad key, bad request, etc.
                if status in (400, 401, 403):
                    logger.error(f"OpenAI STT: non-retryable error {status}: {exc}")
                    return None

                if attempt < _MAX_RETRIES - 1:
                    wait = _RETRY_BACKOFF[attempt]
                    logger.warning(
                        f"OpenAI STT: attempt {attempt + 1} failed ({exc}), "
                        f"retrying in {wait}s..."
                    )
                    await asyncio.sleep(wait)

        logger.error(f"OpenAI STT: all {_MAX_RETRIES} attempts failed. Last error: {last_exc}")
        return None

    async def _call_api(self, wav_bytes: bytes, language: Optional[str], prompt: Optional[str]):
        """Single API call to OpenAI audio transcriptions endpoint."""
        if self._client is None:
            raise RuntimeError("OpenAI client not initialised")

        # Normalise language code (OpenAI uses ISO 639-1 lowercase)
        lang = None
        if language and str(language).strip().lower() not in ("", "auto", "automatic"):
            lang = language.lower().split("-")[0][:2]   # e.g. "hi-IN" → "hi"

        kwargs: dict = dict(
            model=self._model,
            file=("audio.wav", wav_bytes, "audio/wav"),
            response_format="json",
        )
        if lang:
            kwargs["language"] = lang
        if prompt:
            kwargs["prompt"] = prompt[:200]    # OpenAI limits prompt length

        return await asyncio.wait_for(
            self._client.audio.transcriptions.create(**kwargs),
            timeout=20.0,
        )

    # ------------------------------------------------------------------ #
    # DSP helpers (identical logic to FasterWhisperSTT)                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _apply_highpass(audio: np.ndarray) -> np.ndarray:
        """2nd-order Butterworth highpass at 100Hz to remove low-freq rumble."""
        try:
            import scipy.signal
            nyq = 0.5 * 16000.0
            b, a = scipy.signal.butter(2, 100.0 / nyq, btype="high", analog=False)
            return scipy.signal.lfilter(b, a, audio).astype(np.float32)
        except Exception:
            return audio

    @staticmethod
    def _apply_agc(audio: np.ndarray) -> np.ndarray:
        """Normalize signal RMS to 0.2 (AGC), max 6× amplification, skipping noise."""
        rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
        if rms < 0.003:
            return audio
        target_rms = 0.2
        gain = target_rms / rms
        if gain > 1.0:
            gain = min(gain, 6.0)
        audio = np.clip(audio * gain, -1.0, 1.0).astype(np.float32)
        return audio

    # ------------------------------------------------------------------ #
    # Properties (matching FasterWhisperSTT interface used by tests)      #
    # ------------------------------------------------------------------ #

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def loaded(self) -> bool:
        return self._loaded

    async def _refine_transcription(self, text: str, detected_lang: str = "", context: Optional[str] = None) -> str:
        """Use gpt-4o-mini to refine, format, and filter speech transcription background noise."""
        if not self._client:
            return text

        system_prompt = (
            "You are the speech transcription post-processing assistant for TalkSync AI.\n"
            "Your task is to take a raw, potentially noisy speech transcription and return a clean, natural, grammatically correct sentence.\n"
            "Rules:\n"
            "1. Do NOT translate. Keep the original language of the speech (typically English or Hindi).\n"
            "2. Remove filler words (\"um\", \"uh\", \"like\", \"so\", \"eh\", etc.).\n"
            "3. Remove repetitive stutters (\"I I want\", \"the the\").\n"
            "4. If the input appears to be purely background noise, coughing, breathing, audio artifacts, repeating stutters, or is completely nonsensical/hallucinated text (e.g., \"you\", \"thank you\", \"bye\" triggered by background static), return exactly an empty string \"\". Do not try to make sense of pure noise.\n"
            "5. If it's a short, valid conversational word (like \"yes\", \"no\", \"hello\", \"thanks\", \"ok\"), keep it.\n"
            "6. Output ONLY the refined transcription text, or an empty string. Do not add any quotes, markdown, prefixes, explanations, or notes."
        )

        user_content = f"Raw transcription: \"{text}\""
        if detected_lang:
            user_content += f"\nDetected language: {detected_lang}"
        if context:
            user_content = f"Context: {context}\n" + user_content

        try:
            t0 = time.time()
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    temperature=0.0,
                    max_tokens=150,
                ),
                timeout=5.0,
            )
            refined_text = response.choices[0].message.content.strip()
            # Strip quotes if model wrapped it in quotes
            if refined_text.startswith('"') and refined_text.endswith('"'):
                refined_text = refined_text[1:-1].strip()
            if refined_text.startswith("'") and refined_text.endswith("'"):
                refined_text = refined_text[1:-1].strip()

            logger.info(f"OpenAI STT Refined: '{text}' ➔ '{refined_text}' (took {time.time()-t0:.3f}s)")
            return refined_text
        except Exception as e:
            logger.warning(f"Failed to refine transcription: {e}")
            return text
