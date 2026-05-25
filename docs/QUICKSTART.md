# Jarvis Voice Assistant - Quick Start

### 1. Install

```bash
cd ~/jarvis-voice
chmod +x install.sh
./install.sh
./setup.sh
```

`install.sh` creates the venv and dependencies. `setup.sh` handles audio dirs, symlinks, and permissions.

For the full walkthrough (keys, audio, systemd), see [INSTALL_GUIDE.md](INSTALL_GUIDE.md).

### 2. Add Your API Key (Cloud Mode)

```bash
nano config/cloud.env
```

Set at least one cloud provider key (e.g. `XAI_API_KEY`, `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY`). See [../config/README.md](../config/README.md).

### 3. Run Jarvis

```bash
source ~/jarvis-venv/bin/activate
./jarvis
```

Say: **"Hey Jarvis"**

---

## That's it

For more details:

- Full docs: [../README.md](../README.md) (repo root) and [README.md](README.md) (doc index)
- Architecture: [JARVIS_WORKFLOW.md](JARVIS_WORKFLOW.md)
- Doc index status: [DOCS_STATUS.md](DOCS_STATUS.md)

---

## Quick Commands

```bash
# Activate venv first
source ~/jarvis-venv/bin/activate

# Cloud mode (xAI / OpenAI / Anthropic)
./jarvis

# Local mode (Ollama)
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

Common tmux sessions:

```bash
tmux attach -t jarvis-voice       # Wake word loop (cloud)
tmux attach -t jarvis-api         # API cloud mode
tmux attach -t jarvis-api-local   # API local mode
tmux attach -t jarvis-services    # Background services
tmux ls                           # List all
```

---

## Common Issues

**"No input device"**  
→ Check: `arecord -l` and update `IN_DEV` in config

**"Transcription failed"**  
→ Check your API key in `config/cloud.env`

**Not detecting wake word**  
→ Lower `TRIGGER_THRESHOLD` in config (try 0.15)

---

**Enjoy your voice assistant!**
