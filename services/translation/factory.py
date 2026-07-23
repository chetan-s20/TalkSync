from __future__ import annotations

from app.interfaces import BaseTranslator
from services.translation.argos import ArgosTranslator
from services.translation.deepl import DeepLTranslator
from services.translation.dummy import DummyTranslator
from utils.logger import get_logger

logger = get_logger("translation_factory")


class TranslationFactory:
    @staticmethod
    async def create(settings) -> BaseTranslator:
        trans_settings = getattr(settings, "translation", settings)
        primary = None
        try:
            primary = ArgosTranslator(trans_settings)
            await primary.start()
            logger.info("Translation: Argos primary active")
            return primary
        except Exception as e:
            logger.warning(f"Argos unavailable: {e}")

        try:
            primary = DeepLTranslator(trans_settings)
            await primary.start()
            logger.info("Translation: DeepL fallback active")
            return primary
        except Exception as e:
            logger.warning(f"DeepL unavailable: {e}")

        try:
            dummy = DummyTranslator(trans_settings)
            await dummy.start()
            logger.info("Translation: Fallback to Dummy/Mock translator active")
            return dummy
        except Exception as e:
            logger.error(f"Dummy translator failed: {e}")
            raise RuntimeError("No translation engine available") from e

