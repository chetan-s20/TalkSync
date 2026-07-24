from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime
from typing import Optional

import customtkinter as ctk

from app.pipeline import Pipeline
from config.settings import Settings
from services.subtitle.overlay import SubtitleOverlay
from ui.assets.styles import (
    ACCENT_ORANGE, ACCENT_ORANGE_HOVER, ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED,
    BG_CARD, BG_PRIMARY, BG_SECONDARY, BORDER_COLOR,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_LIGHT, TEXT_MUTED,
    CORNER_RADIUS, FONT_FAMILY, FONT_SIZE_SMALL, FONT_SIZE_NORMAL, FONT_SIZE_MEDIUM
)
from ui.dialogs.audio_settings import AudioSettingsPopup
from ui.dialogs.language_selector import LanguageSelectorDialog
from ui.dialogs.history_viewer import HistoryViewerDialog
from ui.dialogs.diagnostics import DiagnosticsDialog
from ui.dialogs.speaker_options import SpeakerOptionsDialog
from ui.dialogs.about import AboutDialog
from ui.dialogs.ai_assistant import AIAssistantDialog
from ui.dialogs.session_summary import SessionSummaryDialog
from ui.widgets.transcript_panel import TranscriptPanel
from ui.widgets.timer_display import TimerDisplay
from ui.widgets.timeline_ruler import TimelineRuler
from ui.widgets.audio_level import AudioLevelMeter
from ui.widgets.status_bar import StatusBar
from utils.logger import get_logger

logger = get_logger("ui")


class MainWindow(ctk.CTk):
    """TalkSync AI Main Window implementation matching reference screenshots."""

    def __init__(self, pipeline: Pipeline, settings: Settings):
        super().__init__()

        self.pipeline = pipeline
        self.settings = settings

        self.title("TalkSync AI")
        self.geometry(f"{settings.window_width}x{settings.window_height}")
        self.minsize(960, 640)
        self.configure(fg_color=BG_PRIMARY)

        # Wire pipeline callbacks
        self.pipeline.on_transcription = self._on_transcription
        self.pipeline.on_translation = self._on_translation
        self.pipeline.on_status = self._on_status
        self.pipeline.on_latency = self._on_latency
        if hasattr(self.pipeline, 'on_audio_level'):
            self.pipeline.on_audio_level = self._on_audio_level

        self._source_lang = settings.source_lang
        self._target_lang = settings.target_lang
        self._translation_mode = settings.translation_mode
        self._loopback_enabled = False
        self._text_mode = False
        self._vmic_enabled_prev = bool(settings.audio.virtual_mic_enabled) if (settings and hasattr(settings, "audio")) else False

        self.subtitle_overlay = SubtitleOverlay(self, settings.subtitles)

        self._build_ui()
        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Apply Windows 11 styling if pywinstyles is available
        try:
            import pywinstyles
            pywinstyles.apply_style(self, "mica")
        except Exception as e:
            logger.debug(f"pywinstyles application skipped: {e}")

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)  # Main Content Grid

        # 1. TOP HEADER TOOLBAR
        self._build_header()

        # 2. MAIN CONTENT GRID: Dual Side-by-Side Cards (Panel A & Panel B)
        self._build_main_content()

        # 3. TEXT INPUT PANEL (Bottom)
        self._build_text_input_panel()

        # 4. BOTTOM STATUS BAR
        self._build_status_bar()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(12, 10))

        # Left Section: Brand Logo, Audio Src Pill, Play Button
        left_frame = ctk.CTkFrame(header, fg_color="transparent")
        left_frame.pack(side="left")

        lbl_logo = ctk.CTkLabel(
            left_frame,
            text="TalkSync AI",
            font=ctk.CTkFont(family=FONT_FAMILY, size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        lbl_logo.pack(side="left", padx=(0, 16))

        # Audio Src Pill Container
        audio_src_container = ctk.CTkFrame(left_frame, fg_color="transparent")
        audio_src_container.pack(side="left", padx=(0, 12))

        btn_audio_src = ctk.CTkButton(
            audio_src_container,
            text="audio src  >",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
            fg_color="#FFFFFF",
            hover_color="#F3F4F6",
            border_color=BORDER_COLOR,
            border_width=1,
            height=32,
            corner_radius=8,
            command=self._show_audio_settings,
        )
        btn_audio_src.pack()

        # Dotted level meter below audio src
        self.top_meter = AudioLevelMeter(audio_src_container, num_dots=14)
        self.top_meter.pack(pady=(2, 0))
        self.top_meter.set_level(0.0)

        # Play / Record Start Button (White rounded square with green triangle)
        self.btn_play = ctk.CTkButton(
            left_frame,
            text="▶",
            font=ctk.CTkFont(size=14),
            text_color=ACCENT_GREEN,
            fg_color="#FFFFFF",
            hover_color="#F3F4F6",
            border_color=BORDER_COLOR,
            border_width=1,
            width=36,
            height=36,
            corner_radius=8,
            command=self._toggle_session,
        )
        self.btn_play.pack(side="left")

        # Center Section: Timer & Timeline Ruler
        center_frame = ctk.CTkFrame(header, fg_color="transparent")
        center_frame.pack(side="left", expand=True)

        self.timer_label = TimerDisplay(
            center_frame,
            font=(FONT_FAMILY, FONT_SIZE_MEDIUM, "bold"),
            text_color=TEXT_PRIMARY,
        )
        self.timer_label.pack()

        self.timeline = TimelineRuler(center_frame, width=220, height=18)
        self.timeline.pack(pady=(2, 0))

        # Right Section: Keywords, Subtitles, History, Premium, Avatar
        right_frame = ctk.CTkFrame(header, fg_color="transparent")
        right_frame.pack(side="right")

        # 💡 Keywords Pill Button
        btn_keywords = ctk.CTkButton(
            right_frame,
            text="💡  Keywords",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
            fg_color="#FFFFFF",
            hover_color="#F3F4F6",
            border_color=BORDER_COLOR,
            border_width=1,
            height=34,
            corner_radius=17,
            command=self._show_ai_assistant,
        )
        btn_keywords.pack(side="left", padx=4)

        # Subtitle PIP Button
        btn_sub = ctk.CTkButton(
            right_frame,
            text="CC",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
            fg_color="#FFFFFF",
            hover_color="#F3F4F6",
            border_color=BORDER_COLOR,
            border_width=1,
            width=34,
            height=34,
            corner_radius=17,
            command=self._toggle_subtitles,
        )
        btn_sub.pack(side="left", padx=4)

        # History Dashboard Clock Button
        btn_history = ctk.CTkButton(
            right_frame,
            text="⏱️",
            font=ctk.CTkFont(size=14),
            text_color=ACCENT_ORANGE,
            fg_color="#FFFFFF",
            hover_color="#F3F4F6",
            border_color=ACCENT_ORANGE,
            border_width=1,
            width=34,
            height=34,
            corner_radius=17,
            command=self._show_history,
        )
        btn_history.pack(side="left", padx=(4, 0))

    def _build_main_content(self) -> None:
        self._content_grid = ctk.CTkFrame(self, fg_color="transparent")
        self._content_grid.grid(row=1, column=0, sticky="nsew", padx=20, pady=4)
        self._content_grid.grid_columnconfigure(0, weight=1)
        self._content_grid.grid_columnconfigure(1, weight=1)
        self._content_grid.grid_rowconfigure(0, weight=1)

        # Panel A (Left Source Card)
        self.panel_a = TranscriptPanel(
            self._content_grid,
            title="Panel A",
            lang_pair=f"{self._source_lang.lower()} → {self._target_lang.lower()}",
            model_name="TalkSync AI",
            speaker_active=True,
            on_lang_click=self._show_language_selector,
            on_speaker_click=self._toggle_panel_a_speaker,
            on_options_click=self._show_diagnostics,
        )
        self.panel_a.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        # Panel B (Right Target Card)
        self.panel_b = TranscriptPanel(
            self._content_grid,
            title="Panel B",
            lang_pair=f"{self._target_lang.lower()} → {self._source_lang.lower()}",
            model_name="TalkSync AI",
            speaker_active=True,
            on_lang_click=self._show_language_selector,
            on_speaker_click=self._toggle_panel_b_speaker,
            on_options_click=self._show_diagnostics,
        )
        self.panel_b.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

    def _build_text_input_panel(self) -> None:
        panel = ctk.CTkFrame(
            self,
            fg_color=BG_CARD,
            border_color=BORDER_COLOR,
            border_width=1,
            corner_radius=CORNER_RADIUS,
        )
        panel.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 8))

        head_row = ctk.CTkFrame(panel, fg_color="transparent")
        head_row.pack(fill="x", padx=14, pady=(8, 2))

        lbl_msg = ctk.CTkLabel(
            head_row,
            text="Message Input",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        lbl_msg.pack(side="left")

        self.text_mode_var = ctk.BooleanVar(value=False)
        chk_mode = ctk.CTkCheckBox(
            head_row,
            text="Text Input Mode",
            variable=self.text_mode_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            text_color=TEXT_PRIMARY,
            fg_color=ACCENT_ORANGE,
            hover_color=ACCENT_ORANGE_HOVER,
            command=self._on_text_mode_toggled,
        )
        chk_mode.pack(side="right")

        input_row = ctk.CTkFrame(panel, fg_color="transparent")
        input_row.pack(fill="x", padx=14, pady=(0, 10))

        self.text_input = ctk.CTkTextbox(
            input_row,
            height=55,
            fg_color=BG_SECONDARY,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            wrap="word",
        )
        self.text_input.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_send = ctk.CTkButton(
            input_row,
            text="Send",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            fg_color=ACCENT_ORANGE,
            hover_color=ACCENT_ORANGE_HOVER,
            width=80,
            height=55,
            corner_radius=8,
            command=self._send_text_input,
        )
        btn_send.pack(side="right")

    def _build_status_bar(self) -> None:
        self.status_bar = StatusBar(self)
        self.status_bar.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 8))

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-Return>", lambda e: self._send_text_input())
        self.bind("<Escape>", lambda e: self.text_input.delete("1.0", "end"))

    # Actions & Dialog Openers
    def _on_close(self) -> None:
        if self.pipeline and self.pipeline.running:
            loop = getattr(self.pipeline, "loop", None) or getattr(self.pipeline, "_loop", None)
            if loop and loop.is_running():
                try:
                    fut = asyncio.run_coroutine_threadsafe(self.pipeline.stop(), loop)
                    fut.result(timeout=2.0)
                except Exception as e:
                    logger.error(f"Error stopping pipeline on window close: {e}")
                    self.pipeline.running = False
            else:
                self.pipeline.running = False
        self.destroy()

    def _toggle_session(self) -> None:
        if not self.pipeline.running:
            # Prevent rapid re-starts if the last attempt failed within 3 seconds
            last_fail = getattr(self, "_last_start_failed_at", 0.0)
            if time.time() - last_fail < 3.0:
                logger.info(f"Skipping start — last attempt failed {time.time()-last_fail:.1f}s ago")
                return
            # Clear panels before starting new session
            self.panel_a.clear()
            self.panel_b.clear()
            self.btn_play.configure(text="■", text_color=ACCENT_RED)
            self.timer_label.start()
            threading.Thread(target=self._run_pipeline_thread, daemon=True).start()
        else:
            self.timer_label.stop()
            self.btn_play.configure(text="▶", text_color=ACCENT_GREEN)

            # Capture blocks before pipeline stop clears them
            blocks = list(getattr(self.pipeline, "_db_blocks", []))

            if self.pipeline.running:
                loop = getattr(self.pipeline, "loop", None) or getattr(self.pipeline, "_loop", None)
                if loop and loop.is_running():
                    try:
                        fut = asyncio.run_coroutine_threadsafe(self.pipeline.stop(), loop)
                        fut.result(timeout=2.0)
                    except Exception as e:
                        logger.error(f"Error stopping pipeline cleanly: {e}")
                        self.pipeline.running = False
                else:
                    self.pipeline.running = False

            self.after(0, lambda: self.status_bar.set_status("Idle"))

            if blocks:
                self.after(500, lambda b=blocks: SessionSummaryDialog(self, b))

    def _run_pipeline_thread(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.pipeline._loop = loop

        async def _task():
            await self.pipeline.start(
                source_lang=self._source_lang,
                target_lang=self._target_lang,
                loopback=self._loopback_enabled,
                text_mode=self._text_mode,
            )
            while self.pipeline.running:
                await asyncio.sleep(0.1)

        try:
            loop.run_until_complete(_task())
        except Exception as e:
            logger.error(f"Pipeline loop error: {e}")
            self._last_start_failed_at = time.time()
            self.after(0, lambda: self.status_bar.set_status(f"Error: {e}"))
            self.after(0, lambda: self.btn_play.configure(text="▶", text_color=ACCENT_GREEN))
            self.after(0, lambda: self.timer_label.stop())
            self.pipeline.running = False

    def _on_text_mode_toggled(self) -> None:
        self._text_mode = self.text_mode_var.get()
        if hasattr(self.pipeline, "text_input_mode"):
            self.pipeline.text_input_mode = self._text_mode

    def _send_text_input(self) -> None:
        text = self.text_input.get("1.0", "end").strip()
        if not text:
            return
        if len(text) > 5000:
            return

        # Guard: require pipeline to be running
        if not self.pipeline.running:
            self.after(0, lambda: self.status_bar.set_status("Press ▶ to start session first"))
            return

        self.text_input.delete("1.0", "end")

        loop = getattr(self.pipeline, "loop", None) or getattr(self.pipeline, "_loop", None)
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.pipeline.process_text_input(text=text, source_lang=self._source_lang),
                loop,
            )
        elif hasattr(self.pipeline, "submit_text_input"):
            self.pipeline.submit_text_input(text=text, source_lang=self._source_lang)
        else:
            self.after(0, lambda: self.status_bar.set_status("Pipeline not running — press ▶ to start"))

    def _show_audio_settings(self) -> None:
        AudioSettingsPopup(self, self.settings, on_update_callback=self._on_audio_settings_changed)

    def _show_ai_assistant(self) -> None:
        AIAssistantDialog(self, self.settings, on_save_callback=self._on_ai_assistant_saved)

    def _show_history(self) -> None:
        HistoryViewerDialog(self, self.settings.history.db_path)

    def _show_speaker_options(self) -> None:
        SpeakerOptionsDialog(self, self.settings, on_update_callback=self._on_speaker_options_changed)

    def _toggle_panel_a_speaker(self, active: bool) -> None:
        if hasattr(self, 'pipeline') and self.pipeline:
            self.pipeline.tts_enabled_a = active

    def _toggle_panel_b_speaker(self, active: bool) -> None:
        if hasattr(self, 'pipeline') and self.pipeline:
            self.pipeline.tts_enabled_b = active

    def _show_language_selector(self) -> None:
        LanguageSelectorDialog(
            self,
            source_lang=self._source_lang,
            target_lang=self._target_lang,
            mode=self._translation_mode,
            on_change_callback=self._update_languages,
        )

    def _show_diagnostics(self) -> None:
        DiagnosticsDialog(self, self.settings, pipeline=self.pipeline)

    def _toggle_subtitles(self) -> None:
        if self.subtitle_overlay.is_visible:
            self.subtitle_overlay.hide()
        else:
            self.subtitle_overlay.show()

    def _update_languages(self, src: str, tgt: str, mode: str) -> None:
        self._source_lang = src
        self._target_lang = tgt
        self._translation_mode = mode
        self.panel_a.update_lang_pair(f"{src.lower()} → {tgt.lower()}")
        self.panel_b.update_lang_pair(f"{tgt.lower()} → {src.lower()}")
        if hasattr(self.pipeline, 'set_translation_mode'):
            self.pipeline.set_translation_mode(mode)

        # Show/hide Panel B based on mode: one-way = single panel, two-way/multi = dual
        if mode == "one_way":
            self.panel_b.grid_remove()
            self._content_grid.grid_columnconfigure(0, weight=1)
            self._content_grid.grid_columnconfigure(1, weight=0)
            self.panel_a.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=0)
        else:
            self.panel_a.grid(row=0, column=0, columnspan=1, sticky="nsew", padx=(0, 10))
            self._content_grid.grid_columnconfigure(0, weight=1)
            self._content_grid.grid_columnconfigure(1, weight=1)
            self.panel_b.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

    # --- Dialog Callback Handlers ---
    def _on_audio_settings_changed(self, input_name, output_name, comp_audio, mic_audio, spk_audio) -> None:
        """Called when audio device selection changes in AudioSettingsPopup."""
        changed_loopback = comp_audio != self._loopback_enabled
        self._loopback_enabled = comp_audio

        # Check if virtual mic state changed
        vmic = False
        if self.settings and hasattr(self.settings, "audio"):
            vmic = bool(self.settings.audio.virtual_mic_enabled)

        vmic_prev = getattr(self, "_vmic_enabled_prev", False)
        changed_vmic = vmic != vmic_prev
        self._vmic_enabled_prev = vmic

        logger.info(f"Audio settings: input={input_name}, output={output_name}, loopback={comp_audio}, vmic={vmic}")

        # Auto-restart pipeline if loopback or virtual mic changed mid-session
        if (changed_loopback or changed_vmic) and self.pipeline.running:
            logger.info("Audio routing changed; restarting pipeline...")
            self._restart_pipeline("routing toggle")

    def _restart_pipeline(self, reason: str = "") -> None:
        """Stop and restart the pipeline. Skips if a restart is already in progress."""
        now = time.time()
        last = getattr(self, "_last_restart_at", 0.0)
        if now - last < 3.0:
            logger.info(f"Skipping restart ({reason}) — restart already in progress")
            return
        self._last_restart_at = now
        self._restarting = True

        if not self.pipeline.running:
            self.panel_a.clear()
            self.panel_b.clear()
            self.timer_label.start()
            threading.Thread(target=self._run_pipeline_thread, daemon=True).start()
            self.after(3000, lambda: setattr(self, "_restarting", False))
            return

        loop = getattr(self.pipeline, "loop", None) or getattr(self.pipeline, "_loop", None)
        if loop and loop.is_running():
            try:
                fut = asyncio.run_coroutine_threadsafe(self.pipeline.stop(), loop)
                fut.result(timeout=5.0)
            except Exception as e:
                logger.error(f"Error stopping pipeline for restart ({reason}): {e}")
                self.pipeline.running = False
        else:
            self.pipeline.running = False

        self.panel_a.clear()
        self.panel_b.clear()
        self.timer_label.start()
        threading.Thread(target=self._run_pipeline_thread, daemon=True).start()
        self.after(3000, lambda: setattr(self, "_restarting", False))

    def _on_ai_assistant_saved(self, keywords: str, context: str, enabled: bool) -> None:
        """Called when AI Assistant dialog saves keywords/context."""
        self.settings.keywords = keywords
        self.settings.context = context
        self.settings.ai_assistant_enabled = enabled
        if hasattr(self.pipeline, '_context_engine') and self.pipeline._context_engine:
            self.pipeline._context_engine.set_seed_context(context)
        logger.info(f"AI Assistant saved: keywords={len(keywords)} chars, context={len(context)} chars, enabled={enabled}")

    def _on_speaker_options_changed(self, volume: float, delay: float, voice: str, enabled: bool) -> None:
        """Called when speaker options change."""
        if hasattr(self.pipeline, 'set_volume'):
            self.pipeline.set_volume(volume)
        if hasattr(self.pipeline, 'set_delay'):
            self.pipeline.set_delay(delay)
        logger.info(f"Speaker options: vol={volume:.2f}, delay={delay:.1f}s, voice={voice}, enabled={enabled}")

    # Pipeline Callback Handlers
    def _on_transcription(self, segment) -> None:
        text = getattr(segment, "text", "") or ""
        source = getattr(segment, "input_source", "VOICE")
        if source in ("COMPUTER_AUDIO", "LOOPBACK"):
            self.after(0, lambda t=text: self.panel_b.update_streaming_text(original=t))
        else:
            self.after(0, lambda t=text: self.panel_a.update_streaming_text(original=t))

    def _on_translation(self, result) -> None:
        orig = getattr(result, "original_text", "")
        trans = getattr(result, "translated_text", "")
        source = getattr(result, "input_source", "VOICE")

        if source in ("COMPUTER_AUDIO", "LOOPBACK"):
            self.after(0, lambda o=orig, t=trans: self.panel_b.append_message(original=o, translated=t, input_source="LOOPBACK"))
        else:
            self.after(0, lambda o=orig, t=trans: self.panel_a.append_message(original=o, translated=t, input_source="VOICE"))

        if self.subtitle_overlay.is_visible:
            self.after(0, lambda o=orig, t=trans: self.subtitle_overlay.update_text(o, t))

    def _on_status(self, message: str, category: str = "info") -> None:
        self.after(0, lambda: self.status_bar.set_status(message))

    def _on_latency(self, latency_data: float | dict) -> None:
        if isinstance(latency_data, dict):
            latency_ms = float(latency_data.get("avg_ms", 0.0))
        elif isinstance(latency_data, (int, float)):
            latency_ms = float(latency_data)
        else:
            try:
                latency_ms = float(latency_data)
            except (TypeError, ValueError):
                latency_ms = 0.0
        self.after(0, lambda: self.status_bar.set_latency(latency_ms))

    def _on_audio_level(self, level: float) -> None:
        """Pipeline callback for live mic RMS level."""
        self.after(0, lambda: self.top_meter.set_level(min(1.0, level * 5.0)))
