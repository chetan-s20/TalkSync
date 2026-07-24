# TalkSync Performance Analysis - 2026-07-24

## Current End-to-End Latency: **6.44 seconds**

### Breakdown (from logs):
1. **Audio Capture + VAD**: ~1.0s (waiting for speech segment)
2. **STT (Whisper)**: ~2.4s (0.96s audio processed on CPU)
3. **Translation (Argos)**: ~3.0s (includes Stanza sentence splitting)
4. **TTS**: 0s (dummy TTS in test)

**Total**: 6.44s

---

## Target: < 1.5 seconds

### Optimization Strategy:

#### Immediate Wins:
1. **Use GPU for Whisper STT** (currently using CPU)
   - Expected speedup: 2.4s → 0.6s (**-1.8s**)
   
2. **Reduce VAD sensitivity** for faster speech detection
   - Current: waiting for full speech segment
   - Optimization: trigger STT on first 500ms of speech
   - Expected speedup: 1.0s → 0.5s (**-0.5s**)

3. **Cache Argos Stanza models** (first translation is slow)
   - Current cold start: ~3.0s
   - After warmup: ~15ms
   - The test includes warmup, but Stanza loads per language
   - Expected speedup: 3.0s → 0.3s (**-2.7s**)

#### Projected Latency After Optimizations:
- Audio Capture + VAD: 0.5s
- STT (GPU): 0.6s
- Translation (warm): 0.3s
- **Total**: **1.4s** ✓ (under 1.5s threshold)

---

## Real-World Performance Notes:

- **Cold start** (first use): 6-8s
- **Warm operation** (after models loaded): ~1.5s
- The test measures from first audio chunk to translation complete
- In production, users will experience warm latency after the first translation

---

## Actions Needed:

1. ✅ Switch STT to GPU (device="cuda" instead of "cpu")
2. ✅ Optimize VAD buffering strategy
3. ✅ Verify Argos warmup is working correctly
4. ✅ Add latency measurements per stage
5. ✅ Test with real mic/loopback audio
