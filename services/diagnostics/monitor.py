from __future__ import annotations

import time
from typing import Any, Optional

import torch

from utils.logger import get_logger

logger = get_logger("diagnostics")


class DiagnosticsMonitor:
    def __init__(self):
        self._start_time = time.time()
        self._stats: dict[str, Any] = {}

    def collect(self) -> dict[str, Any]:
        stats = {
            "uptime_s": time.time() - self._start_time,
            "gpu": self._get_gpu_info(),
            "vram": self._get_vram_info(),
            "latency": {},
            "queue_sizes": {},
            "vad_state": "idle",
        }
        self._stats = stats
        return stats

    def _get_gpu_info(self) -> dict:
        if not torch.cuda.is_available():
            return {"available": False, "name": "CPU"}
        try:
            props = torch.cuda.get_device_properties(0)
            return {
                "available": True,
                "name": props.name,
                "total_memory": props.total_memory,
                "cuda_version": torch.version.cuda,
            }
        except Exception as e:
            logger.debug(f"GPU info error: {e}")
            return {"available": True, "name": "Unknown", "error": str(e)}

    def _get_vram_info(self) -> dict:
        if not torch.cuda.is_available():
            return {"used_mb": 0, "total_mb": 0}
        try:
            total = torch.cuda.get_device_properties(0).total_memory
            free, used = 0, 0
            try:
                free = torch.cuda.mem_get_info(0)[0]
                used = total - free
            except Exception:
                pass
            return {
                "total_mb": total / 1024 / 1024,
                "used_mb": used / 1024 / 1024,
                "free_mb": free / 1024 / 1024,
            }
        except Exception as e:
            logger.debug(f"VRAM info error: {e}")
            return {"used_mb": 0, "total_mb": 0}

    def update_queue_sizes(self, queues: dict[str, int]) -> None:
        if "queue_sizes" not in self._stats:
            self._stats["queue_sizes"] = {}
        self._stats["queue_sizes"].update(queues)

    def update_vad_state(self, state: str) -> None:
        self._stats["vad_state"] = state
