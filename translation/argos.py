"""Argos Translate engine."""
import asyncio
from typing import Optional
from core.interfaces import TranslationResult
from translation.base import BaseTranslator
from utils.logger import get_logger

logger = get_logger("translation_argos")


class ArgosTranslator(BaseTranslator):

    def __init__(self, settings):
        self.settings = settings
        self._model = None
        self._translations = {}

    async def start(self) -> None:
        try:
            import argostranslate.package
            import argostranslate.translate
            try:
                argostranslate.package.update_package_index()
            except Exception as e:
                logger.warning(f"Failed to update Argos package index (offline mode): {e}")
            available = argostranslate.package.get_available_packages()
            for pkg in available:
                if pkg.from_code == "en" and pkg.to_code == "hi":
                    argostranslate.package.install_from_path(pkg.download())
                    break
            self._model = argostranslate.translate
            self._translations["en_hi"] = self._model.get_translation_from_codes("en", "hi")
            self._translations["hi_en"] = self._model.get_translation_from_codes("hi", "en")
            logger.info("Argos Translator ready: EN <-> HI (GPU=auto)")
        except Exception as e:
            logger.warning(f"Argos init failed: {e}")
            raise

    async def stop(self) -> None:
        self._model = None

    async def translate(self, text: str, source_lang: str, target_lang: str, context: Optional[str] = None) -> TranslationResult:
        key = f"{source_lang.lower()}_{target_lang.lower()}"
        t = self._translations.get(key)
        if t is None:
            return TranslationResult(
                original_text=text, translated_text=text,
                source_lang=source_lang, target_lang=target_lang,
                is_final=True,
            )
        result = t.translate(text)
        return TranslationResult(
            original_text=text, translated_text=result,
            source_lang=source_lang, target_lang=target_lang,
            is_final=True,
        )

    async def translate_stream(self, text_stream, source_lang: str, target_lang: str):
        async for text in text_stream:
            yield await self.translate(text, source_lang, target_lang)
