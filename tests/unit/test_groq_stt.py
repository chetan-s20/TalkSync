import pytest
import asyncio
import numpy as np
from services.stt.groq_stt import GroqSTT

@pytest.mark.asyncio
async def test_groq_stt_dual_key_pools():
    key1 = "gsk_key_1_mic_primary"
    key2 = "gsk_key_2_loopback_primary"
    
    stt = GroqSTT(api_key=key1, loopback_api_key=key2)
    assert stt.mic_keys[0] == key1
    assert stt.mic_keys[1] == key2
    assert stt.loopback_keys[0] == key2
    assert stt.loopback_keys[1] == key1
    
    await stt.initialize()
    assert stt.is_initialized
    assert stt._mic_client.headers["Authorization"] == f"Bearer {key1}"
    assert stt._loopback_client.headers["Authorization"] == f"Bearer {key2}"
    
    # Test key rotation on mic
    rotated = await stt._rotate_key("mic")
    assert rotated == key2
    assert stt._mic_client.headers["Authorization"] == f"Bearer {key2}"
    
    # Test key rotation on loopback
    rotated_lb = await stt._rotate_key("loopback")
    assert rotated_lb == key1
    assert stt._loopback_client.headers["Authorization"] == f"Bearer {key1}"
    
    await stt.close()
    assert not stt.is_initialized
