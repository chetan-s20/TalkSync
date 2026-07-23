"""Audio device enumeration and detection utilities."""
from __future__ import annotations

import sounddevice as sd
from typing import Any


def get_default_input_device() -> int | None:
    try:
        info = sd.query_devices(kind="input")
        if isinstance(info, dict):
            default = sd.default.device
            if isinstance(default, (list, tuple)) and len(default) > 0:
                return default[0]
            return None
    except Exception:
        pass
    return None


def list_input_devices() -> list[dict[str, Any]]:
    try:
        devices = sd.query_devices(kind="input")
    except Exception:
        return []
    result = []
    if isinstance(devices, dict):
        devices = [devices]
    for i, device in enumerate(devices):
        if not isinstance(device, dict):
            continue
        result.append({
            "id": i,
            "name": device.get("name", f"Device {i}"),
            "channels": device.get("max_input_channels", 0),
            "sample_rate": int(device.get("default_samplerate", 44100)),
            "hostapi": device.get("hostapi", -1),
        })
    return result


def list_output_devices() -> list[dict[str, Any]]:
    try:
        devices = sd.query_devices(kind="output")
    except Exception:
        return []
    result = []
    if isinstance(devices, dict):
        devices = [devices]
    for i, device in enumerate(devices):
        if not isinstance(device, dict):
            continue
        result.append({
            "id": i,
            "name": device.get("name", f"Device {i}"),
            "channels": device.get("max_output_channels", 0),
            "sample_rate": int(device.get("default_samplerate", 44100)),
        })
    return result


def find_device_by_name(name_substring: str, kind: str = "input") -> int | None:
    devices = list_input_devices() if kind == "input" else list_output_devices()
    needle = name_substring.lower()
    for dev in devices:
        if needle in dev["name"].lower():
            return dev["id"]
    return None
