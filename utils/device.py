"""Audio device enumeration and detection utilities with runtime stream validation."""
from __future__ import annotations

import sounddevice as sd
from typing import Any, Optional


def is_valid_input_device(device_id: int) -> bool:
    """Return True if PortAudio can actually open an input stream on the device."""
    try:
        sd.check_input_settings(device=device_id)
        st = sd.InputStream(device=device_id, samplerate=16000, channels=1)
        st.start()
        st.stop()
        st.close()
        return True
    except Exception:
        return False


def is_valid_output_device(device_id: int) -> bool:
    """Return True if PortAudio can actually open an output stream on the device."""
    try:
        sd.check_output_settings(device=device_id)
        st = sd.OutputStream(device=device_id, samplerate=44100, channels=1)
        st.start()
        st.stop()
        st.close()
        return True
    except Exception:
        return False


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


def find_best_input_device(requested_id: Optional[int] = None) -> tuple[Optional[int], str]:
    """Find the best available microphone input device.
    
    Checks requested_id first. If requested_id is valid, working, and has max_input_channels > 0,
    it is returned. Otherwise, queries sounddevice.query_devices() and auto-detects:
    1. Active default system microphone.
    2. Working headset / headphone microphone.
    3. Any valid working input device.
    """
    from utils.logger import get_logger
    logger = get_logger("device")

    try:
        all_devices = sd.query_devices()
    except Exception as e:
        logger.warning(f"Failed to query audio input devices: {e}")
        return None, "System Default Input"

    if isinstance(all_devices, dict):
        all_devices = [all_devices]

    num_devices = len(all_devices)

    loopback_keywords = ("stereo mix", "cable output", "virtual cable", "loopback", "mapper - input", "primary sound capture")

    # 1. Validate requested_id with actual stream opening check
    if requested_id is not None:
        try:
            req_idx = int(requested_id)
            if 0 <= req_idx < num_devices:
                dev = all_devices[req_idx]
                req_name = (dev.get("name") or "").lower() if isinstance(dev, dict) else ""
                if any(lk in req_name for lk in loopback_keywords):
                    logger.warning(f"Configured input device ID {req_idx} ('{dev.get('name')}') is a loopback endpoint — ignoring for mic input.")
                elif isinstance(dev, dict) and dev.get("max_input_channels", 0) > 0 and is_valid_input_device(req_idx):
                    dev_name = dev.get("name", f"Device {req_idx}")
                    logger.info(f"Selected requested input device: ID {req_idx} ('{dev_name}') [channels={dev.get('max_input_channels')}]")
                    return req_idx, dev_name
                else:
                    dev_name = dev.get("name", "Unknown") if isinstance(dev, dict) else "Unknown"
                    logger.warning(
                        f"Configured input device ID {req_idx} ('{dev_name}') has 0 input channels or failed stream open test; "
                        f"falling back cleanly to auto-detection."
                    )
            else:
                logger.warning(f"Configured input device ID {req_idx} is out of range (0-{num_devices-1}); falling back to auto-detection.")
        except Exception as e:
            logger.warning(f"Error validating input device ID {requested_id}: {e}; falling back to auto-detection.")

    # 2. Auto-detect best working input device
    default_input_idx = None
    try:
        default_dev = sd.default.device
        if isinstance(default_dev, (list, tuple)) and len(default_dev) > 0 and default_dev[0] is not None and default_dev[0] >= 0:
            default_input_idx = int(default_dev[0])
    except Exception:
        pass

    headset_keywords = ("headset", "headphone", "hands-free", "earphone", "buds", "airwave", "boult", "airbass", "bluetooth", "wireless", "earbuds")
    mic_keywords = ("mic", "microphone", "array")
    loopback_keywords = ("stereo mix", "cable output", "virtual cable", "loopback", "mapper - input", "primary sound capture")

    best_id: Optional[int] = None
    best_name = "System Default Input"
    best_score = -9999

    for idx, dev in enumerate(all_devices):
        if not isinstance(dev, dict):
            continue
        ch = dev.get("max_input_channels", 0)
        if ch <= 0:
            continue

        name = (dev.get("name") or "").lower()
        hostapi = dev.get("hostapi", -1)

        # Skip explicit loopback/virtual capture devices from mic auto-detection
        if any(lk in name for lk in loopback_keywords):
            score = -500
        else:
            # Verify stream opening before giving positive score
            if not is_valid_input_device(idx):
                continue

            score = 0
            if default_input_idx is not None and idx == default_input_idx:
                score += 2000
            if any(hk in name for hk in headset_keywords):
                score += 600
            elif any(mk in name for mk in mic_keywords):
                score += 200

            if hostapi in (0, 1, 2):
                score += 50

        if score > best_score:
            best_score = score
            best_id = idx
            best_name = dev.get("name", f"Device {idx}")

    if best_id is not None:
        logger.info(f"Selected auto-detected input device: ID {best_id} ('{best_name}') [score={best_score}]")
        return best_id, best_name

    # Fallback to system default
    if default_input_idx is not None and 0 <= default_input_idx < num_devices:
        dev_name = all_devices[default_input_idx].get("name", f"Device {default_input_idx}")
        logger.info(f"Selected system default input device: ID {default_input_idx} ('{dev_name}')")
        return default_input_idx, dev_name

    logger.warning("No suitable input device auto-detected; using system default")
    return None, "System Default Input"


def find_best_output_device(requested_id: Optional[int] = None) -> tuple[Optional[int], str]:
    """Find the best available headphone/speaker output device.
    
    Checks requested_id first. If requested_id is valid, working, and has max_output_channels > 0,
    it is returned. Otherwise, queries sounddevice.query_devices() and auto-detects:
    1. Active default system speaker / headphone device.
    2. Working headphones / headset playback device.
    3. Any valid working output device.
    """
    from utils.logger import get_logger
    logger = get_logger("device")

    try:
        all_devices = sd.query_devices()
    except Exception as e:
        logger.warning(f"Failed to query audio output devices: {e}")
        return None, "System Default Output"

    if isinstance(all_devices, dict):
        all_devices = [all_devices]

    num_devices = len(all_devices)

    # 1. Validate requested_id
    if requested_id is not None:
        try:
            req_idx = int(requested_id)
            if 0 <= req_idx < num_devices:
                dev = all_devices[req_idx]
                if isinstance(dev, dict) and dev.get("max_output_channels", 0) > 0 and is_valid_output_device(req_idx):
                    dev_name = dev.get("name", f"Device {req_idx}")
                    logger.info(f"Selected requested output device: ID {req_idx} ('{dev_name}') [channels={dev.get('max_output_channels')}]")
                    return req_idx, dev_name
                else:
                    dev_name = dev.get("name", "Unknown") if isinstance(dev, dict) else "Unknown"
                    logger.warning(
                        f"Configured output device ID {req_idx} ('{dev_name}') has 0 output channels or failed stream open test; "
                        f"falling back cleanly to auto-detection."
                    )
            else:
                logger.warning(f"Configured output device ID {req_idx} is out of range (0-{num_devices-1}); falling back to auto-detection.")
        except Exception as e:
            logger.warning(f"Error validating output device ID {requested_id}: {e}; falling back to auto-detection.")

    # 2. Auto-detect best output device
    default_output_idx = None
    try:
        default_dev = sd.default.device
        if isinstance(default_dev, (list, tuple)) and len(default_dev) > 1 and default_dev[1] is not None and default_dev[1] >= 0:
            default_output_idx = int(default_dev[1])
    except Exception:
        pass

    headphone_keywords = ("headphone", "headset", "hands-free", "earphone", "buds", "boult", "airbass", "bluetooth", "wireless", "earbuds")
    speaker_keywords = ("speaker", "speakers")
    virtual_input_keywords = ("cable input", "virtual cable", "mapper - output", "primary sound driver")

    best_id: Optional[int] = None
    best_name = "System Default Output"
    best_score = -9999

    for idx, dev in enumerate(all_devices):
        if not isinstance(dev, dict):
            continue
        ch = dev.get("max_output_channels", 0)
        if ch <= 0:
            continue

        name = (dev.get("name") or "").lower()
        hostapi = dev.get("hostapi", -1)

        # Skip virtual cable input endpoints (used for virtual mic routing)
        if any(vk in name for vk in virtual_input_keywords):
            score = -500
        else:
            # Verify stream opening before giving positive score
            if not is_valid_output_device(idx):
                continue

            score = 0
            if default_output_idx is not None and idx == default_output_idx:
                score += 2000
            if any(hk in name for hk in headphone_keywords):
                score += 600
            elif any(sk in name for sk in speaker_keywords):
                score += 200

            if hostapi in (0, 1, 2):
                score += 50

        if score > best_score:
            best_score = score
            best_id = idx
            best_name = dev.get("name", f"Device {idx}")

    if best_id is not None:
        logger.info(f"Selected auto-detected output device: ID {best_id} ('{best_name}') [score={best_score}]")
        return best_id, best_name

    # Fallback to system default
    if default_output_idx is not None and 0 <= default_output_idx < num_devices:
        dev_name = all_devices[default_output_idx].get("name", f"Device {default_output_idx}")
        logger.info(f"Selected system default output device: ID {default_output_idx} ('{dev_name}')")
        return default_output_idx, dev_name

    logger.warning("No suitable output device auto-detected; using system default")
    return None, "System Default Output"


def find_best_physical_output_device() -> tuple[Optional[int], str]:
    """Auto-detect the best physical headphones/speakers device, strictly ignoring virtual cable devices."""
    try:
        all_devices = sd.query_devices()
    except Exception:
        return None, "System Default Output"

    if isinstance(all_devices, dict):
        all_devices = [all_devices]

    num_devices = len(all_devices)
    virtual_input_keywords = ("cable input", "virtual cable", "vb-audio", "mapper - output")
    headphone_keywords = ("headphone", "headset", "hands-free", "earphone", "buds", "boult", "airbass", "bluetooth", "wireless", "earbuds")
    speaker_keywords = ("speaker", "speakers")

    best_id: Optional[int] = None
    best_name = "System Default Output"
    best_score = -9999

    for idx, dev in enumerate(all_devices):
        if not isinstance(dev, dict):
            continue
        ch = dev.get("max_output_channels", 0)
        if ch <= 0:
            continue

        name = (dev.get("name") or "").lower()
        if any(vk in name for vk in virtual_input_keywords):
            continue

        if not is_valid_output_device(idx):
            continue

        score = 100
        if any(hk in name for hk in headphone_keywords):
            score += 600
        elif any(sk in name for sk in speaker_keywords):
            score += 200

        if score > best_score:
            best_score = score
            best_id = idx
            best_name = dev.get("name", f"Device {idx}")

    if best_id is not None:
        return best_id, best_name

    return None, "System Default Output"
