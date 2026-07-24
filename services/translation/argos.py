from __future__ import annotations

from typing import Optional

import argostranslate.package
import argostranslate.translate

from app.interfaces import TranslationResult, BaseTranslator
from utils.logger import get_logger

logger = get_logger("translation_argos")

DEFAULT_VOCABULARY = {
    "hi_en": {
        "safed": "white",
        "kapde": "clothes",
        "kapda": "cloth",
        "kala": "black",
        "laal": "red",
        "neela": "blue",
        "hara": "green",
        "peela": "yellow",
        "ghar": "home",
        "paise": "money",
        "pyaar": "love",
        "dost": "friend",
        "chai": "tea",
        "pani": "water",
        "roti": "bread",
    },
    "en_hi": {
        "white": "safed",
        "black": "kala",
        "red": "laal",
        "blue": "neela",
        "green": "hara",
        "yellow": "peela",
        "clothes": "kapde",
        "home": "ghar",
        "friend": "dost",
        "tea": "chai",
        "water": "pani",
        "bread": "roti",
    },
}


class ArgosTranslator(BaseTranslator):
    def __init__(self, settings):
        self.settings = settings
        self._model = None
        self._translations = {}

    async def start(self) -> None:
        try:
            try:
                import os
                import argostranslate.settings
                os.environ["ARGOS_CHUNK_TYPE"] = "NONE"
                try:
                    argostranslate.settings.chunk_type = argostranslate.settings.ChunkType.NONE
                except AttributeError:
                    pass
                argostranslate.settings.sentenceBoundaryDetection = False
                logger.info("Argos: Bypassed Stanza sentencizer via ChunkType.NONE and sentenceBoundaryDetection=False")
            except Exception as e:
                logger.debug(f"Could not disable Stanza SBD: {e}")

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

    @staticmethod
    def _apply_default_vocabulary(text: str, source_lang: str, target_lang: str) -> str:
        key = f"{source_lang.lower()}_{target_lang.lower()}"
        vocab = DEFAULT_VOCABULARY.get(key)
        if not vocab:
            return text
        result = text
        for word, replacement in sorted(vocab.items(), key=lambda x: -len(x[0])):
            if word:
                result = result.replace(word, replacement)
        return result

    async def translate(self, text: str, source_lang: str, target_lang: str, context: Optional[str] = None) -> TranslationResult:
        import asyncio
        key = f"{source_lang.lower()}_{target_lang.lower()}"
        t = self._translations.get(key)
        if t is None:
            return TranslationResult(
                original_text=text, translated_text=self._apply_default_vocabulary(text, source_lang, target_lang),
                source_lang=source_lang, target_lang=target_lang,
                is_final=True,
            )

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: t.translate(text))
        except Exception as e:
            logger.error(f"Argos translation failed: {e}")
            result = text

        result = self._apply_default_vocabulary(result, source_lang, target_lang)
        return TranslationResult(
            original_text=text, translated_text=result,
            source_lang=source_lang, target_lang=target_lang,
            is_final=True,
        )
