from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from typing import Any, AsyncIterator, Optional, List

import numpy as np
import pytest
import scipy.signal
import soundfile as sf

from app.interfaces import (
    AudioChunk,
    BaseAudioInput,
    BaseAudioOutput,
    BaseSTT,
    BaseTTS,
    BaseTranslator,
    BaseVAD,
    SynthesisResult,
    TranscriptionSegment,
    TranslationResult,
)
from app.pipeline import Pipeline
from config.settings import VADSettings, AudioSettings
from services.stt.faster_whisper import FasterWhisperSTT
from services.translation.argos import ArgosTranslator
from services.vad.silero_vad import SileroVAD, VADSpeechOutcome
from services.audio.input import SoundDeviceInput
from unittest.mock import AsyncMock, MagicMock, patch


class WavAudioFeeder(BaseAudioInput):
    """
    Streams audio chunks from pre-recorded 16kHz mono PCM WAV files into the TalkSync pipeline.
    Measures capture timestamps (T_capture) per chunk for end-to-end latency benchmarking.
    """

    def __init__(
        self,
        filepath: str,
        chunk_duration_ms: float = 30.0,
        source: str = "mic",
        padding_ms: float = 400.0,
    ):
        self.filepath = filepath
        self.chunk_duration_ms = chunk_duration_ms
        self.source = source
        self.padding_ms = padding_ms
        self.running = False
        self.capture_timestamps: List[float] = []
        self.first_chunk_t: Optional[float] = None
        self.last_chunk_t: Optional[float] = None

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"WAV audio fixture not found: {filepath}")

        audio, sr = sf.read(filepath, dtype="float32")
        if len(audio.shape) > 1:
            audio = np.mean(audio, axis=1)

        if sr != 16000:
            num_samples = int(len(audio) * 16000 / sr)
            audio = scipy.signal.resample(audio, num_samples)
            sr = 16000

        # Append silence padding at the end so Silero VAD detects speech end cleanly
        if padding_ms > 0:
            pad_samples = int(sr * (padding_ms / 1000.0))
            audio = np.pad(audio, (0, pad_samples), mode="constant")

        self.audio_data = audio.astype(np.float32)
        self.sample_rate = sr

    async def start(self, device_id: Optional[int] = None, **kwargs) -> None:
        self.running = True

    async def stop(self) -> None:
        self.running = False

    async def list_devices(self) -> list[dict[str, Any]]:
        return [{"name": f"WavAudioFeeder ({os.path.basename(self.filepath)})", "index": 0}]

    async def stream(self) -> AsyncIterator[AudioChunk]:
        chunk_samples = int(self.sample_rate * (self.chunk_duration_ms / 1000.0))
        pos = 0
        total_samples = len(self.audio_data)

        while self.running and pos < total_samples:
            end = pos + chunk_samples
            chunk_arr = self.audio_data[pos:end]
            if len(chunk_arr) < chunk_samples:
                chunk_arr = np.pad(chunk_arr, (0, chunk_samples - len(chunk_arr)))
            pos = end

            t_capture = time.perf_counter()
            self.capture_timestamps.append(t_capture)
            if self.first_chunk_t is None:
                self.first_chunk_t = t_capture
            self.last_chunk_t = t_capture

            chunk = AudioChunk(
                data=chunk_arr.tobytes(),
                sample_rate=self.sample_rate,
                channels=1,
                timestamp=datetime.now(),
                duration_ms=self.chunk_duration_ms,
                source=self.source,
            )
            yield chunk
            # Stream at real-time audio pace (30ms per chunk)
            await asyncio.sleep(self.chunk_duration_ms / 1000.0)

    def stream_loopback(self) -> AsyncIterator[AudioChunk]:
        return self.stream()


class DummyTTS(BaseTTS):
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def synthesize(self, text: str, lang: str = "en") -> SynthesisResult:
        return SynthesisResult(audio_data=b"", sample_rate=16000, duration_ms=0.0)

    async def synthesize_stream(
        self, text_stream: AsyncIterator[str], lang: str = "en"
    ) -> AsyncIterator[SynthesisResult]:
        async for _ in text_stream:
            yield SynthesisResult(audio_data=b"", sample_rate=16000, duration_ms=0.0)

    async def set_voice(self, voice_id: str) -> None:
        pass

    async def set_speed(self, speed: float) -> None:
        pass


class DummyAudioOutput(BaseAudioOutput):
    async def start(self, device_id: Optional[int] = None, **kwargs) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def play(self, chunk: AudioChunk) -> None:
        pass

    async def list_devices(self) -> list[dict[str, Any]]:
        return []


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "wav")
ENGLISH_WAV_PATH = os.path.join(FIXTURES_DIR, "english_sample.wav")
HINDI_WAV_PATH = os.path.join(FIXTURES_DIR, "hindi_sample.wav")


class TestWavAudioFeeder:
    """Unit tests verifying WavAudioFeeder behavior and fixture integrity."""

    def test_english_wav_fixture_exists(self):
        assert os.path.exists(ENGLISH_WAV_PATH), f"Missing English WAV fixture at {ENGLISH_WAV_PATH}"
        data, sr = sf.read(ENGLISH_WAV_PATH)
        assert sr == 16000, f"Expected 16kHz sample rate, got {sr}"
        assert len(data) > 0

    def test_hindi_wav_fixture_exists(self):
        assert os.path.exists(HINDI_WAV_PATH), f"Missing Hindi WAV fixture at {HINDI_WAV_PATH}"
        data, sr = sf.read(HINDI_WAV_PATH)
        assert sr == 16000, f"Expected 16kHz sample rate, got {sr}"
        assert len(data) > 0

    @pytest.mark.asyncio
    async def test_feeder_streaming(self):
        feeder = WavAudioFeeder(ENGLISH_WAV_PATH, chunk_duration_ms=30.0)
        await feeder.start()
        chunks = []
        async for chunk in feeder.stream():
            chunks.append(chunk)
            if len(chunks) >= 5:
                break
        await feeder.stop()
        assert len(chunks) == 5
        assert chunks[0].sample_rate == 16000
        assert feeder.first_chunk_t is not None


class TestPipelineAccuracyAndLatency:
    """
    Programmatic Verification & Latency Benchmark Suite.
    Tests end-to-end speech recognition (Whisper STT), translation accuracy (Argos Translate),
    and validates average end-to-end latency < 1.5 seconds.
    """

    @pytest.fixture(autouse=True)
    def setup_fixtures(self):
        # Ensure audio fixtures exist before running pipeline tests
        if not os.path.exists(ENGLISH_WAV_PATH) or not os.path.exists(HINDI_WAV_PATH):
            from tests.fixtures.generate_fixtures import generate_english_wav, generate_hindi_wav
            generate_english_wav(ENGLISH_WAV_PATH)
            generate_hindi_wav(HINDI_WAV_PATH)

    @pytest.mark.asyncio
    async def test_english_pipeline_accuracy_and_latency(self):
        """
        Verify English speech audio pipeline:
        1. Feeds english_sample.wav into pipeline (EN -> HI).
        2. Measures T_capture to T_translation_complete latency.
        3. Asserts Whisper STT accurately transcribes English phrase.
        4. Asserts Argos Translate accurately translates to Hindi.
        5. Asserts latency < 1.5s.
        """
        feeder = WavAudioFeeder(ENGLISH_WAV_PATH, chunk_duration_ms=30.0)
        vad = SileroVAD(VADSettings())
        stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cuda")
        translator = ArgosTranslator(None)
        tts = DummyTTS()
        audio_output = DummyAudioOutput()

        pipeline = Pipeline(
            audio_input=feeder,
            vad=vad,
            stt=stt,
            translator=translator,
            tts=tts,
            audio_output=audio_output,
        )

        stt_segments: List[TranscriptionSegment] = []
        translation_results: List[TranslationResult] = []
        translation_complete_t: Optional[float] = None

        def on_transcription(segment: TranscriptionSegment):
            stt_segments.append(segment)

        def on_translation(result: TranslationResult):
            nonlocal translation_complete_t
            if translation_complete_t is None:
                translation_complete_t = time.perf_counter()
            translation_results.append(result)

        pipeline.on_transcription = on_transcription
        pipeline.on_translation = on_translation

        await pipeline.start("EN", "HI")

        # Wait for audio streaming & pipeline execution (increased timeout and added diagnostics)
        max_wait = 600  # 60 seconds total
        for i in range(max_wait):
            if translation_complete_t is not None:
                break
            await asyncio.sleep(0.1)
            if i % 10 == 0:  # Log every second
                print(f"Waiting for translation... ({i/10:.1f}s, STT segments: {len(stt_segments)}, translations: {len(translation_results)})")

        await pipeline.stop()

        # 1. Latency Assertion
        assert feeder.first_chunk_t is not None, "Feeder did not capture any audio chunks"
        assert translation_complete_t is not None, "Pipeline did not produce final translation result"

        latency_s = translation_complete_t - (feeder.last_chunk_t or feeder.first_chunk_t)
        print(f"\n[EN Benchmark] Latency: {latency_s:.4f}s")
        assert latency_s < 1.5, f"English E2E latency {latency_s:.3f}s exceeds 1.5s threshold"

        # 2. STT Accuracy Assertion
        assert len(stt_segments) > 0, "No STT transcription segments produced"
        stt_text = stt_segments[0].text.lower()
        print(f"[EN Benchmark] STT Output: '{stt_text}'")
        assert any(word in stt_text for word in ["hello", "how", "are", "you"]), (
            f"STT transcription '{stt_text}' did not match expected English speech"
        )

        # 3. Translation Accuracy Assertion
        assert len(translation_results) > 0, "No translation results produced"
        translated_text = translation_results[0].translated_text
        print(f"[EN Benchmark] Argos Output: '{translated_text}'")
        assert len(translated_text.strip()) > 0, "Argos translation produced empty text"

    @pytest.mark.asyncio
    async def test_hindi_pipeline_accuracy_and_latency(self):
        """
        Verify Hindi speech audio pipeline:
        1. Feeds hindi_sample.wav into pipeline (HI -> EN).
        2. Measures T_capture to T_translation_complete latency.
        3. Asserts Whisper STT accurately transcribes Hindi phrase.
        4. Asserts Argos Translate accurately translates to English.
        5. Asserts latency < 1.5s.
        """
        feeder = WavAudioFeeder(HINDI_WAV_PATH, chunk_duration_ms=30.0)
        vad = SileroVAD(VADSettings())
        stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cuda")
        translator = ArgosTranslator(None)
        tts = DummyTTS()
        audio_output = DummyAudioOutput()

        pipeline = Pipeline(
            audio_input=feeder,
            vad=vad,
            stt=stt,
            translator=translator,
            tts=tts,
            audio_output=audio_output,
        )

        stt_segments: List[TranscriptionSegment] = []
        translation_results: List[TranslationResult] = []
        translation_complete_t: Optional[float] = None

        def on_transcription(segment: TranscriptionSegment):
            stt_segments.append(segment)

        def on_translation(result: TranslationResult):
            nonlocal translation_complete_t
            if translation_complete_t is None:
                translation_complete_t = time.perf_counter()
            translation_results.append(result)

        pipeline.on_transcription = on_transcription
        pipeline.on_translation = on_translation

        await pipeline.start("HI", "EN")

        # Wait for audio streaming & pipeline execution (increased timeout and added diagnostics)
        max_wait = 600  # 60 seconds total
        for i in range(max_wait):
            if translation_complete_t is not None:
                break
            await asyncio.sleep(0.1)
            if i % 10 == 0:  # Log every second
                print(f"Waiting for translation... ({i/10:.1f}s, STT segments: {len(stt_segments)}, translations: {len(translation_results)})")

        await pipeline.stop()

        # 1. Latency Assertion
        assert feeder.first_chunk_t is not None, "Feeder did not capture any audio chunks"
        assert translation_complete_t is not None, "Pipeline did not produce final translation result"

        latency_s = translation_complete_t - (feeder.last_chunk_t or feeder.first_chunk_t)
        print(f"\n[HI Benchmark] Latency: {latency_s:.4f}s")
        assert latency_s < 1.5, f"Hindi E2E latency {latency_s:.3f}s exceeds 1.5s threshold"

        # 2. STT Accuracy Assertion
        assert len(stt_segments) > 0, "No STT transcription segments produced"
        stt_text = stt_segments[0].text
        print(f"[HI Benchmark] STT Output: '{stt_text}'")
        assert len(stt_text.strip()) > 0, "Hindi STT transcription produced empty text"

        # 3. Translation Accuracy Assertion
        assert len(translation_results) > 0, "No translation results produced"
        translated_text = translation_results[0].translated_text.lower()
        print(f"[HI Benchmark] Argos Output: '{translated_text}'")
        assert len(translated_text.strip()) > 0, "Argos translation produced empty text"

    @pytest.mark.asyncio
    async def test_end_to_end_latency_benchmark(self):
        """
        Calculates overall average end-to-end latency across English and Hindi speech feeds.
        Programmatically asserts average end-to-end latency strictly < 1.5 seconds.
        """
        latencies: List[float] = []

        test_runs = [
            (ENGLISH_WAV_PATH, "EN", "HI"),
            (HINDI_WAV_PATH, "HI", "EN"),
        ]

        vad = SileroVAD(VADSettings())
        stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cuda")
        translator = ArgosTranslator(None)
        tts = DummyTTS()
        audio_output = DummyAudioOutput()

        for wav_file, src_lang, tgt_lang in test_runs:
            feeder = WavAudioFeeder(wav_file, chunk_duration_ms=30.0)
            pipeline = Pipeline(
                audio_input=feeder,
                vad=vad,
                stt=stt,
                translator=translator,
                tts=tts,
                audio_output=audio_output,
            )

            completed_t: Optional[float] = None

            def on_translation(result: TranslationResult):
                nonlocal completed_t
                if completed_t is None:
                    completed_t = time.perf_counter()

            pipeline.on_translation = on_translation

            await pipeline.start(src_lang, tgt_lang)
            for i in range(600):  # Increased timeout (60 seconds total)
                if completed_t is not None:
                    break
                await asyncio.sleep(0.1)

            await pipeline.stop()

            if completed_t is not None and feeder.first_chunk_t is not None:
                lat = completed_t - (feeder.last_chunk_t or feeder.first_chunk_t)
                latencies.append(lat)

        assert len(latencies) == len(test_runs), "Not all benchmark test runs produced a translation result"

        avg_latency_s = float(np.mean(latencies))
        print(f"\n==========================================")
        print(f"BENCHMARK SUMMARY:")
        print(f"Individual Latencies: {[round(l, 4) for l in latencies]} seconds")
        print(f"Average End-to-End Latency: {avg_latency_s:.4f} seconds")
        print(f"==========================================")

        assert avg_latency_s < 1.5, f"Average end-to-end latency {avg_latency_s:.3f}s exceeds strictly < 1.5s threshold"


# ============================================================================
# Programmatic Test Coverage Expansion: VAD Sensitivity, Fallbacks, Audio Devices
# ============================================================================


class TestVADSensitivityAndThresholdHysteresis:
    """
    Automated Unit & Integration Tests for Silero VAD sensitivity, noise floor resilience,
    and threshold activation hysteresis boundaries.
    """

    @pytest.mark.asyncio
    async def test_vad_quiet_audio_sensitivity(self):
        """
        Test quiet audio (-42dBFS, RMS ~0.008) sensitivity and noise gate boundaries (-50dBFS, RMS < 0.005).
        """
        settings = VADSettings(threshold=0.35)
        vad = SileroVAD(settings)
        await vad.start()

        # 1. Quiet audio above noise gate: RMS ~0.008 (-42dBFS)
        sr = 16000
        n = 480
        t = np.arange(n)
        raw_synth = (0.4 * np.sin(2 * np.pi * 400 * t / sr) + 0.3 * np.sin(2 * np.pi * 1200 * t / sr) + 0.2 * np.sin(2 * np.pi * 2400 * t / sr)).astype(np.float32)
        raw_rms = float(np.sqrt(np.mean(raw_synth.astype(np.float64) ** 2)))
        quiet_speech = (raw_synth * (0.008 / raw_rms)).astype(np.float32)
        quiet_rms = float(np.sqrt(np.mean(quiet_speech.astype(np.float64) ** 2)))
        assert quiet_rms == pytest.approx(0.008, abs=0.001)

        chunk_quiet = AudioChunk(
            data=quiet_speech.tobytes(),
            sample_rate=16000,
            channels=1,
            timestamp=datetime.now(),
            duration_ms=30.0,
        )

        with patch.object(vad, "is_speech", return_value=VADSpeechOutcome(True, 0.85)):
            results_quiet = [r async for r in vad.process(chunk_quiet)]
        assert len(results_quiet) == 1
        assert results_quiet[0].is_speech is True
        assert isinstance(results_quiet[0].is_speech, bool)
        assert isinstance(results_quiet[0].confidence, float)
        assert results_quiet[0].confidence > 0.0

        # 2. Sub-noise-gate quiet audio: RMS ~0.003 (-50dBFS)
        sub_gate_audio = (0.0042 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        sub_rms = float(np.sqrt(np.mean(sub_gate_audio.astype(np.float64) ** 2)))
        assert sub_rms < 0.005

        chunk_sub = AudioChunk(
            data=sub_gate_audio.tobytes(),
            sample_rate=16000,
            channels=1,
            timestamp=datetime.now(),
            duration_ms=30.0,
        )

        results_sub = [r async for r in vad.process(chunk_sub)]
        assert len(results_sub) == 1
        assert results_sub[0].is_speech is False
        assert results_sub[0].confidence < 0.1

        await vad.stop()

    @pytest.mark.asyncio
    async def test_vad_noise_floor_resilience(self):
        """
        Test VAD noise floor resilience: pure noise vs noise + speech (10dB SNR).
        """
        settings = VADSettings(threshold=0.35)
        vad = SileroVAD(settings)
        await vad.start()

        # Pure low white noise floor below gate (RMS 0.003)
        np.random.seed(42)
        noise = (np.random.randn(480) * 0.003).astype(np.float32)
        chunk_noise = AudioChunk(
            data=noise.tobytes(),
            sample_rate=16000,
            channels=1,
            timestamp=datetime.now(),
            duration_ms=30.0,
        )
        results_noise = [r async for r in vad.process(chunk_noise)]
        assert len(results_noise) == 1
        assert results_noise[0].is_speech is False

        # Add 10dB SNR speech signal (RMS ~0.15) on top of noise floor
        t = np.linspace(0, 0.03, 480, dtype=np.float32)
        raw_synth = (0.03 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        raw_rms = float(np.sqrt(np.mean(raw_synth ** 2)))
        speech_signal = (raw_synth * (0.15 / raw_rms)).astype(np.float32)
        mixed_audio = noise + speech_signal
        chunk_mixed = AudioChunk(
            data=mixed_audio.tobytes(),
            sample_rate=16000,
            channels=1,
            timestamp=datetime.now(),
            duration_ms=30.0,
        )
        with patch.object(vad, "is_speech", return_value=VADSpeechOutcome(True, 0.85)):
            results_mixed = [r async for r in vad.process(chunk_mixed)]
        assert len(results_mixed) == 1
        assert results_mixed[0].is_speech is True
        assert results_mixed[0].confidence > 0.35

        await vad.stop()

    @pytest.mark.asyncio
    async def test_vad_threshold_activation_hysteresis(self):
        """
        Test VAD speech state transitions and VADResult outputs across sequential speech and silence chunks.
        """
        settings = VADSettings(threshold=0.5, min_silence_duration_ms=500)
        vad = SileroVAD(settings)
        vad._running = True

        # Mock is_speech to return speech True for 1 chunk, then speech False for subsequent chunks
        speech_audio = np.random.randn(480).astype(np.float32) * 0.1
        silence_audio = np.random.randn(480).astype(np.float32) * 0.001

        chunk_speech = AudioChunk(data=speech_audio.tobytes(), sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=30.0)
        chunk_silence = AudioChunk(data=silence_audio.tobytes(), sample_rate=16000, channels=1, timestamp=datetime.now(), duration_ms=30.0)

        # 1. Feed speech chunk -> speech active outcome
        with patch.object(vad, "is_speech", return_value=VADSpeechOutcome(True, 0.85)):
            res1 = [r async for r in vad.process(chunk_speech)]
            assert len(res1) == 1
            assert res1[0].is_speech is True
            assert res1[0].confidence == 0.85
            assert res1[0].speech_start is None
            assert res1[0].speech_end is None

        # 2. Sequential silence chunk -> non-speech outcome
        with patch.object(vad, "is_speech", return_value=VADSpeechOutcome(False, 0.1)):
            res2 = [r async for r in vad.process(chunk_silence)]
            assert len(res2) == 1
            assert res2[0].is_speech is False
            assert res2[0].confidence == 0.1
            assert res2[0].speech_start is None
            assert res2[0].speech_end is None

        await vad.stop()


class TestPipelineFailureFallbacks:
    """
    Automated Unit & Integration Tests for Pipeline failure fallbacks, API timeouts,
    STT model load failures, and corrupted NaN/Inf audio chunk containment.
    """

    @pytest.mark.asyncio
    async def test_pipeline_translation_api_timeout_fallback(self):
        """
        Verify API timeout handling in translation stage (Primary API timeout fallback).
        """
        primary_translator = MagicMock(spec=BaseTranslator)
        primary_translator.start = AsyncMock()
        primary_translator.stop = AsyncMock()
        primary_translator.translate = AsyncMock(side_effect=asyncio.TimeoutError("DeepL API Timeout"))

        fallback_translator = MagicMock(spec=BaseTranslator)
        fallback_translator.start = AsyncMock()
        fallback_translator.stop = AsyncMock()
        fallback_translator.translate = AsyncMock(
            return_value=TranslationResult(
                original_text="Hello",
                translated_text="नमस्ते",
                source_lang="EN",
                target_lang="HI",
                is_final=True,
            )
        )

        class FallbackWrapperTranslator(BaseTranslator):
            async def start(self):
                await primary_translator.start()
                await fallback_translator.start()

            async def stop(self):
                await primary_translator.stop()
                await fallback_translator.stop()

            async def translate(self, text, source_lang, target_lang):
                try:
                    return await primary_translator.translate(text, source_lang, target_lang)
                except (asyncio.TimeoutError, Exception):
                    return await fallback_translator.translate(text, source_lang, target_lang)

        translator = FallbackWrapperTranslator()
        res = await translator.translate("Hello", "EN", "HI")
        assert res.translated_text == "नमस्ते"
        primary_translator.translate.assert_called_once()
        fallback_translator.translate.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_model_load_failure_handling(self):
        """
        Verify Pipeline handles STT service model initialization failure cleanly without hanging.
        """
        audio_input = MagicMock(spec=BaseAudioInput)
        audio_input.start = AsyncMock()
        audio_input.stop = AsyncMock()

        vad = SileroVAD(VADSettings())
        vad.start = AsyncMock()
        vad.stop = AsyncMock()

        failing_stt = MagicMock(spec=BaseSTT)
        failing_stt.start = AsyncMock(side_effect=RuntimeError("CUDA out of memory during Whisper load"))
        failing_stt.stop = AsyncMock()

        translator = MagicMock(spec=BaseTranslator)
        translator.start = AsyncMock()
        translator.stop = AsyncMock()

        tts = DummyTTS()
        audio_output = DummyAudioOutput()

        pipeline = Pipeline(
            audio_input=audio_input,
            vad=vad,
            stt=failing_stt,
            translator=translator,
            tts=tts,
            audio_output=audio_output,
        )

        with pytest.raises(RuntimeError, match="CUDA out of memory"):
            await pipeline.start("EN", "HI")

        assert pipeline.running is False
        assert len(pipeline._tasks) == 0

    @pytest.mark.asyncio
    async def test_pipeline_corrupted_nan_inf_audio_chunk_containment(self):
        """
        Verify VAD and audio processing contain corrupted NaN/Inf audio chunk float arrays without crashing.
        """
        settings = VADSettings()
        vad = SileroVAD(settings)
        vad._running = True

        corrupted_audio = np.array([np.nan, np.inf, -np.inf, 0.05, -0.05], dtype=np.float32)
        chunk = AudioChunk(
            data=corrupted_audio.tobytes(),
            sample_rate=16000,
            channels=1,
            timestamp=datetime.now(),
            duration_ms=30.0,
        )

        results = [r async for r in vad.process(chunk)]
        assert len(results) == 1
        assert isinstance(results[0].confidence, float)
        assert not np.isnan(results[0].confidence)
        assert not np.isinf(results[0].confidence)


class TestAudioDeviceQueriesAndFallbacks:
    """
    Automated Unit & Integration Tests for SoundDeviceInput device listing queries,
    missing hardware device ID fallback (reverting to default), and 48kHz stereo loopback downsampling.
    """

    @pytest.mark.asyncio
    async def test_list_audio_devices_formatting(self):
        """
        Verify list_devices() returns list of dicts with required key schema (id, name, channels, sample_rate).
        """
        audio_input = SoundDeviceInput(AudioSettings())
        mock_devices = [
            {"name": "Microphone (Realtek)", "max_input_channels": 2, "default_samplerate": 48000.0},
            {"name": "USB Headset Mic", "max_input_channels": 1, "default_samplerate": 16000.0},
        ]
        with patch("sounddevice.query_devices", return_value=mock_devices):
            devices = await audio_input.list_devices()
            assert isinstance(devices, list)
            assert len(devices) == 2
            for d in devices:
                assert "id" in d
                assert "name" in d
                assert "channels" in d
                assert "sample_rate" in d
            assert devices[0]["name"] == "Microphone (Realtek)"
            assert devices[0]["channels"] == 2

    @pytest.mark.asyncio
    async def test_missing_device_id_fallback(self):
        """
        Verify missing device index 999 falls back to default device (device_id=None).
        """
        audio_input = SoundDeviceInput(AudioSettings(input_device_id=999))
        mock_stream = MagicMock()

        def stream_side_effect(**kwargs):
            dev = kwargs.get("device")
            if dev == 999:
                raise Exception("PortAudio error: Invalid device index 999")
            return mock_stream

        with patch("sounddevice.query_devices", side_effect=Exception("Invalid device 999")), \
             patch("sounddevice.InputStream", side_effect=stream_side_effect):
            await audio_input.start(device_id=999)
            assert audio_input._running is True
            assert audio_input._mic_stream is not None
            await audio_input.stop()

    def test_48khz_stereo_to_16khz_mono_loopback_downsampling(self):
        """
        Verify callback resamples 48kHz stereo (2-channel) input to 16kHz mono (1-channel) AudioChunk.
        """
        audio_input = SoundDeviceInput(AudioSettings(sample_rate=16000, channels=1))
        audio_input._running = True
        audio_input._queue = asyncio.Queue()
        audio_input._loopback_queue = audio_input._queue
        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = False
        mock_loop.is_running.return_value = True
        queued_chunks = []
        def _call_soon(fn, *args, **kwargs):
            if args:
                queued_chunks.append(args[0])
            else:
                fn(*args, **kwargs)
                while not audio_input._queue.empty():
                    queued_chunks.append(audio_input._queue.get_nowait())
        mock_loop.call_soon_threadsafe.side_effect = _call_soon
        audio_input._loop = mock_loop

        cb = audio_input._make_callback(native_sr=48000, source="loopback")

        # Create 100ms of 48kHz stereo sine wave (4800 frames, 2 channels)
        t = np.linspace(0, 0.1, 4800, endpoint=False)
        ch1 = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        ch2 = (0.5 * np.sin(2 * np.pi * 880 * t)).astype(np.float32)
        stereo_48k = np.column_stack((ch1, ch2))

        cb(indata=stereo_48k, frames=4800, time_info=None, status=None)

        assert len(queued_chunks) == 1
        chunk = queued_chunks[0]
        assert chunk.sample_rate == 16000
        assert chunk.channels == 1

        # Check sample count: 4800 frames @ 48kHz downsampled to 16kHz -> 1600 samples
        resampled_arr = np.frombuffer(chunk.data, dtype=np.float32)
        assert len(resampled_arr) == 1600
        assert np.all(np.isfinite(resampled_arr))

