"""
Audio input service using sounddevice for low-latency microphone streaming.
Provides continuous audio capture with callback-based processing.

Loopback (computer audio) modes on Windows, tried in order:
  1. Stereo Mix / "What U Hear" — native, no install (enable in Windows Sound
     Settings → Recording → Show Disabled → Enable Stereo Mix).
  2. VB-Audio Virtual Cable — requires VB-Cable installation.
"""

import asyncio
from typing import AsyncIterator, Optional
from datetime import datetime

import numpy as np
import sounddevice as sd

from core.interfaces import AudioChunk, BaseAudioInput
from config.settings import AudioSettings
from utils.logger import get_logger

logger = get_logger("audio_input")


class SoundDeviceInput(BaseAudioInput):

    def __init__(self, settings: AudioSettings):
        self.settings = settings
        self._stream: Optional[sd.InputStream] = None
        self._mic_stream: Optional[sd.InputStream] = None
        self._queue: Optional[asyncio.Queue[AudioChunk | None]] = None
        self._loopback_queue: Optional[asyncio.Queue[AudioChunk | None]] = None
        self._running = False
        self._device_sample_rate: int = settings.sample_rate
        self._device_channels: int = settings.channels

    def _make_callback(self, sample_rate: int, source: str = "mic"):
        target_sr = self.settings.sample_rate
        queue = self._loopback_queue if source == "loopback" else self._queue

        def _cb(indata, frames, time_info, status):
            try:
                if status:
                    logger.debug(f"Audio input status: {status}")
                if not self._running:
                    return
                audio: np.ndarray = indata
                if audio.ndim > 1 and audio.shape[1] > 1:
                    audio = np.mean(audio, axis=1)
                elif audio.ndim > 1:
                    audio = audio[:, 0]
                if sample_rate != target_sr:
                    src_len = len(audio)
                    dst_len = int(src_len * target_sr / sample_rate)
                    indices = np.arange(dst_len) * src_len / dst_len
                    audio = np.interp(indices, np.arange(src_len), audio).astype(np.float32)
                dur_ms = (frames / sample_rate) * 1000
                chunk = AudioChunk(
                    data=audio.tobytes(), sample_rate=target_sr, channels=1,
                    timestamp=datetime.now(), duration_ms=dur_ms, source=source,
                )
                loop = self._loop
                if loop is not None and not loop.is_closed():
                    try:
                        loop.call_soon_threadsafe(queue.put_nowait, chunk)
                    except RuntimeError:
                        pass
            except Exception:
                pass
        return _cb

    @staticmethod
    def _find_stereo_mix() -> Optional[int]:
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            name = (d["name"] or "").lower()
            if d["max_input_channels"] > 0 and "stereo mix" in name:
                return i
        return None

    @staticmethod
    def _find_cable_device() -> Optional[int]:
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            name = d["name"]
            if d["max_input_channels"] > 0 and ("CABLE Output" in name or "CABLE" in name):
                if d["hostapi"] in (0, 1):
                    return i
        for i, d in enumerate(devices):
            name = d["name"]
            if d["max_input_channels"] > 0 and ("CABLE Output" in name):
                return i
        return None

    async def start(self, device_id: Optional[int] = None, loopback: bool = False, capture_mic: bool = True) -> None:
        for st in (self._stream, self._mic_stream):
            if st is not None:
                try:
                    st.stop()
                    st.close()
                except Exception:
                    pass
        self._stream = None
        self._mic_stream = None
        self._loop = None
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._loopback_queue = asyncio.Queue() if loopback else None
        self._device_id = device_id
        self._running = True
        if device_id is None:
            device_id = self.settings.input_device_id
        try:
            if loopback:
                methods = [
                    (self._find_stereo_mix(), "Stereo Mix"),
                    (self._find_cable_device(), "VB-Cable"),
                ]
                loop_ok = False
                for dev, desc in methods:
                    if dev is None:
                        continue
                    try:
                        dev_info = sd.query_devices(dev)
                        native_sr = int(dev_info["default_samplerate"])
                        native_ch = max(1, dev_info["max_input_channels"])
                        cb = self._make_callback(native_sr, source="loopback")
                        self._stream = sd.InputStream(
                            samplerate=native_sr, channels=min(native_ch, 2),
                            dtype="float32",
                            blocksize=int(native_sr * self.settings.chunk_duration_ms / 1000),
                            callback=cb, device=dev,
                        )
                        self._stream.start()
                        logger.info(f"Loopback started via {desc} (device {dev}: {dev_info['name']})")
                        loop_ok = True
                        break
                    except Exception as e:
                        logger.warning(f"Loopback via {desc} failed: {e}")
                        if self._stream is not None:
                            try:
                                self._stream.close()
                            except Exception:
                                pass
                            self._stream = None
                        continue
                if not loop_ok:
                    self._running = False
                    raise RuntimeError("No loopback device found.")
                if capture_mic:
                    self._device_sample_rate = self.settings.sample_rate
                    self._device_channels = self.settings.channels
                    mic_id = device_id
                    mic_candidates = []
                    try:
                        dev_info = sd.query_devices(mic_id)
                        native_sr = int(dev_info["default_samplerate"]) if dev_info.get("default_samplerate") else self.settings.sample_rate
                        native_ch = dev_info["max_input_channels"]
                        if native_ch < 1:
                            native_ch = 1
                        mic_candidates.append((mic_id, native_sr, native_ch))
                    except Exception:
                        pass
                    mic_candidates.append((None, self.settings.sample_rate, self.settings.channels))
                    if (None, self.settings.sample_rate, self.settings.channels) != (None, 16000, 1):
                        mic_candidates.append((None, 16000, 1))
                    mic_ok = False
                    for dev, sr, ch in mic_candidates:
                        try:
                            cb = self._make_callback(sr, source="mic")
                            mic_st = sd.InputStream(
                                samplerate=sr, channels=ch, dtype="float32",
                                blocksize=int(sr * self.settings.chunk_duration_ms / 1000),
                                callback=cb, device=dev,
                            )
                            mic_st.start()
                            self._mic_stream = mic_st
                            dev_label = dev if dev is not None else "default"
                            logger.info(f"Loopback mic also started (device={dev_label}, rate={sr}, ch={ch})")
                            mic_ok = True
                            break
                        except Exception as e:
                            logger.warning(f"Loopback mic candidate ({dev}, {sr}, {ch}) failed: {e}")
                            continue
                    if not mic_ok:
                        logger.warning("Loopback mode: microphone not available, continuing with computer audio only")
                else:
                    logger.info("Text Input Mode — loopback only, mic not captured")
            else:
                candidates = []
                try:
                    dev_info = sd.query_devices(device_id)
                    native_sr = int(dev_info["default_samplerate"]) if dev_info.get("default_samplerate") else self.settings.sample_rate
                    native_ch = dev_info["max_input_channels"]
                    if native_ch < 1:
                        logger.warning(f"Device {device_id} reports {native_ch} input channels, forcing 1")
                        native_ch = 1
                    candidates.append((device_id, native_sr, native_ch))
                except Exception:
                    pass
                candidates.append((None, self.settings.sample_rate, self.settings.channels))
                if (None, self.settings.sample_rate, self.settings.channels) != (None, 16000, 1):
                    candidates.append((None, 16000, 1))
                stream = None
                last_err = None
                for dev, sr, ch in candidates:
                    try:
                        cb = self._make_callback(sr, source="mic")
                        stream = sd.InputStream(
                            samplerate=sr, channels=ch, dtype="float32",
                            blocksize=int(sr * self.settings.chunk_duration_ms / 1000),
                            callback=cb, device=dev,
                        )
                        stream.start()
                        self._device_sample_rate = sr
                        self._device_channels = ch
                        self._stream = stream
                        dev_label = dev if dev is not None else "default"
                        logger.info(f"Audio input started (device={dev_label}, rate={sr}, ch={ch})")
                        break
                    except Exception as e:
                        last_err = e
                        if stream is not None:
                            try:
                                stream.close()
                            except Exception:
                                pass
                        stream = None
                        continue
                if stream is None:
                    raise RuntimeError(f"All audio input fallbacks failed: {last_err}")
            if self._stream is None:
                self._running = False
                raise RuntimeError("Audio input stream creation failed")
        except Exception as e:
            self._running = False
            logger.error(f"Failed to start audio input: {e}")
            raise RuntimeError(f"Audio input initialization failed: {e}") from e

    async def stop(self) -> None:
        self._running = False
        old_loop = self._loop
        self._loop = None
        old_queue = self._queue
        old_loopback_queue = self._loopback_queue
        for st in (self._stream, self._mic_stream):
            if st is not None:
                try:
                    st.stop()
                    st.close()
                except Exception as e:
                    logger.debug(f"Error stopping audio input: {e}")
        self._stream = None
        self._mic_stream = None
        if old_queue is not None:
            await old_queue.put(None)
        if old_loopback_queue is not None:
            await old_loopback_queue.put(None)
        self._loopback_queue = None
        logger.info("Audio input stopped")

    async def stream(self) -> AsyncIterator[AudioChunk]:
        while self._running:
            try:
                chunk = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                if chunk is None:
                    break
                yield chunk
            except asyncio.TimeoutError:
                continue

    async def stream_loopback(self) -> AsyncIterator[AudioChunk]:
        q = self._loopback_queue
        if q is None:
            return
        while self._running:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=0.1)
                if chunk is None:
                    break
                yield chunk
            except asyncio.TimeoutError:
                continue

    async def list_devices(self) -> list[dict]:
        devices = sd.query_devices(kind="input")
        result = []
        for i, device in enumerate(devices):
            if isinstance(device, dict):
                result.append({
                    "id": i,
                    "name": device.get("name", f"Device {i}"),
                    "channels": device.get("max_input_channels", 0),
                    "sample_rate": device.get("default_samplerate", 44100),
                })
        return result
