"""DeepL translation provider."""
from typing import Optional
from core.interfaces import TranslationResult
from translation.base import BaseTranslator
from utils.logger import get_logger

logger = get_logger("translation_deepl")


class DeepLTranslator(BaseTranslator):

    def __init__(self, settings):
        self.settings = settings
        self._client = None

    async def start(self) -> None:
        try:
            import deepl
            api_key = getattr(self.settings, "deepl_api_key", "") or ""
            if api_key:
                self._client = deepl.Translator(api_key)
                usage = self._client.get_usage()
                logger.info(f"DeepL API initialized. Character usage: {usage.character.count}/{usage.character.limit}")
            else:
                logger.warning("DeepL API key not configured")
        except Exception as e:
            logger.warning(f"DeepL init failed: {e}")

    async def stop(self) -> None:
        self._client = None

    async def translate(self, text: str, source_lang: str, target_lang: str, context: Optional[str] = None) -> TranslationResult:
        if self._client is None:
            return TranslationResult(
                original_text=text, translated_text=text,
                source_lang=source_lang, target_lang=target_lang,
                is_final=True,
            )
        try:
            result = self._client.translate_text(
                text, source_lang=source_lang.upper(), target_lang=target_lang.upper()
            )
            return TranslationResult(
                original_text=text, translated_text=str(result),
                source_lang=source_lang, target_lang=target_lang,
                is_final=True,
            )
        except Exception as e:
            logger.error(f"DeepL translation error: {e}")
            return TranslationResult(
                original_text=text, translated_text=text,
                source_lang=source_lang, target_lang=target_lang,
                is_final=True,
            )

    async def translate_stream(self, text_stream, source_lang: str, target_lang: str):
        async for text in text_stream:
            yield await self.translate(text, source_lang, target_lang)
