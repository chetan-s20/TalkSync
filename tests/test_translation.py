from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.interfaces import BaseTranslator, TranslationResult
from services.translation.argos import ArgosTranslator
from services.translation.deepl import DeepLTranslator
from services.translation.factory import TranslationFactory
from services.translation.language_validator import LanguageValidator
from services.translation.context_engine import ContextEngine


class TestTranslationInterface:
    def test_base_translator_abstract(self):
        with pytest.raises(TypeError):
            BaseTranslator()

    def test_translation_result_dataclass(self):
        result = TranslationResult(
            original_text="Hello", translated_text="Hola",
            source_lang="en", target_lang="es", is_final=True,
        )
        assert result.original_text == "Hello"
        assert result.translated_text == "Hola"
        assert result.source_lang == "en"
        assert result.target_lang == "es"
        assert result.is_final is True

    def test_translation_result_fields(self):
        result = TranslationResult(
            original_text="", translated_text="",
            source_lang="", target_lang="",
            is_final=False, input_source="TEXT",
        )
        assert result.input_source == "TEXT"
        assert result.is_final is False


class TestArgosTranslate:
    @pytest.mark.asyncio
    async def test_argos_initialization(self):
        with patch("argostranslate.package.update_package_index") as mock_update:
            with patch("argostranslate.package.get_available_packages", return_value=[]):
                with patch("argostranslate.translate") as mock_translate:
                    settings = MagicMock()
                    settings.deepl_api_key = ""
                    settings.proxy_url = ""
                    settings.timeout_s = 5.0

                    translator = ArgosTranslator(settings)
                    await translator.start()

                    assert translator._model is not None
                    mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_argos_translate_success(self):
        with patch("argostranslate.package.update_package_index"):
            with patch("argostranslate.package.get_available_packages", return_value=[]):
                with patch("argostranslate.translate") as mock_translate:
                    mock_instance = MagicMock()
                    mock_instance.translate.return_value = "नमस्ते दुनिया"
                    mock_translate.get_translation_from_codes.return_value = mock_instance

                    settings = MagicMock()
                    settings.deepl_api_key = ""
                    settings.proxy_url = ""
                    settings.timeout_s = 5.0

                    translator = ArgosTranslator(settings)
                    await translator.start()

                    result = await translator.translate("Hello world", "en", "hi")

                    assert result.original_text == "Hello world"
                    assert result.translated_text == "नमस्ते दुनिया"
                    assert result.is_final is True
                    mock_instance.translate.assert_called_once_with("Hello world")

    @pytest.mark.asyncio
    async def test_argos_translate_empty_text(self):
        with patch("argostranslate.package.update_package_index"):
            with patch("argostranslate.package.get_available_packages", return_value=[]):
                with patch("argostranslate.translate") as mock_translate:
                    mock_instance = MagicMock()
                    mock_instance.translate.return_value = ""
                    mock_translate.get_translation_from_codes.return_value = mock_instance

                    settings = MagicMock()
                    settings.deepl_api_key = ""
                    settings.proxy_url = ""
                    settings.timeout_s = 5.0

                    translator = ArgosTranslator(settings)
                    await translator.start()

                    result = await translator.translate("", "en", "hi")

                    assert result.translated_text == ""

    @pytest.mark.asyncio
    async def test_argos_translate_two_way_swap(self):
        with patch("argostranslate.package.update_package_index"):
            with patch("argostranslate.package.get_available_packages", return_value=[]):
                with patch("argostranslate.translate") as mock_translate:
                    hi_en_instance = MagicMock()
                    hi_en_instance.translate.return_value = "Hello"
                    en_hi_instance = MagicMock()
                    en_hi_instance.translate.return_value = "नमस्ते"

                    def get_translation(from_code, to_code):
                        if from_code == "hi" and to_code == "en":
                            return hi_en_instance
                        return en_hi_instance

                    mock_translate.get_translation_from_codes.side_effect = get_translation

                    settings = MagicMock()
                    settings.deepl_api_key = ""
                    settings.proxy_url = ""
                    settings.timeout_s = 5.0

                    translator = ArgosTranslator(settings)
                    await translator.start()

                    result_en_hi = await translator.translate("Hello", "en", "hi")
                    assert result_en_hi.translated_text == "नमस्ते"

                    result_hi_en = await translator.translate("नमस्ते", "hi", "en")
                    assert result_hi_en.translated_text == "Hello"

    @pytest.mark.asyncio
    async def test_argos_cold_start_warmup(self):
        with patch("argostranslate.package.update_package_index"):
            with patch("argostranslate.package.get_available_packages", return_value=[]):
                with patch("argostranslate.translate") as mock_translate:
                    settings = MagicMock()
                    settings.deepl_api_key = ""
                    settings.proxy_url = ""
                    settings.timeout_s = 5.0

                    translator = ArgosTranslator(settings)
                    assert translator._model is None
                    await translator.start()
                    assert translator._model is not None

    @pytest.mark.asyncio
    async def test_argos_language_pair_swap(self):
        with patch("argostranslate.package.update_package_index"):
            with patch("argostranslate.package.get_available_packages", return_value=[]):
                with patch("argostranslate.translate") as mock_translate:
                    mock_instance = MagicMock()
                    mock_instance.translate.return_value = "Texto traducido"
                    mock_translate.get_translation_from_codes.return_value = mock_instance

                    settings = MagicMock()
                    settings.deepl_api_key = ""
                    settings.proxy_url = ""
                    settings.timeout_s = 5.0

                    translator = ArgosTranslator(settings)
                    await translator.start()

                    result = await translator.translate("Translated text", "es", "fr")
                    assert result.translated_text == "Translated text"
                    assert result.source_lang == "es"
                    assert result.target_lang == "fr"

    @pytest.mark.asyncio
    async def test_argos_translate_with_context(self):
        with patch("argostranslate.package.update_package_index"):
            with patch("argostranslate.package.get_available_packages", return_value=[]):
                with patch("argostranslate.translate") as mock_translate:
                    mock_instance = MagicMock()
                    mock_instance.translate.return_value = "नमस्ते"
                    mock_translate.get_translation_from_codes.return_value = mock_instance

                    settings = MagicMock()
                    settings.deepl_api_key = ""
                    settings.proxy_url = ""
                    settings.timeout_s = 5.0

                    translator = ArgosTranslator(settings)
                    await translator.start()

                    result = await translator.translate("Hello", "en", "hi", context="Previous: How are you?")
                    assert result.translated_text == "नमस्ते"


class TestDeepL:
    @pytest.mark.asyncio
    async def test_deepl_initialization(self):
        with patch("deepl.Translator") as mock_deepl:
            mock_client = MagicMock()
            mock_client.get_usage.return_value = None
            mock_deepl.return_value = mock_client

            settings = MagicMock()
            settings.deepl_api_key = "test-key-123"
            settings.proxy_url = "http://proxy:8080"
            settings.timeout_s = 5.0

            translator = DeepLTranslator(settings)
            await translator.start()

            assert translator._client is not None
            mock_deepl.assert_called_once()

    @pytest.mark.asyncio
    async def test_deepl_translate_success(self):
        with patch("deepl.Translator") as mock_deepl:
            mock_client = MagicMock()
            mock_result = MagicMock()
            mock_result.text = "Bonjour le monde"
            mock_client.translate_text.return_value = mock_result
            mock_client.get_usage.return_value = None
            mock_deepl.return_value = mock_client

            settings = MagicMock()
            settings.deepl_api_key = "test-key"
            settings.proxy_url = ""
            settings.timeout_s = 5.0

            translator = DeepLTranslator(settings)
            await translator.start()

            result = await translator.translate("Hello world", "en", "fr")

            assert result.original_text == "Hello world"
            assert result.translated_text == "Bonjour le monde"
            assert result.is_final is True
            mock_client.translate_text.assert_called_once_with(
                "Hello world", source_lang="EN", target_lang="FR",
            )

    @pytest.mark.asyncio
    async def test_deepl_api_timeout(self):
        with patch("deepl.Translator") as mock_deepl:
            mock_client = MagicMock()
            mock_client.translate_text.side_effect = TimeoutError("API timeout")
            mock_client.get_usage.return_value = None
            mock_deepl.return_value = mock_client

            settings = MagicMock()
            settings.deepl_api_key = "test-key"
            settings.proxy_url = ""
            settings.timeout_s = 5.0

            translator = DeepLTranslator(settings)
            await translator.start()

            result = await translator.translate("Hello", "en", "fr")

            assert result.translated_text == "Hello"
            assert result.is_final is True

    @pytest.mark.asyncio
    async def test_deepl_proxy_config(self):
        with patch("deepl.Translator") as mock_deepl:
            mock_client = MagicMock()
            mock_client.get_usage.return_value = None
            mock_deepl.return_value = mock_client

            settings = MagicMock()
            settings.deepl_api_key = "key-with-proxy"
            settings.proxy_url = "https://proxy.company.com:3128"
            settings.timeout_s = 5.0

            with patch("utils.proxy.get_proxy_dict", return_value={"https://": "https://proxy.company.com:3128"}):
                translator = DeepLTranslator(settings)
                await translator.start()

                mock_deepl.assert_called_once()
                _, kwargs = mock_deepl.call_args
                assert "proxy_url" in kwargs

    @pytest.mark.asyncio
    async def test_deepl_fallback_on_error(self):
        with patch("deepl.Translator") as mock_deepl:
            mock_deepl.side_effect = RuntimeError("API key invalid")

            settings = MagicMock()
            settings.deepl_api_key = "bad-key"
            settings.proxy_url = ""
            settings.timeout_s = 5.0

            translator = DeepLTranslator(settings)
            await translator.start()

            assert translator._client is None

            result = await translator.translate("Hello", "en", "fr")
            assert result.translated_text == "Hello"

    @pytest.mark.asyncio
    async def test_deepl_no_api_key(self):
        settings = MagicMock()
        settings.deepl_api_key = ""
        settings.proxy_url = ""
        settings.timeout_s = 5.0

        translator = DeepLTranslator(settings)
        await translator.start()

        assert translator._client is None
        result = await translator.translate("Hello", "en", "fr")
        assert result.translated_text == "Hello"

    @pytest.mark.asyncio
    async def test_deepl_translate_error_returns_original(self):
        with patch("deepl.Translator") as mock_deepl:
            mock_client = MagicMock()
            mock_client.translate_text.side_effect = Exception("Network error")
            mock_client.get_usage.return_value = None
            mock_deepl.return_value = mock_client

            settings = MagicMock()
            settings.deepl_api_key = "test-key"
            settings.proxy_url = ""
            settings.timeout_s = 5.0

            translator = DeepLTranslator(settings)
            await translator.start()

            result = await translator.translate("Hello", "en", "fr")
            assert result.translated_text == "Hello"


class TestTranslationFactory:
    @pytest.mark.asyncio
    async def test_factory_creates_argos_primary(self):
        with patch("services.translation.factory.ArgosTranslator") as mock_argos:
            mock_instance = AsyncMock()
            mock_argos.return_value = mock_instance

            settings = MagicMock()
            settings.translation = MagicMock()

            result = await TranslationFactory.create(settings)

            assert result is mock_instance
            mock_argos.assert_called_once_with(settings.translation)
            mock_instance.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_factory_fallback_chain(self):
        with patch("services.translation.factory.ArgosTranslator") as mock_argos:
            mock_argos_instance = AsyncMock()
            mock_argos_instance.start.side_effect = RuntimeError("Argos failed")
            mock_argos.return_value = mock_argos_instance

            with patch("services.translation.factory.DeepLTranslator") as mock_deepl:
                mock_deepl_instance = AsyncMock()
                mock_deepl.return_value = mock_deepl_instance

                settings = MagicMock()
                settings.translation = MagicMock()

                result = await TranslationFactory.create(settings)

                assert result is mock_deepl_instance
                mock_argos.assert_called_once()
                mock_deepl.assert_called_once()
                mock_deepl_instance.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_factory_all_engines_fail(self):
        with patch("services.translation.factory.ArgosTranslator") as mock_argos:
            mock_argos_instance = AsyncMock()
            mock_argos_instance.start.side_effect = RuntimeError("Argos failed")
            mock_argos.return_value = mock_argos_instance

            with patch("services.translation.factory.DeepLTranslator") as mock_deepl:
                mock_deepl_instance = AsyncMock()
                mock_deepl_instance.start.side_effect = RuntimeError("DeepL failed")
                mock_deepl.return_value = mock_deepl_instance

                settings = MagicMock()
                settings.translation = MagicMock()

                result = await TranslationFactory.create(settings)
                from services.translation.dummy import DummyTranslator
                assert isinstance(result, DummyTranslator)

    @pytest.mark.asyncio
    async def test_factory_engine_initialization_order(self):
        call_order = []

        with patch("services.translation.factory.ArgosTranslator") as mock_argos:
            mock_argos_instance = AsyncMock()
            mock_argos_instance.start.side_effect = lambda: call_order.append("argos")
            mock_argos.return_value = mock_argos_instance

            with patch("services.translation.factory.DeepLTranslator") as mock_deepl:
                mock_deepl_instance = AsyncMock()
                mock_deepl_instance.start.side_effect = lambda: call_order.append("deepl")
                mock_deepl.return_value = mock_deepl_instance

                settings = MagicMock()
                settings.translation = MagicMock()

                await TranslationFactory.create(settings)

                assert call_order == ["argos"]


class TestLanguageValidator:
    def test_validator_high_confidence_accept(self):
        validator = LanguageValidator()
        result = validator.validate("hi", 0.8, "en", "hi")
        assert result == "hi"
        assert validator._last_validated == "hi"

    def test_validator_low_confidence_hysteresis(self):
        validator = LanguageValidator()
        result = validator.validate("hi", 0.2, "en", "hi")
        assert result == "en"
        assert validator._last_validated is None

    def test_validator_low_confidence_with_history(self):
        validator = LanguageValidator()
        validator._last_validated = "en"
        result = validator.validate("hi", 0.2, "en", "hi")
        assert result == "en"

    def test_validator_language_flip_high_confidence(self):
        validator = LanguageValidator()
        result1 = validator.validate("hi", 0.8, "en", "hi")
        assert result1 == "hi"

        result2 = validator.validate("en", 0.8, "en", "hi")
        assert result2 == "en"

    def test_validator_language_flip_low_confidence(self):
        validator = LanguageValidator()
        validator._last_validated = "en"

        result = validator.validate("hi", 0.5, "en", "hi")
        assert result == "en"

    def test_validator_keep_last_validated(self):
        validator = LanguageValidator()
        validator._last_validated = "hi"
        result = validator.validate("en", 0.4, "en", "hi")
        assert result == "hi"

    def test_validator_initial_state(self):
        validator = LanguageValidator()
        assert validator._last_validated is None

    def test_validator_reset(self):
        validator = LanguageValidator()
        validator._last_validated = "en"
        validator.reset()
        assert validator._last_validated is None

    def test_validator_detected_not_in_pair(self):
        validator = LanguageValidator()
        result = validator.validate("fr", 0.9, "en", "hi")
        assert result == "en"
        assert validator._last_validated is None

    def test_validator_confidence_borderline(self):
        validator = LanguageValidator()
        result = validator.validate("hi", 0.6, "en", "hi")
        assert result == "hi"
        assert validator._last_validated == "hi"

    def test_validator_confidence_just_above_threshold(self):
        validator = LanguageValidator()
        result = validator.validate("hi", 0.31, "en", "hi")
        assert result == "en"

    def test_validator_target_lang_detected_high_confidence(self):
        validator = LanguageValidator()
        validator._last_validated = "en"
        result = validator.validate("hi", 0.7, "en", "hi")
        assert result == "hi"
        assert validator._last_validated == "hi"


class TestContextEngine:
    def test_context_sliding_window(self):
        engine = ContextEngine()
        engine.add_segment("Hello", "Hola", "en", "es")
        engine.add_segment("How are you?", "¿Cómo estás?", "en", "es")
        engine.add_segment("I am fine", "Estoy bien", "en", "es")
        prompt = engine.build_context_prompt("en", "es")
        assert "Hello" in prompt
        assert "Hola" in prompt
        assert "How are you?" in prompt

    def test_context_with_recent_history(self):
        engine = ContextEngine()
        for i in range(10):
            engine.add_segment(f"Line {i}", f"Linea {i}", "en", "es")
        prompt = engine.build_context_prompt("en", "es")
        lines = prompt.strip().split("\n")
        assert len(lines) <= 6

    def test_context_with_seed_context(self):
        engine = ContextEngine()
        engine.set_seed_context("This is a conversation about technology.")
        engine.add_segment("What is AI?", "¿Qué es IA?", "en", "es")
        prompt = engine.build_context_prompt("en", "es")
        assert "technology" in prompt
        assert "AI" in prompt

    def test_context_empty_initial(self):
        engine = ContextEngine()
        prompt = engine.build_context_prompt("en", "es")
        assert prompt is None

    def test_context_empty_with_seed(self):
        engine = ContextEngine()
        engine.set_seed_context("Seed context")
        prompt = engine.build_context_prompt("en", "es")
        assert prompt == "Seed context"

    def test_context_clear_method(self):
        engine = ContextEngine()
        engine.add_segment("Hello", "Hola", "en", "es")
        engine.clear()
        prompt = engine.build_context_prompt("en", "es")
        assert prompt is None

    def test_context_max_segments(self):
        engine = ContextEngine()
        for i in range(20):
            engine.add_segment(f"Text {i}", f"Texto {i}", "en", "es")
        prompt = engine.build_context_prompt("en", "es")
        lines = prompt.strip().split("\n")
        assert "Text 19" in prompt
