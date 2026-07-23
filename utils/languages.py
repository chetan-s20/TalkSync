"""Language code mappings and utilities for TalkSync Pro."""
from __future__ import annotations

from typing import Optional


ISO6391_TO_NAME: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "ar": "Arabic",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "gu": "Gujarati",
    "pa": "Punjabi",
    "kn": "Kannada",
    "ml": "Malayalam",
    "ur": "Urdu",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "th": "Thai",
    "id": "Indonesian",
    "nl": "Dutch",
    "pl": "Polish",
    "sv": "Swedish",
    "da": "Danish",
    "fi": "Finnish",
    "no": "Norwegian",
    "cs": "Czech",
    "el": "Greek",
    "he": "Hebrew",
    "ro": "Romanian",
    "hu": "Hungarian",
    "uk": "Ukrainian",
    "bg": "Bulgarian",
    "hr": "Croatian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "et": "Estonian",
    "lv": "Latvian",
    "lt": "Lithuanian",
    "sr": "Serbian",
    "bs": "Bosnian",
    "mk": "Macedonian",
    "sq": "Albanian",
    "mt": "Maltese",
    "is": "Icelandic",
    "ga": "Irish",
    "cy": "Welsh",
    "ca": "Catalan",
    "eu": "Basque",
    "gl": "Galician",
}

NAME_TO_ISO6391: dict[str, str] = {v.lower(): k for k, v in ISO6391_TO_NAME.items()}

DEEPL_TO_ISO6391: dict[str, str] = {
    "EN": "en",
    "DE": "de",
    "FR": "fr",
    "ES": "es",
    "IT": "it",
    "NL": "nl",
    "PL": "pl",
    "PT": "pt",
    "RU": "ru",
    "JA": "ja",
    "ZH": "zh",
    "CS": "cs",
    "DA": "da",
    "EL": "el",
    "FI": "fi",
    "HU": "hu",
    "NB": "no",
    "RO": "ro",
    "SK": "sk",
    "SL": "sl",
    "SV": "sv",
    "TR": "tr",
    "LT": "lt",
    "LV": "lv",
    "ET": "et",
    "BG": "bg",
    "UK": "uk",
    "HR": "hr",
    "SR": "sr",
    "ID": "id",
    "KO": "ko",
    "HI": "hi",
}

WHISPER_TO_ISO6391: dict[str, str] = {
    "english": "en",
    "hindi": "hi",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "japanese": "ja",
    "korean": "ko",
    "chinese": "zh",
    "arabic": "ar",
    "bengali": "bn",
    "tamil": "ta",
    "telugu": "te",
    "marathi": "mr",
    "gujarati": "gu",
    "punjabi": "pa",
    "kannada": "kn",
    "malayalam": "ml",
    "urdu": "ur",
    "turkish": "tr",
    "vietnamese": "vi",
    "thai": "th",
    "indonesian": "id",
}


def get_supported_languages() -> list[dict]:
    result = []
    for code, name in ISO6391_TO_NAME.items():
        result.append({"code": code, "name": name})
    return sorted(result, key=lambda x: x["name"])


def get_language_code(input_str: str) -> Optional[str]:
    if not input_str:
        return None
    s = input_str.strip().lower()
    if len(s) == 2:
        return ISO6391_TO_NAME.get(s, {}).get("code", s) if isinstance(ISO6391_TO_NAME.get(s), dict) else s
    if s in NAME_TO_ISO6391:
        return NAME_TO_ISO6391[s]
    if s in WHISPER_TO_ISO6391:
        return WHISPER_TO_ISO6391[s]
    return None


def get_language_name(code: str) -> str:
    s = (code or "").strip().lower()
    if len(s) == 2 and s in ISO6391_TO_NAME:
        return ISO6391_TO_NAME[s]
    return NAME_TO_ISO6391.get(s, code)


def normalize_lang(code: str) -> str:
    if not code:
        return code
    normalized = get_language_code(code)
    return (normalized or code).upper()


def is_supported_by_deepl(code: str) -> bool:
    return code.upper() in DEEPL_TO_ISO6391 or code.lower() in {v.lower() for v in DEEPL_TO_ISO6391}


LANGUAGES: dict[str, str] = {k.upper(): v for k, v in ISO6391_TO_NAME.items()}
