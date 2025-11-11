# Quick Test Commands

Use these commands to verify your Jarvis setup works correctly.

## Prerequisites
```bash
cd /home/boss/jarvis-voice
source ~/jarvis-venv/bin/activate
```

---

## Test 1: Configuration Loading

### Cloud Config
```bash
python3 << 'PY'
import sys
sys.path.insert(0, 'lib')
from config_loader import load_config, get_config_value

load_config('cloud')
print("✓ Cloud config loaded")
print(f"  Chat Model: {get_config_value('CHAT_MODEL')}")
print(f"  Wake Model: {get_config_value('WAKE_MODEL')}")
print(f"  Trigger Threshold: {get_config_value('TRIGGER_THRESHOLD')}")
PY
```

### Local Config
```bash
python3 << 'PY'
import sys
sys.path.insert(0, 'lib')
from config_loader import load_config, get_config_value

load_config('local')
print("✓ Local config loaded")
print(f"  Ollama Model: {get_config_value('OLLAMA_MODEL')}")
print(f"  TTS URL: {get_config_value('TTS_URL')}")
PY
```

---

## Test 2: Skills (Tools)

### Time Skill
```bash
echo '{}' | ./skills/time.sh | jq .
```

**Expected output:**
```json
{
  "ok": true,
  "speech": "It's 03:45 PM on Tuesday, November 11",
  "data": {
    "time": "15:45"
  }
}
```

### Weather Skill (Mock)
```bash
echo '{"location":"Portland"}' | ./skills/weather.sh | jq .
```

**Expected output:**
```json
{
  "ok": true,
  "speech": "It's 72 degrees and partly cloudy in Portland",
  "data": {
    "location": "Portland",
    "temp": 72,
    "condition": "partly cloudy"
  }
}
```

### Python Example Tool
```bash
echo '{"name":"Boss"}' | ./skills/example_tool.py | jq .
```

---

## Test 3: Orchestrator

### Router Test
```bash
./orchestrator/router.py cloud "What time is it?"
```

**Expected:** Intent should be "tool" with tool_name "time"

```bash
./orchestrator/router.py cloud "What's the weather in Seattle?"
```

**Expected:** Intent should be "tool" with tool_name "weather"

```bash
./orchestrator/router.py cloud "Tell me a joke"
```

**Expected:** Intent should be "qa"

### Executor Test
```bash
./orchestrator/executor.py cloud time '{}'
```

**Expected:** JSON response with current time

---

## Test 4: TTS (Text-to-Speech)

### Cloud TTS
```bash
# Make sure OPENAI_API_KEY is set in config/cloud.env first!
./bin/say.sh "Testing cloud text to speech"
```

**Expected:** Audio plays, file saved in `audio/cloud/recordings/`

### Local TTS
```bash
# Make sure Kokoro TTS is running at the configured endpoint
./bin/say-local.sh "Testing local text to speech"
```

**Expected:** Audio plays, file saved in `audio/local/tts/`

---

## Test 5: Q&A (Without Microphone)

### Cloud Q&A
```bash
./bin/question.sh "What is two plus two?"
```

**Expected:** Gets answer from OpenAI, speaks it, saves files

### Local Q&A
```bash
./bin/question-local.sh "What is two plus two?"
```

**Expected:** Gets answer from Ollama, speaks it, saves files

---

## Test 6: Wake Word Detection (Full Test)

### Cloud Mode
```bash
./jarvis
# Say "Hey Jarvis" near your microphone
# Then ask a question when prompted
# Ctrl+C to exit
```

### Local Mode
```bash
./jarvis-local
# Say "Hey Jarvis" near your microphone
# Then ask a question when prompted
# Ctrl+C to exit
```

---

## Test 7: Audio Devices

### Check Microphone
```bash
arecord -l
```

**Expected:** Should show your TONOR G11 USB microphone

### Check Speaker
```bash
aplay -l
```

**Expected:** Should show your ALC269VC (Generic_1) device

### Test Recording
```bash
# Record 3 seconds
arecord -D plughw:CARD=microphone,DEV=0 -r 16000 -c 1 -f S16_LE -d 3 test_mic.wav
# Play it back
aplay -D plughw:CARD=Generic_1,DEV=0 test_mic.wav
rm test_mic.wav
```

---

## Test 8: Git Repository

### Check Status
```bash
git log --oneline
git status
git branch
```

### Test Branch Creation
```bash
git checkout -b test/verify-git
git checkout master
git branch -d test/verify-git
```

---

## Troubleshooting Failed Tests

### Test 1 Failed (Config Loading)
- Check `config/cloud.env` and `config/local.env` exist
- Check syntax in config files (no quotes around values needed)

### Test 2 Failed (Skills)
- Run `chmod +x skills/*.sh skills/*.py`
- Check `jq` is installed: `sudo apt install jq`

### Test 3 Failed (Orchestrator)
- Run `chmod +x orchestrator/*.py`
- Check Python path is correct

### Test 4 Failed (TTS)
- **Cloud**: Verify `OPENAI_API_KEY` in config/cloud.env
- **Local**: Verify Kokoro TTS server is running
- Check audio devices with `aplay -l`

### Test 5 Failed (Q&A)
- Same as Test 4, plus:
- Check `curl`, `ffmpeg`, `sox` are installed

### Test 6 Failed (Wake Word)
- Check Test 7 (audio devices) first
- Check microphone permissions
- Verify venv is activated: `source ~/jarvis-venv/bin/activate`
- Check `openwakeword` is installed: `pip list | grep openwakeword`

---

## All Tests Passed? 🎉

You're ready to use Jarvis! 

**Next steps:**
1. Read `README.md` for full documentation
2. Try creating a custom skill in `skills/`
3. Experiment with git branches
4. Customize personality in config files

---
