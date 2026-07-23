from __future__ import annotations

import asyncio
import queue
import threading
from typing import Optional

import numpy as np
import sounddevice as sd

from app.interfaces import AudioChunk, BaseAudioOutput
from config.settings import AudioSettings
from services.audio.loopback import find_vb_cable_output
from services.audio.resampler import resample
from utils.logger import get_logger

logger = get_logger("audio_output")

OUTPUT_RATES = (24000, 44100, 48000, 16000)
OUTPUT_CHANNELS = (2, 1)


class SoundDeviceOutput(BaseAudioOutput):
    def __init__(self, settings: AudioSettings):
        self.settings = settings
        self._speaker_stream: Optional[sd.OutputStream] = None
        self._virtual_stream: Optional[sd.OutputStream] = None
        self._play_queue: queue.Queue = queue.Queue(maxsize=256)
        self._running = False
        self._play_thread: Optional[threading.Thread] = None
        self._volume: float = 1.0
        self._muted: bool = False
        self._delay_s: float = 0.0

    @staticmethod
    def _is_valid_output_device(device_id: Optional[int]) -> bool:
        """Return True if the device supports audio output (has output channels)."""
        if device_id is None:
            return True  # system default is always valid
        try:
            info = sd.query_devices(device_id)
            return int(info.get("max_output_channels", 0)) > 0
        except Exception:
            return False

    async def start(self, device_id: Optional[int] = None) -> None:
        if device_id is None:
            device_id = self.settings.output_device_id

        # Validate: reject recording-only devices (e.g. Stereo Mix idx 4)
        if device_id is not None and not self._is_valid_output_device(device_id):
            logger.warning(
                f"Configured output device {device_id} has no output channels "
                f"(likely a recording device like Stereo Mix). Falling back to system default."
            )
            device_id = None

        self._running = True
        self._play_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._play_thread.start()

        self._speaker_stream = self._try_open_output(device_id)
        if self._speaker_stream is None:
            logger.warning("Speaker output stream creation failed — trying system default")
            self._speaker_stream = self._try_open_output(None)

        if self.settings.virtual_mic_enabled:
            vb_dev = find_vb_cable_output()
            if vb_dev is not None:
                self._virtual_stream = self._try_open_output(vb_dev)
                if self._virtual_stream is not None:
                    logger.info(f"Virtual mic output started (device {vb_dev})")
            else:
                logger.warning("VB-Cable output not found for virtual mic")

    def _try_open_output(self, device_id: Optional[int] = None) -> Optional[sd.OutputStream]:
        # Build candidate list: try specified device first, then system default
        candidate_devices: list[Optional[int]] = []
        if device_id is not None and self._is_valid_output_device(device_id):
            candidate_devices.append(device_id)
        # Always include system default as final fallback
        if None not in candidate_devices:
            candidate_devices.append(None)

        for dev in candidate_devices:
            for rate in OUTPUT_RATES:
                for channels in OUTPUT_CHANNELS:
                    try:
                        stream = sd.OutputStream(
                            samplerate=rate, channels=channels,
                            dtype="float32", device=dev,
                        )
                        stream.start()
                        logger.info(f"Audio output opened (device={dev}, rate={rate}, ch={channels})")
                        return stream
                    except Exception as e:
                        logger.debug(f"Failed opening output stream (device={dev}, rate={rate}, ch={channels}): {e}")
                        continue
        logger.error("All output device candidates failed")
        return None

    async def stop(self) -> None:
        self._running = False
        try:
            self._play_queue.put_nowait((None, 0))
        except queue.Full:
            pass
        if self._play_thread is not None and self._play_thread.is_alive():
            self._play_thread.join(timeout=2.0)
        while not self._play_queue.empty():
            try:
                self._play_queue.get_nowait()
            except queue.Empty:
                break
        for st in (self._speaker_stream, self._virtual_stream):
            if st is not None:
                try:
                    st.stop()
                    st.close()
                except Exception:
                    pass
        self._speaker_stream = None
        self._virtual_stream = None

    def _enqueue(self, raw: bytes, sample_rate: int) -> None:
        try:
            self._play_queue.put_nowait((raw, sample_rate))
        except queue.Full:
            pass

    def _playback_loop(self) -> None:
        try:
            while self._running:
                try:
                    raw, sr = self._play_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if raw is None:
                    break
                if self._muted:
                    continue
                try:
                    audio = np.frombuffer(raw, dtype=np.float32)
                except Exception:
                    continue
                if self._volume != 1.0:
                    audio = np.clip(audio * self._volume, -1.0, 1.0).astype(np.float32)

                for stream in (self._speaker_stream, self._virtual_stream):
                    if stream is None:
                        continue
                    try:
                        out_audio = audio
                        if sr != stream.samplerate:
                            out_audio = resample(audio, sr, int(stream.samplerate))
                        if stream.channels == 2 and out_audio.ndim == 1:
                            out_audio = np.column_stack([out_audio, out_audio])
                        elif stream.channels == 1 and out_audio.ndim == 2:
                            out_audio = out_audio[:, 0]
                        stream.write(out_audio.astype(np.float32))
                    except Exception as e:
                        logger.debug(f"Output write error: {e}")
        except Exception as e:
            logger.error(f"Playback loop error: {e}")

    async def play(self, chunk: AudioChunk) -> None:
        if self._delay_s > 0:
            await asyncio.sleep(self._delay_s)
        self._enqueue(chunk.data, chunk.sample_rate)

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))

    def set_muted(self, muted: bool) -> None:
        self._muted = muted

    def set_delay(self, delay_s: float) -> None:
        self._delay_s = max(0.0, delay_s)

    async def list_devices(self) -> list[dict]:
        try:
            all_devices = sd.query_devices()
        except Exception:
            return []
        result = []
        if isinstance(all_devices, dict):
            all_devices = [all_devices]
        for idx, device in enumerate(all_devices):
            if isinstance(device, dict) and device.get("max_output_channels", 0) > 0:
                result.append({
                    "id": idx,
                    "name": device.get("name", f"Device {idx}"),
                    "channels": device.get("max_output_channels", 0),
                    "sample_rate": int(device.get("default_samplerate", 44100)),
                })
        return result
