"""Conversation context engine."""
from typing import Optional


class ContextEngine:

    def __init__(self):
        self._segments = []
        self._seed_context = ""

    def set_seed_context(self, context: str) -> None:
        self._seed_context = context

    def add_segment(self, original: str, translated: str, source_lang: str, target_lang: str) -> None:
        self._segments.append({
            "original": original, "translated": translated,
            "source_lang": source_lang, "target_lang": target_lang,
        })

    def build_context_prompt(self, source_lang: str, target_lang: str) -> Optional[str]:
        if not self._segments:
            return None
        recent = self._segments[-3:]
        lines = []
        for seg in recent:
            lines.append(f"{seg['source_lang']}: {seg['original']}")
            lines.append(f"{seg['target_lang']}: {seg['translated']}")
        return "\n".join(lines)

    def clear(self) -> None:
        self._segments.clear()
