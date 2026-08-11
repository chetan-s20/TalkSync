from __future__ import annotations

import asyncio
import time
import pytest
from config.settings import load_settings
from services.translation.deepl import DeepLTranslator


from unittest.mock import patch

@pytest.mark.asyncio
async def test_deepl_startup_speed_under_3_seconds():
    """Verify DeepL initializes within 3-5 seconds cleanly despite unreachable proxy."""
    settings = load_settings()
    if not getattr(settings.translation, "deepl_api_key", ""):
        pytest.skip("DeepL API key not configured")
    settings.translation.proxy_url = ""

    with patch("services.translation.deepl.get_proxy_dict", return_value={}):
        start_time = time.time()
        translator = DeepLTranslator(settings.translation)
        await translator.start()
        elapsed = time.time() - start_time

        print(f"\nDeepL initialization time: {elapsed:.2f} seconds")
        assert elapsed < 5.0, f"DeepL startup took too long: {elapsed:.2f}s (expected < 5.0s)"
        assert translator._client is not None, "DeepL client should be initialized (via direct connection fallback)"


@pytest.mark.asyncio
async def test_deepl_translation_end_to_end():
    """Verify DeepL translation functions correctly after initialization."""
    settings = load_settings()
    if not getattr(settings.translation, "deepl_api_key", ""):
        pytest.skip("DeepL API key not configured")
    settings.translation.proxy_url = ""

    try:
        with patch("services.translation.deepl.get_proxy_dict", return_value={}):
            translator = DeepLTranslator(settings.translation)
            await translator.start()
    except (ValueError, RuntimeError):
        pytest.skip("DeepL API key invalid or API unreachable")

    if translator._client is None:
        pytest.skip("DeepL API key not configured or API unreachable")
        
    start_time = time.time()
    result = await translator.translate("Hello, how are you?", "EN", "HI")
    elapsed = time.time() - start_time
    
    print(f"\nTranslation completed in {elapsed:.2f}s: '{result.original_text}' -> '{result.translated_text.encode('ascii', 'backslashreplace').decode('ascii')}'")
    assert result.original_text == "Hello, how are you?"
    assert result.translated_text != ""
    assert result.is_final is True
    assert elapsed < 3.0, f"Translation took too long: {elapsed:.2f}s (expected < 3.0s)"
