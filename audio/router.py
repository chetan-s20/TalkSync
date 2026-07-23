"""Audio router for speaker playback, VB-Cable virtual mic, and recording."""
from __future__ import annotations

import asyncio
import queue
import threading
import time
from typing import Optional

import numpy as np
import sounddevice as sd

from core.interfaces import AudioChunk, BaseAudioOutput
from config.settings import AudioSettings
from utils.logger import get_logger

logger = get_logger("audio_router")


class AudioRouter(BaseAudioOutput):
    def __init__(self, settings: AudioSettings):
        self.settings = settings
        self._stream: Optional[sd.OutputStream] = None
        self._play_queue: queue.Queue = queue.Queue(maxsize=256)
        self._running = False
        self._play_thread: Optional[threading.Thread] = None
        self._volume: float = 1.0
        self._muted: bool = False
        self._delay_s: float = 0.0
        self._output_sample_rate: int = getattr(settings, "output_sample_rate", 24000)

    async def start(self, device_id: Optional[int] = None) -> None:
        if device_id is None:
            device_id = getattr(self.settings, "output_device_id", None)
        self._running = True
        self._play_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._play_thread.start()
        await asyncio.sleep(0.05)

    async def stop(self) -> None:
        self._running = False
        if self._play_thread is not None:
            self._play_thread.join(timeout=1.5)
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def enqueue_audio(self, synthesis_result) -> None:
        try:
            self._play_queue.put_nowait(synthesis_result)
        except queue.Full:
            pass

    def _playback_loop(self) -> None:
        try:
            while self._running:
                try:
                    result = self._play_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if result is None:
                    break
                audio = result.audio_data
                sr = result.sample_rate
                if sr != self._output_sample_rate:
                    audio = self._resample(audio, sr, self._output_sample_rate)
                self._play_audio(audio, self._output_sample_rate)
        except Exception as e:
            logger.error(f"AudioRouter playback error: {e}")

    def _play_audio(self, raw: bytes, sample_rate: int) -> None:
        if self._muted:
            return
        try:
            audio = np.frombuffer(raw, dtype=np.float32)
            if self._volume != 1.0:
                audio = np.clip(audio * self._volume, -1.0, 1.0).astype(np.float32)
                raw = audio.tobytes()
        except Exception:
            pass
        try:
            sd.play(raw, samplerate=sample_rate, blocking=False)
        except Exception as e:
            logger.warning(f"Audio playback failed: {e}")

    def _resample(self, raw: bytes, src_sr: int, dst_sr: int) -> bytes:
        try:
            audio = np.frombuffer(raw, dtype=np.float32)
            if dst_sr == src_sr:
                return raw
            src_len = len(audio)
            dst_len = int(src_len * dst_sr / src_sr)
            indices = np.arange(dst_len) * src_len / dst_len
            resampled = np.interp(indices, np.arange(src_len), audio).astype(np.float32)
            return resampled.tobytes()
        except Exception:
            return raw

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)

    def set_delay(self, delay_s: float) -> None:
        self._delay_s = max(0.0, delay_s)

    async def list_devices(self) -> list[dict]:
        try:
            devices = sd.query_devices(kind="output")
        except Exception:
            return []
        result = []
        if isinstance(devices, dict):
            devices = [devices]
        for i, device in enumerate(devices):
            if not isinstance(device, dict):
                continue
            result.append({
                "id": i,
                "name": device.get("name", f"Device {i}"),
                "channels": device.get("max_output_channels", 0),
                "sample_rate": int(device.get("default_samplerate", 44100)),
            })
        return result

    async def play(self, chunk: AudioChunk) -> None:
        try:
            sd.play(chunk.data, samplerate=chunk.sample_rate, blocking=True)
        except Exception as e:
            logger.warning(f"AudioRouter play failed: {e}")
