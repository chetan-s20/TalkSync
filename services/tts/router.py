from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

import numpy as np

from app.interfaces import SynthesisResult, BaseTTS
from services.tts.piper import PiperTTS
from services.tts.sarvam import SarvamTTS
from utils.logger import get_logger

logger = get_logger("tts_router")

SARVAM_LANGS = {"hi", "mr", "ta", "te", "kn", "ml", "gu", "bn", "pa", "or", "en"}


def _lang_family(code: str) -> str:
    return code.lower().split("-")[0][:2]


class MultilingualTTSRouter(BaseTTS):
    def __init__(self, settings):
        self.settings = settings
        self._piper = None
        self._sarvam = None
        self._running = False

    async def _get_piper(self):
        if self._piper is None:
            try:
                self._piper = PiperTTS(self.settings)
                await self._piper.start()
            except Exception as e:
                logger.warning(f"Piper unavailable: {e}")
                self._piper = None
        return self._piper

    async def _get_sarvam(self):
        if self._sarvam is None:
            try:
                self._sarvam = SarvamTTS(self.settings)
                await self._sarvam.start()
            except Exception as e:
                logger.warning(f"Sarvam unavailable: {e}")
                self._sarvam = None
        return self._sarvam

    def _select_engine(self, target_lang: str) -> str:
        if _lang_family(target_lang) in SARVAM_LANGS:
            return "sarvam"
        return "piper"

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False
        for eng in (self._piper, self._sarvam):
            if eng is not None:
                try:
                    await eng.stop()
                except Exception:
                    pass
        self._piper = self._sarvam = None

    async def synthesize(self, text: str, lang: str = "en") -> SynthesisResult:
        if not self._running:
            return self._silence()
        engine_name = self._select_engine(lang)
        order = [engine_name]
        order.append("piper" if engine_name == "sarvam" else "sarvam")

        for name in order:
            eng = await (self._get_sarvam() if name == "sarvam" else self._get_piper())
            if eng is None:
                continue
            try:
                res = await eng.synthesize(text, lang)
                data = res.audio_data or b""
                if len(data) > 0:
                    remainder = len(data) % 4
                    buf = data[:-remainder] if remainder else data
                    if len(buf) > 0:
                        arr = np.frombuffer(buf, dtype=np.float32)
                        if len(arr) > 0 and not np.all(arr == 0):
                            return res
                    else:
                        return res
            except Exception as e:
                logger.warning(f"TTS '{name}' failed: {e}")

        logger.info(f"Falling back to Windows SAPI5 TTS for text: {text[:30]}")
        self._sapi_speak(text)
        return self._silence()

    @staticmethod
    def _sapi_speak(text: str) -> None:
        try:
            import subprocess
            clean = text.replace('"', '').replace("'", '').replace('\n', ' ')
            cmd = f'Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Speak("{clean}")'
            subprocess.Popen(["powershell", "-NoProfile", "-Command", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.debug(f"SAPI5 speak failed: {e}")

    async def synthesize_stream(self, text_stream, lang: str = "en") -> AsyncIterator[SynthesisResult]:
        async for text in text_stream:
            if not self._running:
                break
            if text.strip():
                yield await self.synthesize(text.strip(), lang)

    async def set_voice(self, voice_id: str) -> None:
        if self._piper is not None:
            await self._piper.set_voice(voice_id)

    async def set_speed(self, speed: float) -> None:
        if self._piper is not None:
            await self._piper.set_speed(speed)

    @staticmethod
    def _silence() -> SynthesisResult:
        return SynthesisResult(
            audio_data=np.zeros(16000, dtype=np.float32).tobytes(),
            sample_rate=16000, duration_ms=1000.0,
        )
