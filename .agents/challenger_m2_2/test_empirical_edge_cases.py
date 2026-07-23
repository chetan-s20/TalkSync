from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

sys.path.insert(0, "d:/talksync/talksync")

from app.interfaces import TranscriptionSegment
from app.pipeline import Pipeline
from services.stt.faster_whisper import FasterWhisperSTT
from utils.languages import get_language_code, normalize_lang


async def _get_transcribe_res(stt, audio, sample_rate=16000, language=None, initial_prompt=None):
    res = stt.transcribe(audio, sample_rate, language=language, initial_prompt=initial_prompt)
    if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
        res = await res
    elif hasattr(res, "result"):
        res = res.result()
    return res


async def test_stt_invalid_language_param_types():
    """Empirically test how FasterWhisperSTT handles unexpected types for 'language' parameter."""
    print("=== Testing STT Invalid Language Parameter Types ===")
    results = {}

    with patch("faster_whisper.WhisperModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_model_cls.return_value = mock_model

        mock_seg = MagicMock(text="Edge case text", avg_logprob=-0.1, no_speech_prob=0.01, compression_ratio=1.0)
        mock_info = MagicMock(language="en", language_probability=0.9)
        mock_model.transcribe.return_value = ([mock_seg], mock_info)

        stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
        audio = np.zeros(16000, dtype=np.float32)

        invalid_inputs = [
            (123, "int"),
            (None, "NoneType"),
            (["en"], "list"),
            ({"lang": "en"}, "dict"),
            ("", "empty_string"),
            ("   ", "whitespace_string"),
        ]

        for val, name in invalid_inputs:
            mock_model.transcribe.reset_mock()
            try:
                res = await _get_transcribe_res(stt, audio, 16000, language=val)
                passed = True
                call_kwargs = mock_model.transcribe.call_args[1] if mock_model.transcribe.called else {}
                lang_kwarg = call_kwargs.get("language")
                print(f"  Type {name} ({val!r}): Handled gracefully -> res text='{res.text if res else None}', passed language kwarg: {lang_kwarg!r}")
                results[name] = {"passed": True, "res": res.text if res else None, "lang_kwarg": lang_kwarg}
            except Exception as e:
                print(f"  Type {name} ({val!r}): Exception raised -> {e}")
                results[name] = {"passed": False, "error": str(e)}

    return results


async def test_stt_malformed_info_object():
    """Empirically test how FasterWhisperSTT handles missing/None attributes on WhisperModel info return object."""
    print("\n=== Testing STT Malformed Info Object ===")
    results = {}

    with patch("faster_whisper.WhisperModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_model_cls.return_value = mock_model

        mock_seg = MagicMock(text="Test", avg_logprob=-0.1, no_speech_prob=0.01, compression_ratio=1.0)
        stt = FasterWhisperSTT(model_name="Systran/faster-whisper-small", device="cpu")
        audio = np.zeros(16000, dtype=np.float32)

        # Subcase 1: info.language is None
        mock_info1 = MagicMock()
        mock_info1.language = None
        mock_info1.language_probability = 0.85
        mock_model.transcribe.return_value = ([mock_seg], mock_info1)

        res1 = await _get_transcribe_res(stt, audio, 16000)
        p1 = (res1 is not None and res1.language == "" and res1.language_probability == 0.85)
        print(f"  Subcase 1: info.language=None -> language='{res1.language if res1 else None}', prob={res1.language_probability if res1 else None} -> PASS={p1}")
        results["info_language_none"] = {"passed": p1}

        # Subcase 2: info.language_probability is None
        mock_info2 = MagicMock()
        mock_info2.language = "fr"
        mock_info2.language_probability = None
        mock_model.transcribe.return_value = ([mock_seg], mock_info2)

        res2 = await _get_transcribe_res(stt, audio, 16000)
        p2 = (res2 is not None and res2.language == "fr" and res2.language_probability == 0.0)
        print(f"  Subcase 2: info.language_probability=None -> language='{res2.language if res2 else None}', prob={res2.language_probability if res2 else None} -> PASS={p2}")
        results["info_probability_none"] = {"passed": p2}

    return results


def test_language_code_edge_cases():
    """Empirically test language code resolution and normalization for edge inputs."""
    print("\n=== Testing Language Code Edge Cases & Normalization ===")
    results = {}

    test_inputs = [
        ("en", "EN"),
        ("English", "EN"),
        ("english", "EN"),
        ("HI", "HI"),
        ("hindi", "HI"),
        ("Hindi", "HI"),
        ("FR", "FR"),
        ("French", "FR"),
        ("es", "ES"),
        ("Spanish", "ES"),
        ("unknown_lang_name", "UNKNOWN_LANG_NAME"),  # Fallback to uppercase input
        ("", ""),
        (None, None),
    ]

    for inp, expected in test_inputs:
        norm = normalize_lang(inp)
        passed = (norm == expected)
        results[f"norm_{inp}"] = {"passed": passed, "actual": norm, "expected": expected}
        print(f"  normalize_lang({inp!r}) -> {norm!r} (Expected: {expected!r}) -> PASS={passed}")

    return results


async def main():
    print("==================================================")
    print("STARTING EMPIRICAL EDGE CASE VERIFICATION")
    print("==================================================")
    r1 = await test_stt_invalid_language_param_types()
    r2 = await test_stt_malformed_info_object()
    r3 = test_language_code_edge_cases()

    all_passed = (
        all(v["passed"] for v in r1.values()) and
        all(v["passed"] for v in r2.values()) and
        all(v["passed"] for v in r3.values())
    )
    print("\n==================================================")
    print(f"EDGE CASE SUITE OVERALL RESULT: {'PASS' if all_passed else 'FAIL'}")
    print("==================================================")
    return all_passed


if __name__ == "__main__":
    asyncio.run(main())
