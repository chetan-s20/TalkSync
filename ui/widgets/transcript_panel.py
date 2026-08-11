from __future__ import annotations

import customtkinter as ctk
from typing import Callable, Optional

from ui.assets.styles import (
    BG_CARD, BORDER_COLOR, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    ACCENT_ORANGE, FONT_FAMILY, FONT_SIZE_NORMAL, FONT_SIZE_MEDIUM,
    CORNER_RADIUS, BADGE_VOICE, BADGE_TEXT, ACCENT_PURPLE, ACCENT_BLUE
)


class TranscriptPanel(ctk.CTkFrame):
    """Side-by-side translation panel matching Transync AI reference screenshot."""

    def __init__(
        self,
        parent,
        title: str,
        lang_pair: str,
        model_name: str = "TalkSync AI",
        speaker_active: bool = False,
        mic_active: Optional[bool] = None,
        on_lang_click: Optional[Callable] = None,
        on_speaker_click: Optional[Callable] = None,
        on_mic_click: Optional[Callable] = None,
        on_options_click: Optional[Callable] = None,
        **kwargs,
    ):
        super().__init__(
            parent,
            fg_color=BG_CARD,
            border_color=BORDER_COLOR,
            border_width=1,
            corner_radius=CORNER_RADIUS,
            **kwargs,
        )

        self.on_lang_click = on_lang_click
        self.on_speaker_click = on_speaker_click
        self.on_mic_click = on_mic_click
        self.on_options_click = on_options_click

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Top Header Bar inside Card
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        header.grid_columnconfigure(1, weight=1)

        # Left Pill Button: e.g. "en → zh  >"
        self.lang_btn = ctk.CTkButton(
            header,
            text=f"{lang_pair}  >",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
            fg_color="#F3F4F6",
            hover_color="#E5E7EB",
            height=30,
            corner_radius=8,
            command=self._on_lang_btn_click,
        )
        self.lang_btn.pack(side="left")

        # Right Action Buttons: Mic (if enabled), Speaker 🔊 & More Options •••
        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.pack(side="right")

        self._mic_active = mic_active
        if self._mic_active is not None:
            mic_color = ACCENT_ORANGE if self._mic_active else "#EF4444"
            self.mic_btn = ctk.CTkButton(
                actions,
                text="🎙️",
                font=ctk.CTkFont(size=14),
                text_color=mic_color,
                fg_color="transparent",
                hover_color="#F3F4F6",
                width=30,
                height=30,
                corner_radius=15,
                command=self._on_mic_btn_click,
            )
            self.mic_btn.pack(side="left", padx=2)

        self._speaker_active = speaker_active
        spk_color = ACCENT_ORANGE if self._speaker_active else "#6B7280"
        self.speaker_btn = ctk.CTkButton(
            actions,
            text="🔊",
            font=ctk.CTkFont(size=14),
            text_color=spk_color,
            fg_color="transparent",
            hover_color="#F3F4F6",
            width=30,
            height=30,
            corner_radius=15,
            command=self._on_speaker_btn_click,
        )
        self.speaker_btn.pack(side="left", padx=2)

        self.options_btn = ctk.CTkButton(
            actions,
            text="•••",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_SECONDARY,
            fg_color="transparent",
            hover_color="#F3F4F6",
            width=30,
            height=30,
            corner_radius=15,
            command=self._on_options_btn_click,
        )
        self.options_btn.pack(side="left", padx=2)

        # Subtitle Lines:
        # Line 1: Source Language / Target Language
        # Line 2: Current Model: TalkSync AI
        meta_frame = ctk.CTkFrame(self, fg_color="transparent")
        meta_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))

        lbl_sub1 = ctk.CTkLabel(
            meta_frame,
            text="Source Language / Target Language",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15),
            text_color="#94A3B8",
            anchor="w",
        )
        lbl_sub1.pack(fill="x")

        self.lbl_model = ctk.CTkLabel(
            meta_frame,
            text=f"Current Model: {model_name}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15),
            text_color="#94A3B8",
            anchor="w",
        )
        self.lbl_model.pack(fill="x")

        # Scrollable Transcript Textbox
        self.textbox = ctk.CTkTextbox(
            self,
            fg_color="transparent",
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            wrap="word",
            border_width=0,
        )
        self.textbox.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 14))

        # Tag configuration for styled timestamps and badges
        self._setup_tags()

    def _setup_tags(self) -> None:
        raw_text = self.textbox._textbox
        raw_text.tag_config("timestamp", foreground="#94A3B8", font=(FONT_FAMILY, 10))
        raw_text.tag_config("badge_mic", foreground=ACCENT_ORANGE, font=(FONT_FAMILY, 10, "bold"))
        raw_text.tag_config("badge_loopback", foreground=ACCENT_PURPLE, font=(FONT_FAMILY, 10, "bold"))
        raw_text.tag_config("badge_text", foreground=ACCENT_BLUE, font=(FONT_FAMILY, 10, "bold"))
        raw_text.tag_config("streaming", foreground="#64748B", font=(FONT_FAMILY, 11, "italic"))
        raw_text.tag_config("original", foreground="#475569", font=(FONT_FAMILY, 12))
        raw_text.tag_config("translated", foreground=TEXT_PRIMARY, font=(FONT_FAMILY, 13, "bold"))

    def update_lang_pair(self, lang_pair: str) -> None:
        self.lang_btn.configure(text=f"{lang_pair}  >")

    def update_model(self, model_name: str) -> None:
        self.lbl_model.configure(text=f"Current Model: {model_name}")

    def update_streaming_text(self, original: str, translated: str = "") -> None:
        raw_text = self.textbox._textbox
        if raw_text.tag_ranges("streaming"):
            raw_text.delete("streaming.first", "streaming.last")

        parts = []
        if original and original.strip():
            parts.append(original.strip())
        if translated and translated.strip():
            parts.append(translated.strip())

        if parts:
            display_text = " → ".join(parts)
            raw_text.insert("end", f"⚡ {display_text}\n", "streaming")
            self.textbox.see("end")

    def append_message(self, original: str, translated: str, input_source: str = "VOICE", timestamp: str = "") -> None:
        raw_text = self.textbox._textbox

        if raw_text.tag_ranges("streaming"):
            raw_text.delete("streaming.first", "streaming.last")

        if not timestamp:
            from datetime import datetime
            timestamp = datetime.now().strftime("%H:%M:%S")

        src_str = str(input_source).upper()
        if src_str in ("VOICE", "MIC"):
            badge_str = "[MIC]"
            badge_tag = "badge_mic"
        elif src_str in ("LOOPBACK", "COMPUTER_AUDIO"):
            badge_str = "[LOOPBACK]"
            badge_tag = "badge_loopback"
        elif src_str == "TEXT":
            badge_str = "[TEXT]"
            badge_tag = "badge_text"
        else:
            badge_str = f"[{src_str}]"
            badge_tag = "timestamp"

        raw_text.insert("end", f"{timestamp} ", "timestamp")
        raw_text.insert("end", f"{badge_str}\n", badge_tag)
        if original:
            raw_text.insert("end", f"{original}\n\n", "original")
        if translated:
            raw_text.insert("end", f"{translated}\n\n", "translated")
        self.textbox.see("end")

    def clear(self) -> None:
        self.textbox.delete("1.0", "end")

    def _on_lang_btn_click(self) -> None:
        if self.on_lang_click:
            self.on_lang_click()

    def toggle_speaker(self) -> None:
        self._speaker_active = not self._speaker_active
        color = ACCENT_ORANGE if self._speaker_active else "#6B7280"
        self.speaker_btn.configure(text_color=color)
        return self._speaker_active

    def set_speaker(self, active: bool) -> None:
        self._speaker_active = active
        color = ACCENT_ORANGE if self._speaker_active else "#6B7280"
        self.speaker_btn.configure(text_color=color)

    @property
    def speaker_active(self) -> bool:
        return self._speaker_active

    def _on_speaker_btn_click(self) -> None:
        active = self.toggle_speaker()
        if self.on_speaker_click:
            self.on_speaker_click(active)

    def toggle_mic(self) -> bool:
        if self._mic_active is None:
            return False
        self._mic_active = not self._mic_active
        color = ACCENT_ORANGE if self._mic_active else "#EF4444"
        self.mic_btn.configure(text_color=color)
        return self._mic_active

    def set_mic(self, active: bool) -> None:
        if self._mic_active is None:
            return
        self._mic_active = active
        color = ACCENT_ORANGE if self._mic_active else "#EF4444"
        self.mic_btn.configure(text_color=color)

    @property
    def mic_active(self) -> bool:
        return bool(self._mic_active)

    def _on_mic_btn_click(self) -> None:
        active = self.toggle_mic()
        if self.on_mic_click:
            self.on_mic_click(active)

    def _on_options_btn_click(self) -> None:
        if self.on_options_click:
            self.on_options_click()
