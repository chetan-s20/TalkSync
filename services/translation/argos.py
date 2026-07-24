from __future__ import annotations

from typing import Optional

import argostranslate.package
import argostranslate.translate

from app.interfaces import TranslationResult, BaseTranslator
from utils.logger import get_logger

logger = get_logger("translation_argos")


class ArgosTranslator(BaseTranslator):
    def __init__(self, settings):
        self.settings = settings
        self._model = None
        self._translations = {}

    async def start(self) -> None:
        try:
            # Disable Stanza sentence boundary detection for faster translation
            # This eliminates ~3s per language direction for loading Stanza models
            # Trade-off: Best for short conversational phrases (< 20 words)
            try:
                import argostranslate.settings
                argostranslate.settings.sentenceBoundaryDetection = False
                logger.info("Argos: Stanza sentence splitting disabled for faster translation")
            except Exception as e:
                logger.debug(f"Could not disable Stanza: {e}")

            try:
                argostranslate.package.update_package_index()
            except Exception as e:
                logger.warning(f"Failed to update Argos package index (offline mode): {e}")

            try:
                available = argostranslate.package.get_available_packages() or []
                for pkg in available:
                    if pkg.from_code == "en" and pkg.to_code == "hi":
                        try:
                            dl = pkg.download()
                            argostranslate.package.install_from_path(dl)
                        except Exception as dl_err:
                            logger.warning(f"Failed to download Argos package: {dl_err}")
                        break
            except Exception as pkg_err:
                logger.warning(f"Failed to check/install Argos packages: {pkg_err}")

            self._model = argostranslate.translate
            self._translations["en_hi"] = self._model.get_translation_from_codes("en", "hi")
            self._translations["hi_en"] = self._model.get_translation_from_codes("hi", "en")
            logger.info("Argos Translator ready: EN <-> HI")
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
