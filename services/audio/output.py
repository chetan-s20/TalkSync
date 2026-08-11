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
from utils.device import find_best_output_device, find_best_physical_output_device
from utils.logger import get_logger

logger = get_logger("audio_output")

OUTPUT_RATES = (44100, 48000, 24000, 16000)
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

        resolved_id, resolved_name = find_best_output_device(device_id)
        logger.info(f"Playback selection resolved to device ID {resolved_id} ('{resolved_name}')")

        self._running = True
        self._play_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._play_thread.start()

        # Check if resolved_id is VB-Cable endpoint
        is_virtual = any(k in (resolved_name or "").lower() for k in ("cable input", "virtual cable", "vb-audio"))
        if is_virtual:
            logger.info(f"Configured output '{resolved_name}' is VB-Cable virtual mic endpoint")
            self._virtual_stream = self._try_open_virtual_output(resolved_id)
            phys_id, phys_name = find_best_physical_output_device()
            logger.info(f"Physical headphone/speaker output auto-detected on device ID {phys_id} ('{phys_name}')")
            self._speaker_stream = self._try_open_output(phys_id)
        else:
            self._speaker_stream = self._try_open_output(resolved_id)
            if self._speaker_stream is None:
                logger.warning("Speaker/headphones output stream creation failed — trying system default")
                self._speaker_stream = self._try_open_output(None)

            vb_dev = find_vb_cable_output()
            if vb_dev is not None:
                self._virtual_stream = self._try_open_virtual_output(vb_dev)
                if self._virtual_stream is not None:
                    logger.info(f"Virtual mic output started on VB-Cable (device {vb_dev})")
            elif self.settings.virtual_mic_enabled:
                logger.warning("VB-Cable output not found for virtual mic")

    def _try_open_virtual_output(self, device_id: int) -> Optional[sd.OutputStream]:
        """Try to open dedicated virtual mic output stream without speaker fallback."""
        for rate in OUTPUT_RATES:
            for channels in OUTPUT_CHANNELS:
                try:
                    stream = sd.OutputStream(
                        samplerate=rate, channels=channels,
                        dtype="float32", device=device_id,
                    )
                    stream.start()
                    logger.info(f"Virtual mic output stream opened (device={device_id}, rate={rate}, ch={channels})")
                    return stream
                except Exception as e:
                    logger.debug(f"Failed opening virtual mic stream (device={device_id}, rate={rate}, ch={channels}): {e}")
                    continue
        return None

    def _try_open_output(self, device_id: Optional[int] = None) -> Optional[sd.OutputStream]:
        candidate_devices: list[Optional[int]] = []
        if device_id is not None and self._is_valid_output_device(device_id):
            candidate_devices.append(device_id)
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
            self._play_queue.put_nowait((None, 0, "both"))
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

    def _enqueue(self, raw: bytes, sample_rate: int, target: str = "both") -> None:
        try:
            self._play_queue.put_nowait((raw, sample_rate, target))
        except queue.Full:
            pass

    def _playback_loop(self) -> None:
        try:
            while self._running:
                try:
                    item = self._play_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if item[0] is None:
                    break
                if self._muted:
                    continue

                raw, sr = item[0], item[1]
                target = item[2] if len(item) > 2 else "both"

                try:
                    audio = np.frombuffer(raw, dtype=np.float32)
                except Exception:
                    continue
                if self._volume != 1.0:
                    audio = np.clip(audio * self._volume, -1.0, 1.0).astype(np.float32)

                streams_to_write = []
                if target == "speaker":
                    if self._speaker_stream is not None:
                        streams_to_write.append(self._speaker_stream)
                elif target == "virtual":
                    if self._virtual_stream is not None:
                        streams_to_write.append(self._virtual_stream)
                    if self._speaker_stream is not None:
                        streams_to_write.append(self._speaker_stream)
                else:  # "both"
                    for st in (self._speaker_stream, self._virtual_stream):
                        if st is not None:
                            streams_to_write.append(st)

                threads = []
                def write_to_stream(st, data):
                    try:
                        st.write(data)
                    except Exception as e:
                        logger.debug(f"Output write error: {e}")

                for stream in streams_to_write:
                    try:
                        out_audio = audio
                        if sr != stream.samplerate:
                            out_audio = resample(audio, sr, int(stream.samplerate))
                        if stream.channels > 1 and out_audio.ndim == 1:
                            out_audio = np.tile(out_audio[:, np.newaxis], (1, stream.channels))
                        elif stream.channels == 1 and out_audio.ndim == 2:
                            out_audio = out_audio[:, 0]
                        
                        t = threading.Thread(target=write_to_stream, args=(stream, out_audio.astype(np.float32)), daemon=True)
                        t.start()
                        threads.append(t)
                    except Exception as prep_err:
                        logger.error(f"Failed preparing stream write: {prep_err}")

                for t in threads:
                    t.join()
        except Exception as e:
            logger.error(f"Playback loop error: {e}")

    async def play(self, chunk: AudioChunk, target: str = "both") -> None:
        if self._delay_s > 0:
            await asyncio.sleep(self._delay_s)
        src = (getattr(chunk, "source", "") or "").lower()
        if src in ("panel_a", "mic"):
            target = "virtual"
        elif src in ("panel_b", "loopback", "computer_audio"):
            target = "speaker"
        self._enqueue(chunk.data, chunk.sample_rate, target=target)

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
