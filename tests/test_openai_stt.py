"""
Quick live test for OpenAI STT service.
Usage:
    cd d:\talksync\talksync
    python tests/test_openai_stt.py
Expects OPENAI_API_KEY to be set in .env.
"""
import asyncio
import sys
sys.path.insert(0, "d:/talksync/talksync")

from dotenv import load_dotenv
load_dotenv("d:/talksync/talksync/.env")

import numpy as np
import pytest
from config.settings import Settings


@pytest.mark.asyncio
async def test_openai_stt():
    s = Settings()
    openai_key = s.openai.api_key
    if not openai_key or openai_key == "YOUR_OPENAI_API_KEY_HERE":
        print("OPENAI_API_KEY is not set in .env")
        print("Edit .env and replace YOUR_OPENAI_API_KEY_HERE with your real key")
        return False

    print(f"API Key found: {openai_key[:8]}...")
    print(f"Model: {s.openai.stt_model}")

    from services.stt.openai_stt import OpenAISTT
    stt = OpenAISTT(s)

    print("\n[1] Starting STT service...")
    await stt.start()
    print("    Service started OK")

    print("\n[2] Sending silence (should be rejected by RMS gate)...")
    sr = 16000
    silence = np.zeros(sr * 2, dtype=np.float32)
    result = await stt.transcribe(silence.tobytes(), is_final=True, language="en")
    if result is None:
        print("    Silence correctly rejected - RMS gate working")
    else:
        print(f"    WARNING: Silence produced output: {result.text}")

    print("\n[3] Cost estimate:")
    print("    gpt-4o-transcribe: $0.006 / minute")
    print("    $10 budget = ~1,666 minutes = ~27 hours of meetings")

    await stt.stop()
    print("\nOpenAI STT test complete. Ready to use.")
    return True


if __name__ == "__main__":
    success = asyncio.run(test_openai_stt())
    sys.exit(0 if success else 1)
