"""
Manual integration test for Sarvam TTS API.
Run directly: python tests/test_sarvam_network.py
Not collected by pytest (no 'test_' prefixed class or function).
"""
import asyncio, sys, httpx
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from config.settings import TTSSettings
settings = TTSSettings()
key = settings.sarvam_api_key
print(f"API key: {key[:12]}...")

async def run_network_test():
    payload = {
        "inputs": ["namaste, aap kaise hain"],
        "target_language_code": "hi-IN",
        "speaker": "ritu",
        "pace": 1.0,
        "speech_sample_rate": 22050,
        "enable_preprocessing": True,
        "model": "bulbul:v3",
    }
    headers = {"api-subscription-key": key}

    print("Trying DIRECT connection (no proxy)...")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)) as c:
            r = await c.post("https://api.sarvam.ai/text-to-speech", json=payload, headers=headers)
            print(f"Direct: status={r.status_code}, content_len={len(r.content)}")
            if r.status_code == 200:
                data = r.json()
                audios = data.get("audios", [])
                print(f"audios count: {len(audios)}, first audio b64 len: {len(audios[0]) if audios else 0}")
                print("DIRECT CONNECTION SUCCESS")
                return True
            else:
                print(f"Direct error body: {r.text[:300]}")
    except Exception as e:
        print(f"Direct failed: {type(e).__name__}: {e}")

    print("Trying PROXY connection...")
    try:
        async with httpx.AsyncClient(proxy="http://192.168.0.1:8090", timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)) as c:
            r = await c.post("https://api.sarvam.ai/v1/text-to-speech", json=payload, headers=headers)
            print(f"Proxy: status={r.status_code}")
            if r.status_code == 200:
                print("PROXY CONNECTION SUCCESS")
                return True
            else:
                print(f"Proxy error body: {r.text[:300]}")
    except Exception as e:
        print(f"Proxy failed: {type(e).__name__}: {e}")

    return False

result = asyncio.run(run_network_test())
print(f"Result: {'SUCCESS' if result else 'BOTH FAILED'}")
