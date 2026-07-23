from __future__ import annotations

import asyncio
from datetime import datetime
from typing import AsyncIterator, Optional

import numpy as np
import sounddevice as sd

from app.interfaces import AudioChunk, BaseAudioInput
from config.settings import AudioSettings
from services.audio.loopback import find_loopback_device, find_vb_cable_output
from services.audio.resampler import resample
from utils.logger import get_logger

logger = get_logger("audio_input")


class SoundDeviceInput(BaseAudioInput):
    def __init__(self, settings: AudioSettings):
        self.settings = settings
        self._mic_stream: Optional[sd.InputStream] = None
        self._loopback_stream: Optional[sd.InputStream] = None
        self._queue: Optional[asyncio.Queue[AudioChunk]] = None
        self._loopback_queue: Optional[asyncio.Queue[AudioChunk]] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _make_callback(self, native_sr: int, source: str):
        target_sr = self.settings.sample_rate
        q = self._loopback_queue if source == "loopback" else self._queue
        _log_counter = [0]  # nonlocal counter for periodic logging

        def _cb(indata, frames, time_info, status):
            if status:
                logger.debug(f"Audio {source} status: {status}")
            if not self._running or q is None:
                return
            try:
                audio = indata
                if audio.ndim > 1 and audio.shape[1] > 1:
                    audio = np.mean(audio, axis=1)
                elif audio.ndim > 1:
                    audio = audio[:, 0]
                if native_sr != target_sr:
                    audio = resample(audio, native_sr, target_sr)
                dur_ms = (frames / native_sr) * 1000

                # DIAG: log RMS level every ~100th callback for loopback
                _log_counter[0] += 1
                if source == "loopback" and _log_counter[0] % 100 == 0:
                    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
                    logger.info(f"[DIAG] LOOPBACK callback #{_log_counter[0]}: frames={frames}, rms={rms:.6f}, dur_ms={dur_ms:.1f}")

                chunk = AudioChunk(
                    data=audio.tobytes(), sample_rate=target_sr, channels=1,
                    timestamp=datetime.now(), duration_ms=dur_ms, source=source,
                )
                loop = self._loop
                if loop is not None and loop.is_running() and not loop.is_closed():
                    _chunk = chunk
                    _q = q

                    def _safe_put(_c=_chunk, _queue=_q):
                        try:
                            _queue.put_nowait(_c)
                        except asyncio.QueueFull:
                            logger.warning(f"Audio input queue overflow for source '{source}'; dropping chunk")
                        except Exception:
                            pass

                    try:
                        loop.call_soon_threadsafe(_safe_put)
                    except RuntimeError:
                        pass  # loop closed

            except Exception as e:
                logger.warning(f"Error in audio input callback for source '{source}': {e}")
        return _cb

    async def start(self, device_id: Optional[int] = None, loopback: bool = False, capture_mic: bool = True) -> None:
        if self._running or self._mic_stream is not None or self._loopback_stream is not None:
            await self.stop()

        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=500)
        self._loopback_queue = asyncio.Queue(maxsize=500) if loopback else None
        self._running = True

        if device_id is None:
            device_id = self.settings.input_device_id

        try:
            if loopback:
                await self._start_loopback(device_id, capture_mic)
            else:
                await self._start_mic(device_id)
        except Exception as e:
            self._running = False
            logger.error(f"Audio input start failed: {e}")
            raise

    async def _start_loopback(self, device_id: Optional[int], capture_mic: bool) -> None:
        loop_dev = find_loopback_device()
        if loop_dev is None:
            self._running = False
            raise RuntimeError("No loopback device found (Stereo Mix or VB-Cable)")

        dev_id, desc = loop_dev
        try:
            dev_info = sd.query_devices(dev_id)
        except Exception as e:
            self._running = False
            raise RuntimeError(f"Loopback device {dev_id} ({desc}) not available: {e}")

        native_sr = int(dev_info["default_samplerate"])
        native_ch = max(1, dev_info["max_input_channels"])
        cb = self._make_callback(native_sr, source="loopback")

        # Try WASAPI host first (Stereo Mix requires it on some systems), fall back to default
        last_err = None
        wasapi_options = [("WASAPI", sd.WasapiSettings(exclusive=False)), ("default", None)]
        try:
            sd.WasapiSettings
        except AttributeError:
            wasapi_options = [("default", None)]
        for host_label, extra in wasapi_options:
            try:
                self._loopback_stream = sd.InputStream(
                    samplerate=native_sr, channels=min(native_ch, 2),
                    dtype="float32",
                    blocksize=int(native_sr * self.settings.chunk_duration_ms / 1000),
                    callback=cb, device=dev_id,
                    extra_settings=extra,
                )
                self._loopback_stream.start()
                logger.info(f"Loopback started via {desc} (device {dev_id}, host={host_label})")
                last_err = None
                break
            except Exception as e:
                last_err = e
                logger.debug(f"Loopback via {host_label} failed: {e}")

        if last_err is not None:
            self._running = False
            raise RuntimeError(f"Failed to open loopback stream on {desc} (device {dev_id}): {last_err}")

        if capture_mic:
            await self._start_mic(None)

    async def _start_mic(self, device_id: Optional[int]) -> None:
        candidates = []
        try:
            dev_info = sd.query_devices(device_id)
            native_sr = int(dev_info["default_samplerate"]) if dev_info.get("default_samplerate") else self.settings.sample_rate
            native_ch = dev_info["max_input_channels"]
            if native_ch < 1:
                native_ch = 1
            candidates.append((device_id, native_sr, native_ch))
        except Exception:
            pass
        candidates.append((None, self.settings.sample_rate, self.settings.channels))

        last_err = None
        for dev, sr, ch in candidates:
            stream = None
            try:
                cb = self._make_callback(sr, source="mic")
                stream = sd.InputStream(
                    samplerate=sr, channels=ch, dtype="float32",
                    blocksize=int(sr * self.settings.chunk_duration_ms / 1000),
                    callback=cb, device=dev,
                )
                stream.start()
                self._mic_stream = stream
                logger.info(f"Mic started (device={dev}, rate={sr}, ch={ch})")
                return
            except Exception as e:
                last_err = e
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
        raise RuntimeError(f"Mic fallbacks failed: {last_err}")

    async def stop(self) -> None:
        self._running = False
        for st in (self._mic_stream, self._loopback_stream):
            if st is not None:
                try:
                    st.stop()
                    st.close()
                except Exception:
                    pass
        self._mic_stream = None
        self._loopback_stream = None
        if self._queue is not None:
            try:
                await self._queue.put(None)
            except Exception:
                pass
        if self._loopback_queue is not None:
            try:
                await self._loopback_queue.put(None)
            except Exception:
                pass
        logger.info("Audio input stopped")

    async def stream(self) -> AsyncIterator[AudioChunk]:
        q = self._queue
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
        try:
            all_devices = sd.query_devices()
        except Exception:
            return []
        result = []
        if isinstance(all_devices, dict):
            all_devices = [all_devices]
        for idx, device in enumerate(all_devices):
            if isinstance(device, dict) and device.get("max_input_channels", 0) > 0:
                result.append({
                    "id": idx,
                    "name": device.get("name", f"Device {idx}"),
                    "channels": device.get("max_input_channels", 0),
                    "sample_rate": int(device.get("default_samplerate", 44100)),
                })
        return result
