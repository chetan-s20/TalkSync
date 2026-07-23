import json
from pathlib import Path


DEFAULT_CONFIG = {
    "stt": {
        "model": "Systran/faster-whisper-small",
        "beam_size": 2,
    },
    "translation": {
        "primary": "argos",
        "fallback": "deepl",
        "argos_model": "en_hi",
    },
    "tts": {
        "piper_voice": "en_US-lessac-medium",
        "sarvam_voice": "shubh",
        "sarvam_lang": "hi-IN",
        "output_sample_rate": 24000,
    },
    "vad": {
        "threshold": 0.6,
        "min_speech_duration_ms": 250,
        "min_silence_duration_ms": 550,
    },
}


def load_config(path: str | None = None) -> dict:
    if path is None:
        path = str(Path(__file__).with_name("models_config.json"))
    p = Path(path)
    if not p.exists():
        return dict(DEFAULT_CONFIG)
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    merged = dict(DEFAULT_CONFIG)
    for section, values in data.items():
        if section in merged and isinstance(merged[section], dict) and isinstance(values, dict):
            merged[section] = {**merged[section], **values}
        else:
            merged[section] = values
    return merged


def update_config(key_path: str, value) -> None:
    parts = key_path.split(".")
    data = load_config()
    cursor = data
    for part in parts[:-1]:
        if part not in cursor or not isinstance(cursor[part], dict):
            cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = value
    save_config(data)


def save_config(data: dict, path: str | None = None) -> None:
    if path is None:
        path = str(Path(__file__).with_name("models_config.json"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
