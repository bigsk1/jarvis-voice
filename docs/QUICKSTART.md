# Jarvis Voice Assistant - Quick Start


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
source ~/jarvis-venv/bin/activate
./jarvis
```

Say: **"Hey Jarvis"** 🎙️

---

## That's it!

For more details:
- Full docs: `README.md`
- Migration: `MIGRATION.md`
- Architecture: `JARVIS_WORKFLOW.md`

---

## Quick Commands

```bash
# Activate venv first
source ~/jarvis-venv/bin/activate

# Cloud mode (OpenAI - powerful)
./jarvis

# Local mode (Ollama - private)
./jarvis-local

# Ask a question without wake word
./bin/question.sh "What's 2+2?"

# Just speak text
./bin/say.sh "Hello world"
```

## Dashboard

```bash
./bin/jarvis-dashboard
```


All unique sessions now:
```bash
tmux attach -t jarvis-voice       # Wake word loop (cloud)
tmux attach -t jarvis-api         # API cloud mode
tmux attach -t jarvis-api-local   # API local mode
tmux attach -t jarvis-services    # Background services
```

# List all
tmux ls

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

