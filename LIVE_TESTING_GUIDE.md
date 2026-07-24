# TalkSync AI - Live Testing Guide

**App Status**: 🟢 RUNNING  
**Time**: 2026-07-24 13:20 (IST)

---

## 🎤 Quick Testing Steps

### 1. **Check the App Window**
The TalkSync app should now be visible on your screen with:
- ✅ Main window with CustomTkinter interface
- ✅ Transcript panels (source and translation)
- ✅ Control buttons (Start/Stop/Mute)
- ✅ Status indicators

### 2. **Test Basic Speech Translation** (English → Hindi)

**Steps**:
1. Click the **"Start"** button in the app
2. Speak clearly into your microphone: **"Hello, how are you?"**
3. Wait 2-3 seconds
4. You should see:
   - ✅ Original text: "Hello, how are you?"
   - ✅ Translation: "नमस्ते, आप कैसे हैं?"
   - ✅ Audio playback of Hindi translation

**What to Watch For**:
- Green status indicator when listening
- Blue status when processing
- Transcript appears in both panels
- Hindi audio plays through speakers

### 3. **Test Reverse Translation** (Hindi → English)

**If you can speak Hindi**:
1. Say: **"नमस्ते, मैं ठीक हूं"** (Namaste, main theek hoon)
2. Should translate to: "Hello, I am fine"

**Alternative Test**:
- The app is in "two_way" mode
- It auto-detects language and translates accordingly
- Try switching between English and Hindi phrases

### 4. **Test Text Input Mode**

1. Find the text input box at the bottom
2. Type: **"Good morning"**
3. Press **Ctrl+Enter**
4. Should translate to: "सुप्रभात"

---

## 🔍 What to Verify

### Audio Capture ✓
- [ ] Microphone icon lights up when speaking
- [ ] Audio level indicator responds to your voice
- [ ] No choppy or distorted audio

### Speech Recognition ✓
- [ ] Transcription appears within 2-3 seconds
- [ ] Accuracy > 90% for clear speech
- [ ] Detects language correctly

### Translation ✓
- [ ] Translation appears immediately after transcription
- [ ] Hindi output is grammatically correct
- [ ] No error messages in UI

### Audio Playback ✓
- [ ] Hindi audio plays through speakers
- [ ] Volume is audible and clear
- [ ] No crackling or distortion

---

## 📊 Expected Performance

Based on our optimizations:

| Metric | Expected | Notes |
|--------|----------|-------|
| **First translation** | ~2.0s | Cold start (models loading) |
| **Subsequent translations** | < 1.0s | Warm (models loaded) |
| **STT accuracy** | > 90% | Clear speech, low noise |
| **Translation accuracy** | > 85% | Short conversational phrases |
| **Audio quality** | High | 16kHz, no distortion |

---

## 🐛 Troubleshooting

### If Nothing Happens:
```bash
# Check if app is running
ps aux | grep python | grep main.py

# View debug logs
tail -f output.log
tail -f error.log
```

### If Microphone Not Working:
1. Check Windows Sound Settings → Recording
2. Ensure "Microphone Array (Realtek)" is enabled
3. Set as default device
4. Test with Windows Voice Recorder first

### If Translation is Slow (> 5s):
- First translation is slower (loading models)
- Check GPU is being used: Look for log message "STT using GPU: NVIDIA GeForce RTX 4060"
- Subsequent translations should be much faster

### If Hindi Audio Doesn't Play:
- Check speaker volume
- Verify TTS speaker icon is not muted in app
- Hindi TTS uses Sarvam API (requires internet through proxy)

---

## 🔊 Advanced Tests

### Test Loopback (Computer Audio):

1. **Enable Stereo Mix**:
   - Right-click speaker icon → Sounds
   - Recording tab → Right-click → Show Disabled Devices
   - Enable "Stereo Mix"

2. **In TalkSync**:
   - Enable loopback mode (if available in settings)
   - Play a YouTube video in English
   - Should capture and translate computer audio

### Test Different Accents:
- American English
- British English
- Indian English (Hinglish)
- Native Hindi

---

## 📝 What to Note

Please observe and report:

1. **Latency**: How long from speaking to hearing translation?
2. **Accuracy**: What percentage of words are correct?
3. **Errors**: Any crashes, freezes, or error messages?
4. **Quality**: Audio clarity, any distortion?
5. **Usability**: Is the UI responsive and intuitive?

---

## 🛑 Stopping the App

When done testing:
1. Click **"Stop"** button in app
2. Close the window
3. Or run: `pkill -f "python main.py"`

---

## 📸 Expected UI Layout

```
┌─────────────────────────────────────────────────┐
│  TalkSync AI        [GPU] [EN↔HI] [●Listening]  │
├─────────────────────────────────────────────────┤
│  ┌─────────────────┬─────────────────┐          │
│  │ English         │ हिंदी           │          │
│  │                 │                 │          │
│  │ Hello, how      │ नमस्ते, आप     │          │
│  │ are you?        │ कैसे हैं?       │          │
│  │                 │                 │          │
│  └─────────────────┴─────────────────┘          │
│                                                  │
│  Type a message... (Ctrl+Enter)     [▶]         │
│  [● Mic] [🔊 Speaker] [📊 Stats] [▶ Start]     │
└─────────────────────────────────────────────────┘
```

---

## ✅ Success Criteria

The live app test is successful if:
- ✅ App window opens without errors
- ✅ Microphone captures audio clearly
- ✅ Speech is transcribed accurately (> 90%)
- ✅ Translation appears in 2-3 seconds
- ✅ Hindi audio plays through speakers
- ✅ No crashes or freezes
- ✅ Subsequent translations are faster (< 1s)

---

**Current Status**: App is running. Please test with the steps above and report your findings!
