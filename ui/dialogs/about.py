from __future__ import annotations

import customtkinter as ctk
from ui.assets.styles import BG_CARD, TEXT_PRIMARY, TEXT_MUTED, FONT_FAMILY


class AboutDialog(ctk.CTkToplevel):
    """About dialog for TalkSync AI."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("About TalkSync AI")
        self.geometry("320x220")
        self.resizable(False, False)
        self.configure(fg_color=BG_CARD)

        self.transient(parent)

        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        lbl_title = ctk.CTkLabel(
            main_frame,
            text="TalkSync AI",
            font=ctk.CTkFont(family=FONT_FAMILY, size=18, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        lbl_title.pack(pady=(0, 4))

        lbl_ver = ctk.CTkLabel(
            main_frame,
            text="Version 2.5.0 Pro",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=TEXT_MUTED,
        )
        lbl_ver.pack(pady=(0, 12))

        lbl_desc = ctk.CTkLabel(
            main_frame,
            text="Real-Time Speech & Text Translation Platform\nPowered by faster-whisper, Argos & Sarvam AI.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=TEXT_PRIMARY,
            justify="center",
        )
        lbl_desc.pack(pady=(0, 16))

        btn_ok = ctk.CTkButton(
            main_frame,
            text="OK",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            fg_color="#F3F4F6",
            text_color=TEXT_PRIMARY,
            hover_color="#E5E7EB",
            height=30,
            command=self.destroy,
        )
        btn_ok.pack()
