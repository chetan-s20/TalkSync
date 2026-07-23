from __future__ import annotations

import tkinter as tk
import customtkinter as ctk
from ui.assets.styles import ACCENT_ORANGE, BORDER_COLOR


class AudioLevelMeter(ctk.CTkFrame):
    """Horizontal dotted volume level meter."""

    def __init__(self, parent, num_dots: int = 12, dot_size: int = 3, bg_color: str = "#EFEFEF", **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.num_dots = num_dots
        self.dot_size = dot_size
        self._level = 0.0

        self.canvas = tk.Canvas(
            self,
            width=num_dots * 6,
            height=8,
            bg=bg_color,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(side="left", padx=2)
        self._redraw_meter()

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))
        self._redraw_meter()

    def _redraw_meter(self) -> None:
        self.canvas.delete("all")
        active_count = int(self._level * self.num_dots)
        for i in range(self.num_dots):
            x = i * 6 + 2
            y = 4
            color = ACCENT_ORANGE if i < active_count else "#D1D5DB"
            self.canvas.create_rectangle(
                x, y - 1, x + 2, y + 2, fill=color, outline=""
            )
