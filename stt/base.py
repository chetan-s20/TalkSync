"""Base STT interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from core.interfaces import AudioChunk, TranscriptionSegment


class BaseSTT(ABC):
    @abstractmethod
    async def start(self, language: str = "auto") -> None:
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...

    @abstractmethod
    async def stream(self, audio: Any) -> AsyncIterator[TranscriptionSegment]:
        ...

    @abstractmethod
    async def transcribe(self, audio: Any, **kwargs) -> TranscriptionSegment:
        ...
