from __future__ import annotations

import customtkinter as ctk
from typing import Any, Optional

from ui.assets.styles import (
    BG_CARD, BORDER_COLOR, TEXT_PRIMARY, TEXT_MUTED, TEXT_SECONDARY,
    ACCENT_ORANGE, ACCENT_GREEN, FONT_FAMILY
)


class DiagnosticsDialog(ctk.CTkToplevel):
    """Diagnostics and System Metrics Window with live GPU/VRAM/latency data."""

    def __init__(self, parent, settings=None, pipeline=None):
        super().__init__(parent)
        self.parent = parent
        self.settings = settings
        self._pipeline = pipeline
        self._monitor = None

        self.title("Metrics & System Diagnostics")
        self.geometry("420x440")
        self.resizable(False, False)
        self.configure(fg_color=BG_CARD)

        self.transient(parent)

        # Try to create a DiagnosticsMonitor
        try:
            from services.diagnostics.monitor import DiagnosticsMonitor
            self._monitor = DiagnosticsMonitor()
        except Exception:
            pass

        self._metric_labels: dict[str, ctk.CTkLabel] = {}
        self._build_ui()
        self._refresh()
        self.update_idletasks()

    def _build_ui(self) -> None:
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=16)

        # Header Row
        header = ctk.CTkFrame(main_frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 14))

        lbl_title = ctk.CTkLabel(
            header,
            text="📊 Metrics & Diagnostics",
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
            command=self._on_close,
        )
        btn_close.pack(side="right")

        # Metric rows
        self._metrics_frame = main_frame
        metric_keys = [
            ("GPU", "Detecting..."),
            ("VRAM Usage", "Detecting..."),
            ("CUDA Version", "Detecting..."),
            ("STT Model", self._get_stt_model()),
            ("Translation", self._get_translation_info()),
            ("TTS Engine", "Piper (EN) / Sarvam AI (HI)"),
            ("Sample Rate", "16,000 Hz / 24,000 Hz"),
            ("Pipeline Latency", "—"),
            ("Pipeline Status", "Idle"),
            ("Uptime", "0s"),
        ]

        for label, default_val in metric_keys:
            row = ctk.CTkFrame(main_frame, fg_color="transparent")
            row.pack(fill="x", pady=4)
            lbl = ctk.CTkLabel(
                row,
                text=label,
                font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                text_color=TEXT_PRIMARY,
            )
            lbl.pack(side="left")
            val_lbl = ctk.CTkLabel(
                row,
                text=default_val,
                font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                text_color=TEXT_SECONDARY,
            )
            val_lbl.pack(side="right")
            self._metric_labels[label] = val_lbl

        # Status indicator dot
        sep = ctk.CTkFrame(main_frame, height=1, fg_color=BORDER_COLOR)
        sep.pack(fill="x", pady=(12, 8))

        status_row = ctk.CTkFrame(main_frame, fg_color="transparent")
        status_row.pack(fill="x")

        self._status_dot = ctk.CTkLabel(
            status_row,
            text="●",
            font=ctk.CTkFont(size=12),
            text_color=ACCENT_GREEN,
        )
        self._status_dot.pack(side="left", padx=(0, 6))

        self._status_text = ctk.CTkLabel(
            status_row,
            text="System Ready",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=TEXT_SECONDARY,
        )
        self._status_text.pack(side="left")

    def _get_stt_model(self) -> str:
        if self.settings and hasattr(self.settings, "stt"):
            model = getattr(self.settings.stt, "model", "faster-whisper-small")
            compute = getattr(self.settings.stt, "compute_type", "float16")
            device = getattr(self.settings.stt, "device", "auto")
            return f"{model} ({device} {compute})"
        return "faster-whisper-small (CUDA fp16)"

    def _get_translation_info(self) -> str:
        if self.settings and hasattr(self.settings, "translation"):
            provider = getattr(self.settings.translation, "provider", "argos")
            fallback = getattr(self.settings.translation, "fallback_provider", "deepl")
            return f"{provider.title()} (primary) / {fallback.title()} (fallback)"
        return "Argos (primary) / DeepL (fallback)"

    def _refresh(self) -> None:
        """Refresh live metrics every 1 second."""
        try:
            if self._monitor:
                stats = self._monitor.collect()

                # GPU info
                gpu = stats.get("gpu", {})
                gpu_name = gpu.get("name", "N/A")
                self._metric_labels["GPU"].configure(text=gpu_name)

                cuda_ver = gpu.get("cuda_version", "N/A")
                self._metric_labels["CUDA Version"].configure(text=str(cuda_ver))

                # VRAM info
                vram = stats.get("vram", {})
                used = vram.get("used_mb", 0)
                total = vram.get("total_mb", 0)
                if total > 0:
                    pct = (used / total) * 100
                    self._metric_labels["VRAM Usage"].configure(
                        text=f"{used:.0f} / {total:.0f} MB ({pct:.0f}%)"
                    )

                # Uptime
                uptime_s = stats.get("uptime_s", 0)
                mins, secs = divmod(int(uptime_s), 60)
                hrs, mins = divmod(mins, 60)
                self._metric_labels["Uptime"].configure(text=f"{hrs}h {mins}m {secs}s")

            # Pipeline status
            if self._pipeline:
                is_running = getattr(self._pipeline, "running", False)
                self._metric_labels["Pipeline Status"].configure(
                    text="Running" if is_running else "Stopped"
                )
                self._status_dot.configure(text_color=ACCENT_GREEN if is_running else TEXT_MUTED)
                self._status_text.configure(text="Pipeline Active" if is_running else "Pipeline Idle")
        except Exception:
            pass

        # Schedule next refresh
        try:
            self.after(1000, self._refresh)
        except Exception:
            pass

    def _on_close(self) -> None:
        self.destroy()


# Backward compatibility alias
DiagnosticsWindow = DiagnosticsDialog
