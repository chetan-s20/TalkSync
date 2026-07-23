from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

sys.path.insert(0, "d:/talksync/talksync")

from app.interfaces import AudioChunk, TranscriptionSegment, TranslationResult
from app.pipeline import Pipeline
from services.stt.faster_whisper import FasterWhisperSTT
from services.translation.language_validator import LanguageValidator


async def _get_transcribe_res(stt, audio, sample_rate=16000, language=None, initial_prompt=None):
    res = stt.transcribe(audio, sample_rate, language=language, initial_prompt=initial_prompt)
    if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
        res = await res
    elif hasattr(res, "result"):  # concurrent.futures.Future
        res = res.result()
    return res


async def test_stt_auto_language_normalization():
    """Verify how FasterWhisperSTT handles auto/AUTO/automatic language strings."""
    print("=== Testing FasterWhisperSTT Auto Language Normalization ===")
    results = {}

    with patch("faster_whisper.WhisperModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_model_cls.return_value = mock_model

        mock_seg = MagicMock()
        mock_seg.text = "Empirical test transcript"
        mock_seg.avg_logprob = -0.15
        mock_seg.no_speech_prob = 0.02
        mock_seg.compression_ratio = 1.1

        mock_info = MagicMock()
        mock_info.language = "hi"
        mock_info.language_probability = 0.94

        mock_model.transcribe.return_value = ([mock_seg], mock_info)

        stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
        audio = np.zeros(16000, dtype=np.float32)

        # Test variations of auto string
        auto_variations = ["auto", "AUTO", "Automatic", "  auto  ", "automatic"]
        for auto_str in auto_variations:
            mock_model.transcribe.reset_mock()
            res = await _get_transcribe_res(stt, audio, 16000, language=auto_str)
            call_kwargs = mock_model.transcribe.call_args[1] if mock_model.transcribe.called else {}
            lang_passed = call_kwargs.get("language")

            passed = (lang_passed is None) and (res is not None) and (res.language == "hi") and (res.language_probability == 0.94)
            results[f"auto_variant_{auto_str.strip()}"] = {
                "passed": passed,
                "passed_to_whisper": lang_passed,
                "returned_language": res.language if res else None,
                "language_probability": res.language_probability if res else None,
            }
            print(f"  Variant '{auto_str}' -> passed to whisper: {lang_passed}, result lang: {res.language if res else None}, prob: {res.language_probability if res else None} -> PASS={passed}")

    return results


async def test_stt_probability_and_fallback_reporting():
    """Verify language probability extraction, low prob, missing prob, and segment filtering."""
    print("\n=== Testing STT Language Probability Reporting & Filtering ===")
    results = {}

    with patch("faster_whisper.WhisperModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_model_cls.return_value = mock_model
        stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
        audio = np.zeros(16000, dtype=np.float32)

        # Case 1: Normal prob
        mock_seg = MagicMock(text="Valid text", avg_logprob=-0.1, no_speech_prob=0.01, compression_ratio=1.0)
        mock_info = MagicMock(language="en", language_probability=0.88)
        mock_model.transcribe.return_value = ([mock_seg], mock_info)
        res1 = await _get_transcribe_res(stt, audio, 16000)
        results["normal_prob"] = {
            "passed": res1 is not None and res1.language_probability == 0.88 and res1.confidence == 0.88,
            "confidence": res1.confidence if res1 else None,
            "lang_prob": res1.language_probability if res1 else None,
        }
        print(f"  Normal prob 0.88 -> confidence={res1.confidence if res1 else None}, lang_prob={res1.language_probability if res1 else None}")

        # Case 2: Missing language_probability attribute (None)
        mock_info_none = MagicMock(spec=["language"])
        mock_info_none.language = "es"
        mock_model.transcribe.return_value = ([mock_seg], mock_info_none)
        res2 = await _get_transcribe_res(stt, audio, 16000)
        results["missing_prob_attr"] = {
            "passed": res2 is not None and res2.language_probability == 0.0,
            "lang_prob": res2.language_probability if res2 else None,
        }
        print(f"  Missing prob attr -> fallback lang_prob={res2.language_probability if res2 else None}")

        # Case 3: Noise filtering - low logprob
        mock_noisy_seg = MagicMock(text="Garbage", avg_logprob=-2.5, no_speech_prob=0.01, compression_ratio=1.0)
        mock_model.transcribe.return_value = ([mock_noisy_seg], mock_info)
        res3 = await _get_transcribe_res(stt, audio, 16000)
        results["filter_low_logprob"] = {
            "passed": res3 is None,
            "result": res3,
        }
        print(f"  Low logprob (-2.5 < -1.0) -> filtered out (res is None): {res3 is None}")

        # Case 4: High no_speech_prob
        mock_nospeech_seg = MagicMock(text="Noise", avg_logprob=-0.1, no_speech_prob=0.95, compression_ratio=1.0)
        mock_model.transcribe.return_value = ([mock_nospeech_seg], mock_info)
        res4 = await _get_transcribe_res(stt, audio, 16000)
        results["filter_high_no_speech"] = {
            "passed": res4 is None,
            "result": res4,
        }
        print(f"  High no_speech_prob (0.95 > 0.7) -> filtered out (res is None): {res4 is None}")

        # Case 5: High compression ratio (repetition loop)
        mock_repeat_seg = MagicMock(text="Repeat repeat repeat", avg_logprob=-0.1, no_speech_prob=0.01, compression_ratio=3.5)
        mock_model.transcribe.return_value = ([mock_repeat_seg], mock_info)
        res5 = await _get_transcribe_res(stt, audio, 16000)
        results["filter_high_compression_ratio"] = {
            "passed": res5 is None,
            "result": res5,
        }
        print(f"  High compression ratio (3.5 > 2.4) -> filtered out (res is None): {res5 is None}")

    return results


async def test_pipeline_auto_resolution_matrix():
    """Verify dynamic AUTO language resolution matrix in Pipeline._translate_and_route."""
    print("\n=== Testing Pipeline Dynamic AUTO Language Resolution Matrix ===")
    results = {}

    audio_input, vad, stt, tts, audio_output = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()

    test_cases = [
        # (source_lang, target_lang, detected_lang, expected_src, expected_tgt)
        ("AUTO", "EN", "fr", "FR", "EN"),
        ("AUTO", "HI", "en", "EN", "HI"),
        ("EN", "AUTO", "hi", "EN", "HI"),
        ("EN", "AUTO", "en", "EN", "HI"),
        ("HI", "AUTO", "hi", "HI", "EN"),
        ("AUTO", "AUTO", "es", "ES", "EN"),
        ("AUTO", "EN", "", "EN", "EN"),  # Fallback when detected is empty
        ("AUTO", "EN", None, "EN", "EN"),  # Fallback when detected is None
    ]

    for idx, (src_in, tgt_in, det_lang, exp_src, exp_tgt) in enumerate(test_cases):
        translator = AsyncMock()
        translator.translate = AsyncMock(return_value=TranslationResult(
            original_text="Test", translated_text="Translated", source_lang=exp_src, target_lang=exp_tgt, is_final=True
        ))

        pipeline = Pipeline(audio_input, vad, stt, translator, tts, audio_output)
        pipeline._source_lang = src_in
        pipeline._target_lang = tgt_in

        seg = TranscriptionSegment(
            text="Test sentence", is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language=det_lang, confidence=0.9, language_probability=0.9,
            input_source="VOICE",
        )

        await pipeline._translate_and_route(seg, is_final=True, enqueue_tts=False)

        if translator.translate.called:
            call_args = translator.translate.call_args
            actual_src = call_args[0][1]
            actual_tgt = call_args[0][2]
            passed = (actual_src == exp_src) and (actual_tgt == exp_tgt)
        else:
            actual_src, actual_tgt = None, None
            passed = False

        key = f"case_{idx}_{src_in}_{tgt_in}_det_{det_lang}"
        results[key] = {
            "passed": passed,
            "input_src": src_in, "input_tgt": tgt_in, "detected": det_lang,
            "actual_src": actual_src, "actual_tgt": actual_tgt,
            "expected_src": exp_src, "expected_tgt": exp_tgt,
        }
        print(f"  [{src_in} -> {tgt_in}] detected='{det_lang}' -> resolved: [{actual_src} -> {actual_tgt}] (Expected: [{exp_src} -> {exp_tgt}]) -> PASS={passed}")

    return results


def test_language_validator_hysteresis():
    """Verify LanguageValidator threshold logic and hysteresis state transitions."""
    print("\n=== Testing LanguageValidator Thresholds & Hysteresis ===")
    results = {}
    validator = LanguageValidator()

    # Step 1: Low confidence (< 0.3) -> should return source_lang ("EN")
    val1 = validator.validate(detected_lang="HI", confidence=0.25, source_lang="EN", target_lang="HI")
    pass1 = (val1 == "EN")
    print(f"  Step 1: det='HI', conf=0.25 -> val='{val1}' (exp 'EN') -> PASS={pass1}")

    # Step 2: Medium confidence (0.45) with no lock -> should return source_lang ("EN")
    val2 = validator.validate(detected_lang="HI", confidence=0.45, source_lang="EN", target_lang="HI")
    pass2 = (val2 == "EN")
    print(f"  Step 2: det='HI', conf=0.45 -> val='{val2}' (exp 'EN') -> PASS={pass2}")

    # Step 3: High confidence (0.80) -> locks 'HI'
    val3 = validator.validate(detected_lang="HI", confidence=0.80, source_lang="EN", target_lang="HI")
    pass3 = (val3 == "HI")
    print(f"  Step 3: det='HI', conf=0.80 -> val='{val3}' (exp 'HI') -> PASS={pass3}")

    # Step 4: Subsequent medium confidence (0.40) matching locked 'HI' -> stays 'HI'
    val4 = validator.validate(detected_lang="HI", confidence=0.40, source_lang="EN", target_lang="HI")
    pass4 = (val4 == "HI")
    print(f"  Step 4: det='HI', conf=0.40 -> val='{val4}' (exp 'HI') -> PASS={pass4}")

    # Step 5: High confidence (0.75) for 'EN' -> locks 'EN'
    val5 = validator.validate(detected_lang="EN", confidence=0.75, source_lang="EN", target_lang="HI")
    pass5 = (val5 == "EN")
    print(f"  Step 5: det='EN', conf=0.75 -> val='{val5}' (exp 'EN') -> PASS={pass5}")

    results["hysteresis"] = {
        "passed": pass1 and pass2 and pass3 and pass4 and pass5,
        "steps": [val1, val2, val3, val4, val5]
    }

    return results


async def main():
    print("==================================================")
    print("STARTING EMPIRICAL CHALLENGER VERIFICATION SUITE")
    print("==================================================")
    r1 = await test_stt_auto_language_normalization()
    r2 = await test_stt_probability_and_fallback_reporting()
    r3 = await test_pipeline_auto_resolution_matrix()
    r4 = test_language_validator_hysteresis()

    all_passed = (
        all(v["passed"] for v in r1.values()) and
        all(v["passed"] for v in r2.values()) and
        all(v["passed"] for v in r3.values()) and
        all(v["passed"] for v in r4.values())
    )
    print("\n==================================================")
    print(f"EMPIRICAL SUITE OVERALL RESULT: {'PASS' if all_passed else 'FAIL'}")
    print("==================================================")
    return all_passed


if __name__ == "__main__":
    asyncio.run(main())
