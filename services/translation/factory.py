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
        provider = getattr(trans_settings, "provider", "argos").lower()

        # Build candidate list based on user preference
        engines = []
        if provider == "deepl":
            engines.append(("DeepL", DeepLTranslator))
            engines.append(("Argos", ArgosTranslator))
        else:
            engines.append(("Argos", ArgosTranslator))
            engines.append(("DeepL", DeepLTranslator))

        primary = None
        for name, cls in engines:
            try:
                primary = cls(trans_settings)
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

