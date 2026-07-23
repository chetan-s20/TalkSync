"""Translation factory - creates translator with fallback chain."""
from utils.logger import get_logger

logger = get_logger("translation_factory")


class TranslationFactory:

    @staticmethod
    async def create(settings):
        primary = None
        try:
            from translation.argos import ArgosTranslator
            primary = ArgosTranslator(settings.translation)
            await primary.start()
            logger.info("Fallback translation enabled: argos -> deepl")
            return primary
        except Exception as e:
            logger.warning(f"Argos unavailable: {e}")
        try:
            from translation.deepl import DeepLTranslator
            primary = DeepLTranslator(settings.translation)
            await primary.start()
            logger.info("Fallback translation enabled: deepl")
            return primary
        except Exception as e:
            logger.warning(f"DeepL unavailable: {e}")
        raise RuntimeError("No translation engine available")
