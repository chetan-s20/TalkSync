"""TalkSync AI — Application orchestrator."""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from app.interfaces import AudioProcessor
from app.pipeline import Pipeline
from app.pipeline_errors import ServiceError
from config.settings import AudioSettings, Settings
from utils.logger import get_logger

logger = get_logger("application")


def validate_and_resolve_audio_devices(settings: Settings) -> None:
    """Validate configured audio device IDs against active channel counts at startup.
    Fallback to auto-detection if configured device is invalid or unplugged.
    """
    from utils.device import find_best_input_device, find_best_output_device

    in_id, in_name = find_best_input_device(settings.audio.input_device_id)
    settings.audio.input_device_id = in_id
    settings.selected_input_device_name = in_name

    out_id, out_name = find_best_output_device(settings.audio.output_device_id)
    settings.audio.output_device_id = out_id
    settings.selected_output_device_name = out_name

    logger.info(f"Startup Input Device: ID {in_id} ('{in_name}')")
    logger.info(f"Startup Output Device: ID {out_id} ('{out_name}')")


class Application:
    def __init__(self, settings: Optional[Settings] = None):
        from config.settings import load_settings
        self.settings = settings or load_settings()
        validate_and_resolve_audio_devices(self.settings)
        self.pipeline: Optional[Pipeline] = None
        self._services: dict[str, Any] = {}
        self._audio_processors: list[AudioProcessor] = []
        self._main_window: Optional[Any] = None

    def register_service(self, name: str, service: Any) -> None:
        self._services[name] = service

    def get_service(self, name: str) -> Any:
        return self._services.get(name)

    def add_audio_processor(self, processor: AudioProcessor) -> None:
        self._audio_processors.append(processor)

    def build_pipeline(self) -> Pipeline:
        from services.audio.input import SoundDeviceInput
        from services.audio.output import SoundDeviceOutput
        from services.vad.silero_vad import SileroVAD
        from services.stt.faster_whisper import FasterWhisperSTT
        from services.translation.factory import TranslationFactory
        from services.tts.router import MultilingualTTSRouter
        from services.translation.context_engine import ContextEngine
        from services.history.database import HistoryDatabase

        audio_input = self._services.get("audio_input") or SoundDeviceInput(self.settings.audio)
        audio_output = self._services.get("audio_output") or SoundDeviceOutput(self.settings.audio)
        vad = self._services.get("vad") or SileroVAD(self.settings.vad)

        # --- STT Engine Selection via STTFactory ---
        if not self._services.get("stt"):
            from services.stt.factory import STTFactory
            try:
                loop = asyncio.get_running_loop()
                fut = asyncio.run_coroutine_threadsafe(STTFactory.create(self.settings), loop)
                stt = fut.result(timeout=15.0)
            except RuntimeError:
                stt = asyncio.run(STTFactory.create(self.settings))
        else:
            stt = self._services.get("stt")
        tts = self._services.get("tts") or MultilingualTTSRouter(self.settings.tts)
        context_engine = ContextEngine()

        db = self._services.get("db")
        if db is None:
            db = HistoryDatabase(self.settings.history.db_path)

        translator = self._services.get("translator")
        if translator is None:
            try:
                loop = asyncio.get_running_loop()
                fut = asyncio.run_coroutine_threadsafe(TranslationFactory.create(self.settings), loop)
                translator = fut.result(timeout=15.0)
            except RuntimeError:
                translator = asyncio.run(TranslationFactory.create(self.settings))

        self.register_service("audio_input", audio_input)
        self.register_service("audio_output", audio_output)
        self.register_service("vad", vad)
        self.register_service("stt", stt)
        self.register_service("tts", tts)
        self.register_service("translator", translator)
        self.register_service("db", db)

        self.pipeline = Pipeline(
            audio_input=audio_input,
            vad=vad,
            stt=stt,
            translator=translator,
            tts=tts,
            audio_output=audio_output,
            audio_processors=self._audio_processors,
            context_engine=context_engine,
            settings=self.settings,
            db=db,
        )
        return self.pipeline

    def set_main_window(self, window: Any) -> None:
        self._main_window = window

    @property
    def main_window(self) -> Optional[Any]:
        return self._main_window
