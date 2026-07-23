from __future__ import annotations

import customtkinter as ctk
import sounddevice as sd
from typing import Callable, Optional

from ui.assets.styles import (
    BG_CARD, BORDER_COLOR, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    ACCENT_ORANGE, FONT_FAMILY, FONT_SIZE_SMALL, FONT_SIZE_NORMAL,
    CORNER_RADIUS, CORNER_RADIUS_SMALL
)
from ui.widgets.audio_level import AudioLevelMeter


class AudioSettingsPopup(ctk.CTkToplevel):
    """Audio Source Selection Popup matching Transync AI reference screenshot 5."""

    def __init__(self, parent, settings=None, on_update_callback: Optional[Callable] = None):
        super().__init__(parent)
        self.parent = parent
        self.settings = settings
        self.on_update_callback = on_update_callback

        self.title("Select Audio Source")
        self.geometry("380x520")
        self.resizable(False, False)
        self.configure(fg_color=BG_CARD)

        self.transient(parent)

        self._build_ui()
        self.update_idletasks()

    def _build_ui(self) -> None:
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=16, pady=16)

        # Header Row: Title & Close Button
        header = ctk.CTkFrame(main_frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))

        lbl_title = ctk.CTkLabel(
            header,
            text="Select Audio Source",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        lbl_title.pack(side="left")

        btn_close = ctk.CTkButton(
            header,
            text="✕",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=TEXT_MUTED,
            fg_color="transparent",
            hover_color="#F3F4F6",
            width=24,
            height=24,
            corner_radius=12,
            command=self.destroy,
        )
        btn_close.pack(side="right")

        # 1. Computer Audio Checkbox Section
        comp_default = getattr(self.settings, "loopback_enabled", False) if self.settings else False
        self.comp_var = ctk.BooleanVar(value=comp_default)
        chk_comp = ctk.CTkCheckBox(
            main_frame,
            text="Computer Audio",
            variable=self.comp_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=TEXT_PRIMARY,
            fg_color=ACCENT_ORANGE,
            hover_color="#E54D1F",
            command=self._on_changed,
        )
        chk_comp.pack(anchor="w", pady=(0, 2))

        lbl_comp_sub = ctk.CTkLabel(
            main_frame,
            text="Select this if you need to translate other participants'\nspeech in online meetings.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=TEXT_MUTED,
            justify="left",
            anchor="w",
        )
        lbl_comp_sub.pack(anchor="w", padx=(24, 0), pady=(0, 2))

        lbl_comp_hint = ctk.CTkLabel(
            main_frame,
            text="Note: Enable 'Stereo Mix' in Windows Sound Settings → Recording.\nMust stop & restart pipeline for this change to take effect.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=9),
            text_color=TEXT_MUTED,
            justify="left",
            anchor="w",
        )
        lbl_comp_hint.pack(anchor="w", padx=(24, 0), pady=(0, 12))

        div1 = ctk.CTkFrame(main_frame, height=1, fg_color=BORDER_COLOR)
        div1.pack(fill="x", pady=(0, 12))

        # 2. Microphone Audio Checkbox Section
        mic_default = getattr(self.settings, "mic_enabled", True) if self.settings else True
        self.mic_var = ctk.BooleanVar(value=mic_default)
        chk_mic = ctk.CTkCheckBox(
            main_frame,
            text="Microphone Audio",
            variable=self.mic_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=TEXT_PRIMARY,
            fg_color=ACCENT_ORANGE,
            hover_color="#E54D1F",
            command=self._on_changed,
        )
        chk_mic.pack(anchor="w", pady=(0, 4))

        # Microphone Devices Dropdown / List
        mic_devices = self._get_input_devices()
        current_input = getattr(self.settings, "selected_input_device_name", "") if self.settings else ""
        self.mic_menu = ctk.CTkOptionMenu(
            main_frame,
            values=mic_devices,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            fg_color="#F3F4F6",
            text_color=TEXT_PRIMARY,
            button_color="#E5E7EB",
            button_hover_color="#D1D5DB",
            command=self._on_changed,
        )
        if current_input and current_input in mic_devices:
            self.mic_menu.set(current_input)
        self.mic_menu.pack(fill="x", padx=(24, 0), pady=(0, 12))

        div2 = ctk.CTkFrame(main_frame, height=1, fg_color=BORDER_COLOR)
        div2.pack(fill="x", pady=(0, 12))

        # 3. Speaker Section with Dotted Audio Meter
        spk_header = ctk.CTkFrame(main_frame, fg_color="transparent")
        spk_header.pack(fill="x", pady=(0, 4))

        spk_default = getattr(self.settings, "spk_enabled", True) if self.settings else True
        self.spk_var = ctk.BooleanVar(value=spk_default)
        chk_spk = ctk.CTkCheckBox(
            spk_header,
            text="Speaker",
            variable=self.spk_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=TEXT_PRIMARY,
            fg_color=ACCENT_ORANGE,
            hover_color="#E54D1F",
            command=self._on_changed,
        )
        chk_spk.pack(side="left")

        # Level meter
        self.level_meter = AudioLevelMeter(spk_header, num_dots=10)
        self.level_meter.pack(side="right")
        self.level_meter.set_level(0.0)

        spk_devices = self._get_output_devices()
        current_output = getattr(self.settings, "selected_output_device_name", "") if self.settings else ""
        self.spk_menu = ctk.CTkOptionMenu(
            main_frame,
            values=spk_devices,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            fg_color="#F3F4F6",
            text_color=TEXT_PRIMARY,
            button_color="#E5E7EB",
            button_hover_color="#D1D5DB",
            command=self._on_changed,
        )
        if current_output and current_output in spk_devices:
            self.spk_menu.set(current_output)
        self.spk_menu.pack(fill="x", padx=(24, 0), pady=(0, 16))

        # 4. Virtual Microphone Container Box
        vmic_box = ctk.CTkFrame(
            main_frame,
            fg_color="#F9FAFB",
            border_color=BORDER_COLOR,
            border_width=1,
            corner_radius=CORNER_RADIUS_SMALL,
        )
        vmic_box.pack(fill="x", pady=(0, 4))

        vmic_head = ctk.CTkFrame(vmic_box, fg_color="transparent")
        vmic_head.pack(fill="x", padx=12, pady=(8, 2))

        lbl_vmic_title = ctk.CTkLabel(
            vmic_head,
            text="Virtual Microphone",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        lbl_vmic_title.pack(side="left")

        lbl_view = ctk.CTkLabel(
            vmic_head,
            text="View",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, underline=True),
            text_color=TEXT_SECONDARY,
            cursor="hand2",
        )
        lbl_view.pack(side="right")

        lbl_vmic_desc = ctk.CTkLabel(
            vmic_box,
            text="Allow other participants in the meeting software\nto hear only your translated broadcast voice.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color=TEXT_MUTED,
            justify="left",
            anchor="w",
        )
        lbl_vmic_desc.pack(anchor="w", padx=12, pady=(0, 8))

    def _get_input_devices(self) -> list[str]:
        try:
            devs = sd.query_devices()
            names = ["Default Microphone"]
            for d in devs:
                if d.get("max_input_channels", 0) > 0:
                    name = d["name"]
                    if name not in names:
                        names.append(name)
            return names[:8]
        except Exception:
            return ["Default Microphone"]

    def _get_output_devices(self) -> list[str]:
        try:
            devs = sd.query_devices()
            names = ["Default Speaker"]
            for d in devs:
                if d.get("max_output_channels", 0) > 0:
                    name = d["name"]
                    if name not in names:
                        names.append(name)
            return names[:8]
        except Exception:
            return ["Default Speaker"]

    def _resolve_device_id(self, name: str, kind: str) -> Optional[int]:
        """Resolve a device name to its sounddevice ID."""
        if name.startswith("Default"):
            return None
        try:
            devs = sd.query_devices()
            for i, d in enumerate(devs):
                ch_key = "max_input_channels" if kind == "input" else "max_output_channels"
                if d["name"] == name and d.get(ch_key, 0) > 0:
                    return i
        except Exception:
            pass
        return None

    def _on_changed(self, *args) -> None:
        input_name = self.mic_menu.get()
        output_name = self.spk_menu.get()

        # Update settings with device names, resolved IDs, and checkbox states
        if self.settings:
            self.settings.selected_input_device_name = input_name
            self.settings.selected_output_device_name = output_name
            self.settings.loopback_enabled = self.comp_var.get()
            self.settings.mic_enabled = self.mic_var.get()
            self.settings.spk_enabled = self.spk_var.get()
            input_id = self._resolve_device_id(input_name, "input")
            output_id = self._resolve_device_id(output_name, "output")
            if hasattr(self.settings, "audio"):
                self.settings.audio.input_device_id = input_id
                self.settings.audio.output_device_id = output_id

        if self.on_update_callback:
            self.on_update_callback(
                input_name, output_name,
                self.comp_var.get(), self.mic_var.get(), self.spk_var.get(),
            )


# Backward compatibility alias
AudioSourcePopup = AudioSettingsPopup
