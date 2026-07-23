from __future__ import annotations

import customtkinter as ctk
from typing import Callable, Optional

from ui.assets.styles import (
    BG_CARD, BORDER_COLOR, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    ACCENT_ORANGE, ACCENT_ORANGE_HOVER, FONT_FAMILY, FONT_SIZE_SMALL, CORNER_RADIUS
)


class AIAssistantDialog(ctk.CTkToplevel):
    """AI Assistant & Keywords dialog matching Transync AI reference screenshot 2."""

    def __init__(self, parent, settings=None, on_save_callback: Optional[Callable] = None):
        super().__init__(parent)
        self.parent = parent
        self.settings = settings
        self.on_save_callback = on_save_callback

        self.title("AI Assistant")
        self.geometry("520x660")
        self.resizable(False, False)
        self.configure(fg_color=BG_CARD)

        self.transient(parent)

        self._build_ui()
        self.update_idletasks()

    def _build_ui(self) -> None:
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=24, pady=20)

        # Header Row: Title & Close Button
        header = ctk.CTkFrame(main_frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 16))

        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.pack(side="left")

        lbl_icon = ctk.CTkLabel(title_frame, text="💡", font=ctk.CTkFont(size=18))
        lbl_icon.pack(side="left", padx=(0, 6))

        lbl_title = ctk.CTkLabel(
            title_frame,
            text="AI Assistant",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        lbl_title.pack(side="left")

        btn_close = ctk.CTkButton(
            header,
            text="✕",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
            fg_color="transparent",
            hover_color="#F3F4F6",
            width=28,
            height=28,
            corner_radius=14,
            command=self.destroy,
        )
        btn_close.pack(side="right")

        # Row 1: Knowledge base & Enabled pill
        kb_row = ctk.CTkFrame(main_frame, fg_color="transparent")
        kb_row.pack(fill="x", pady=(0, 14))

        lbl_kb = ctk.CTkLabel(
            kb_row,
            text="Knowledge base:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        lbl_kb.pack(side="left")

        ai_enabled = getattr(self.settings, "ai_assistant_enabled", True) if self.settings else True
        self._kb_enabled = ai_enabled
        self.enabled_btn = ctk.CTkButton(
            kb_row,
            text="• Enabled" if ai_enabled else "• Disabled",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            text_color=ACCENT_ORANGE if ai_enabled else TEXT_MUTED,
            fg_color="#FFFFFF",
            hover_color="#FFF5F2",
            border_color=ACCENT_ORANGE if ai_enabled else BORDER_COLOR,
            border_width=1,
            height=26,
            corner_radius=6,
            command=self._toggle_enabled,
        )
        self.enabled_btn.pack(side="right")

        # Row 2: Keywords Prompt & Description
        lbl_kw_title = ctk.CTkLabel(
            main_frame,
            text="Keywords: that may appear during translation, separated by commas or the Enter key. Connect the original text and the target translation with an equal sign.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=TEXT_PRIMARY,
            justify="left",
            wraplength=460,
            anchor="w",
        )
        lbl_kw_title.pack(anchor="w", pady=(0, 8))

        # Examples tags: examples: [ Telemedicine ] [ Biopsy = 活检 ]
        ex_row = ctk.CTkFrame(main_frame, fg_color="transparent")
        ex_row.pack(anchor="w", pady=(0, 8))

        lbl_ex = ctk.CTkLabel(
            ex_row,
            text="examples: ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=TEXT_MUTED,
        )
        lbl_ex.pack(side="left")

        tag1 = ctk.CTkLabel(
            ex_row,
            text="Telemedicine",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color="#F3F4F6",
            text_color=TEXT_SECONDARY,
            corner_radius=4,
            padx=6,
            pady=2,
        )
        tag1.pack(side="left", padx=2)

        tag2 = ctk.CTkLabel(
            ex_row,
            text="Biopsy = 活检",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color="#F3F4F6",
            text_color=TEXT_SECONDARY,
            corner_radius=4,
            padx=6,
            pady=2,
        )
        tag2.pack(side="left", padx=4)

        # Keywords Multi-line Textarea 1
        self.txt_keywords = ctk.CTkTextbox(
            main_frame,
            height=110,
            fg_color="#F9FAFB",
            border_color=BORDER_COLOR,
            border_width=1,
            corner_radius=8,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        self.txt_keywords.pack(fill="x", pady=(0, 4))

        # Pre-fill from settings
        kw_text = getattr(self.settings, "keywords", "") if self.settings else ""
        if kw_text:
            self.txt_keywords.insert("1.0", kw_text)

        self.lbl_count1 = ctk.CTkLabel(
            main_frame,
            text=f"{len(kw_text)}/2000",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color=TEXT_MUTED,
        )
        self.lbl_count1.pack(anchor="e", pady=(0, 14))

        # Bind key events for live character count
        self.txt_keywords.bind("<KeyRelease>", self._update_counts)

        # Row 3: Context Prompt Section
        lbl_ctx_title = ctk.CTkLabel(
            main_frame,
            text="Context: What should TalkSync AI know about you?",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        )
        lbl_ctx_title.pack(anchor="w", pady=(0, 8))

        # Context Multi-line Textarea 2
        self.txt_context = ctk.CTkTextbox(
            main_frame,
            height=120,
            fg_color="#F9FAFB",
            border_color=BORDER_COLOR,
            border_width=1,
            corner_radius=8,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        self.txt_context.pack(fill="x", pady=(0, 4))

        # Pre-fill from settings
        ctx_text = getattr(self.settings, "context", "") if self.settings else ""
        if ctx_text:
            self.txt_context.insert("1.0", ctx_text)

        self.lbl_count2 = ctk.CTkLabel(
            main_frame,
            text=f"{len(ctx_text)}/800",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color=TEXT_MUTED,
        )
        self.lbl_count2.pack(anchor="e", pady=(0, 16))

        self.txt_context.bind("<KeyRelease>", self._update_counts)

        # Footer Row: Save Button + AI-marked models only
        footer_row = ctk.CTkFrame(main_frame, fg_color="transparent")
        footer_row.pack(fill="x")

        lbl_footer = ctk.CTkLabel(
            footer_row,
            text="AI-marked models only",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color=TEXT_MUTED,
        )
        lbl_footer.pack(side="left")

        btn_save = ctk.CTkButton(
            footer_row,
            text="Save",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            fg_color=ACCENT_ORANGE,
            hover_color=ACCENT_ORANGE_HOVER,
            text_color="#FFFFFF",
            width=80,
            height=32,
            corner_radius=8,
            command=self._save,
        )
        btn_save.pack(side="right")

    def _update_counts(self, event=None) -> None:
        kw_len = len(self.txt_keywords.get("1.0", "end").strip())
        ctx_len = len(self.txt_context.get("1.0", "end").strip())
        self.lbl_count1.configure(text=f"{kw_len}/2000")
        self.lbl_count2.configure(text=f"{ctx_len}/800")

    def _toggle_enabled(self) -> None:
        self._kb_enabled = not self._kb_enabled
        if self._kb_enabled:
            self.enabled_btn.configure(
                text="• Enabled",
                text_color=ACCENT_ORANGE,
                border_color=ACCENT_ORANGE,
            )
        else:
            self.enabled_btn.configure(
                text="• Disabled",
                text_color=TEXT_MUTED,
                border_color=BORDER_COLOR,
            )

    def _save(self) -> None:
        keywords = self.txt_keywords.get("1.0", "end").strip()
        context = self.txt_context.get("1.0", "end").strip()

        # Update settings directly
        if self.settings:
            self.settings.keywords = keywords
            self.settings.context = context
            self.settings.ai_assistant_enabled = self._kb_enabled

        # Call callback if provided
        if self.on_save_callback:
            self.on_save_callback(keywords, context, self._kb_enabled)

        self.destroy()
