from __future__ import annotations

import tkinter as tk
import customtkinter as ctk
from ui.assets.styles import ACCENT_ORANGE, BORDER_COLOR


class TimelineRuler(ctk.CTkFrame):
    """Timeline ruler widget with faint vertical tick marks and an orange center playhead."""

    def __init__(self, parent, width: int = 240, height: int = 20, **kwargs):
        super().__init__(parent, fg_color="transparent", width=width, height=height, **kwargs)
        self.canvas = tk.Canvas(
            self,
            width=width,
            height=height,
            bg="#EFEFEF",
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.bind("<Configure>", self._redraw_ruler)

    def _redraw_ruler(self, event=None):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1:
            w = 240
        if h <= 1:
            h = 20

        # Draw tick marks across ruler width
        spacing = 6
        center_x = w // 2
        for x in range(0, w, spacing):
            # Taller tick every 5th line
            idx = x // spacing
            tick_h = 10 if idx % 5 == 0 else 5
            y1 = h - tick_h
            y2 = h
            color = "#CBD5E1" if idx % 5 == 0 else "#E2E8F0"
            self.canvas.create_line(x, y1, x, y2, fill=color, width=1)

        # Draw red/orange playhead indicator line in the middle
        self.canvas.create_line(center_x, 0, center_x, h, fill=ACCENT_ORANGE, width=2)
