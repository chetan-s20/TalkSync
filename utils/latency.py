"""Latency tracking utilities for TalkSync Pro."""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LatencyMeasurement:
    stage: str
    start: float
    end: float

    @property
    def duration_ms(self) -> float:
        return (self.end - self.start) * 1000.0


class LatencyTracker:
    def __init__(self, window_size: int = 50):
        self._lock = threading.Lock()
        self._measurements: list[LatencyMeasurement] = []
        self._window_size = window_size

    def record(self, stage: str, start: float, end: float) -> None:
        with self._lock:
            self._measurements.append(LatencyMeasurement(stage, start, end))
            if len(self._measurements) > self._window_size:
                self._measurements = self._measurements[-self._window_size :]

    def summary(self) -> dict[str, dict]:
        with self._lock:
            buckets: dict[str, list[float]] = defaultdict(list)
            for m in self._measurements:
                buckets[m.stage].append(m.duration_ms)
        result = {}
        for stage, durations in buckets.items():
            if not durations:
                continue
            sorted_d = sorted(durations)
            n = len(sorted_d)
            p50 = sorted_d[int(n * 0.50)]
            p95 = sorted_d[int(min(n * 0.95, n - 1))]
            p99 = sorted_d[int(min(n * 0.99, n - 1))]
            result[stage] = {
                "count": n,
                "avg_ms": sum(sorted_d) / n,
                "min_ms": sorted_d[0],
                "max_ms": sorted_d[-1],
                "p50_ms": p50,
                "p95_ms": p95,
                "p99_ms": p99,
            }
        return result

    def reset(self) -> None:
        with self._lock:
            self._measurements.clear()


_tracker: Optional[LatencyTracker] = None
_tracker_lock = threading.Lock()


def get_tracker() -> LatencyTracker:
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = LatencyTracker()
    return _tracker


def measure_latency(stage: str):
    import contextlib
    @contextlib.contextmanager
    def _cm():
        tracker = get_tracker()
        start = time.perf_counter()
        try:
            yield
        finally:
            end = time.perf_counter()
            tracker.record(stage, start, end)
    return _cm()


def get_latency_tracker() -> LatencyTracker:
    return get_tracker()


def get_all_latency_summaries() -> list[dict]:
    tracker = get_tracker()
    summary = tracker.summary()
    result = []
    for stage, data in summary.items():
        result.append({
            "name": stage,
            "avg_ms": data["avg_ms"],
            "p95_ms": data["p95_ms"],
            "count": data["count"],
        })
    return result


def reset_latency_trackers() -> None:
    get_tracker().reset()
