from __future__ import annotations

import json
from typing import Sequence


def export_txt(blocks: Sequence[dict]) -> str:
    if not blocks:
        return ""
    lines = []
    for b in blocks:
        ts = b.get("timestamp", "")
        src = b.get("input_source", "VOICE")
        orig = b.get("original", "")
        trans = b.get("translated", "")
        lines.append(f"[{ts}] [{src}] {orig}")
        lines.append(f"{trans}")
        lines.append("")
        lines.append("")
    return "\n".join(lines)


def export_json(blocks: Sequence[dict]) -> str:
    return json.dumps(blocks, indent=2, ensure_ascii=False)


def _format_time(ts: str) -> str:
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%H:%M:%S,%f")[:12]
    except Exception:
        return "00:00:00,000"


def export_srt(blocks: Sequence[dict]) -> str:
    lines = []
    for i, b in enumerate(blocks, 1):
        ts = b.get("timestamp", "")
        start = _format_time(ts)
        end_hms = _increment_seconds(start, 3)
        orig = b.get("original", "")
        trans = b.get("translated", "")
        lines.append(str(i))
        lines.append(f"{start} --> {end_hms}")
        lines.append(f"{orig}\n{trans}")
        lines.append("")
    return "\n".join(lines)


def _increment_seconds(srt_time: str, secs: int = 3) -> str:
    try:
        parts = srt_time.replace(",", ".").split(":")
        h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
        s += secs
        if s >= 60:
            s -= 60
            m += 1
        if m >= 60:
            m -= 60
            h += 1
        ms = int((s - int(s)) * 1000)
        return f"{h:02d}:{m:02d}:{int(s):02d},{ms:03d}"
    except Exception:
        return "00:00:03,000"


def export_vtt(blocks: Sequence[dict]) -> str:
    lines = ["WEBVTT", ""]
    for b in blocks:
        ts = b.get("timestamp", "")
        start = _format_time(ts).replace(",", ".")
        end = _increment_seconds(_format_time(ts), 3).replace(",", ".")
        orig = b.get("original", "")
        trans = b.get("translated", "")
        lines.append(f"{start} --> {end}")
        lines.append(f"{orig}\n{trans}")
        lines.append("")
    return "\n".join(lines)


EXPORT_FORMATS = {
    "txt": export_txt,
    "json": export_json,
    "srt": export_srt,
    "vtt": export_vtt,
}


def export_blocks(blocks: Sequence[dict], fmt: str = "txt") -> str:
    func = EXPORT_FORMATS.get(fmt.lower(), export_txt)
    return func(blocks)
