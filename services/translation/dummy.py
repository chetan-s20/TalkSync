from __future__ import annotations

from typing import Optional

from app.interfaces import BaseTranslator, TranslationResult
from utils.logger import get_logger

logger = get_logger("translation_dummy")


class DummyTranslator(BaseTranslator):
    """Fallback translator that returns original text when primary engines are unavailable."""

    def __init__(self, settings=None):
        self.settings = settings
        self._started = False

    async def start(self) -> None:
        self._started = True
        logger.info("Dummy/Mock Translator started")

    async def stop(self) -> None:
        self._started = False

    async def translate(
        self, text: str, source_lang: str, target_lang: str, context: Optional[str] = None
    ) -> TranslationResult:
        return TranslationResult(
            original_text=text,
            translated_text=text,
            source_lang=source_lang,
            target_lang=target_lang,
            is_final=True,
        )


MockTranslator = DummyTranslator
