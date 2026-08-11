from __future__ import annotations

from typing import Any
from app.interfaces import BaseSTT
from services.stt.faster_whisper import FasterWhisperSTT
from services.stt.openai_stt import OpenAISTT
from services.stt.groq_stt import GroqSTT
from utils.logger import get_logger

logger = get_logger("stt_factory")


class STTFactory:
    """Factory for creating and initializing STT engine instances with fallback capability."""

    @staticmethod
    async def create(settings: Any) -> BaseSTT:
        """Attempt creating GroqSTT / OpenAISTT and fall back cleanly to FasterWhisperSTT."""
        stt_settings = getattr(settings, "stt", settings)
        
        # Check Groq configuration
        groq_key = getattr(settings, "groq_api_key", None) or getattr(stt_settings, "groq_api_key", "")
        if not groq_key and hasattr(settings, "groq"):
            groq_key = getattr(settings.groq, "api_key", "")

        openai_cfg = getattr(settings, "openai", None)
        openai_key = getattr(openai_cfg, "api_key", "") or ""
        engine_pref = getattr(settings, "stt_engine", "groq").lower()

        engines = []
        if groq_key and engine_pref in ("groq", "auto"):
            groq_model = getattr(settings, "groq_stt_model", "whisper-large-v3-turbo")
            engines.append(("Groq LPU", lambda s: GroqSTT(stt_settings, api_key=groq_key, model=groq_model)))

        if openai_key and engine_pref in ("openai", "auto"):
            engines.append(("OpenAI", OpenAISTT))

        # Always add FasterWhisperSTT as reliable fallback
        engines.append(("FasterWhisper", FasterWhisperSTT))

        for name, factory_fn in engines:
            try:
                stt = factory_fn(settings)
                if hasattr(stt, "start") and callable(stt.start):
                    await stt.start()
                elif hasattr(stt, "initialize") and callable(stt.initialize):
                    await stt.initialize()
                logger.info(f"STT: {name} active as primary engine")
                return stt
            except Exception as e:
                logger.warning(f"STT engine {name} unavailable ({e}) — attempting fallback")

        # Ultimate fallback to FasterWhisperSTT
        try:
            stt = FasterWhisperSTT(settings)
            await stt.start()
            logger.info("STT: FasterWhisperSTT fallback active")
            return stt
        except Exception as e:
            logger.error(f"FasterWhisperSTT fallback failed: {e}")
            raise RuntimeError("No STT engine available") from e
