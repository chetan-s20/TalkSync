from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

SPEECH_FRAMES_TO_ACTIVATE = 2
SILENCE_FRAMES_TO_DEACTIVATE = 8
MIN_SPEECH_SAMPLES = 4000  # 250ms at 16kHz — balances latency & hallucination reduction


class SpeechTracker:
    def __init__(self, threshold: float = 0.6):
        self._threshold = threshold
        self._speech_active = False
        self._speech_frames = 0
        self._silence_frames = 0

    def update(self, is_speech: bool) -> bool:
        if is_speech:
            self._speech_frames += 1
            self._silence_frames = 0
            if not self._speech_active and self._speech_frames >= SPEECH_FRAMES_TO_ACTIVATE:
                self._speech_active = True
        else:
            self._silence_frames += 1
            self._speech_frames = 0
            if self._speech_active and self._silence_frames >= SILENCE_FRAMES_TO_DEACTIVATE:
                self._speech_active = False
        return self._speech_active

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
    def __init__(self, source: str, sample_rate: int = 16000, max_duration_s: float = 10.0):
        self.source = source
        self.sample_rate = sample_rate
        self.max_samples = int(max_duration_s * sample_rate)
        self._segments: list[np.ndarray] = []
        self._total_samples = 0
        self._partial_offset = 0
        self._accumulated_text = ""
        self._last_final_text = ""
        self._last_partial_text = ""
        self._last_feed_time = 0.0

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
