# Jarvis Voice Assistant

A self-hosted, voice-activated AI assistant with dual-mode operation (cloud and local).

---

## 🎯 Features

- **Wake Word Detection**: "Hey Jarvis" using OpenWakeWord
- **Dual Mode Operation**:
  - **Cloud Mode**: OpenAI (GPT-4o-mini, Whisper, TTS) - More powerful
  - **Local Mode**: Ollama + faster-whisper + Kokoro TTS - Private and offline
- **Fine-tuned Audio**: Optimized for noisy environments and far-field microphone
- **Organized & Extensible**: Clean architecture ready for tools and automations
- **Version Controlled**: Git-based, local-only repository for safe experimentation

---

## 📁 Project Structure

```
jarvis-voice/
├── bin/                      # Executable scripts
│   ├── wake_jarvis.py        # Cloud wake word loop
│   ├── wake_jarvis_local.py  # Local wake word loop
│   ├── say.sh                # Cloud TTS
│   ├── say-local.sh          # Local TTS
│   ├── question.sh           # Cloud Q&A from text
│   ├── question-local.sh     # Local Q&A from text
│   ├── question-mic.sh       # Cloud Q&A from mic
│   ├── question-mic-local.sh # Local Q&A from mic
│   └── stt_local.py          # Local speech-to-text
├── lib/                      # Shared libraries
│   ├── config_loader.py      # Python config loader
│   └── config_loader.sh      # Bash config loader
├── config/                   # Configuration files
│   ├── cloud.env             # Cloud/OpenAI settings
│   ├── local.env             # Local/Offline settings
│   └── config.env.template   # Template for new configs
├── skills/                   # Future: tool scripts
├── orchestrator/             # Future: planning & routing
├── audio/                    # Audio artifacts
│   ├── cloud/                # Cloud mode recordings
│   └── local/                # Local mode recordings
├── docs/                     # Documentation
├── setup.sh                  # Setup/migration script
└── README.md                 # This file
```

---

## 🚀 Quick Start

### 1. Setup

Run the setup script:

```bash
cd /home/boss/jarvis-voice
./setup.sh
```

This will:
- Check dependencies (sox, ffmpeg, jq, python packages)
- Create audio directories
- Initialize git repository
- Create convenience symlinks

### 2. Configure

Edit configuration files with your settings:

**For Cloud Mode:**
```bash
nano config/cloud.env
```
- Add your `OPENAI_API_KEY`
- Adjust audio device names if needed
- Customize personality settings

**For Local Mode:**
```bash
nano config/local.env
```
- Set your Ollama endpoint (default: `http://192.168.70.226:11434`)
- Set your Kokoro TTS endpoint (default: `http://192.168.70.226:8880`)
- Adjust model names if needed

### 3. Run

Activate your Python environment:
```bash
conda activate jarvis-venv
```

Run Jarvis:
```bash
# Cloud mode (more powerful)
./jarvis

# Local mode (private, offline)
./jarvis-local
```

Say "**Hey Jarvis**" to wake it up!

---

## 🎙️ Audio Configuration

### Hardware
- **Microphone**: TONOR G11 USB (configured as `plughw:CARD=microphone,DEV=0`)
- **Speaker**: ALC269VC analog (configured as `plughw:CARD=Generic_1,DEV=0`)

### Fine-tuned Settings

These values have been carefully tuned for a noisy office environment with far-field microphone. **Don't change them unless testing in a new environment!**

**Wake Word Detection:**
- `TRIGGER_THRESHOLD=0.2` (0.2-0.5 range; lower = more sensitive)
- `HIT_FRAMES_REQUIRED=4` (consecutive frames to trigger)
- `MIN_RMS=2e-4` (noise gate threshold)
- `VAD_THRESHOLD=0.40` (voice activity detection)
- `ARM_GRACE_SEC=1.0-1.2` (cooldown after re-arming)
- `COOLDOWN_AFTER_QA=2.8` (wait before listening again)

**Recording (SoX):**
- `THRESH=3%` (silence detection threshold)
- `PRE_SIL=0.1` (initial silence before speech)
- `POST_SIL=1.5` (trailing silence to stop)
- `highpass 300` (filter out low-frequency noise)

---

## 🔧 Development Workflow

### Creating a Feature Branch

```bash
cd /home/boss/jarvis-voice

# Create a new branch for your feature
git checkout -b feature/home-automation

# Make your changes...
# Edit skills/, orchestrator/, or other files

# Test thoroughly
./jarvis  # or ./jarvis-local

# Commit your changes
git add .
git commit -m "Add home automation skill"

# Switch back to main
git checkout master

# Merge if everything works
git merge feature/home-automation
```

### Rollback if Something Breaks

```bash
# See what changed
git log --oneline

# Revert to a previous commit
git reset --hard <commit-hash>

# Or just check out a specific file
git checkout <commit-hash> -- config/cloud.env
```

---

## 🛠️ Extending Jarvis

### Adding a New Tool/Skill

1. **Create the tool script** in `skills/`:
   ```bash
   nano skills/weather.sh
   ```

2. **Define the interface**:
   - Input: JSON via stdin
   - Output: JSON to stdout
   - Exit code: 0 for success

3. **Example tool**:
   ```bash
   #!/bin/bash
   # skills/weather.sh
   INPUT=$(cat)
   LOCATION=$(echo "$INPUT" | jq -r '.location')
   
   # Get weather somehow...
   TEMP="72°F"
   
   # Return JSON
   jq -n --arg speech "It's $TEMP in $LOCATION" '{ok:true, speech:$speech}'
   ```

4. **Integrate** via orchestrator (see next section)

### Orchestrator Pattern

The orchestrator will:
1. Receive transcribed text
2. Determine intent (using LLM router)
3. Call appropriate tool/skill
4. Return speech text for TTS

```
Transcription → Orchestrator → Tool Selection → Execution → TTS
```

---

## 📝 Usage Examples

### Cloud Mode

```bash
# Run the wake loop
./jarvis

# Say: "Hey Jarvis"
# Jarvis: "Heh heh heh... I am the ghost pokemon..."
# You: "What's the weather like?"
# Jarvis: [Responds]
```

### Local Mode

```bash
# Run the wake loop
./jarvis-local

# Say: "Hey Jarvis"
# Jarvis: "What is it this time?"
# You: "Tell me a joke"
# Jarvis: [Responds using Ollama]
```

### Manual Q&A (No Wake Word)

```bash
# Cloud
./bin/question.sh "What is 2+2?"

# Local
./bin/question-local.sh "What is 2+2?"
```

### Just TTS (Text to Speech)

```bash
# Cloud
./bin/say.sh "Hello world"

# Local
./bin/say-local.sh "Hello world"
```

---

## 🐛 Troubleshooting

### "No input device found"

Check your microphone:
```bash
arecord -l
```
Update `IN_DEV` in `config/*.env` if the device changed.

### "aplay failed"

Check your speaker:
```bash
aplay -l
```
Update `OUT_DEV` in `config/*.env`.

### "Transcription failed"

- Check your `OPENAI_API_KEY` (cloud mode)
- Verify Ollama is running (local mode): `curl http://192.168.70.226:11434/api/tags`

### Wake word not detecting

- Try speaking louder/closer
- Lower `TRIGGER_THRESHOLD` in config (e.g., from 0.2 to 0.15)
- Check `MIN_RMS` threshold (raise if too sensitive to noise)

### Too many false triggers

- Raise `TRIGGER_THRESHOLD` (e.g., from 0.2 to 0.3)
- Increase `HIT_FRAMES_REQUIRED` (e.g., from 4 to 6)
- Raise `MIN_RMS` to filter out background noise

---

## 🔒 Security Notes

- `config/*.env` files contain secrets (API keys)
- `.gitignore` prevents committing secrets
- Files are `chmod 600` by default
- This repo is **local only** - never push to public GitHub!

---

## 📚 Documentation

See `jarvis-docs/jarvis-voice-architecture.md` for detailed technical documentation on:
- Audio pipeline architecture
- End-to-end flow diagrams
- Extension patterns
- MCP integration (future)

---

## 🎭 Personality Customization

Edit `SYSTEM_PROMPT`, `TTS_INSTRUCTIONS`, and `WAKE_GREETING` in your config files to change Jarvis's personality.

**Current default (cloud)**: Ghost Pokemon personality (eerie, playful, haunting)

---

## 🤝 Contributing

This is a local project, but you can:
1. Create feature branches
2. Test thoroughly
3. Merge to master when stable
4. Keep detailed commit messages
5. Tag major versions: `git tag v1.0`

---

## 📜 License

Personal project - use however you want!

---

## 🙏 Credits

- **OpenWakeWord**: Wake word detection
- **OpenAI**: GPT-4, Whisper, TTS
- **Ollama**: Local LLM
- **faster-whisper**: Local STT
- **Kokoro TTS**: Local text-to-speech
- **SoX**: Audio recording/processing
- **ALSA/PipeWire**: Linux audio stack

---

**Built with ❤️ and a lot of fine-tuning!**

