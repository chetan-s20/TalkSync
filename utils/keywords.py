"""Keyword parsing and replacement utilities for TalkSync Pro."""
from __future__ import annotations


def parse_keywords(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    if not raw:
        return result
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for sep in ("->", "=>", "→", "=", ":"):
            if sep in line:
                parts = line.split(sep, 1)
                key = parts[0].strip()
                val = parts[1].strip()
                if key:
                    result[key] = val
                break
    return result


def apply_keywords(text: str, kw_map: dict[str, str]) -> str:
    if not kw_map:
        return text
    result = text
    for key, val in sorted(kw_map.items(), key=lambda x: -len(x[0])):
        if key:
            result = result.replace(key, val)
    return result
