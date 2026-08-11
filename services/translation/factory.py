from __future__ import annotations

from app.interfaces import BaseTranslator
from services.translation.gpt_translator import GPTTranslator
from services.translation.deepl import DeepLTranslator
from services.translation.argos import ArgosTranslator
from services.translation.dummy import DummyTranslator
from utils.logger import get_logger

logger = get_logger("translation_factory")


class TranslationFactory:
    @staticmethod
    async def create(settings) -> BaseTranslator:
        trans_settings = getattr(settings, "translation", settings)
        provider = getattr(trans_settings, "provider", "gpt").lower()

        # Check OpenAI key availability for GPT translator
        openai_key = ""
        if hasattr(settings, "openai") and getattr(settings.openai, "api_key", ""):
            openai_key = settings.openai.api_key
        elif hasattr(trans_settings, "deepl_api_key"):
            openai_key = getattr(trans_settings, "deepl_api_key", "")

        engines = []
        if provider in ("gpt", "openai", "gpt-4o-mini", "auto") and openai_key:
            engines.append(("GPT-4o-mini", lambda s: GPTTranslator(settings, api_key=openai_key)))
        if provider == "deepl" or not engines:
            engines.append(("DeepL", lambda s: DeepLTranslator(trans_settings)))
            engines.append(("Argos", lambda s: ArgosTranslator(trans_settings)))
        engines.append(("Argos", lambda s: ArgosTranslator(trans_settings)))

        for name, factory_fn in engines:
            try:
                primary = factory_fn(settings)
                if hasattr(primary, "start") and callable(primary.start):
                    await primary.start()
                logger.info(f"Translation: {name} active as primary engine")
                return primary
            except Exception as e:
                logger.warning(f"Translation engine {name} unavailable: {e}")

        try:
            dummy = DummyTranslator(trans_settings)
            await dummy.start()
            logger.info("Translation: Fallback to Dummy/Mock translator active")
            return dummy
        except Exception as e:
            logger.error(f"Dummy translator failed: {e}")
            raise RuntimeError("No translation engine available") from e
