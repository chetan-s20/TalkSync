from __future__ import annotations

import base64
import io
import wave
from typing import AsyncIterator

import numpy as np

from app.interfaces import SynthesisResult, BaseTTS
from utils.logger import get_logger
from utils.proxy import create_async_client

logger = get_logger("tts_sarvam")

SARVAM_URL = "https://api.sarvam.ai/text-to-speech"

# Language code → Sarvam bulbul:v3 speaker mapping
# Valid bulbul:v3 speakers: aditya, ritu, ashutosh, priya, neha, rahul, pooja, rohan,
#   simran, kavya, amit, dev, ishita, shreya, ratan, varun, manan, sumit, roopa,
#   kabir, aayan, shubh, advait, anand, tanya, tarun
_LANG_SPEAKER: dict[str, str] = {
    "hi": "ritu",
    "hi-in": "ritu",
    "mr": "ritu",
    "ta": "ritu",
    "te": "ritu",
    "kn": "ritu",
    "ml": "ritu",
    "gu": "ritu",
    "bn": "ritu",
    "pa": "ritu",
    "or": "ritu",
}


def _wav_bytes_to_float32(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    """Parse WAV bytes and return (float32 array, sample_rate)."""
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        sr = wf.getframerate()
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())

    if sampwidth == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        audio = np.frombuffer(raw, dtype=np.uint8).astype(np.float32) / 128.0 - 1.0

    # Mix down to mono if stereo
    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)

    return audio, sr


class SarvamTTS(BaseTTS):
    def __init__(self, settings):
        self.settings = settings
        self._api_key = getattr(settings, "sarvam_api_key", "")
        self._speaker = getattr(settings, "sarvam_voice", "meera")
        self._lang = getattr(settings, "sarvam_lang", "hi-IN")
        self._timeout = getattr(settings, "sarvam_timeout_s", 30.0)

    async def start(self) -> None:
        if self._api_key:
            logger.info(f"Sarvam TTS ready: speaker={self._speaker}, lang={self._lang}")
        else:
            logger.warning("Sarvam API key not configured")

    async def stop(self) -> None:
        pass

    # Valid bulbul:v3 speakers (from https://docs.sarvam.ai/api/getting-started/models/bulbul)
    _VALID_SPEAKERS = {
        "aditya", "ritu", "ashutosh", "priya", "neha", "rahul", "pooja", "rohan",
        "simran", "kavya", "amit", "dev", "ishita", "shreya", "ratan", "varun",
        "manan", "sumit", "roopa", "kabir", "aayan", "shubh", "advait", "anand",
        "tanya", "tarun",
    }

    def _resolve_speaker(self, lang: str) -> str:
        key = lang.lower().split("-")[0]
        speaker = _LANG_SPEAKER.get(key, self._speaker)
        if speaker not in self._VALID_SPEAKERS:
            speaker = "ritu"
        return speaker


    def _resolve_lang_code(self, lang: str) -> str:
        """Convert short codes like 'hi' → 'hi-IN'."""
        lang_lower = lang.lower()
        mapping = {
            "hi": "hi-IN", "mr": "mr-IN", "ta": "ta-IN",
            "te": "te-IN", "kn": "kn-IN", "ml": "ml-IN",
            "gu": "gu-IN", "bn": "bn-IN", "pa": "pa-IN",
            "or": "or-IN", "en": "en-IN",
        }
        if "-" in lang_lower:
            return lang
        return mapping.get(lang_lower, f"{lang_lower}-IN")

    async def synthesize(self, text: str, lang: str = "hi") -> SynthesisResult:
        if not self._api_key or not self._api_key.strip():
            logger.debug("Sarvam API key not configured, skipping cloud TTS")
            return self._silence()

        target_lang_code = self._resolve_lang_code(lang)
        # Use configured speaker if valid, else resolve from language code
        speaker = (
            self._speaker
            if self._speaker in self._VALID_SPEAKERS
            else self._resolve_speaker(lang)
        )

        payload = {
            "inputs": [text],
            "target_language_code": target_lang_code,
            "speaker": speaker,
            "pace": 1.0,
            "speech_sample_rate": 22050,
            "enable_preprocessing": True,
            "model": "bulbul:v3",
        }
        headers = {
            "api-subscription-key": self._api_key,
            "Content-Type": "application/json",
        }

        import asyncio as _asyncio
        import httpx as _httpx

        last_err = None
        # Strategy: try direct (no proxy) first — proxy often drops Sarvam connections
        # Then fall back to proxy on failure
        connection_configs = [
            {"proxy": None, "label": "direct"},
            {"proxy": "http://192.168.0.1:8090", "label": "proxy"},
        ]

        for attempt, cfg in enumerate(connection_configs * 2):  # up to 4 total attempts
            try:
                timeout = _httpx.Timeout(connect=10.0, read=self._timeout, write=10.0, pool=5.0)
                proxy = cfg["proxy"]
                try:
                    client = _httpx.AsyncClient(proxy=proxy, timeout=timeout)
                except TypeError:
                    # Older httpx uses proxies dict
                    proxies = {"http://": proxy, "https://": proxy} if proxy else None
                    client = _httpx.AsyncClient(proxies=proxies, timeout=timeout)

                async with client:
                    resp = await client.post(SARVAM_URL, json=payload, headers=headers)
                    if resp.status_code != 200:
                        logger.warning(
                            f"Sarvam API error {resp.status_code} [{cfg['label']}]: {resp.text[:200]}"
                        )
                        return self._silence()

                    data = resp.json()
                    audios = data.get("audios", [])
                    if not audios:
                        logger.warning("Sarvam returned empty audios list")
                        return self._silence()

                    wav_bytes = base64.b64decode(audios[0])
                    if not wav_bytes:
                        return self._silence()

                    try:
                        audio, sr = _wav_bytes_to_float32(wav_bytes)
                    except Exception as e:
                        logger.warning(f"WAV parse failed, trying raw float32: {e}")
                        audio = np.frombuffer(wav_bytes, dtype=np.float32)
                        sr = 8000

                    if len(audio) == 0:
                        return self._silence()

                    logger.info(
                        f"Sarvam TTS ok [{cfg['label']}]: lang={target_lang_code}, speaker={speaker}, "
                        f"sr={sr}, samples={len(audio)}, dur={len(audio)/sr*1000:.0f}ms"
                    )
                    return SynthesisResult(
                        audio_data=audio.tobytes(),
                        sample_rate=sr,
                        duration_ms=(len(audio) / sr) * 1000,
                    )
            except Exception as e:
                last_err = e
                logger.warning(f"Sarvam TTS attempt {attempt+1} [{cfg['label']}] failed: {e}")
                if attempt < 3:
                    await _asyncio.sleep(1.0)

        logger.warning(f"Sarvam TTS all attempts failed: {last_err}")
        return self._silence()


    def _silence(self) -> SynthesisResult:
        return SynthesisResult(
            audio_data=np.zeros(8000, dtype=np.float32).tobytes(),
            sample_rate=8000,
            duration_ms=1000.0,
        )

    async def synthesize_stream(
        self, text_stream, lang: str = "hi"
    ) -> AsyncIterator[SynthesisResult]:
        async for text in text_stream:
            if text.strip():
                yield await self.synthesize(text.strip(), lang)

    async def set_voice(self, voice_id: str) -> None:
        self._speaker = voice_id

    async def set_speed(self, speed: float) -> None:
        pass
