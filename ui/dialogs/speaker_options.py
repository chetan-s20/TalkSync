from __future__ import annotations

import customtkinter as ctk
from typing import Callable, Optional

from ui.assets.styles import (
    BG_CARD, BORDER_COLOR, TEXT_PRIMARY, TEXT_MUTED,
    ACCENT_ORANGE, ACCENT_ORANGE_HOVER, FONT_FAMILY, CORNER_RADIUS
)


class SpeakerOptionsDialog(ctk.CTkToplevel):
    """Speaker Options Popup with Volume dial, Voice Selection, and Playback Delay slider."""

    def __init__(self, parent, settings=None, on_update_callback: Optional[Callable] = None):
        super().__init__(parent)
        self.parent = parent
        self.settings = settings
        self.on_update_callback = on_update_callback

        self.title("Speaker Options")
        self.geometry("360x420")
        self.resizable(False, False)
        self.configure(fg_color=BG_CARD)

        self.transient(parent)

        # Read initial values from settings
        self._volume = getattr(settings.audio, "volume", 1.0) if settings and hasattr(settings, "audio") else 1.0
        self._delay = getattr(settings.audio, "playback_delay_s", 0.0) if settings and hasattr(settings, "audio") else 0.0
        self._voice = getattr(settings.tts, "voice", "en_US-lessac-medium") if settings and hasattr(settings, "tts") else "en_US-lessac-medium"
        self._playback_enabled = getattr(settings.audio, "tts_playback_enabled", True) if settings and hasattr(settings, "audio") else True

        self._build_ui()
        self.update_idletasks()
        try:
            import pywinstyles
            pywinstyles.apply_style(self, "mica")
        except Exception:
            pass

    def _build_ui(self) -> None:
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=16)

        # Header Row
        header = ctk.CTkFrame(main_frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 14))

        lbl_title = ctk.CTkLabel(
            header,
            text="Speaker Options",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        lbl_title.pack(side="left")

        btn_close = ctk.CTkButton(
            header,
            text="✕",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TEXT_MUTED,
            fg_color="transparent",
            hover_color="#F3F4F6",
            width=26,
            height=26,
            corner_radius=13,
            command=self.destroy,
        )
        btn_close.pack(side="right")

        # Start Playback toggle button
        self.active_btn = ctk.CTkButton(
            main_frame,
            text="• Activated" if self._playback_enabled else "• Deactivated",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=ACCENT_ORANGE if self._playback_enabled else TEXT_MUTED,
            fg_color="#FFFFFF",
            hover_color="#FFF5F2",
            border_color=ACCENT_ORANGE if self._playback_enabled else BORDER_COLOR,
            border_width=1,
            height=30,
            corner_radius=6,
            command=self._toggle_active,
        )
        self.active_btn.pack(fill="x", pady=(0, 16))

        # Select Voice OptionMenu
        lbl_voice = ctk.CTkLabel(
            main_frame,
            text="Select Voice:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        )
        lbl_voice.pack(fill="x", pady=(0, 4))

        voice_options = ["en_US-lessac-medium", "en_US-amy-medium", "en_US-ryan-medium", "Hindi Sarvam Shubh"]
        self.voice_menu = ctk.CTkOptionMenu(
            main_frame,
            values=voice_options,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            fg_color="#F3F4F6",
            text_color=TEXT_PRIMARY,
            button_color="#E5E7EB",
            button_hover_color="#D1D5DB",
            command=self._on_voice_changed,
        )
        if self._voice in voice_options:
            self.voice_menu.set(self._voice)
        self.voice_menu.pack(fill="x", pady=(0, 16))

        # Volume Slider
        vol_header = ctk.CTkFrame(main_frame, fg_color="transparent")
        vol_header.pack(fill="x", pady=(0, 4))

        lbl_vol = ctk.CTkLabel(
            vol_header,
            text="Volume:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        )
        lbl_vol.pack(side="left")

        self.lbl_vol_val = ctk.CTkLabel(
            vol_header,
            text=f"{int(self._volume * 100)}%",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=TEXT_MUTED,
        )
        self.lbl_vol_val.pack(side="right")

        self.slider_vol = ctk.CTkSlider(
            main_frame,
            from_=0,
            to=100,
            number_of_steps=100,
            button_color=ACCENT_ORANGE,
            button_hover_color="#E54D1F",
            progress_color=ACCENT_ORANGE,
            command=self._on_volume_changed,
        )
        self.slider_vol.pack(fill="x", pady=(0, 16))
        self.slider_vol.set(int(self._volume * 100))

        # Playback Delay Slider
        delay_header = ctk.CTkFrame(main_frame, fg_color="transparent")
        delay_header.pack(fill="x", pady=(0, 4))

        lbl_delay = ctk.CTkLabel(
            delay_header,
            text="Playback Delay:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        )
        lbl_delay.pack(side="left")

        self.lbl_delay_val = ctk.CTkLabel(
            delay_header,
            text=f"{self._delay:.1f}s",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=TEXT_MUTED,
        )
        self.lbl_delay_val.pack(side="right")

        self.slider_delay = ctk.CTkSlider(
            main_frame,
            from_=0,
            to=5,
            number_of_steps=50,
            button_color=ACCENT_ORANGE,
            button_hover_color="#E54D1F",
            progress_color=ACCENT_ORANGE,
            command=self._on_delay_changed,
        )
        self.slider_delay.pack(fill="x", pady=(0, 4))
        self.slider_delay.set(self._delay)

    def _toggle_active(self) -> None:
        self._playback_enabled = not self._playback_enabled
        if self._playback_enabled:
            self.active_btn.configure(text="• Activated", text_color=ACCENT_ORANGE, border_color=ACCENT_ORANGE)
        else:
            self.active_btn.configure(text="• Deactivated", text_color=TEXT_MUTED, border_color=BORDER_COLOR)
        self._notify()

    def _on_voice_changed(self, value: str) -> None:
        self._voice = value
        self._notify()

    def _on_volume_changed(self, value: float) -> None:
        self._volume = value / 100.0
        self.lbl_vol_val.configure(text=f"{int(value)}%")
        self._notify()

    def _on_delay_changed(self, value: float) -> None:
        self._delay = value
        self.lbl_delay_val.configure(text=f"{value:.1f}s")
        self._notify()

    def _notify(self) -> None:
        """Push all current values back to settings and callback."""
        if self.settings:
            if hasattr(self.settings, "audio"):
                self.settings.audio.volume = self._volume
                self.settings.audio.playback_delay_s = self._delay
                self.settings.audio.tts_playback_enabled = self._playback_enabled
            if hasattr(self.settings, "tts"):
                self.settings.tts.voice = self._voice

        if self.on_update_callback:
            self.on_update_callback(self._volume, self._delay, self._voice, self._playback_enabled)


# Backward compatibility alias
SpeakerOptionsPopup = SpeakerOptionsDialog
