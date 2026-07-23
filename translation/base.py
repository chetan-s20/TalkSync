"""Base translator interface."""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from core.interfaces import TranslationResult


class BaseTranslator(ABC):

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass

    @abstractmethod
    async def translate(self, text: str, source_lang: str, target_lang: str, context: Optional[str] = None) -> TranslationResult:
        pass

    @abstractmethod
    async def translate_stream(
        self, text_stream: AsyncIterator[str], source_lang: str, target_lang: str
    ) -> AsyncIterator[TranslationResult]:
        pass
