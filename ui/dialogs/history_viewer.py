from __future__ import annotations

import customtkinter as ctk
from typing import Callable, Optional
from services.history.database import get_database
from ui.assets.styles import (
    BG_CARD, BG_PRIMARY, BG_SIDEBAR, BORDER_COLOR, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    ACCENT_ORANGE, FONT_FAMILY, FONT_SIZE_SMALL, CORNER_RADIUS, CORNER_RADIUS_SMALL
)


class HistoryViewerDialog(ctk.CTkToplevel):
    """History Dashboard matching Transync AI reference screenshots 3 & 4."""

    def __init__(self, parent, db_path: str = "talksync.db", on_close_callback: Optional[Callable] = None):
        super().__init__(parent)
        self.parent = parent
        self.db = get_database(db_path)
        self.on_close_callback = on_close_callback

        self.title("Transync AI - History Dashboard")
        self.geometry("1100x700")
        self.configure(fg_color=BG_PRIMARY)

        self.transient(parent)

        self.selected_session_id: Optional[int] = None
        self._build_ui()
        self._load_session_list()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=240)  # Left Sidebar
        self.grid_columnconfigure(1, weight=1)               # Center Log Viewer
        self.grid_columnconfigure(2, weight=1)               # Right AI Summary
        self.grid_rowconfigure(1, weight=1)                  # Content Row

        # Top Header Bar (Row 0)
        header = ctk.CTkFrame(self, fg_color="transparent", height=44)
        header.grid(row=0, column=0, columnspan=3, sticky="ew", padx=16, pady=(8, 8))

        lbl_logo = ctk.CTkLabel(
            header,
            text="Transync AI",
            font=ctk.CTkFont(family=FONT_FAMILY, size=18, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        lbl_logo.pack(side="left", padx=4)

        btn_close = ctk.CTkButton(
            header,
            text="✕",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
            fg_color="transparent",
            hover_color="#E5E7EB",
            width=32,
            height=32,
            corner_radius=16,
            command=self.destroy,
        )
        btn_close.pack(side="right")

        # 1. LEFT SIDEBAR: Search & Record List
        sidebar = ctk.CTkFrame(self, fg_color="transparent", width=240)
        sidebar.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=(0, 16))
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(3, weight=1)

        # Search bar
        search_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        search_frame.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        self.search_entry = ctk.CTkEntry(
            search_frame,
            placeholder_text="🔍 Search",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            fg_color=BG_CARD,
            border_color=BORDER_COLOR,
            border_width=1,
            corner_radius=8,
            height=32,
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_check = ctk.CTkButton(
            search_frame,
            text="✓",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=BG_CARD,
            text_color=TEXT_PRIMARY,
            hover_color="#E5E7EB",
            border_color=BORDER_COLOR,
            border_width=1,
            width=32,
            height=32,
            corner_radius=8,
        )
        btn_check.pack(side="right")

        # Folder section header
        folder_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        folder_frame.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        lbl_folder = ctk.CTkLabel(
            folder_frame, text="📁 Folder", font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"), text_color=TEXT_PRIMARY
        )
        lbl_folder.pack(side="left")
        btn_add_folder = ctk.CTkButton(
            folder_frame, text="+", font=ctk.CTkFont(size=14), fg_color="transparent", text_color=TEXT_MUTED, width=20, height=20
        )
        btn_add_folder.pack(side="right")

        # Starred section header
        lbl_starred = ctk.CTkLabel(
            sidebar, text="> ⭐ Starred", font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"), text_color=TEXT_PRIMARY, anchor="w"
        )
        lbl_starred.grid(row=2, column=0, sticky="w", pady=(4, 8))

        # Record List
        self.record_scroll = ctk.CTkScrollableFrame(sidebar, fg_color="transparent")
        self.record_scroll.grid(row=3, column=0, sticky="nsew")

        lbl_no_more = ctk.CTkLabel(sidebar, text="No more data", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=TEXT_MUTED)
        lbl_no_more.grid(row=4, column=0, pady=(8, 0))

        # 2. CENTER PANEL: Transcript Conversation Viewer
        center_card = ctk.CTkFrame(self, fg_color=BG_CARD, border_color=BORDER_COLOR, border_width=1, corner_radius=CORNER_RADIUS)
        center_card.grid(row=1, column=1, sticky="nsew", padx=8, pady=(0, 16))
        center_card.grid_rowconfigure(1, weight=1)
        center_card.grid_columnconfigure(0, weight=1)

        center_head = ctk.CTkFrame(center_card, fg_color="transparent")
        center_head.grid(row=0, column=0, sticky="ew", padx=16, pady=12)

        self.lbl_session_title = ctk.CTkLabel(
            center_head, text="Atmosphere Layers a... 0:00:34", font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"), text_color=TEXT_PRIMARY
        )
        self.lbl_session_title.pack(side="left")

        actions_right = ctk.CTkFrame(center_head, fg_color="transparent")
        actions_right.pack(side="right")

        btn_view_mode = ctk.CTkButton(
            actions_right, text="⁞≡ Original + Translation >", font=ctk.CTkFont(family=FONT_FAMILY, size=11), fg_color="#F3F4F6", text_color=TEXT_PRIMARY, height=28, corner_radius=6
        )
        btn_view_mode.pack(side="left", padx=4)

        btn_copy = ctk.CTkButton(
            actions_right, text="📋", font=ctk.CTkFont(size=12), fg_color="#F3F4F6", text_color=TEXT_PRIMARY, width=28, height=28, corner_radius=6
        )
        btn_copy.pack(side="left")

        self.log_textbox = ctk.CTkTextbox(
            center_card, fg_color="transparent", text_color=TEXT_PRIMARY, font=ctk.CTkFont(family=FONT_FAMILY, size=12), wrap="word", border_width=0
        )
        self.log_textbox.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))

        # 3. RIGHT PANEL: AI Auto Summary
        right_card = ctk.CTkFrame(self, fg_color=BG_CARD, border_color=BORDER_COLOR, border_width=1, corner_radius=CORNER_RADIUS)
        right_card.grid(row=1, column=2, sticky="nsew", padx=(8, 16), pady=(0, 16))
        right_card.grid_columnconfigure(0, weight=1)

        right_head = ctk.CTkFrame(right_card, fg_color="transparent")
        right_head.pack(fill="x", padx=16, pady=12)

        lbl_ai_head = ctk.CTkLabel(
            right_head, text="✨ AI Summary", font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"), text_color=TEXT_PRIMARY
        )
        lbl_ai_head.pack(side="left")

        btn_lang_summary = ctk.CTkButton(
            right_head, text="🇺🇸 English en >", font=ctk.CTkFont(family=FONT_FAMILY, size=11), fg_color="#F3F4F6", text_color=TEXT_PRIMARY, height=26, corner_radius=6
        )
        btn_lang_summary.pack(side="right")

        # Center Graphic & Start Summary Button
        summary_center = ctk.CTkFrame(right_card, fg_color="transparent")
        summary_center.pack(expand=True)

        lbl_sparkle = ctk.CTkLabel(summary_center, text="✨", font=ctk.CTkFont(size=36))
        lbl_sparkle.pack(pady=(0, 8))

        lbl_auto_title = ctk.CTkLabel(
            summary_center, text="AI Auto Summary", font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"), text_color=TEXT_PRIMARY
        )
        lbl_auto_title.pack(pady=(0, 16))

        btn_start_summary = ctk.CTkButton(
            summary_center,
            text="Start Summary",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            fg_color=ACCENT_ORANGE,
            hover_color="#E54D1F",
            height=36,
            corner_radius=8,
            command=self._generate_summary,
        )
        btn_start_summary.pack()

    def _load_session_list(self) -> None:
        for widget in self.record_scroll.winfo_children():
            widget.destroy()

        sessions = self.db.list_sessions()
        if not sessions:
            lbl_empty = ctk.CTkLabel(
                self.record_scroll,
                text="No sessions recorded yet.\nStart a session to see history here.",
                font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                text_color=TEXT_MUTED,
                justify="center",
            )
            lbl_empty.pack(expand=True, pady=20)
            return

        for s in sessions:
            sid = s["id"]
            name = s.get("name") or f"Session #{sid}"
            btn = ctk.CTkButton(
                self.record_scroll,
                text=f"{name}  •••",
                font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                fg_color="transparent",
                text_color=TEXT_PRIMARY,
                hover_color="#E5E7EB",
                anchor="w",
                height=32,
                corner_radius=6,
                command=lambda s_id=sid: self._select_session(s_id),
            )
            btn.pack(fill="x", pady=2)

        if sessions:
            self._select_session(sessions[0]["id"])

    def _select_session(self, session_id: int) -> None:
        self.selected_session_id = session_id
        records = self.db.get_session_segments(session_id)
        self.log_textbox.delete("1.0", "end")

        if not records:
            self.log_textbox.insert("end", "No transcript data for this session.\n", "timestamp")
        else:
            for r in records:
                ts = r.get("timestamp", "00:00")
                orig = r.get("original_text", "")
                trans = r.get("translated_text", "")
                self.log_textbox.insert("end", f"{ts}\n", "timestamp")
                if orig:
                    self.log_textbox.insert("end", f"{orig}\n", "orig")
                if trans:
                    self.log_textbox.insert("end", f"{trans}\n\n", "trans")

    def _generate_summary(self) -> None:
        """Generate an extractive summary from the current session transcript."""
        content = self.log_textbox.get("1.0", "end").strip()
        if not content or content == "No transcript data for this session.":
            self.log_textbox.insert("end", "\n[Summary] No transcript content to summarize.\n")
            return

        # Extract key sentences (simple extractive: take first sentence from each block)
        lines = [l.strip() for l in content.split("\n") if l.strip() and not l.strip().startswith("00:")]
        # Take up to 5 representative lines
        summary_lines = lines[:5] if len(lines) > 5 else lines
        summary = " | ".join(summary_lines)

        self.log_textbox.insert(
            "end",
            f"\n\n✨ [Auto Summary]\n{summary}\n",
            "timestamp",
        )


# Backward compatibility alias
HistoryScreen = HistoryViewerDialog

