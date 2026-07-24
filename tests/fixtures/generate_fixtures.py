import os
import sys
import ctypes
import numpy as np
import scipy.signal
import soundfile as sf

# Ensure talksync root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

def generate_english_wav(output_path: str):
    import piper
    from services.tts.voice_cache import find_voice_model
    model_path = find_voice_model("en_US-lessac-medium")
    if model_path:
        config_path = f"{model_path}.json"
        voice = piper.PiperVoice.load(model_path, config_path=config_path, use_cuda=False)
        chunks = list(voice.synthesize("hello how are you"))
        arrs = [c.audio_int16_array for c in chunks if len(c.audio_int16_array) > 0]
        if arrs:
            raw_int16 = np.concatenate(arrs)
            sr = voice.config.sample_rate
            if sr != 16000:
                num_samples = int(len(raw_int16) * 16000 / sr)
                raw_float = raw_int16.astype(np.float32) / 32768.0
                resampled = scipy.signal.resample(raw_float, num_samples)
                pcm_16k = np.clip(resampled * 32767.0, -32768, 32767).astype(np.int16)
            else:
                pcm_16k = raw_int16
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            sf.write(output_path, pcm_16k, 16000, subtype="PCM_16")
            print(f"Generated English WAV at {output_path} ({len(pcm_16k)} samples, {len(pcm_16k)/16000:.2f}s)")
            return True
    return False

def generate_hindi_wav(output_path: str):
    import espeakng_loader
    espeakng_loader.make_library_available()
    data_path = espeakng_loader.get_data_path()
    dll_path = espeakng_loader.get_library_path()
    lib = ctypes.cdll.LoadLibrary(dll_path)
    
    pcm_chunks = []
    AUDIO_CALLBACK = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)
    
    def callback(wav_ptr, numsamples, events_ptr):
        if numsamples > 0:
            arr = np.ctypeslib.as_array(wav_ptr, shape=(numsamples,))
            pcm_chunks.append(arr.copy())
        return 0

    c_callback = AUDIO_CALLBACK(callback)
    sr = lib.espeak_Initialize(1, 0, data_path.encode('utf-8'), 0)
    lib.espeak_SetSynthCallback(c_callback)
    lib.espeak_SetVoiceByName(b'hi')
    
    text = "नमस्ते आप कैसे हैं".encode('utf-8')
    lib.espeak_Synth(text, len(text) + 1, 0, 0, 0, 0x1000, None, None)
    lib.espeak_Synchronize()
    
    if pcm_chunks:
        pcm = np.concatenate(pcm_chunks)
        if sr != 16000:
            num_samples = int(len(pcm) * 16000 / sr)
            raw_float = pcm.astype(np.float32) / 32768.0
            resampled = scipy.signal.resample(raw_float, num_samples)
            pcm_16k = np.clip(resampled * 32767.0, -32768, 32767).astype(np.int16)
        else:
            pcm_16k = pcm
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        sf.write(output_path, pcm_16k, 16000, subtype="PCM_16")
        print(f"Generated Hindi WAV at {output_path} ({len(pcm_16k)} samples, {len(pcm_16k)/16000:.2f}s)")
        return True
    return False

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    wav_dir = os.path.join(base_dir, "wav")
    en_path = os.path.join(wav_dir, "english_sample.wav")
    hi_path = os.path.join(wav_dir, "hindi_sample.wav")
    generate_english_wav(en_path)
    generate_hindi_wav(hi_path)
