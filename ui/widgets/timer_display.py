from __future__ import annotations

import time
from typing import Optional
import customtkinter as ctk

from ui.assets.styles import TEXT_PRIMARY, FONT_FAMILY, FONT_SIZE_MEDIUM


class TimerDisplay(ctk.CTkLabel):
    def __init__(self, parent, **kwargs):
        font_val = kwargs.pop("font", (FONT_FAMILY, FONT_SIZE_MEDIUM, "bold"))
        text_color_val = kwargs.pop("text_color", TEXT_PRIMARY)
        text_val = kwargs.pop("text", "00:00:00")
        super().__init__(
            parent,
            text=text_val,
            font=font_val,
            text_color=text_color_val,
            **kwargs,
        )
        self._start_time: Optional[float] = None
        self._running = False
        self._update()

    def start(self) -> None:
        self._start_time = time.time()
        self._running = True
        self._update()

    def stop(self) -> None:
        self._running = False

    def reset(self) -> None:
        self._start_time = None
        self._running = False
        self.configure(text="00:00:00")

    def _update(self) -> None:
        if self._running and self._start_time is not None:
            elapsed = time.time() - self._start_time
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            self.configure(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        try:
            self.after(1000, self._update)
        except Exception:
            pass
