from __future__ import annotations

import customtkinter as ctk
from typing import Callable, Optional

from ui.assets.styles import (
    BG_CARD, BORDER_COLOR, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    ACCENT_ORANGE, ACCENT_ORANGE_HOVER, FONT_FAMILY, CORNER_RADIUS, CORNER_RADIUS_SMALL
)

LANGUAGES = [
    ("🇺🇸 English", "en"),
    ("🇨🇳 Chinese", "zh"),
    ("🇯🇵 Japanese", "ja"),
    ("🇰🇷 Korean", "ko"),
    ("🇩🇪 German", "de"),
    ("🇫🇷 French", "fr"),
    ("🇪🇸 Spanish", "es"),
    ("🇮🇹 Italian", "it"),
    ("🇷🇺 Russian", "ru"),
    ("🇿🇦 Afrikaans", "af"),
    ("🇸🇦 Arabic", "ar"),
    ("🇦🇿 Azeri", "az"),
    ("🇮🇳 Hindi", "hi"),
    ("🇮🇳 Kannada", "kn"),
]


class LanguageSelectorDialog(ctk.CTkToplevel):
    """Language & Translation Mode selector popup matching Transync AI reference screenshot."""

    def __init__(
        self,
        parent,
        source_lang: str = "EN",
        target_lang: str = "HI",
        mode: str = "two_way",
        on_change_callback: Optional[Callable] = None,
    ):
        super().__init__(parent)
        self.parent = parent
        self.source_lang = source_lang.lower()
        self.target_lang = target_lang.lower()
        self.mode = mode
        self.on_change_callback = on_change_callback

        self.title("Translation Mode")
        self.geometry("380x480")
        self.resizable(False, False)
        self.configure(fg_color=BG_CARD)

        self.transient(parent)

        self.selected_src = self.source_lang
        self.selected_tgt = self.target_lang
        self.selected_mode = mode

        self._build_ui()
        self.update_idletasks()

    def _build_ui(self) -> None:
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=16)

        # Title: Translation mode
        lbl_title = ctk.CTkLabel(
            main_frame,
            text="Translation mode",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        )
        lbl_title.pack(fill="x", pady=(0, 10))

        # Tab Switcher Container: One way | Two way | Multilingual
        tab_container = ctk.CTkFrame(
            main_frame,
            fg_color="#F3F4F6",
            height=36,
            corner_radius=10,
        )
        tab_container.pack(fill="x", pady=(0, 14))

        self.btn_one_way = ctk.CTkButton(
            tab_container,
            text="One way",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            fg_color="#FFFFFF" if self.selected_mode == "one_way" else "transparent",
            text_color=TEXT_PRIMARY,
            hover_color="#E5E7EB",
            height=28,
            corner_radius=8,
            command=lambda: self._set_mode("one_way"),
        )
        self.btn_one_way.pack(side="left", fill="both", expand=True, padx=4, pady=4)

        self.btn_two_way = ctk.CTkButton(
            tab_container,
            text="Two way",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            fg_color="#FFFFFF" if self.selected_mode == "two_way" else "transparent",
            text_color=TEXT_PRIMARY,
            hover_color="#E5E7EB",
            height=28,
            corner_radius=8,
            command=lambda: self._set_mode("two_way"),
        )
        self.btn_two_way.pack(side="left", fill="both", expand=True, padx=4, pady=4)

        self.btn_multi = ctk.CTkButton(
            tab_container,
            text="Multilingual",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            fg_color="#FFFFFF" if self.selected_mode == "multilingual" else "transparent",
            text_color=TEXT_PRIMARY,
            hover_color="#E5E7EB",
            height=28,
            corner_radius=8,
            command=lambda: self._set_mode("multilingual"),
        )
        self.btn_multi.pack(side="left", fill="both", expand=True, padx=4, pady=4)

        # Dual Column Header: Source | ⇄ | Target
        col_header = ctk.CTkFrame(main_frame, fg_color="transparent")
        col_header.pack(fill="x", pady=(0, 6))

        lbl_src_hdr = ctk.CTkLabel(
            col_header,
            text="Source",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
            width=140,
            anchor="w",
        )
        lbl_src_hdr.pack(side="left")

        btn_swap = ctk.CTkButton(
            col_header,
            text="⇄",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
            fg_color="transparent",
            hover_color="#F3F4F6",
            width=28,
            height=24,
            command=self._swap_languages,
        )
        btn_swap.pack(side="left", expand=True)

        lbl_tgt_hdr = ctk.CTkLabel(
            col_header,
            text="Target",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
            width=140,
            anchor="w",
        )
        lbl_tgt_hdr.pack(side="right")

        # Dual Scrollable Lists Area
        lists_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        lists_frame.pack(fill="both", expand=True, pady=(0, 14))
        lists_frame.grid_columnconfigure(0, weight=1)
        lists_frame.grid_columnconfigure(1, weight=1)
        lists_frame.grid_rowconfigure(0, weight=1)

        # Source Scroll List
        self.src_scroll = ctk.CTkScrollableFrame(lists_frame, fg_color="transparent")
        self.src_scroll.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        # Target Scroll List
        self.tgt_scroll = ctk.CTkScrollableFrame(lists_frame, fg_color="transparent")
        self.tgt_scroll.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        self._populate_language_lists()

        # Bottom Footer Bar: Model Pill Button on Left, Orange Confirm Button on Right
        footer = ctk.CTkFrame(main_frame, fg_color="transparent")
        footer.pack(fill="x")

        btn_model = ctk.CTkButton(
            footer,
            text="⚙ TalkSync AI  >",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            text_color=TEXT_PRIMARY,
            fg_color="#F3F4F6",
            hover_color="#E5E7EB",
            height=34,
            corner_radius=8,
        )
        btn_model.pack(side="left")

        btn_confirm = ctk.CTkButton(
            footer,
            text="Confirm",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            fg_color=ACCENT_ORANGE,
            hover_color=ACCENT_ORANGE_HOVER,
            text_color="#FFFFFF",
            width=84,
            height=34,
            corner_radius=8,
            command=self._confirm,
        )
        btn_confirm.pack(side="right")

    def _populate_language_lists(self) -> None:
        # Clear existing items
        for w in self.src_scroll.winfo_children():
            w.destroy()
        for w in self.tgt_scroll.winfo_children():
            w.destroy()

        # Populate Source List
        for name, code in LANGUAGES:
            is_sel = code == self.selected_src
            dot = "• " if is_sel else "  "
            btn = ctk.CTkButton(
                self.src_scroll,
                text=f"{dot}{name} {code}",
                font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold" if is_sel else "normal"),
                text_color=ACCENT_ORANGE if is_sel else TEXT_PRIMARY,
                fg_color="#FFF5F2" if is_sel else "transparent",
                hover_color="#F3F4F6",
                anchor="w",
                height=28,
                corner_radius=6,
                command=lambda c=code: self._select_source(c),
            )
            btn.pack(fill="x", pady=1)

        # Populate Target List
        for name, code in LANGUAGES:
            is_sel = code == self.selected_tgt
            dot = "• " if is_sel else "  "
            btn = ctk.CTkButton(
                self.tgt_scroll,
                text=f"{dot}{name} {code}",
                font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold" if is_sel else "normal"),
                text_color=ACCENT_ORANGE if is_sel else TEXT_PRIMARY,
                fg_color="#FFF5F2" if is_sel else "transparent",
                hover_color="#F3F4F6",
                anchor="w",
                height=28,
                corner_radius=6,
                command=lambda c=code: self._select_target(c),
            )
            btn.pack(fill="x", pady=1)

    def _select_source(self, code: str) -> None:
        self.selected_src = code
        self._populate_language_lists()

    def _select_target(self, code: str) -> None:
        self.selected_tgt = code
        self._populate_language_lists()

    def _swap_languages(self) -> None:
        self.selected_src, self.selected_tgt = self.selected_tgt, self.selected_src
        self._populate_language_lists()

    def _set_mode(self, mode: str) -> None:
        self.selected_mode = mode
        self.btn_one_way.configure(fg_color="#FFFFFF" if mode == "one_way" else "transparent")
        self.btn_two_way.configure(fg_color="#FFFFFF" if mode == "two_way" else "transparent")
        self.btn_multi.configure(fg_color="#FFFFFF" if mode == "multilingual" else "transparent")

    def _confirm(self) -> None:
        if self.on_change_callback:
            self.on_change_callback(
                self.selected_src.upper(),
                self.selected_tgt.upper(),
                self.selected_mode,
            )
        self.destroy()


# Backward compatibility aliases
TranslationModePopup = LanguageSelectorDialog
