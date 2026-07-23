"""Base TTS interface."""
from abc import ABC, abstractmethod
from typing import AsyncIterator
from core.interfaces import SynthesisResult


class BaseTTS(ABC):

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass

    @abstractmethod
    async def synthesize_stream(self, text_stream, target_lang: str | None = None) -> AsyncIterator[SynthesisResult]:
        pass

    @abstractmethod
    async def synthesize(self, text: str) -> SynthesisResult:
        pass

    @abstractmethod
    async def set_voice(self, voice_id: str) -> None:
        pass

    @abstractmethod
    async def set_speed(self, speed: float) -> None:
        pass
