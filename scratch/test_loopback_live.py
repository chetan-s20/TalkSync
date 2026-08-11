import sys
sys.path.append("d:/talksync/talksync")
import asyncio
import numpy as np
from services.audio.input import SoundDeviceInput
from config.settings import AudioSettings
from utils.logger import get_logger

logger = get_logger("test_loopback")

async def test_live_loopback():
    settings = AudioSettings(chunk_duration_ms=30.0)
    inp = SoundDeviceInput(settings)
    
    print("Starting audio input with loopback=True, capture_mic=True...")
    await inp.start(loopback=True, capture_mic=True)
    print("Input started cleanly!")
    
    print("Listening for loopback chunks for 3 seconds...")
    chunk_count = 0
    max_rms = 0.0
    
    async for chunk in inp.stream_loopback():
        chunk_count += 1
        arr = np.frombuffer(chunk.data, dtype=np.float32)
        rms = float(np.sqrt(np.mean(arr ** 2)))
        max_rms = max(max_rms, rms)
        if chunk_count % 30 == 0:
            print(f"Captured {chunk_count} loopback chunks. Current RMS: {rms:.6f}, Max RMS: {max_rms:.6f}")
        if chunk_count >= 100:
            break
            
    await inp.stop()
    print(f"Loopback test complete! Total chunks: {chunk_count}, Max RMS: {max_rms:.6f}")

if __name__ == "__main__":
    asyncio.run(test_live_loopback())
