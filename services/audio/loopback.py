from __future__ import annotations

from typing import Optional

import numpy as np
import sounddevice as sd

from utils.device import find_best_input_device, find_best_output_device
from utils.logger import get_logger

logger = get_logger("loopback")


def find_wasapi_loopback(output_device_id: Optional[int] = None) -> Optional[str]:
    """Find WASAPI loopback device via soundcard (native Windows loopback).
    Prefers the loopback endpoint corresponding to the active output device (e.g. headphones).
    Returns the device name if found, None otherwise."""
    try:
        import soundcard as sc
        target_keyword = "headphone"
        if output_device_id is not None:
            try:
                info = sd.query_devices(output_device_id)
                dev_name = (info.get("name", "") or "").lower()
                if "headphone" in dev_name or "headset" in dev_name:
                    target_keyword = "headphone"
                elif "speaker" in dev_name:
                    target_keyword = "speaker"
            except Exception:
                pass
        else:
            try:
                best_out = find_best_output_device()
                if best_out is not None:
                    info = sd.query_devices(best_out)
                    dev_name = (info.get("name", "") or "").lower()
                    if "headphone" in dev_name or "headset" in dev_name:
                        target_keyword = "headphone"
            except Exception:
                pass

        loopback_mics = [m for m in sc.all_microphones(include_loopback=True) if getattr(m, "isloopback", False)]

        # 0. Check if Windows default speaker has an exact WASAPI loopback match
        try:
            def_spk = sc.default_speaker()
            if def_spk:
                for m in loopback_mics:
                    if m.name.lower() == def_spk.name.lower() or def_spk.name.lower() in m.name.lower() or m.name.lower() in def_spk.name.lower():
                        logger.info(f"Found WASAPI loopback matching Windows default speaker: {m.name}")
                        return m.name
        except Exception as e:
            logger.debug(f"Default speaker lookup skipped: {e}")

        # 1. Prefer WASAPI loopback matching target output keyword (headphone/headset)
        for m in loopback_mics:
            name_lower = m.name.lower()
            if target_keyword in name_lower or (target_keyword == "headphone" and "headset" in name_lower):
                logger.info(f"Found targeted WASAPI loopback for active output '{target_keyword}': {m.name}")
                return m.name

        # 2. If headphone WASAPI loopback was specifically preferred but not found via soundcard,
        # fallback to the first available WASAPI loopback before returning None.
        if target_keyword == "headphone":
            if loopback_mics:
                logger.info(f"No headphone-specific WASAPI loopback found; falling back to first available WASAPI loopback: {loopback_mics[0].name}")
                return loopback_mics[0].name
            logger.info("No headphone-specific WASAPI loopback endpoint found via soundcard; falling back to Stereo Mix")
            return None

        if loopback_mics:
            logger.info(f"Found WASAPI loopback: {loopback_mics[0].name}")
            return loopback_mics[0].name
    except Exception as e:
        logger.debug(f"soundcard WASAPI loopback not available: {e}")
    return None


def find_stereo_mix() -> Optional[int]:
    """Find Stereo Mix — the primary loopback capture device on this system.

    Two-pass search:
    Pass 1: Prefer the Realtek HD Audio / HAP driver variant (more reliable with headphones).
    Pass 2: Fall back to any Stereo Mix device.
    """
    try:
        devices = sd.query_devices()
    except Exception:
        return None

    hap_candidate: Optional[int] = None
    generic_candidate: Optional[int] = None

    for i, d in enumerate(devices):
        if not isinstance(d, dict):
            continue
        name = (d.get("name", "") or "").lower()
        if d.get("max_input_channels", 0) > 0 and "stereo mix" in name:
            # Prefer HD Audio / HAP WASAPI driver over generic MME
            if "hd audio" in name or "hap" in name:
                if hap_candidate is None:
                    hap_candidate = i
                    logger.debug(f"Found HD Audio Stereo Mix (preferred) at index {i}: {d.get('name')}")
            else:
                if generic_candidate is None:
                    generic_candidate = i
                    logger.debug(f"Found generic Stereo Mix at index {i}: {d.get('name')}")

    result = hap_candidate if hap_candidate is not None else generic_candidate
    if result is not None:
        logger.info(f"Stereo Mix loopback resolved to device {result}: {devices[result].get('name')}")
    return result



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


def find_loopback_device(output_device_id: Optional[int] = None) -> Optional[tuple]:
    """Find best available loopback device. Priority: WASAPI (headphone preferred) > Stereo Mix > VB-Cable.
    Returns (device_id_or_name, type_label) where type_label is 'WASAPI', 'Stereo Mix', or 'VB-Cable'."""
    try:
        # 1. Prefer WASAPI loopback matching active output device (e.g. headphones)
        dev = find_wasapi_loopback(output_device_id)
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
