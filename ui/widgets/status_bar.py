from __future__ import annotations

import customtkinter as ctk
from ui.assets.styles import TEXT_MUTED, ACCENT_ORANGE, FONT_FAMILY, FONT_SIZE_SMALL


class StatusBar(ctk.CTkFrame):
    """Bottom status bar with latency meter, GPU info, and live status dot."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", height=24, **kwargs)

        self.lbl_status = ctk.CTkLabel(
            self,
            text="Ready",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_SMALL),
            text_color=TEXT_MUTED,
        )
        self.lbl_status.pack(side="left", padx=8)

        self.lbl_latency = ctk.CTkLabel(
            self,
            text="Latency: --",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_SMALL, weight="bold"),
            text_color=ACCENT_ORANGE,
        )
        self.lbl_latency.pack(side="right", padx=8)

    def set_status(self, text: str) -> None:
        self.lbl_status.configure(text=text)

    def set_latency(self, latency_ms: float) -> None:
        self.lbl_latency.configure(text=f"Latency: {latency_ms:.0f}ms")
