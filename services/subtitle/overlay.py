from __future__ import annotations

from typing import Optional

import customtkinter as ctk

from utils.logger import get_logger

logger = get_logger("subtitles")


class SubtitleOverlay:
    def __init__(self, parent: ctk.CTk, settings=None):
        self._parent = parent
        self._window = ctk.CTkToplevel(parent)
        self._window.overrideredirect(True)
        self._window.attributes("-topmost", True)
        self._window.configure(fg_color="#1E293B")
        self._window.attributes("-alpha", 0.9)
        self._window.withdraw()  # Start hidden by default

        self._frame = ctk.CTkFrame(self._window, fg_color="#1E293B", corner_radius=8)
        self._frame.pack(fill="both", expand=True, padx=4, pady=4)

        self._original_label = ctk.CTkLabel(
            self._frame, text="", font=("Segoe UI", 14),
            text_color="#94A3B8", wraplength=560,
        )
        self._original_label.pack(padx=8, pady=(4, 0))

        self._translated_label = ctk.CTkLabel(
            self._frame, text="", font=("Segoe UI", 20, "bold"),
            text_color="#F8FAFC", wraplength=560,
        )
        self._translated_label.pack(padx=8, pady=(0, 4))

        self._make_draggable()

    def _make_draggable(self) -> None:
        self._drag_data = {"x": 0, "y": 0}

        def start_drag(event):
            self._drag_data["x"] = event.x_root - self._window.winfo_x()
            self._drag_data["y"] = event.y_root - self._window.winfo_y()

        def drag(event):
            x = event.x_root - self._drag_data["x"]
            y = event.y_root - self._drag_data["y"]
            self._window.geometry(f"+{x}+{y}")

        self._frame.bind("<Button-1>", start_drag)
        self._frame.bind("<B1-Motion>", drag)

    def update_text(self, original: str, translated: str, source_lang: str = "", target_lang: str = "", is_final: bool = True) -> None:
        try:
            self._original_label.configure(text=f"{source_lang}: {original}" if source_lang else original)
            self._translated_label.configure(text=f"{target_lang}: {translated}" if target_lang else translated)
        except Exception as e:
            logger.debug(f"Subtitle update error: {e}")

    def hide(self) -> None:
        self._window.withdraw()

    def show(self) -> None:
        try:
            sw = self._parent.winfo_screenwidth()
            sh = self._parent.winfo_screenheight()
            w, h = 700, 110
            x = (sw - w) // 2
            y = sh - h - 60  # 60px margin from bottom taskbar
            self._window.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            self._window.geometry("700x110+100+800")
        self._window.deiconify()
        self._window.attributes("-topmost", True)
        self._window.lift()

    @property
    def is_visible(self) -> bool:
        try:
            return self._window.winfo_viewable() != 0
        except Exception:
            return False

    def destroy(self) -> None:
        try:
            self._window.destroy()
        except Exception:
            pass
