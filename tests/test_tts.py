from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.interfaces import BaseTTS, SynthesisResult
from services.tts.piper import PiperTTS
from services.tts.sarvam import SarvamTTS
from services.tts.router import MultilingualTTSRouter, SARVAM_LANGS, _lang_family
from services.tts.voice_cache import find_voice_model, SEARCH_DIRS


class TestTTSInterface:
    def test_base_tts_abstract(self):
        with pytest.raises(TypeError):
            BaseTTS()

    def test_tts_result_dataclass(self):
        result = SynthesisResult(
            audio_data=b"test", sample_rate=24000, duration_ms=1000.0, is_streaming=False,
        )
        assert result.audio_data == b"test"
        assert result.sample_rate == 24000
        assert result.duration_ms == 1000.0
        assert result.is_streaming is False

    def test_tts_result_streaming_flag(self):
        result = SynthesisResult(
            audio_data=b"", sample_rate=16000, duration_ms=0.0, is_streaming=True,
        )
        assert result.is_streaming is True


class TestPiperTTS:
    @pytest.mark.asyncio
    async def test_piper_initialization(self):
        with patch("piper.PiperVoice.load") as mock_load:
            with patch("services.tts.piper.find_voice_model", return_value="/fake/path/model.onnx"):
                with patch("os.path.exists", return_value=True):
                    mock_voice = MagicMock()
                    mock_load.return_value = mock_voice

                    settings = MagicMock()
                    settings.piper_voice = "en_US-lessac-medium"

                    tts = PiperTTS(settings)
                    await tts.start()

                    assert tts._voice is not None
                    mock_load.assert_called_once()

    @pytest.mark.asyncio
    async def test_piper_synthesize_success(self):
        with patch("piper.PiperVoice.load") as mock_load:
            with patch("services.tts.piper.find_voice_model", return_value="/fake/path/model.onnx"):
                with patch("os.path.exists", return_value=True):
                    mock_voice = MagicMock()
                    mock_chunk = MagicMock()
                    mock_chunk.audio_float_array = np.ones(16000, dtype=np.float32) * 0.1
                    mock_voice.synthesize.return_value = [mock_chunk]
                    mock_voice.config.sample_rate = 16000
                    mock_load.return_value = mock_voice

                    settings = MagicMock()
                    settings.piper_voice = "en_US-lessac-medium"

                    tts = PiperTTS(settings)
                    await tts.start()

                    result = await tts.synthesize("Hello world", lang="en")

                    assert len(result.audio_data) > 0
                    assert result.sample_rate == 16000
                    assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_piper_synthesize_empty_text(self):
        with patch("piper.PiperVoice.load") as mock_load:
            with patch("services.tts.piper.find_voice_model", return_value="/fake/path/model.onnx"):
                with patch("os.path.exists", return_value=True):
                    mock_voice = MagicMock()
                    mock_voice.synthesize.return_value = []
                    mock_voice.config.sample_rate = 16000
                    mock_load.return_value = mock_voice

                    settings = MagicMock()
                    settings.piper_voice = "en_US-lessac-medium"

                    tts = PiperTTS(settings)
                    await tts.start()

                    result = await tts.synthesize("", lang="en")
                    assert len(result.audio_data) > 0
                    assert result.duration_ms == 1000.0

    @pytest.mark.asyncio
    async def test_piper_load_voice_api(self):
        with patch("piper.PiperVoice.load") as mock_load:
            with patch("services.tts.piper.find_voice_model", return_value="/fake/path/model.onnx"):
                with patch("os.path.exists", return_value=True):
                    mock_voice = MagicMock()
                    mock_load.return_value = mock_voice

                    settings = MagicMock()
                    settings.piper_voice = "en_US-lessac-medium"

                    tts = PiperTTS(settings)
                    await tts.start()
                    await tts.set_voice("en_GB-seminary-medium")

                    assert tts._voice_name == "en_GB-seminary-medium"

    @pytest.mark.asyncio
    async def test_piper_voice_discovery_paths(self):
        with patch("piper.PiperVoice.load") as mock_load:
            with patch("services.tts.piper.find_voice_model", return_value="/custom/path/voice.onnx"):
                with patch("os.path.exists", return_value=True):
                    mock_voice = MagicMock()
                    mock_load.return_value = mock_voice

                    settings = MagicMock()
                    settings.piper_voice = "custom_voice"

                    tts = PiperTTS(settings)
                    await tts.start()

                    assert tts._voice is not None

    @pytest.mark.asyncio
    async def test_piper_use_cuda_false(self):
        with patch("piper.PiperVoice.load") as mock_load:
            with patch("services.tts.piper.find_voice_model", return_value="/fake/path/model.onnx"):
                with patch("os.path.exists", return_value=True):
                    mock_voice = MagicMock()
                    mock_load.return_value = mock_voice

                    settings = MagicMock()
                    settings.piper_voice = "en_US-lessac-medium"

                    tts = PiperTTS(settings)
                    await tts.start()

                    _, kwargs = mock_load.call_args
                    assert "use_cuda" in kwargs
                    assert kwargs["use_cuda"] is False

    @pytest.mark.asyncio
    async def test_piper_voice_not_found(self):
        with patch("services.tts.piper.find_voice_model", return_value=None):
            settings = MagicMock()
            settings.piper_voice = "nonexistent-voice"

            tts = PiperTTS(settings)
            await tts.start()

            assert tts._voice is None

    @pytest.mark.asyncio
    async def test_piper_config_not_found(self):
        with patch("services.tts.piper.find_voice_model", return_value="/fake/path/model.onnx"):
            with patch("os.path.exists", return_value=False):
                settings = MagicMock()
                settings.piper_voice = "test_voice"

                tts = PiperTTS(settings)
                await tts.start()
                assert tts._voice is None

    @pytest.mark.asyncio
    async def test_piper_no_voice_synthesize_returns_silence(self):
        settings = MagicMock()
        settings.piper_voice = "nonexistent"

        tts = PiperTTS(settings)
        result = await tts.synthesize("Hello")
        assert result.sample_rate == 16000
        assert result.duration_ms == 1000.0

    @pytest.mark.asyncio
    async def test_piper_synthesize_error_returns_silence(self):
        with patch("piper.PiperVoice.load") as mock_load:
            with patch("services.tts.piper.find_voice_model", return_value="/fake/path/model.onnx"):
                with patch("os.path.exists", return_value=True):
                    mock_voice = MagicMock()
                    mock_voice.synthesize.side_effect = RuntimeError("Synthesis failed")
                    mock_voice.config.sample_rate = 16000
                    mock_load.return_value = mock_voice

                    settings = MagicMock()
                    settings.piper_voice = "en_US-lessac-medium"

                    tts = PiperTTS(settings)
                    await tts.start()

                    result = await tts.synthesize("Hello")
                    assert result.sample_rate == 16000
                    assert result.duration_ms == 1000.0

    @pytest.mark.asyncio
    async def test_piper_synthesize_stream(self):
        with patch("piper.PiperVoice.load") as mock_load:
            with patch("services.tts.piper.find_voice_model", return_value="/fake/path/model.onnx"):
                with patch("os.path.exists", return_value=True):
                    mock_voice = MagicMock()
                    mock_chunk = MagicMock()
                    mock_chunk.audio_float_array = np.ones(16000, dtype=np.float32) * 0.1
                    mock_voice.synthesize.return_value = [mock_chunk]
                    mock_voice.config.sample_rate = 16000
                    mock_load.return_value = mock_voice

                    settings = MagicMock()
                    settings.piper_voice = "en_US-lessac-medium"

                    tts = PiperTTS(settings)
                    await tts.start()

                    async def text_gen():
                        yield "Hello"
                        yield "World"

                    results = []
                    async for r in tts.synthesize_stream(text_gen()):
                        results.append(r)

                    assert len(results) == 2

    @pytest.mark.asyncio
    async def test_piper_stop_sets_voice_none(self):
        with patch("piper.PiperVoice.load") as mock_load:
            with patch("services.tts.piper.find_voice_model", return_value="/fake/path/model.onnx"):
                with patch("os.path.exists", return_value=True):
                    mock_voice = MagicMock()
                    mock_load.return_value = mock_voice

                    settings = MagicMock()
                    settings.piper_voice = "en_US-lessac-medium"

                    tts = PiperTTS(settings)
                    await tts.start()
                    assert tts._voice is not None

                    await tts.stop()
                    assert tts._voice is None

    @pytest.mark.asyncio
    async def test_piper_set_speed_noop(self):
        settings = MagicMock()
        tts = PiperTTS(settings)
        await tts.set_speed(1.5)


def _make_wav_bytes(sample_rate: int = 24000, duration_s: float = 1.0) -> bytes:
    """Create valid WAV bytes containing sine wave audio."""
    import io
    import wave
    import struct
    import math
    n_samples = int(sample_rate * duration_s)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            val = int(math.sin(2 * math.pi * 440 * i / sample_rate) * 32767 * 0.3)
            wf.writeframes(struct.pack("<h", val))
    return buf.getvalue()


class TestSarvamTTS:
    @pytest.mark.asyncio
    async def test_sarvam_initialization(self):
        settings = MagicMock()
        settings.sarvam_api_key = "test-key"
        settings.sarvam_voice = "shubh"
        settings.sarvam_lang = "hi-IN"
        settings.sarvam_timeout_s = 30.0

        tts = SarvamTTS(settings)
        await tts.start()

        assert tts._api_key == "test-key"
        assert tts._speaker == "shubh"
        assert tts._lang == "hi-IN"

    @pytest.mark.asyncio
    async def test_sarvam_initialization_no_key(self):
        settings = MagicMock()
        settings.sarvam_api_key = ""
        settings.sarvam_voice = "shubh"
        settings.sarvam_lang = "hi-IN"
        settings.sarvam_timeout_s = 30.0

        tts = SarvamTTS(settings)
        await tts.start()

        assert tts._api_key == ""

    @pytest.mark.asyncio
    async def test_sarvam_synthesize_success(self):
        import base64
        wav_bytes = _make_wav_bytes(24000, 0.5)
        b64_audio = base64.b64encode(wav_bytes).decode()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"audios": [b64_audio]}
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            settings = MagicMock()
            settings.sarvam_api_key = "test-key"
            settings.sarvam_voice = "shubh"
            settings.sarvam_lang = "hi-IN"
            settings.sarvam_timeout_s = 30.0

            tts = SarvamTTS(settings)
            await tts.start()

            result = await tts.synthesize("नमस्ते", lang="hi")
            assert result.sample_rate == 24000
            assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_sarvam_api_timeout(self):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.side_effect = TimeoutError("Request timed out")
            mock_client_cls.return_value = mock_client

            settings = MagicMock()
            settings.sarvam_api_key = "test-key"
            settings.sarvam_voice = "shubh"
            settings.sarvam_lang = "hi-IN"
            settings.sarvam_timeout_s = 30.0

            tts = SarvamTTS(settings)
            await tts.start()

            result = await tts.synthesize("नमस्ते")
            assert result.sample_rate == 8000
            assert result.duration_ms == 1000.0

    @pytest.mark.asyncio
    async def test_sarvam_decode_base64_audio(self):
        import base64
        wav_bytes = _make_wav_bytes(24000, 0.3)
        b64_audio = base64.b64encode(wav_bytes).decode()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"audios": [b64_audio]}
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            settings = MagicMock()
            settings.sarvam_api_key = "test-key"
            settings.sarvam_voice = "shubh"
            settings.sarvam_lang = "hi-IN"
            settings.sarvam_timeout_s = 30.0

            tts = SarvamTTS(settings)
            await tts.start()

            result = await tts.synthesize("नमस्ते")
            assert len(result.audio_data) > 0
            assert result.sample_rate == 24000

    @pytest.mark.asyncio
    async def test_sarvam_api_error_status(self):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            settings = MagicMock()
            settings.sarvam_api_key = "bad-key"
            settings.sarvam_voice = "shubh"
            settings.sarvam_lang = "hi-IN"
            settings.sarvam_timeout_s = 30.0

            tts = SarvamTTS(settings)
            await tts.start()

            result = await tts.synthesize("नमस्ते")
            assert result.sample_rate == 8000
            assert result.duration_ms == 1000.0

    @pytest.mark.asyncio
    async def test_sarvam_no_api_key_returns_silence(self):
        settings = MagicMock()
        settings.sarvam_api_key = ""
        settings.sarvam_voice = "shubh"
        settings.sarvam_lang = "hi-IN"
        settings.sarvam_timeout_s = 30.0

        tts = SarvamTTS(settings)
        await tts.start()

        result = await tts.synthesize("Hello")
        assert result.sample_rate == 8000
        assert result.duration_ms == 1000.0

    @pytest.mark.asyncio
    async def test_sarvam_empty_audio_response(self):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"audios": []}
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            settings = MagicMock()
            settings.sarvam_api_key = "test-key"
            settings.sarvam_voice = "shubh"
            settings.sarvam_lang = "hi-IN"
            settings.sarvam_timeout_s = 30.0

            tts = SarvamTTS(settings)
            await tts.start()

            result = await tts.synthesize("नमस्ते")
            assert result.duration_ms == 1000.0

    @pytest.mark.asyncio
    async def test_sarvam_synthesize_stream(self):
        import base64
        wav_bytes = _make_wav_bytes(24000, 0.3)
        b64_audio = base64.b64encode(wav_bytes).decode()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"audios": [b64_audio]}
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            settings = MagicMock()
            settings.sarvam_api_key = "test-key"
            settings.sarvam_voice = "shubh"
            settings.sarvam_lang = "hi-IN"
            settings.sarvam_timeout_s = 30.0

            tts = SarvamTTS(settings)
            await tts.start()

            async def text_gen():
                yield "नमस्ते"
                yield "दुनिया"

            results = []
            async for r in tts.synthesize_stream(text_gen()):
                results.append(r)

            assert len(results) == 2

    @pytest.mark.asyncio
    async def test_sarvam_set_voice(self):
        settings = MagicMock()
        settings.sarvam_api_key = "test-key"
        settings.sarvam_voice = "shubh"
        settings.sarvam_lang = "hi-IN"
        settings.sarvam_timeout_s = 30.0

        tts = SarvamTTS(settings)
        await tts.set_voice("neel")
        assert tts._speaker == "neel"

    def test_resolve_speaker_known_lang(self):
        settings = MagicMock()
        tts = SarvamTTS(settings)
        assert tts._resolve_speaker("hi") == "shubh"
        assert tts._resolve_speaker("hi-IN") == "shubh"
        assert tts._resolve_speaker("ta") == "shubh"
        assert tts._resolve_speaker("mr") == "shubh"

    def test_resolve_speaker_unknown_lang_falls_back_to_default(self):
        settings = MagicMock()
        tts = SarvamTTS(settings)
        assert tts._resolve_speaker("fr") == "shubh"
        assert tts._resolve_speaker("en") == "shubh"
        assert tts._resolve_speaker("es") == "shubh"

    def test_resolve_speaker_invalid_speaker_falls_back_to_default(self):
        settings = MagicMock()
        settings.sarvam_voice = "unknown_invalid_voice"
        tts = SarvamTTS(settings)
        assert tts._resolve_speaker("en") == "shubh"

    def test_resolve_speaker_returns_mapped_speaker_when_valid(self):
        settings = MagicMock()
        settings.sarvam_voice = "anushka"
        tts = SarvamTTS(settings)
        assert tts._resolve_speaker("hi") == "shubh"


class TestTTSRouter:
    @pytest.mark.asyncio
    async def test_router_english_to_piper(self):
        with patch("services.tts.router.PiperTTS") as mock_piper:
            mock_piper_instance = AsyncMock()
            mock_piper.return_value = mock_piper_instance
            mock_result = SynthesisResult(
                audio_data=b"test", sample_rate=16000, duration_ms=500.0,
            )
            mock_piper_instance.synthesize.return_value = mock_result

            settings = MagicMock()
            router = MultilingualTTSRouter(settings)
            await router.start()

            result = await router.synthesize("Hello world", lang="en")

            assert result is mock_result
            mock_piper_instance.synthesize.assert_called_once_with("Hello world", "en")

    @pytest.mark.asyncio
    async def test_router_hindi_to_sarvam(self):
        with patch("services.tts.router.SarvamTTS") as mock_sarvam:
            mock_sarvam_instance = AsyncMock()
            mock_sarvam.return_value = mock_sarvam_instance
            mock_result = SynthesisResult(
                audio_data=b"test", sample_rate=24000, duration_ms=500.0,
            )
            mock_sarvam_instance.synthesize.return_value = mock_result

            settings = MagicMock()
            router = MultilingualTTSRouter(settings)
            await router.start()

            result = await router.synthesize("नमस्ते", lang="hi")

            assert result is mock_result
            mock_sarvam_instance.synthesize.assert_called_once_with("नमस्ते", "hi")

    @pytest.mark.asyncio
    async def test_router_unknown_language_fallback(self):
        with patch("services.tts.router.PiperTTS") as mock_piper:
            mock_piper_instance = AsyncMock()
            mock_piper.return_value = mock_piper_instance
            mock_result = SynthesisResult(
                audio_data=b"test", sample_rate=16000, duration_ms=500.0,
            )
            mock_piper_instance.synthesize.return_value = mock_result

            settings = MagicMock()
            router = MultilingualTTSRouter(settings)
            await router.start()

            result = await router.synthesize("Bonjour", lang="fr")

            assert result is mock_result
            mock_piper_instance.synthesize.assert_called_once_with("Bonjour", "fr")

    @pytest.mark.asyncio
    async def test_router_fallback_chain_on_failure(self):
        with patch("services.tts.router.PiperTTS") as mock_piper:
            mock_piper_instance = AsyncMock()
            mock_piper_instance.synthesize.side_effect = RuntimeError("Piper failed")
            mock_piper.return_value = mock_piper_instance

            with patch("services.tts.router.SarvamTTS") as mock_sarvam:
                mock_sarvam_instance = AsyncMock()
                mock_sarvam.return_value = mock_sarvam_instance
                mock_result = SynthesisResult(
                    audio_data=b"sarvam", sample_rate=24000, duration_ms=500.0,
                )
                mock_sarvam_instance.synthesize.return_value = mock_result

                settings = MagicMock()
                router = MultilingualTTSRouter(settings)
                await router.start()

                result = await router.synthesize("Hello", lang="en")

                assert result.audio_data == b"sarvam"

    @pytest.mark.asyncio
    async def test_router_both_engines_fail_return_silence(self):
        with patch("services.tts.router.PiperTTS") as mock_piper:
            mock_piper_instance = AsyncMock()
            mock_piper_instance.synthesize.side_effect = RuntimeError("Piper failed")
            mock_piper.return_value = mock_piper_instance

            with patch("services.tts.router.SarvamTTS") as mock_sarvam:
                mock_sarvam_instance = AsyncMock()
                mock_sarvam_instance.synthesize.side_effect = RuntimeError("Sarvam failed")
                mock_sarvam.return_value = mock_sarvam_instance

                settings = MagicMock()
                router = MultilingualTTSRouter(settings)
                await router.start()

                result = await router.synthesize("Hello", lang="en")

                assert result.sample_rate == 16000
                assert result.duration_ms == 1000.0

    @pytest.mark.asyncio
    async def test_router_not_running_returns_silence(self):
        settings = MagicMock()
        router = MultilingualTTSRouter(settings)
        result = await router.synthesize("Hello", lang="en")
        assert result.sample_rate == 16000

    @pytest.mark.asyncio
    async def test_router_sarvam_lang_set(self):
        assert "hi" in SARVAM_LANGS
        assert "mr" in SARVAM_LANGS
        assert "en" in SARVAM_LANGS  # English now supported via Sarvam en-IN

    def test_lang_family(self):
        assert _lang_family("en-US") == "en"
        assert _lang_family("hi-IN") == "hi"
        assert _lang_family("fr") == "fr"

    @pytest.mark.asyncio
    async def test_router_synthesize_stream(self):
        with patch("services.tts.router.PiperTTS") as mock_piper:
            mock_piper_instance = AsyncMock()
            mock_piper.return_value = mock_piper_instance
            mock_result = SynthesisResult(
                audio_data=b"test", sample_rate=16000, duration_ms=500.0,
            )
            mock_piper_instance.synthesize.return_value = mock_result

            settings = MagicMock()
            router = MultilingualTTSRouter(settings)
            await router.start()

            async def text_gen():
                yield "Hello"
                yield "World"

            results = []
            async for r in router.synthesize_stream(text_gen(), lang="en"):
                results.append(r)

            assert len(results) == 2

    @pytest.mark.asyncio
    async def test_router_set_voice_piper_only(self):
        with patch("services.tts.router.PiperTTS") as mock_piper:
            mock_piper_instance = AsyncMock()
            mock_piper.return_value = mock_piper_instance

            settings = MagicMock()
            router = MultilingualTTSRouter(settings)
            await router.start()
            await router._get_piper()

            await router.set_voice("en_GB-voice")
            mock_piper_instance.set_voice.assert_called_once_with("en_GB-voice")

    @pytest.mark.asyncio
    async def test_router_stops_sub_engines(self):
        with patch("services.tts.router.PiperTTS") as mock_piper:
            mock_piper_instance = AsyncMock()
            mock_piper.return_value = mock_piper_instance

            with patch("services.tts.router.SarvamTTS") as mock_sarvam:
                mock_sarvam_instance = AsyncMock()
                mock_sarvam.return_value = mock_sarvam_instance

                settings = MagicMock()
                router = MultilingualTTSRouter(settings)
                await router.start()
                await router._get_piper()
                await router._get_sarvam()

                await router.stop()

                mock_piper_instance.stop.assert_called_once()
                mock_sarvam_instance.stop.assert_called_once()


class TestVoiceCache:
    def test_voice_discovery_cwd(self):
        with patch("os.path.isdir", return_value=True):
            with patch("os.walk") as mock_walk:
                mock_walk.return_value = [
                    ("/cwd", [], ["voice.onnx", "other.txt"]),
                ]
                with patch("services.tts.voice_cache.SEARCH_DIRS", [os.getcwd()]):
                    result = find_voice_model("voice")
                    assert result is not None
                    assert result.endswith(".onnx")

    def test_voice_discovery_voices_dir(self):
        with patch("os.path.isdir", return_value=True):
            with patch("os.walk") as mock_walk:
                mock_walk.return_value = [
                    ("/voices", [], ["en_US-lessac-medium.onnx"]),
                ]
                with patch("services.tts.voice_cache.SEARCH_DIRS", ["/voices"]):
                    result = find_voice_model("en_US-lessac-medium")
                    assert result is not None

    def test_voice_discovery_env_var(self):
        with patch("os.path.isdir", return_value=True):
            with patch("os.walk") as mock_walk:
                mock_walk.return_value = [
                    ("/envvoices", [], ["custom_voice.onnx"]),
                ]
                with patch.dict("os.environ", {"PIPER_VOICE_DIR": "/envvoices"}):
                    result = find_voice_model("custom_voice")
                    assert result is not None

    def test_voice_discovery_not_found(self):
        with patch("os.path.isdir", return_value=True):
            with patch("os.walk") as mock_walk:
                mock_walk.return_value = [
                    ("/voices", [], ["other_voice.onnx"]),
                ]
                with patch("services.tts.voice_cache.SEARCH_DIRS", ["/voices"]):
                    with patch.dict("os.environ", {}, clear=True):
                        result = find_voice_model("nonexistent_voice")
                        assert result is None

    def test_voice_discovery_with_hyphen_in_name(self):
        with patch("os.path.isdir", return_value=True):
            with patch("os.walk") as mock_walk:
                mock_walk.return_value = [
                    ("/voices", [], ["en_US-lessac-medium.onnx"]),
                ]
                with patch("services.tts.voice_cache.SEARCH_DIRS", ["/voices"]):
                    result = find_voice_model("en_US-lessac-medium")
                    assert result == "/voices/en_US-lessac-medium.onnx"

    def test_voice_discovery_nonexistent_dir(self):
        with patch("os.path.isdir", return_value=False):
            result = find_voice_model("any_voice")
            assert result is None

    def test_voice_discovery_only_onnx_files(self):
        with patch("os.path.isdir", return_value=True):
            with patch("os.walk") as mock_walk:
                mock_walk.return_value = [
                    ("/voices", [], ["voice.json", "voice.txt", "voice.onnx"]),
                ]
                with patch("services.tts.voice_cache.SEARCH_DIRS", ["/voices"]):
                    result = find_voice_model("voice")
                    assert result == "/voices/voice.onnx"
