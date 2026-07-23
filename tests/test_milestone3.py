from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.interfaces import SynthesisResult
from services.tts.router import MultilingualTTSRouter, SARVAM_LANGS
from services.audio.output import SoundDeviceOutput


class TestMilestone3TTSRouting:
    @pytest.mark.asyncio
    async def test_router_hindi_routes_to_sarvam(self):
        with patch("services.tts.router.SarvamTTS") as mock_sarvam:
            mock_instance = AsyncMock()
            mock_instance.synthesize.return_value = SynthesisResult(
                audio_data=np.ones(24000, dtype=np.float32).tobytes(),
                sample_rate=24000, duration_ms=1000.0,
            )
            mock_sarvam.return_value = mock_instance

            settings = MagicMock()
            router = MultilingualTTSRouter(settings)
            await router.start()

            result = await router.synthesize("नमस्ते", lang="hi")
            assert result.sample_rate == 24000
            mock_instance.synthesize.assert_called_once_with("नमस्ते", "hi")

    @pytest.mark.asyncio
    async def test_router_marathi_routes_to_sarvam(self):
        with patch("services.tts.router.SarvamTTS") as mock_sarvam:
            mock_instance = AsyncMock()
            mock_instance.synthesize.return_value = SynthesisResult(
                audio_data=np.ones(24000, dtype=np.float32).tobytes(),
                sample_rate=24000, duration_ms=1000.0,
            )
            mock_sarvam.return_value = mock_instance

            settings = MagicMock()
            router = MultilingualTTSRouter(settings)
            await router.start()

            result = await router.synthesize("नमस्कार", lang="mr")
            assert result.sample_rate == 24000

    @pytest.mark.asyncio
    async def test_router_all_indic_langs_use_sarvam(self):
        for lang in ["ta", "te", "kn", "ml", "gu", "bn", "pa", "or"]:
            assert lang in SARVAM_LANGS, f"{lang} should be in SARVAM_LANGS"

    @pytest.mark.asyncio
    async def test_router_english_routes_to_piper(self):
        with patch("services.tts.router.PiperTTS") as mock_piper:
            mock_instance = AsyncMock()
            mock_instance.synthesize.return_value = SynthesisResult(
                audio_data=np.ones(16000, dtype=np.float32).tobytes(),
                sample_rate=16000, duration_ms=500.0,
            )
            mock_piper.return_value = mock_instance

            settings = MagicMock()
            router = MultilingualTTSRouter(settings)
            await router.start()

            result = await router.synthesize("Hello world", lang="en")
            assert result.sample_rate == 16000
            mock_instance.synthesize.assert_called_once_with("Hello world", "en")

    @pytest.mark.asyncio
    async def test_router_sarvam_falls_back_to_piper(self):
        with patch("services.tts.router.SarvamTTS") as mock_sarvam:
            mock_sarvam_instance = AsyncMock()
            mock_sarvam_instance.synthesize.side_effect = RuntimeError("Sarvam failed")
            mock_sarvam.return_value = mock_sarvam_instance

            with patch("services.tts.router.PiperTTS") as mock_piper:
                mock_piper_instance = AsyncMock()
                mock_piper_instance.synthesize.return_value = SynthesisResult(
                    audio_data=np.ones(16000, dtype=np.float32).tobytes(),
                    sample_rate=16000, duration_ms=500.0,
                )
                mock_piper.return_value = mock_piper_instance

                settings = MagicMock()
                router = MultilingualTTSRouter(settings)
                await router.start()

                result = await router.synthesize("नमस्ते", lang="hi")
                assert result.sample_rate == 16000
                mock_piper_instance.synthesize.assert_called_once()

    @pytest.mark.asyncio
    async def test_router_set_voice_propagates_to_piper(self):
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
    async def test_router_synthesize_stream_routes_per_chunk(self):
        with patch("services.tts.router.PiperTTS") as mock_piper:
            mock_piper_instance = AsyncMock()
            mock_piper_instance.synthesize.return_value = SynthesisResult(
                audio_data=np.ones(16000, dtype=np.float32).tobytes(),
                sample_rate=16000, duration_ms=500.0,
            )
            mock_piper.return_value = mock_piper_instance

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
            assert mock_piper_instance.synthesize.call_count == 2


class TestMilestone3VirtualMic:
    @pytest.mark.asyncio
    async def test_output_initialization_defaults(self):
        settings = MagicMock()
        settings.sample_rate = 16000
        settings.output_device_id = None
        settings.virtual_mic_enabled = False
        settings.tts_playback_enabled = True
        settings.volume = 1.0
        settings.playback_delay_s = 0.0

        output = SoundDeviceOutput(settings)
        assert output._volume == 1.0
        assert output._running is False

    def test_is_valid_output_device_valid(self):
        with patch("sounddevice.query_devices") as mock_query:
            mock_query.return_value = {"max_output_channels": 2}
            result = SoundDeviceOutput._is_valid_output_device(0)
            assert result is True

    def test_is_valid_output_device_invalid(self):
        with patch("sounddevice.query_devices") as mock_query:
            mock_query.return_value = {"max_output_channels": 0}
            result = SoundDeviceOutput._is_valid_output_device(0)
            assert result is False

    def test_is_valid_output_device_none(self):
        result = SoundDeviceOutput._is_valid_output_device(None)
        assert result is True

    @pytest.mark.asyncio
    async def test_output_set_volume_clamps(self):
        settings = MagicMock()
        output = SoundDeviceOutput(settings)
        output.set_volume(1.5)
        assert output._volume == 1.0
        output.set_volume(-0.5)
        assert output._volume == 0.0
        output.set_volume(0.75)
        assert output._volume == 0.75

    @pytest.mark.asyncio
    async def test_output_set_muted(self):
        settings = MagicMock()
        output = SoundDeviceOutput(settings)
        output.set_muted(True)
        assert output._muted is True
        output.set_muted(False)
        assert output._muted is False

    @pytest.mark.asyncio
    async def test_output_set_delay(self):
        settings = MagicMock()
        output = SoundDeviceOutput(settings)
        output.set_delay(0.5)
        assert output._delay_s == 0.5
        output.set_delay(-1.0)
        assert output._delay_s == 0.0

    @pytest.mark.asyncio
    async def test_output_enqueue_and_volume_playback(self):
        settings = MagicMock()
        output = SoundDeviceOutput(settings)
        output._running = True
        output._play_queue = __import__("queue").Queue()

        import threading
        results = []

        def draining_thread():
            while output._running or not output._play_queue.empty():
                try:
                    raw, sr = output._play_queue.get(timeout=0.1)
                    if raw is None:
                        break
                    results.append((len(raw), sr))
                except __import__("queue").Empty:
                    continue

        t = threading.Thread(target=draining_thread, daemon=True)
        t.start()

        output._enqueue(b"test_data", 16000)
        await __import__("asyncio").sleep(0.05)
        output._running = False
        t.join(timeout=1.0)

        assert len(results) >= 1
        assert results[0][1] == 16000
