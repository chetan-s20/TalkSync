"""Language validator with hysteresis for two-way conversation."""


class LanguageValidator:

    def __init__(self):
        self._last_validated = None
        self._confidence_sum = 0.0

    def validate(self, detected_lang: str, confidence: float, source_lang: str, target_lang: str, context_engine=None) -> str:
        if confidence < 0.3:
            return self._last_validated or source_lang
        if detected_lang in (source_lang, target_lang):
            if detected_lang == self._last_validated:
                return detected_lang
            if confidence > 0.6:
                self._last_validated = detected_lang
                return detected_lang
        return self._last_validated or source_lang

    def reset(self) -> None:
        self._last_validated = None
