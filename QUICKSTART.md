# Jarvis Voice Assistant - Quick Start

## 5-Minute Setup

### 1. Navigate & Setup
```bash
cd /home/boss/jarvis-voice
./setup.sh
```

### 2. Add Your API Key (Cloud Mode)
```bash
nano config/cloud.env
```
Find `OPENAI_API_KEY` and paste your key.

### 3. Run Jarvis!
```bash
conda activate jarvis-venv
./jarvis
```

Say: **"Hey Jarvis"** 🎙️

---

## That's it!

For more details:
- Full docs: `README.md`
- Migration: `MIGRATION.md`
- Architecture: `/home/boss/jarvis-docs/jarvis-voice-architecture.md`

---

## Quick Commands

```bash
# Cloud mode (OpenAI - powerful)
./jarvis

# Local mode (Ollama - private)
./jarvis-local

# Ask a question without wake word
./bin/question.sh "What's 2+2?"

# Just speak text
./bin/say.sh "Hello world"
```

---

## Common Issues

**"No input device"**  
→ Check: `arecord -l` and update `IN_DEV` in config

**"Transcription failed"**  
→ Check your `OPENAI_API_KEY` in `config/cloud.env`

**Not detecting wake word**  
→ Lower `TRIGGER_THRESHOLD` in config (try 0.15)

---

**Enjoy your voice assistant! 🎉**

