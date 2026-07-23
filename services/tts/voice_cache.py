from __future__ import annotations

import os
from typing import Optional

SEARCH_DIRS = [
    os.getcwd(),
    os.path.join(os.getcwd(), "voices"),
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "voices"),
    os.path.expanduser("~/.local/share/piper/voices"),
]


def find_voice_model(voice_name: str) -> Optional[str]:
    target = voice_name.lower().replace("-", "_")
    for base in SEARCH_DIRS:
        expanded = os.path.expanduser(base)
        if not os.path.isdir(expanded):
            continue
        for root, dirs, files in os.walk(expanded):
            for f in files:
                if f.endswith(".onnx") and target in f.lower().replace("-", "_"):
                    return os.path.join(root, f).replace("\\", "/")

    env_dir = os.environ.get("PIPER_VOICE_DIR")
    if env_dir and os.path.isdir(env_dir):
        for root, dirs, files in os.walk(env_dir):
            for f in files:
                if f.endswith(".onnx") and target in f.lower().replace("-", "_"):
                    return os.path.join(root, f).replace("\\", "/")

    return None
