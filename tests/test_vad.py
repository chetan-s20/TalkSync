from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.interfaces import BaseVAD, VADResult
from config.settings import VADSettings
from services.vad.silero_vad import SileroVAD


class TestVADInterface:
    def test_base_vad_abstract(self):
        with pytest.raises(TypeError):
            BaseVAD()

    def test_vad_result_dataclass(self):
        result = VADResult(is_speech=True, speech_start=0.0, speech_end=1.0, confidence=0.85)
        assert result.is_speech is True
        assert result.confidence == 0.85
        assert result.speech_start == 0.0
        assert result.speech_end == 1.0

    def test_vad_result_no_speech(self):
        result = VADResult(is_speech=False, confidence=0.1)
        assert result.is_speech is False
        assert result.speech_start is None
        assert result.speech_end is None

    def test_vad_result_repr(self):
        result = VADResult(is_speech=True, confidence=0.95)
        r = repr(result)
        assert "VADResult" in r
        assert "is_speech=True" in r


class TestSileroVAD:
    def test_vad_initialization_default(self):
        settings = VADSettings()
        with patch("torch.hub.load") as mock_load:
            mock_model = MagicMock()
            mock_load.return_value = (mock_model, None)
            vad = SileroVAD(settings)
            assert vad is not None
            assert vad.settings.threshold == 0.3
            assert vad.settings.min_speech_duration_ms == 250

    def test_vad_initialization_custom_threshold(self):
        settings = VADSettings(threshold=0.8)
        with patch("torch.hub.load") as mock_load:
            mock_model = MagicMock()
            mock_load.return_value = (mock_model, None)
            vad = SileroVAD(settings)
            assert vad is not None
            assert vad.settings.threshold == 0.8

    def test_vad_start_success(self):
        settings = VADSettings()
        with patch("torch.hub.load") as mock_load:
            mock_model = MagicMock()
            mock_load.return_value = (mock_model, None)
            vad = SileroVAD(settings)
            import asyncio
            asyncio.run(vad.start())
            assert vad._running is True
            assert vad._model is not None

    def test_vad_start_failure_fallback(self):
        settings = VADSettings()
        with patch("torch.hub.load", side_effect=Exception("Load failed")):
            vad = SileroVAD(settings)
            import asyncio
            asyncio.run(vad.start())
            assert vad._running is True
            assert vad._model is None

    def test_vad_stop(self):
        settings = VADSettings()
        with patch("torch.hub.load") as mock_load:
            mock_model = MagicMock()
            mock_load.return_value = (mock_model, None)
            vad = SileroVAD(settings)
            import asyncio
            asyncio.run(vad.start())
            asyncio.run(vad.stop())
            assert vad._running is False
            assert vad._model is None

    def test_vad_process_speech(self):
        settings = VADSettings()
        with patch("torch.hub.load") as mock_load:
            mock_model = MagicMock()
            mock_model.return_value.item.return_value = 0.6
            mock_load.return_value = (mock_model, None)
            vad = SileroVAD(settings)
            import asyncio
            asyncio.run(vad.start())

            audio = np.random.randn(480).astype(np.float32)
            chunk = MagicMock()
            chunk.data = audio.tobytes()

            results = []
            async def collect():
                async for result in vad.process(chunk):
                    results.append(result)

            asyncio.run(collect())
            assert len(results) == 1
            assert results[0].is_speech is True
            assert results[0].confidence == pytest.approx(0.6, abs=0.1)

    def test_vad_process_no_speech(self):
        settings = VADSettings()
        with patch("torch.hub.load") as mock_load:
            mock_model = MagicMock()
            mock_model.return_value.item.return_value = 0.1
            mock_load.return_value = (mock_model, None)
            vad = SileroVAD(settings)
            import asyncio
            asyncio.run(vad.start())

            audio = np.random.randn(480).astype(np.float32) * 0.001
            chunk = MagicMock()
            chunk.data = audio.tobytes()

            results = []
            async def collect():
                async for result in vad.process(chunk):
                    results.append(result)

            asyncio.run(collect())
            assert len(results) == 1
            assert results[0].is_speech is False

    def test_vad_reset_state(self):
        settings = VADSettings()
        with patch("torch.hub.load") as mock_load:
            mock_model = MagicMock()
            mock_load.return_value = (mock_model, None)
            vad = SileroVAD(settings)
            import asyncio
            asyncio.run(vad.start())
            assert vad._running is True
            asyncio.run(vad.stop())
            assert vad._running is False
            assert vad._model is None

    def test_vad_source_tagging(self):
        settings = VADSettings()
        with patch("torch.hub.load") as mock_load:
            mock_model = MagicMock()
            mock_load.return_value = (mock_model, None)
            vad = SileroVAD(settings)
            import asyncio
            asyncio.run(vad.start())

            for source in ["mic", "loopback"]:
                chunk = MagicMock()
                chunk.data = np.random.randn(480).tobytes()

                results = []
                async def collect():
                    async for result in vad.process(chunk):
                        results.append(result)

                asyncio.run(collect())
                assert len(results) == 1

    def test_vad_empty_audio(self):
        settings = VADSettings()
        with patch("torch.hub.load") as mock_load:
            mock_model = MagicMock()
            mock_load.return_value = (mock_model, None)
            vad = SileroVAD(settings)
            import asyncio
            asyncio.run(vad.start())

            audio = np.zeros(480, dtype=np.float32)
            chunk = MagicMock()
            chunk.data = audio.tobytes()

            results = []
            async def collect():
                async for result in vad.process(chunk):
                    results.append(result)

            asyncio.run(collect())
            assert len(results) == 1

    def test_vad_different_sample_rates(self):
        settings = VADSettings()
        with patch("torch.hub.load") as mock_load:
            mock_model = MagicMock()
            mock_load.return_value = (mock_model, None)
            vad = SileroVAD(settings)
            import asyncio
            asyncio.run(vad.start())

            for sr in [8000, 16000, 44100, 48000]:
                audio = np.random.randn(sr).astype(np.float32)
                chunk = MagicMock()
                chunk.data = audio.tobytes()

                results = []
                async def collect():
                    async for result in vad.process(chunk):
                        results.append(result)

                asyncio.run(collect())
                assert len(results) == 1

    @pytest.mark.asyncio
    async def test_vad_integration(self):
        settings = VADSettings()
        with patch("torch.hub.load") as mock_load:
            mock_model = MagicMock()
            mock_load.return_value = (mock_model, None)
            vad = SileroVAD(settings)
            await vad.start()

            audio = np.random.randn(480).astype(np.float32)
            chunk = MagicMock()
            chunk.data = audio.tobytes()

            async for result in vad.process(chunk):
                assert isinstance(result, VADResult)
                assert "is_speech" in result.__dict__

            await vad.stop()


class TestVADEdgeCases:
    def test_vad_process_error_handling(self):
        settings = VADSettings()
        with patch("torch.hub.load") as mock_load:
            mock_model = MagicMock()
            mock_load.return_value = (mock_model, None)
            vad = SileroVAD(settings)
            import asyncio
            asyncio.run(vad.start())

            chunk = MagicMock()
            chunk.data = b"invalid"

            results = []
            async def collect():
                async for result in vad.process(chunk):
                    results.append(result)

            asyncio.run(collect())
            assert len(results) == 1
            assert results[0].is_speech is False

    def test_vad_model_none_fallback(self):
        settings = VADSettings()
        vad = SileroVAD(settings)
        vad._model = None
        vad._running = True

        audio = np.zeros(480, dtype=np.float32)
        chunk = MagicMock()
        chunk.data = audio.tobytes()

        results = []
        async def collect():
            async for result in vad.process(chunk):
                results.append(result)

        import asyncio
        asyncio.run(collect())
        assert len(results) == 1
        assert results[0].is_speech is False
        assert results[0].confidence == 0.2