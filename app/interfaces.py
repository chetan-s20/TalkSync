from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Optional


@dataclass
class AudioChunk:
    data: bytes
    sample_rate: int
    channels: int
    timestamp: datetime
    duration_ms: float
    source: str = "mic"


@dataclass
class TranscriptionSegment:
    text: str
    is_final: bool
    start_time: datetime
    end_time: datetime
    language: str
    confidence: float
    language_probability: float = 0.0
    input_source: str = "VOICE"


@dataclass
class TranslationResult:
    original_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    is_final: bool
    input_source: str = "VOICE"


@dataclass
class SynthesisResult:
    audio_data: bytes
    sample_rate: int
    duration_ms: float
    is_streaming: bool = False


@dataclass
class VADResult:
    is_speech: bool
    speech_start: Optional[float] = None
    speech_end: Optional[float] = None
    confidence: float = 0.0
    chunk: Optional[Any] = None


@dataclass
class SegmentBlock:
    timestamp: str
    original: str
    translated: str
    source_lang: str
    target_lang: str
    input_source: str
    latency_ms: float
    provider: str = ""
    tts_engine: str = ""


class BaseVAD(ABC):
    @abstractmethod
    async def start(self) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
    @abstractmethod
    def process(self, chunk: AudioChunk) -> AsyncIterator[VADResult]: ...


class BaseSTT(ABC):
    @abstractmethod
    async def start(self, language: Optional[str] = None) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
    @abstractmethod
    async def transcribe(self, audio: Any, **kwargs) -> TranscriptionSegment: ...
    @abstractmethod
    async def stream(self, audio: Any) -> AsyncIterator[TranscriptionSegment]: ...


class BaseTranslator(ABC):
    @abstractmethod
    async def start(self) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
    @abstractmethod
    async def translate(self, text: str, source_lang: str, target_lang: str, context: Optional[str] = None) -> TranslationResult: ...


class BaseTTS(ABC):
    @abstractmethod
    async def start(self) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
    @abstractmethod
    async def synthesize(self, text: str, lang: str = "en") -> SynthesisResult: ...
    @abstractmethod
    def synthesize_stream(self, text_stream: AsyncIterator[str], lang: str = "en") -> AsyncIterator[SynthesisResult]: ...
    @abstractmethod
    async def set_voice(self, voice_id: str) -> None: ...
    @abstractmethod
    async def set_speed(self, speed: float) -> None: ...


class BaseAudioInput(ABC):
    @abstractmethod
    async def start(self, device_id: Optional[int] = None, **kwargs) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
    @abstractmethod
    def stream(self) -> AsyncIterator[AudioChunk]: ...
    @abstractmethod
    async def list_devices(self) -> list[dict[str, Any]]: ...


class BaseAudioOutput(ABC):
    @abstractmethod
    async def start(self, device_id: Optional[int] = None, **kwargs) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
    @abstractmethod
    async def play(self, chunk: AudioChunk) -> None: ...
    @abstractmethod
    async def list_devices(self) -> list[dict[str, Any]]: ...


class AudioProcessor(ABC):
    @abstractmethod
    async def process(self, audio: Any, sample_rate: int) -> Any: ...
