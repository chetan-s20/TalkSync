"""Translation module."""
from translation.translation_factory import TranslationFactory

def create_translator(settings, device="auto", compute_type="float16"):
    """Create a translator instance based on settings."""
    provider = getattr(settings, "provider", "argos").lower()
    if provider == "deepl":
        from translation.deepl import DeepLTranslator
        return DeepLTranslator(settings)
    elif provider == "argos":
        from translation.argos import ArgosTranslator
        return ArgosTranslator(settings)
    else:
        from translation.argos import ArgosTranslator
        return ArgosTranslator(settings)
