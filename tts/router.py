"""Multilingual TTS Router."""
import asyncio
import numpy as np
from typing import AsyncIterator, Optional
from core.interfaces import SynthesisResult
from tts.base import BaseTTS
from utils.logger import get_logger

logger = get_logger("tts_router")

SARVAM_LANGS = {"hi", "mr", "ta", "te", "kn", "ml", "gu", "bn", "pa", "or"}

def _lang_family(code: str) -> str:
    c = code.lower().split("-")[0][:2]
    return c


class MultilingualTTSRouter(BaseTTS):

    def __init__(self, settings, source_lang="EN", target_lang="HI"):
        self.settings = settings
        self._source_lang = source_lang
        self._target_lang = target_lang
        self._piper = None
        self._sarvam = None
        self._sarvam_available = True
        self._running = False

    async def _get_piper(self):
        if self._piper is None:
            try:
                from tts.piper import PiperTTS
                self._piper = PiperTTS(self.settings)
                await self._piper.start()
            except Exception as e:
                logger.warning(f"Piper TTS unavailable: {e}")
                self._piper = None
        return self._piper

    async def _get_sarvam(self):
        if self._sarvam is None:
            try:
                from tts.sarvam import SarvamTTS
                self._sarvam = SarvamTTS(self.settings)
                await self._sarvam.start()
            except Exception as e:
                logger.warning(f"Sarvam TTS unavailable: {e}")
                self._sarvam_available = False
                self._sarvam = None
        return self._sarvam

    def _select_engine(self, target_lang: str) -> str:
        fam = _lang_family(target_lang)
        if fam in SARVAM_LANGS:
            return "sarvam"
        return "piper"

    async def start(self) -> None:
        self._running = True
        langs = {self._source_lang, self._target_lang}
        getters = []
        for lang in langs:
            name = self._select_engine(lang or "")
            getter = {"sarvam": self._get_sarvam, "piper": self._get_piper}.get(name)
            if getter is not None:
                getters.append(getter)
        if getters:
            asyncio.create_task(self._preload_engines(getters))
        logger.info("Multilingual TTS Router started (preload scheduled)")

    async def _preload_engines(self, getters):
        for getter in getters:
            try:
                await getter()
            except Exception as e:
                logger.warning(f"Preload TTS engine failed: {e}")

    async def stop(self) -> None:
        self._running = False
        for eng in (self._piper, self._sarvam):
            try:
                if eng is not None:
                    await eng.stop()
            except Exception:
                pass
        self._piper = self._sarvam = None
        logger.info("Multilingual TTS Router stopped")

    @property
    def available_engines(self):
        engines = []
        if self._piper is not None:
            engines.append("piper")
        if self._sarvam is not None:
            engines.append("sarvam")
        return engines

    async def synthesize(self, text: str, target_lang: str | None = None) -> SynthesisResult:
        if not self._running:
            raise RuntimeError("TTS router not started")
        engine_name = self._select_engine(target_lang or "")
        last_err = None
        order = [engine_name]
        if engine_name == "sarvam":
            order += ["piper"]
        else:
            order += ["sarvam"]
        for name in order:
            try:
                if name == "sarvam":
                    eng = await self._get_sarvam()
                else:
                    eng = await self._get_piper()
                if eng is None:
                    continue
                return await eng.synthesize(text)
            except Exception as e:
                last_err = e
                logger.warning(f"TTS engine '{name}' failed: {e}")
                if name == "sarvam" and ("401" in str(e) or "403" in str(e) or "connect" in str(e).lower()):
                    self._sarvam_available = False
                    self._sarvam = None
        logger.error(f"All TTS engines failed: {last_err}")
        return SynthesisResult(
            audio_data=np.zeros(16000, dtype=np.float32).tobytes(),
            sample_rate=16000, duration_ms=1000.0, is_streaming=False,
        )

    async def synthesize_stream(self, text_stream, target_lang: str | None = None):
        async for text in text_stream:
            if not self._running:
                break
            if text.strip():
                yield await self.synthesize(text.strip(), target_lang)

    async def set_voice(self, voice_id: str) -> None:
        if self._piper is not None:
            await self._piper.set_voice(voice_id)

    async def set_speed(self, speed: float) -> None:
        if self._piper is not None:
            await self._piper.set_speed(speed)

    async def set_language(self, language_code: str) -> None:
        if self._sarvam is not None:
            await self._sarvam.set_language(language_code)
