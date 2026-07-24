from __future__ import annotations

from typing import Optional

import customtkinter as ctk

from ui.assets.styles import (
    BG_CARD, BORDER_COLOR, TEXT_PRIMARY, TEXT_MUTED,
    ACCENT_ORANGE, FONT_FAMILY, FONT_SIZE_SMALL, CORNER_RADIUS,
)


class SessionSummaryDialog(ctk.CTkToplevel):
    """Post-session AI summary popup showing conversation blocks and a generated summary."""

    def __init__(self, parent, blocks: list[dict], title: str = "Conversation Summary"):
        super().__init__(parent)
        self.title(title)
        self.geometry("500x400")
        self.resizable(True, True)
        self.configure(fg_color=BG_CARD)
        self.transient(parent)

        self._build_ui(blocks)
        self.update_idletasks()
        try:
            import pywinstyles
            pywinstyles.apply_style(self, "mica")
        except Exception:
            pass

    def _build_ui(self, blocks: list[dict]) -> None:
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=16, pady=16)

        header = ctk.CTkFrame(main, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            header,
            text="Conversation Summary",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")

        ctk.CTkButton(
            header,
            text="✕",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=TEXT_MUTED,
            fg_color="transparent",
            hover_color="#F3F4F6",
            width=24, height=24,
            corner_radius=12,
            command=self.destroy,
        ).pack(side="right")

        # Summary section
        summary = self._generate_summary(blocks)
        summary_frame = ctk.CTkFrame(main, fg_color="#FFF5F2", border_color=ACCENT_ORANGE, border_width=1, corner_radius=CORNER_RADIUS)
        summary_frame.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            summary_frame,
            text="Summary",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=ACCENT_ORANGE,
            anchor="w",
        ).pack(fill="x", padx=12, pady=(8, 2))

        ctk.CTkLabel(
            summary_frame,
            text=summary,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=TEXT_PRIMARY,
            anchor="w",
            justify="left",
            wraplength=440,
        ).pack(fill="x", padx=12, pady=(2, 8))

        # Conversation log
        ctk.CTkLabel(
            main,
            text="Transcript",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", pady=(0, 4))

        textbox = ctk.CTkTextbox(
            main, fg_color="transparent",
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            wrap="word", border_width=0,
        )
        textbox.pack(fill="both", expand=True)

        for b in blocks:
            ts = b.get("ts", "")[:19] if b.get("ts") else ""
            orig = b.get("original", "")
            trans = b.get("translated", "")
            src = b.get("src", "")
            tgt = b.get("tgt", "")
            source = b.get("source", "VOICE")

            badge = "🖥" if source == "COMPUTER_AUDIO" else "🎤"
            textbox.insert("end", f"{badge} [{ts}] {src}→{tgt}\n")
            if orig:
                textbox.insert("end", f"  {orig}\n")
            if trans:
                textbox.insert("end", f"  → {trans}\n\n")

        textbox.configure(state="disabled")

    def _generate_summary(self, blocks: list[dict]) -> str:
        if not blocks:
            return "No conversation data recorded."

        lines = []
        for b in blocks:
            orig = b.get("original", "").strip()
            trans = b.get("translated", "").strip()
            if orig:
                lines.append(orig)
            if trans and trans != orig:
                lines.append(trans)

        if not lines:
            return "No conversation data recorded."

        unique = list(dict.fromkeys(lines))
        summary_lines = unique[:6]
        return " • " + "\n • ".join(summary_lines)
