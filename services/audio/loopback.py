from __future__ import annotations

from typing import Optional

import numpy as np
import sounddevice as sd

from utils.logger import get_logger

logger = get_logger("loopback")


def find_wasapi_loopback() -> Optional[str]:
    """Find WASAPI loopback device via soundcard (native Windows loopback).
    Returns the device name if found, None otherwise."""
    try:
        import soundcard as sc
        for m in sc.all_microphones(include_loopback=True):
            if m.isloopback:
                logger.info(f"Found WASAPI loopback: {m.name}")
                return m.name
    except Exception as e:
        logger.debug(f"soundcard WASAPI loopback not available: {e}")
    return None


def find_stereo_mix() -> Optional[int]:
    """Find Stereo Mix — the primary loopback capture device on this system."""
    try:
        devices = sd.query_devices()
    except Exception:
        return None
    for i, d in enumerate(devices):
        if not isinstance(d, dict):
            continue
        name = (d.get("name", "") or "").lower()
        if d.get("max_input_channels", 0) > 0 and "stereo mix" in name:
            logger.debug(f"Found Stereo Mix at index {i}: {d.get('name')}")
            return i
    return None


def find_vb_cable() -> Optional[int]:
    """Find VB-Audio Cable Output (input-capable) — used as loopback source."""
    try:
        devices = sd.query_devices()
    except Exception:
        return None
    for i, d in enumerate(devices):
        if not isinstance(d, dict):
            continue
        name = (d.get("name", "") or "").lower()
        # Match CABLE Output which is the input side of VB-Cable
        if d.get("max_input_channels", 0) > 0 and (
            "cable output" in name or "vb-audio virtual cable" in name
        ):
            logger.debug(f"Found VB-Cable Output (loopback) at index {i}: {d.get('name')}")
            return i
    return None


def find_loopback_device() -> Optional[tuple]:
    """Find best available loopback device. Priority: WASAPI > Stereo Mix > VB-Cable.
    Returns (device_id_or_name, type_label) where type_label is 'WASAPI', 'Stereo Mix', or 'VB-Cable'."""
    try:
        # 1. Prefer WASAPI loopback (soundcard) — captures digital output directly
        dev = find_wasapi_loopback()
        if dev is not None:
            logger.info(f"Resolved loopback device: WASAPI ({dev})")
            return dev, "WASAPI"

        # 2. Fallback to Stereo Mix
        dev = find_stereo_mix()
        if dev is not None:
            logger.info(f"Resolved loopback device: Stereo Mix (index {dev})")
            return dev, "Stereo Mix"

        # 3. Fallback to VB-Audio Cable Output
        dev = find_vb_cable()
        if dev is not None:
            logger.info(f"Resolved loopback device: VB-Cable Output (index {dev})")
            return dev, "VB-Cable Output"

    except Exception as e:
        logger.warning(f"Error querying loopback devices: {e}")

    logger.error(
        "No audio loopback device found. "
        "Enable Stereo Mix in Windows Sound Settings → Recording → "
        "Show Disabled Devices → Enable Stereo Mix."
    )
    return None


def find_vb_cable_output() -> Optional[int]:
    """Find VB-Audio Cable Input (output-capable) to route TTS to virtual mic."""
    try:
        devices = sd.query_devices()
    except Exception:
        return None
    for i, d in enumerate(devices):
        if not isinstance(d, dict):
            continue
        name = (d.get("name", "") or "")
        name_lower = name.lower()
        # "CABLE Input (VB-Audio Virtual Cable)" — this is an OUTPUT device
        if d.get("max_output_channels", 0) > 0 and (
            "cable input" in name_lower or ("vb-" in name_lower and "input" in name_lower)
        ):
            logger.debug(f"Found VB-Cable Input (virtual mic output) at index {i}: {name}")
            return i
    return None
