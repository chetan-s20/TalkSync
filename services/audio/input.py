from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from typing import AsyncIterator, Optional

import numpy as np
import sounddevice as sd

from app.interfaces import AudioChunk, BaseAudioInput
from config.settings import AudioSettings
from services.audio.loopback import find_loopback_device, find_stereo_mix, find_vb_cable, find_vb_cable_output
from services.audio.resampler import resample
from utils.device import find_best_input_device
from utils.logger import get_logger

logger = get_logger("audio_input")


class SoundDeviceInput(BaseAudioInput):
    def __init__(self, settings: AudioSettings):
        self.settings = settings
        self._mic_stream: Optional[sd.InputStream] = None
        self._loopback_stream: Optional[object] = None  # sd.InputStream or sentinel for WASAPI
        self._queue: Optional[asyncio.Queue[AudioChunk]] = None
        self._loopback_queue: Optional[asyncio.Queue[AudioChunk]] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._wasapi_thread: Optional[threading.Thread] = None
        self._wasapi_running: Optional[list[bool]] = None
        self._overflow_count = 0
        self._underflow_count = 0
        self._total_chunks_processed = 0
        self._device_init_errors: list[str] = []

    def _make_callback(self, native_sr: int, source: str):
        target_sr = self.settings.sample_rate
        _log_counter = [0]  # nonlocal counter for periodic logging

        def _cb(indata, frames, time_info, status):
            if status:
                logger.debug(f"Audio {source} status: {status}")
            q = self._loopback_queue if source == "loopback" else self._queue
            if not self._running or q is None:
                return
            try:
                audio = indata.copy()
                if audio.ndim > 1 and audio.shape[1] > 1:
                    audio = np.mean(audio, axis=1)
                elif audio.ndim > 1:
                    audio = audio[:, 0]

                # Fixed gain & Anti-clipping protection
                gain = float(getattr(self.settings, "volume", 1.0))
                if gain != 1.0:
                    audio = audio * gain
                audio = np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)
                audio = np.clip(audio, -1.0, 1.0).astype(np.float32)

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
                is_closed = False
                if loop is not None and hasattr(loop, "is_closed"):
                    try:
                        is_closed = bool(loop.is_closed())
                    except Exception:
                        is_closed = False

                if loop is not None and loop.is_running() and not is_closed:
                    _chunk = chunk
                    _q = q

                    def _safe_put(_c=_chunk, _queue=_q):
                        try:
                            if _queue.full():
                                self._overflow_count += 1
                                try:
                                    _queue.get_nowait()  # Evict oldest chunk to prevent pipeline stall
                                except Exception:
                                    pass
                                now = time.time()
                                attr_name = f"_last_overflow_log_{source}"
                                if now - getattr(self, attr_name, 0.0) >= 5.0:
                                    setattr(self, attr_name, now)
                                    logger.warning(f"Audio input queue overflow for source '{source}' (evicting oldest chunks)")
                            _queue.put_nowait(_c)
                            self._total_chunks_processed += 1
                        except Exception as e:
                            logger.warning(f"Audio input queue dispatch error for '{source}': {e}")

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
        self._device_init_errors.clear()

        if device_id is None:
            device_id = self.settings.input_device_id

        try:
            if loopback:
                try:
                    await self._start_loopback(device_id, capture_mic)
                except Exception as loop_e:
                    logger.warning(f"Audio loopback capture initialization failed ({loop_e}) — falling back cleanly to microphone-only capture")
                    self._loopback_queue = None
                    self._loopback_stream = None
                    if capture_mic:
                        await self._start_mic(device_id)
                    else:
                        raise
            else:
                await self._start_mic(device_id)
        except Exception as e:
            self._running = False
            logger.error(f"Audio input start failed: {e}")
            raise

    async def _start_loopback(self, device_id: Optional[int], capture_mic: bool) -> None:
        loop_dev = find_loopback_device(getattr(self.settings, "output_device_id", None))
        if loop_dev is None:
            raise RuntimeError("No loopback device found (WASAPI, Stereo Mix, or VB-Cable)")

        dev, dev_type = loop_dev

        if dev_type == "WASAPI":
            # Use soundcard WASAPI loopback (preferred)
            try:
                await self._start_wasapi_loopback(str(dev))
                logger.info(f"Loopback capturing from: {dev} — headphone audio WILL be captured")
                logger.info(f"Loopback started via WASAPI ({dev})")
            except Exception as e:
                err_msg = f"WASAPI loopback failed ({dev}): {e}"
                logger.warning(f"{err_msg}; attempting fallback loopback device")
                self._device_init_errors.append(err_msg)
                # Attempt fallback sounddevice loopback
                await self._start_fallback_loopback()
        else:
            # Use sounddevice (Stereo Mix or VB-Cable)
            await self._start_sd_loopback(int(dev), str(dev_type))

        if capture_mic:
            await self._start_mic(device_id)

    async def _start_fallback_loopback(self) -> None:
        """Fallback helper when WASAPI loopback fails."""
        sm = find_stereo_mix()
        if sm is not None:
            await self._start_sd_loopback(int(sm), "Stereo Mix")
            return
        vbc = find_vb_cable()
        if vbc is not None:
            await self._start_sd_loopback(int(vbc), "VB-Cable Output")
            return
        raise RuntimeError("WASAPI loopback failed and no sounddevice fallback loopback device found")

    async def _start_wasapi_loopback(self, device_name: str) -> None:
        """Start WASAPI loopback capture via soundcard in a background thread."""
        try:
            import soundcard as sc
        except ImportError as e:
            raise RuntimeError(f"soundcard package not available: {e}")

        # Find the loopback device by name
        loop_dev = None
        try:
            for m in sc.all_microphones(include_loopback=True):
                if m.isloopback and m.name == device_name:
                    loop_dev = m
                    break
        except Exception as e:
            raise RuntimeError(f"Error enumerating soundcard WASAPI loopback devices: {e}")

        if loop_dev is None:
            raise RuntimeError(f"WASAPI loopback device '{device_name}' not found via soundcard")

        target_sr = self.settings.sample_rate
        chunk_size = int(target_sr * self.settings.chunk_duration_ms / 1000)  # e.g., 480 @ 16kHz for 30ms
        q = self._loopback_queue
        loop = self._loop
        _running = [True]

        self._loopback_stream = object()  # non-None sentinel for cleanup
        self._wasapi_running = _running

        def _capture():
            try:
                import ctypes
                try:
                    ctypes.windll.ole32.CoInitialize(None)
                except Exception:
                    pass
                gain = float(getattr(self.settings, "volume", 1.0))
                
                # Determine loopback sample rates to try
                rates_to_try = [target_sr]
                native_rate = 48000
                try:
                    if hasattr(loop_dev, "default_samplerate"):
                        native_rate = int(loop_dev.default_samplerate)
                    elif hasattr(loop_dev, "samplerate"):
                        native_rate = int(loop_dev.samplerate)
                except Exception:
                    pass
                if native_rate not in rates_to_try:
                    rates_to_try.append(native_rate)
                for r in (44100, 48000):
                    if r not in rates_to_try:
                        rates_to_try.append(r)

                rec = None
                active_sr = target_sr
                for rate in rates_to_try:
                    try:
                        block = int(rate * self.settings.chunk_duration_ms / 1000)
                        rec = loop_dev.recorder(samplerate=rate, channels=1, blocksize=block)
                        active_sr = rate
                        logger.info(f"Opened WASAPI loopback recorder at sample rate {rate}Hz (blocksize={block})")
                        break
                    except Exception as e:
                        logger.warning(f"Failed opening WASAPI loopback at {rate}Hz: {e}", exc_info=True)
                
                if rec is None:
                    raise RuntimeError("All sample rates failed to open loopback recorder")

                with rec:
                    block = int(active_sr * self.settings.chunk_duration_ms / 1000)
                    while _running[0]:
                        data = rec.record(numframes=block)
                        if data is None or len(data) == 0:
                            continue
                        data = np.asarray(data, dtype=np.float32)
                        if data.ndim > 1:
                            data = np.mean(data, axis=1) if data.shape[1] > 1 else data[:, 0]
                        else:
                            data = data.ravel()
                        
                        # Resample if captured rate differs from target (16000)
                        if active_sr != target_sr:
                            data = resample(data, active_sr, target_sr)
                            
                        if gain != 1.0:
                            data = data * gain
                        data = np.nan_to_num(data, nan=0.0, posinf=1.0, neginf=-1.0)
                        data = np.clip(data, -1.0, 1.0).astype(np.float32)

                        dur_ms = (len(data) / target_sr) * 1000
                        chunk = AudioChunk(
                            data=data.tobytes(), sample_rate=target_sr, channels=1,
                            timestamp=datetime.now(), duration_ms=dur_ms, source="loopback",
                        )
                        if loop is not None and loop.is_running() and not loop.is_closed():
                            _c = chunk
                            _q = q
                            def _put(_c=_c, _q=_q):
                                try:
                                    if _q.full():
                                        self._overflow_count += 1
                                        try:
                                            _q.get_nowait()
                                        except Exception:
                                            pass
                                        logger.warning("WASAPI loopback queue full; evicted oldest chunk")
                                    _q.put_nowait(_c)
                                    self._total_chunks_processed += 1
                                except Exception as e:
                                    logger.warning(f"WASAPI loopback queue put error: {e}")
                            try:
                                loop.call_soon_threadsafe(_put)
                            except RuntimeError:
                                pass
            except Exception as e:
                logger.error(f"WASAPI loopback capture error: {e}")
                self._device_init_errors.append(f"WASAPI capture error: {e}")

        self._wasapi_thread = threading.Thread(target=_capture, daemon=True)
        self._wasapi_thread.start()

    async def _start_sd_loopback(self, dev_id: int, desc: str) -> None:
        """Start loopback capture via sounddevice (Stereo Mix or VB-Cable)."""
        try:
            dev_info = sd.query_devices(dev_id)
        except Exception as e:
            raise RuntimeError(f"Loopback device {dev_id} ({desc}) not available: {e}")

        native_sr = int(dev_info.get("default_samplerate", 44100))
        native_ch = max(1, dev_info.get("max_input_channels", 2))
        loopback_name = dev_info.get("name", desc)

        logger.info(f"Loopback capturing from: {loopback_name} — headphone audio WILL be captured")

        # Open at native sample rate (44.1kHz/48kHz) first, then resample to 16kHz in callback
        if native_sr != self.settings.sample_rate:
            sample_rates = [native_sr, self.settings.sample_rate]
        else:
            sample_rates = [self.settings.sample_rate]

        last_err = None
        for sr in sample_rates:
            cb = self._make_callback(sr, source="loopback")
            wasapi_options = [("WASAPI", sd.WasapiSettings(exclusive=False)), ("default", None)]
            try:
                sd.WasapiSettings
            except AttributeError:
                wasapi_options = [("default", None)]

            for host_label, extra in wasapi_options:
                try:
                    self._loopback_stream = sd.InputStream(
                        samplerate=sr, channels=min(native_ch, 2),
                        dtype="float32",
                        blocksize=int(sr * self.settings.chunk_duration_ms / 1000),
                        callback=cb, device=dev_id,
                        extra_settings=extra,
                    )
                    self._loopback_stream.start()
                    logger.info(f"Loopback (sounddevice) started via {desc} (device {dev_id}, rate={sr}, host={host_label})")
                    return
                except Exception as e:
                    last_err = e
                    logger.debug(f"Loopback via {host_label} at {sr}Hz failed: {e}")

        if last_err is not None:
            err_msg = f"Failed to open loopback stream on {desc} (device {dev_id}): {last_err}"
            self._device_init_errors.append(err_msg)
            raise RuntimeError(err_msg)

    async def _start_mic(self, device_id: Optional[int]) -> None:
        best_id, best_name = find_best_input_device(device_id)
        logger.info(f"Microphone selection resolved to device ID {best_id} ('{best_name}')")

        candidates = []
        if best_id is not None:
            try:
                dev_info = sd.query_devices(best_id)
                native_sr = int(dev_info["default_samplerate"]) if dev_info.get("default_samplerate") else self.settings.sample_rate
                native_ch = int(dev_info.get("max_input_channels", 1))
                if native_ch >= 1:
                    candidates.append((best_id, self.settings.sample_rate, min(native_ch, self.settings.channels)))
                    candidates.append((best_id, native_sr, min(native_ch, self.settings.channels)))
                    candidates.append((best_id, native_sr, 1))
            except Exception as e:
                logger.debug(f"Failed to query resolved mic device {best_id}: {e}")
                self._device_init_errors.append(f"Query specified mic device {best_id} failed: {e}")

        # Fallback candidates using system default if resolved device fails or is None
        candidates.append((None, self.settings.sample_rate, self.settings.channels))
        candidates.append((None, self.settings.sample_rate, 1))
        candidates.append((None, 44100, 1))
        candidates.append((None, 16000, 1))

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
                if dev is not None:
                    self.settings.input_device_id = dev
                logger.info(f"Mic stream started cleanly (device={dev} ['{best_name}'], rate={sr}Hz, ch={ch})")
                return
            except Exception as e:
                last_err = e
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
        err_msg = f"Mic fallbacks failed: {last_err}"
        self._device_init_errors.append(err_msg)
        raise RuntimeError(err_msg)

    async def stop(self) -> None:
        self._running = False

        # Stop WASAPI loopback thread if running
        if self._wasapi_running is not None:
            self._wasapi_running[0] = False
        if self._wasapi_thread is not None:
            self._wasapi_thread.join(timeout=2)
            self._wasapi_thread = None
        self._wasapi_running = None

        # Stop sounddevice streams
        for st in (self._mic_stream, self._loopback_stream):
            if st is not None and hasattr(st, "stop"):
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

    def get_diagnostics(self) -> dict:
        """Return diagnostic metrics for stream health and reliability monitoring."""
        return {
            "running": self._running,
            "mic_active": self._mic_stream is not None,
            "loopback_active": self._loopback_stream is not None,
            "overflow_count": self._overflow_count,
            "underflow_count": self._underflow_count,
            "total_chunks": self._total_chunks_processed,
            "device_init_errors": list(self._device_init_errors),
        }

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

