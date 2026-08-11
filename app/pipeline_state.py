from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from collections import deque

SPEECH_FRAMES_TO_ACTIVATE = 1
SILENCE_FRAMES_TO_DEACTIVATE = 18
MIN_SPEECH_SAMPLES = 4000  # 250ms at 16kHz — balances latency & hallucination reduction


class SpeechTracker:
    def __init__(self, threshold: float = 0.6, pre_roll_chunks: int = 15):
        self._threshold = threshold
        self._speech_active = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._ring_buffer: deque[np.ndarray] = deque(maxlen=pre_roll_chunks)  # ~450ms pre-activation audio
        self._speech_body_frames: list[np.ndarray] = []

    def update(self, is_speech: bool, frame: Optional[np.ndarray] = None) -> bool:
        if frame is not None:
            self._ring_buffer.append(frame)

        if is_speech:
            self._speech_frames += 1
            self._silence_frames = 0
            if frame is not None:
                self._speech_body_frames.append(frame)
            if not self._speech_active and self._speech_frames >= SPEECH_FRAMES_TO_ACTIVATE:
                self._speech_active = True
        else:
            self._silence_frames += 1
            self._speech_frames = 0
            if self._speech_active:
                if frame is not None:
                    self._speech_body_frames.append(frame)
                if self._silence_frames >= SILENCE_FRAMES_TO_DEACTIVATE:
                    self._speech_active = False
            else:
                self._speech_body_frames.clear()

        return self._speech_active

    def get_and_clear_pending_frames(self) -> list[np.ndarray]:
        # Prepend the pre-roll ring buffer (~450ms preceding speech activation) + initial speech frames
        pre_roll = list(self._ring_buffer)
        body = list(self._speech_body_frames)
        self._speech_body_frames.clear()
        self._ring_buffer.clear()
        
        frames = pre_roll + [f for f in body if not any(np.array_equal(f, pr) for pr in pre_roll)]
        return frames

    @property
    def speech_active(self) -> bool:
        return self._speech_active

    @property
    def just_activated(self) -> bool:
        return self._speech_active and self._speech_frames == SPEECH_FRAMES_TO_ACTIVATE

    @property
    def just_deactivated(self) -> bool:
        return not self._speech_active and self._silence_frames == SILENCE_FRAMES_TO_DEACTIVATE

    def reset(self) -> None:
        self._speech_active = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._ring_buffer.clear()
        self._speech_body_frames.clear()


@dataclass
class SttJob:
    source: str
    audio: bytes
    sample_rate: int
    is_final: bool
    last_final_text: str = ""
    last_partial_text: str = ""
    accumulated_text: str = ""


class PerSourceAudioBuffer:
    def __init__(self, source: str = "mic", sample_rate: int = 16000, max_duration_s: float = 10.0, max_samples: Optional[int] = None):
        self.source = source
        self.sample_rate = sample_rate
        self.max_samples = max_samples if max_samples is not None else int(max_duration_s * sample_rate)
        self._segments: list[np.ndarray] = []
        self._total_samples = 0
        self._partial_offset = 0
        self._accumulated_text = ""
        self._last_final_text = ""
        self._last_partial_text = ""
        self._last_feed_time = 0.0

    def get_audio_and_clear(self) -> np.ndarray:
        if not self._segments:
            return np.array([], dtype=np.float32)
        full = np.concatenate(self._segments)
        self.clear()
        return full

    def append(self, audio: np.ndarray) -> None:
        self._segments.append(audio)
        self._total_samples += audio.size

    @property
    def total_samples(self) -> int:
        return self._total_samples

    @property
    def is_full(self) -> bool:
        return self._total_samples >= self.max_samples

    @property
    def has_minimum(self) -> bool:
        return self._total_samples >= MIN_SPEECH_SAMPLES

    @property
    def last_feed_time(self) -> float:
        return self._last_feed_time

    @last_feed_time.setter
    def last_feed_time(self, value: float) -> None:
        self._last_feed_time = value

    @property
    def accumulated_text(self) -> str:
        return self._accumulated_text

    def finalize(self, partial: bool = False) -> Optional[SttJob]:
        if not self._segments or self._total_samples < MIN_SPEECH_SAMPLES:
            if partial:
                return None
            self.clear()
            return None

        full = np.concatenate(self._segments).tobytes()
        if partial:
            if self._partial_offset >= self._total_samples:
                return None
            new_audio = np.concatenate(self._segments)[self._partial_offset:]
            if len(new_audio) < MIN_SPEECH_SAMPLES:
                return None
            self._partial_offset = self._total_samples
            job = SttJob(
                source=self.source,
                audio=full,
                sample_rate=self.sample_rate,
                is_final=False,
                last_final_text=self._last_final_text,
                last_partial_text=self._last_partial_text,
                accumulated_text=self._accumulated_text,
            )
            return job

        job = SttJob(
            source=self.source,
            audio=full,
            sample_rate=self.sample_rate,
            is_final=True,
            last_final_text=self._last_final_text,
        )
        self.clear()
        return job

    def clear(self) -> None:
        self._segments.clear()
        self._total_samples = 0
        self._partial_offset = 0
        self._accumulated_text = ""


class PipelineState:
    def __init__(self, sample_rate: int = 16000):
        self._buffers: dict[str, PerSourceAudioBuffer] = {}
        self._speech_trackers: dict[str, SpeechTracker] = {}
        self._sample_rate = sample_rate

    def get_buffer(self, source: str) -> PerSourceAudioBuffer:
        if source not in self._buffers:
            self._buffers[source] = PerSourceAudioBuffer(source, self._sample_rate)
        return self._buffers[source]

    def get_speech_tracker(self, source: str) -> SpeechTracker:
        if source not in self._speech_trackers:
            self._speech_trackers[source] = SpeechTracker()
        return self._speech_trackers[source]

    def reset(self) -> None:
        self._buffers.clear()
        self._speech_trackers.clear()
