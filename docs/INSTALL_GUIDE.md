# Jarvis Voice Assistant - Installation Guide

Complete installation guide. Follow these steps **in order** from top to bottom.

**Recommended path:** clone to `~/jarvis-voice` and run `./install.sh`.

**Important:** This project does **not** require a Unix user named `boss`. The portable default layout is:
- Repo: `~/jarvis-voice`
- Virtual environment: `~/jarvis-venv`

Optional integrations such as OpenCode and n8n are covered later and are **not required** for a normal Jarvis install.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1: Create User](#step-1-create-user)
3. [Step 2: Clone Repository](#step-2-clone-repository)
4. [Step 3: Install System Packages](#step-3-install-system-packages)
5. [Step 4: Create Python Environment](#step-4-create-python-environment)
6. [Step 5: Configure Environment Files](#step-5-configure-environment-files)
7. [Step 6: Run Setup Scripts](#step-6-run-setup-scripts)
8. [Step 7: Configure Audio Devices](#step-7-configure-audio-devices)
9. [Step 8: Optional Integrations](#step-8-optional-integrations)
10. [Step 9: Setup Aliases](#step-9-setup-aliases)
11. [Step 10: Verify and Start](#step-10-verify-and-start)
12. [Database Restoration](#database-restoration)
13. [Troubleshooting](#troubleshooting)
14. [Additional Resources](#additional-resources)

---

## Prerequisites

### Server Requirements
- **OS:** Ubuntu Server 24.04 LTS (fresh install recommended)
- **RAM:** 8GB minimum, 16GB+ if running local LLMs
- **Storage:** 50GB+ SSD
- **Network:** Static IP recommended
- **User:** Any sudo-capable Linux user
- **Checkout path:** `~/jarvis-voice`
- **Virtual Environment:** `~/jarvis-venv`
- **Python Version:** 3.12+

### Hardware
- USB microphone or audio interface
- Speakers or audio output
- Ethernet preferred over WiFi

---

## Step 1: Create User

Skip this if you already have a normal sudo-capable user account.

If you want to create a dedicated user for Jarvis, use any username you want:

```bash
sudo useradd -m -s /bin/bash jarvis
sudo passwd jarvis
sudo usermod -aG sudo jarvis
sudo usermod -aG docker jarvis  # Optional: only if using Docker later for n8n

# Switch to that user for remaining steps
su - jarvis
cd ~
```

---

## Step 2: Clone Repository

```bash
cd ~
git clone https://github.com/bigsk1/jarvis-voice.git
cd jarvis-voice
```

## Fast Path: One-Command Install

If you want the smoothest setup, stop here and run:

```bash
cd ~/jarvis-voice
chmod +x install.sh
./install.sh
```

That script handles:
- system dependencies
- `uv` install if missing
- `~/jarvis-venv` creation and package sync
- seeding `config/cloud.env` and `config/local.env` if missing
- `setup.sh`
- `verify-env.sh`
- `setup_tools.sh`

After it finishes, edit your API keys and audio device settings, then continue at **Step 7: Configure Audio Devices** and **Step 9: Setup Aliases** if you want them.

---

## Step 3: Install System Packages

```bash
# Update system first
sudo apt update && sudo apt upgrade -y

# Install all system dependencies
sudo ./install-system-deps.sh

# This installs: ffmpeg, sox, sqlite3, portaudio, pulseaudio, jq, curl, git, etc.
# See system-packages.txt for full list
```

**Verify key packages:**
```bash
ffmpeg -version
sox --version
python3 --version  # Should be 3.12+
```

---

## Step 4: Create Python Environment

**Option A: Using uv (Recommended - faster, exact versions)**
```bash
# Install uv if not present
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc  # or restart terminal

# Create virtual environment
uv venv ~/jarvis-venv

# Activate it
source ~/jarvis-venv/bin/activate
export JARVIS_VENV="$HOME/jarvis-venv"
export UV_PROJECT_ENVIRONMENT="$JARVIS_VENV"

# Install all packages from lockfile (exact versions)
cd ~/jarvis-voice
uv sync --active --no-install-project
```

**Option B: Using pip (Traditional)**
```bash
# Create virtual environment
python3 -m venv ~/jarvis-venv

# Activate it
source ~/jarvis-venv/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel

# Install packages
cd ~/jarvis-voice
pip install -r requirements.txt
```

---

## Step 5: Configure Environment Files

**This must be done BEFORE running setup.sh**

```bash
cd ~/jarvis-voice

# Copy example configs
cp config/cloud.env.example config/cloud.env
# OpenAI-only minimum (one key; other tools gate automatically):
# cp config/cloud.openai.env.example config/cloud.env
cp config/local.env.example config/local.env

# Secure permissions
chmod 600 config/cloud.env config/local.env

# Edit cloud config with your API keys and settings
nano config/cloud.env
nano config/local.env
```

**What you usually need to change in `cloud.env`:**

For a **single OpenAI key**, start from `config/cloud.openai.env.example`
instead of the full template — set `OPENAI_API_KEY` only, then run
`./bin/sync-tools.py cloud` and `./bin/manage-tools.py --mode cloud list`.

```bash
# ===== LLM Provider (pick ONE) =====
LLM_PROVIDER="xai"  # Options: "xai", "anthropic", "openai", "ollama"

# API Key for your chosen provider
XAI_API_KEY=your-xai-key
# or ANTHROPIC_API_KEY=your-anthropic-key
# or OPENAI_API_KEY=your-openai-key

# Model for your provider (see lib/model_catalog.py for curated options)
XAI_MODEL="grok-4.5"              # recommended default
# XAI_MODEL="grok-4.3"            # alternative: 1M context or reasoning_effort=none
# XAI_MODEL="grok-build-0.1"      # alternative: coding / build-heavy workloads
# or ANTHROPIC_MODEL="claude-sonnet-4-5-20250929"
# or OPENAI_MODEL="gpt-4o"

# Or Ollama Cloud through a signed-in Ollama daemon:
# LLM_PROVIDER="ollama"
# OLLAMA_BASE_URL="http://your-ollama-host:11434"
# OLLAMA_CLOUD_MODEL="minimax-m3:cloud"  # daemon path requires a cloud tag
# Alternatively set OLLAMA_API_KEY and use an ID from https://ollama.com/api/tags.

# ===== Speech-to-Text (STT) =====
STT_PROVIDER="openai"  # Options: "openai", "local" (uses faster-whisper)
STT_MODEL="gpt-4o-mini-transcribe"  # For openai provider
OPENAI_API_KEY=your-openai-key

# ===== Text-to-Speech (TTS) =====
TTS_PROVIDER="elevenlabs"  # Options: "elevenlabs", "xai", "openai", "qwen3-tts"

# If using ElevenLabs:
ELEVENLABS_API_KEY=your-elevenlabs-key
ELEVENLABS_TTS_VOICE=your-voice-id  # Get from elevenlabs.io/app/voice-library
ELEVENLABS_TTS_MODEL=eleven_v3
ELEVENLABS_STATUS_TTS_MODEL=eleven_flash_v2_5  # Faster/cheaper progress phrases

# Or if using OpenAI TTS (uses OPENAI_API_KEY):
# TTS_MODEL="gpt-4o-mini-tts"

# Or if using xAI TTS (uses XAI_API_KEY):
# TTS_PROVIDER="xai"
# XAI_TTS_VOICE="eve"  # eve, ara, rex, sal, leo
# XAI_TTS_LANGUAGE="en"

# ===== Audio Devices (configure after Step 7) =====
# Linux native:
IN_DEV="plughw:CARD=Microphone,DEV=0"
OUT_DEV="plughw:CARD=Device,DEV=0"

# WSL2 with PulseAudio:
# IN_DEV="pulse"
# OUT_DEV="pulse"
```

> **Important:** Do **not** shrink `cloud.env` down to only the fields shown above.
> Start by copying the full `config/cloud.env.example` to `config/cloud.env`, then keep the existing defaults unless you have a reason to change them.
>
> In most cases, the only things a new user needs to decide are:
> - provider choices (`LLM_PROVIDER`, `STT_PROVIDER`, `TTS_PROVIDER`)
> - API keys for the providers they enabled
> - model selections if they want something different from the defaults
> - audio device values (`IN_DEV`, `OUT_DEV`)
>
> The example file already contains many smaller settings that are tuned to work well together, so leaving the rest alone is usually the best path.
>
> `JARVIS_MODE` and `LLM_PROVIDER` are separate. Cloud mode selects
> `config/cloud.env` and cloud databases; it does not prohibit Ollama Cloud.
> Local mode normally uses `OLLAMA_MODEL` with a locally hosted daemon. See
> [ollama/README.md](ollama/README.md) for the supported combinations.

---

## Step 6: Run Setup Scripts

If you already ran `./install.sh`, most of this step is already done.

For a manual install, run the setup scripts **in this order**:

```bash
cd ~/jarvis-voice
source ~/jarvis-venv/bin/activate

# 1. Initial setup (creates directories, permissions, symlinks)
./setup.sh

# 2. Verify everything is configured
./verify-env.sh

# 3. Verify tool registration / executable bits
./setup_tools.sh
```

### Script Reference

| Script | Purpose |
|--------|---------|
| `setup.sh` | Creates audio dirs, symlinks, permissions |
| `verify-env.sh` | Validates config files and dependencies |
| `setup_tools.sh` | Makes scripts executable, checks the venv, and verifies tool registration |
| `install-system-deps.sh` | Installs apt packages (run with sudo) |

---

## Step 7: Configure Audio Devices

**Find your audio devices:**
```bash
# List playback devices (speakers)
aplay -L | grep -E '^(plughw|hw):'

# List recording devices (microphones)
arecord -L | grep -E '^(plughw|hw):'
```

or

```bash
aplay -L
arecord -L
```


**Test audio:**
```bash
# Test speakers (should hear white noise)
speaker-test -D plughw:CARD=Device,DEV=0 -c 2 -t wav

# Test microphone (record 5 seconds)
arecord -D plughw:CARD=Microphone,DEV=0 -f cd -d 5 test.wav
aplay test.wav  # Play it back
rm test.wav
```

or

```bash
speaker-test -D pulse -c 2 -t wav
# if pulse doesn't work:
speaker-test -D default -c 2 -t wav
```

```bash
arecord -D pulse -f cd -d 5 test.wav
# if pulse doesn't work:
arecord -D default -f cd -d 5 test.wav

aplay test.wav
rm test.wav
```

If `pulse` isn't listed at all, you can try:

```bash
cat /proc/version
echo $DISPLAY
```

Figure out your own mic and speaker setup and update config/local.env and config/cloud.env with your device names.

---

## Step 8: Optional Integrations

You can skip this entire section if you only want the core Jarvis install.

### OpenCode (Optional)

See [OPENCODE.md](opencode/OPENCODE.md) for the full setup and configuration reference.

If you want OpenCode for autonomous coding:

1. Add the provider keys OpenCode will use, such as `OPENAI_API_KEY`,
   `ANTHROPIC_API_KEY`, or `XAI_API_KEY`, to `config/cloud.env`.
2. Run the setup commands below. The service installer automatically copies the
   supported provider keys and OpenCode authentication values from
   `config/cloud.env` to `~/.config/opencode/jarvis-env.env`.

`config/cloud.env` is the default source. For a local-mode-only setup, run the
installer with `OPENCODE_ENV_FILE=config/local.env`.

```bash
# Create OpenCode workspace
./setup_opencode_workspace.sh

# Create the service environment, sync plugins, and install the service
./bin/install-opencode-service.sh

# Local-mode-only alternative:
# OPENCODE_ENV_FILE=config/local.env ./bin/install-opencode-service.sh
```

The installer creates `~/.config/opencode/jarvis-env.env`, syncs the tracked
workspace-protection plugin to `~/.config/opencode/plugin/`, and starts the
service. Use `./bin/update-opencode-service.sh` after changing provider keys,
server authentication, the service definition, or the tracked plugin.

### n8n (Optional)

If you want n8n workflows, Docker-based automations, or Google Calendar sync, use the optional n8n section later in this guide. It is not required for core Jarvis voice/chat usage.

---

## Step 9: Setup Aliases

Install convenient Bash/Zsh commands. The updater adds one managed source block to the selected RC file; the command definitions remain in the tracked `.jarvis-aliases` file so future pulls update them automatically.

```bash
cd ~/jarvis-voice

# Run alias setup script (detects .bashrc or .zshrc automatically)
./update-aliases.sh

# Reload using the exact command printed by the updater
source ~/.bashrc   # Bash
source ~/.zshrc    # Zsh
```

If you launched Zsh from Bash without making it your login shell, select it explicitly:

```bash
./update-aliases.sh --shell zsh
source ~/.zshrc
```

Advanced overrides:

```bash
./update-aliases.sh --shell bash
./update-aliases.sh --rc-file ~/.config/zsh/custom.zsh
```

**Test aliases:**
```bash
say hello
```

**Available aliases after setup:**
| Alias | Command |
|-------|---------|
| `jarvis` | Start wake word listener (cloud mode) |
| `jarvis-local` | Start wake word listener (local mode) |
| `jarvis-cli` | Full cloud orchestrator from text, without voice output |
| `jarvis-local-cli` | Full local orchestrator from text, without voice output |
| `jarvis-cli-json` / `jarvis-local-cli-json` | Corresponding CLI with JSON output |
| `jarvis-d` | Open TUI dashboard |
| `jarvis-start` / `jarvis-start-local` | Start the complete cloud/local service stack |
| `jarvis-stop` | Stop all Jarvis tmux sessions |
| `jarvis-status` | Show status for every managed session |
| `jarvis-web` / `jarvis-web-local` | Start cloud/local Web UI |
| `jarvis-web-stop` | Stop only the Web UI tmux session |
| `jarvis-api` / `jarvis-api-local` | Start cloud/local API server |
| `jarvis-cd` | cd to jarvis-voice directory |
| `jarvis-env` | Activate Python venv |
| `jarvis-logs` | Open the current tool-log viewer |
| `jarvis-help` | List every installed Jarvis shell command |

The older `question*` aliases remain available for their direct speech/question flows. Use `jarvis-cli` or `jarvis-local-cli` when you want the current provider-aware Jarvis orchestrator, tool routing, memory, and mode isolation.

---

## Step 10: Verify and Start

**Final verification:**
```bash
cd ~/jarvis-voice
source ~/jarvis-venv/bin/activate

# Check everything
./verify-env.sh

# Sync tool embeddings after your keys/providers are configured
./bin/sync-tools.py cloud
./bin/sync-tools.py local

# Test orchestrator
./orchestrator/orchestrator_v2.py cloud "what time is it"

# Open the command dashboard
jarvis-d

# If you are not using aliases, start with:
./bin/jarvis-dashboard
```

If you get warnings about a provider SDK missing, install the SDK for the provider you enabled in `config/cloud.env`, for example:

```bash
source ~/jarvis-venv/bin/activate
pip install xai-sdk
```

From the dashboard, select **Start All Services** for cloud/default startup or
**Start All Services (Local)** for a local-only install, then use **Service
Status** until the services report healthy. The equivalent command-line
operations are `./bin/start`, `./bin/start --local`, `./bin/start --list`, and
`./bin/start --stop`.

**Test voice mode:**
```bash
# Start wake word listener
./jarvis
# Say "Hey Jarvis" followed by a question
```

**Test web UI:**
```bash
# Start web UI (if not already running)
./bin/start web

# Open in browser: http://localhost:5001
```

---

## Quick Reference

### Directory Structure
```
$HOME/
├── jarvis-voice/          # Main codebase
├── jarvis-venv/           # Python virtual environment
├── jarvis-workspace/      # OpenCode projects (autonomous coding sandbox)
└── .config/opencode/      # OpenCode config
    └── plugin/            # OpenCode safety plugins
```

### Key Config Files
| File | Purpose |
|------|---------|
| `config/cloud.env` | API keys, LLM/TTS providers, audio devices |
| `config/local.env` | Ollama settings for local mode |
| `config/ssh.json` | SSH hosts for remote command execution |
| `jarvis-web/config/web_config.json` | Web UI settings (created locally; gitignored) |
| `jarvis-intel/user_profile.md` | Profile Card (copy from `user_profile.md.example` on first install) |

### Profile Card (first install)

`jarvis-intel/user_profile.md` is gitignored. On a fresh clone Jarvis runs fine without it; Tier 2 profile injection is skipped until you create the file:

```bash
cp jarvis-intel/user_profile.md.example jarvis-intel/user_profile.md
# Edit ## Profile Card (~15 lines), then optionally ingest reference sections:
./skills/ingest_intel.py '{"path":"jarvis-intel"}'
```

The tracked `user_profile.md.example` is **not** ingested — `ingest_intel` only scans `*.md` and `*.txt`. See `docs/USER_PROFILE_SYSTEM.md`.

---

## API Key Reference

Get API keys from:
- **xAI**: https://console.x.ai/
- **Anthropic**: https://console.anthropic.com/
- **OpenAI**: https://platform.openai.com/api-keys
- **Google Gemini / Google AI Studio**: https://aistudio.google.com/apikey
- **ElevenLabs**: https://elevenlabs.io/
- **Brave Search**: https://api.search.brave.com/
- **OpenWeatherMap**: https://home.openweathermap.org/api_keys
- **Spotify Developer Dashboard**: https://developer.spotify.com/dashboard
- **Vapi**: https://dashboard.vapi.ai/
- **SerpApi**: https://serpapi.com/dashboard
- **CoinGecko API**: https://www.coingecko.com/en/api
- **Cloudflare API Tokens**: https://dash.cloudflare.com/profile/api-tokens
- **GitHub Personal Access Tokens**: https://github.com/settings/tokens

For self-hosted or optional integrations:
- **OpenCode**: no separate Jarvis-specific provider key is required. Add the provider keys OpenCode will use, such as `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `XAI_API_KEY`, to `config/cloud.env` before running `./bin/install-opencode-service.sh`. The installer copies them to the systemd environment file at `~/.config/opencode/jarvis-env.env`. It uses `config/cloud.env` by default; set `OPENCODE_ENV_FILE=config/local.env` for a local-mode-only service. Optional `OPENCODE_SERVER_PASSWORD` protects both the OpenCode web UI and API with HTTP Basic auth. See `docs/opencode/OPENCODE.md`.
- **n8n**: generate the API key from your own n8n instance at `Settings -> API` after n8n is running. Used by `N8N_LOCAL_API_KEY`.
- **Crawl4AI**: if using a hosted Crawl4AI service, use the key issued by that service/provider.

**Verify keys are set:**
```bash
grep "API_KEY" config/cloud.env | grep -v "^#"
```

---

## Database Restoration

### Step 1: Verify Databases

```bash
cd "$HOME/jarvis-voice/data"

# Check databases exist
ls -lh jarvis_memory.db jarvis_memory_local.db

# Verify integrity
sqlite3 jarvis_memory.db "SELECT COUNT(*) FROM memories;"
sqlite3 jarvis_memory.db "SELECT COUNT(*) FROM conversations;"
sqlite3 jarvis_memory_local.db "SELECT COUNT(*) FROM memories;"
```

---

## n8n Setup (Docker) OPTIONAL!

### Step 1: Install Docker (if not done)

```bash
sudo apt install docker.io docker-compose -y
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker $USER

# Log out and back in for group to take effect
```

### Step 2: Create n8n Container

- see docs/n8n/

```bash
# Create n8n data directory or install on another host
mkdir -p ~/.n8n

# Run n8n container
docker run -d \
  --name n8n \
  --restart unless-stopped \
  -p 5678:5678 \
  -e N8N_HOST=localhost \
  -e WEBHOOK_URL=http://localhost:5678/ \
  -e N8N_PROTOCOL=http \
  -v ~/.n8n:/home/node/.n8n \
  n8nio/n8n:latest

# Verify running
docker ps | grep n8n
```

### Step 3: Access n8n Web UI

Open browser: `http://localhost:5678`

**First-time setup:**
1. Create owner account
2. Set email/password

### Step 4: Configure n8n Credentials

**SMTP Account** (for email tool):
1. Click "Credentials" → "Add Credential"
2. Search "SMTP"
3. Fill in your SMTP details:
   - Host: `smtp.mailgun.org` (or your provider)
   - Port: `587` (TLS) or `465` (SSL)
   - User: Your SMTP username
   - Password: Your SMTP password

**Google Calendar OAuth2** (for calendar sync):
1. Go to https://console.cloud.google.com/
2. Create project (or use existing)
3. Enable Google Calendar API
4. Create OAuth 2.0 credentials (Desktop app)
5. In n8n: Add "Google Calendar" credential
6. Paste Client ID and Secret
7. Authenticate with your Google account

### Step 5: Import n8n Workflows

**Option A: Manual Recreation** (if no backup):
See [`docs/n8n/docs/GOOGLE_CALENDAR_SYNC.md`](n8n/docs/GOOGLE_CALENDAR_SYNC.md) and [`docs/n8n/docs/WEBHOOK_AND_EMAIL_SYSTEM.md`](n8n/docs/WEBHOOK_AND_EMAIL_SYSTEM.md)

**Option B: Import from JSON** (if you have backups, see docs/n8n/docs/workflows/):

```bash
# Workflows are in docs/n8n/workflows/
# Or export from old n8n before disaster

# In n8n UI:
# 1. Click "Workflows" → "Import from File"
# 2. Select JSON file
# 3. Update credentials (OAuth, SMTP)
# 4. Update webhook URLs if IPs changed
# 5. Activate workflow
```

**Required workflows if using these systems with jarvis:**
1. **Jarvis → Send Email** - Email sending via SMTP
2. **Jarvis → Google Calendar Sync** - Reminder to calendar
3. **Google Calendar → Jarvis Sync** - Calendar to reminder (with update/delete)

### Step 6: Generate n8n API Key

1. In n8n: Settings → API → "Create API Key"
2. Copy the key
3. Add to Jarvis config:

```bash
nano "$HOME/jarvis-voice/config/cloud.env"
```

Update:
```bash
N8N_LOCAL_API_KEY="your-api-key-here"
```

---

## Starting Jarvis Services

### Primary Method: tmux Sessions (Recommended)

Jarvis services run in tmux sessions, managed by `./bin/start`:

```bash
cd "$HOME/jarvis-voice"
source ~/jarvis-venv/bin/activate

# Start all services
./bin/start

# Local-only install (requires config/local.env; config/cloud.env may be absent)
./bin/start --local

# Or start specific services
./bin/start api        # API server only
./bin/start web        # Web UI only
./bin/start --ui-only  # All web UIs (no API or background services)
./bin/start --ui-only --local  # All web UIs loading config/local.env

# Check status
./bin/start --list

# Stop all
./bin/start --stop
```

Cloud remains the native default. `--local` may appear before or after the
action or service name (for example, `./bin/start memory --local`). Native
launchers honor an exported `JARVIS_MODE`, but they never read the repo-root
`.env`; that file is reserved for Docker Compose.

**tmux session names:**
- `jarvis-api` - Main API server (port 8880)
- `jarvis-services` - Background services
- `jarvis-web` - Web UI (port 5001)
- `jarvis-canvas` - Canvas service (port 8890)
- `jarvis-memory` - Memory service (port 5002)
- `jarvis-intelligence` - Intelligence service (port 5003)
- `jarvis-docs` - Docs service (port 5004)

### Service Watchdog (Cron)

After starting services, install the watchdog cron job. This ensures the
self-healing daemon (which monitors all other background services) auto-restarts
if it crashes unexpectedly.

> **Running Jarvis in Docker?** Skip this cron entry (or comment it out if already installed).
> Docker uses `restart: unless-stopped` on containers and separate PID files under
> `logs/docker/`. The native watchdog reads `logs/self_healing_daemon.pid` and will
> fight Docker by spawning duplicate host daemons. See [docs/docker/README.md](docker/README.md).

```bash
# Add watchdog cron entry (native tmux install only — not Docker)
(crontab -l 2>/dev/null; echo "# Jarvis watchdog - restart self_healing_daemon if it crashes"; echo "*/5 * * * * \$HOME/jarvis-voice/bin/watchdog-services.sh >> \$HOME/jarvis-voice/logs/watchdog.log 2>&1") | crontab -
```

The watchdog checks every 5 minutes. It only restarts if the PID file exists
but the process is dead (crash). If you intentionally stop services with
`jarvis-services --stop`, the PID files are removed and the watchdog does nothing.

See `docs/service/README.md` for the full supervision chain.

**Attach to a session:**
```bash
tmux attach -t jarvis-api    # View API logs
tmux attach -t jarvis-web    # View web UI logs
# Detach: Ctrl+B then D
```

### TUI Dashboard

The dashboard is the recommended terminal control center, not just a monitor. It
can start and stop the full stack, show service health, launch individual
components, and run common maintenance and debugging commands.

```bash
./bin/jarvis-dashboard
# Or with alias:
jarvis-d
```

A simple daily workflow:

1. Run `jarvis-d`.
2. Select **Start All Services**, or **Start All Services (Local)** when this
   install uses `config/local.env`.
3. Select **Service Status** while startup completes; wait for the services to
   report healthy before opening the web UIs.
4. Attach to a service session when you need live output, for example
   `tmux attach -t jarvis-web`. Detach with `Ctrl+B`, then `D`.
5. When finished, return to `jarvis-d` and select **Stop All Services**.

While dashboard startup is running, its temporary control session is named
`jarvis-start-all` or `jarvis-start-all-local`. UI-only controllers use
`jarvis-start-ui` or `jarvis-start-ui-local`. They close automatically when
startup finishes. **Stop All Services** closes any active controller first,
then stops the API, background services, and UI sessions.

### Systemd Service (Optional - OpenCode Only)

Only one systemd service exists for OpenCode server:

```bash
# First install
./bin/install-opencode-service.sh

# Apply later config, plugin, or service changes
./bin/update-opencode-service.sh

# Check status
sudo systemctl status opencode-jarvis.service
sudo journalctl -u opencode-jarvis.service -n 50 --no-pager
```

**Note:** The main Jarvis services (API, Web, etc.) run via tmux, not systemd.
This allows easy log viewing, debugging, and manual restarts during development.

---

## Final Validation

### Step 1: Test Cloud Mode

```bash
cd "$HOME/jarvis-voice"
source ~/jarvis-venv/bin/activate

# Test basic query
./orchestrator/orchestrator_v2.py cloud "what time is it"

# Test memory
./orchestrator/orchestrator_v2.py cloud "remember my favorite color is blue"
./orchestrator/orchestrator_v2.py cloud "what is my favorite color"

# Test bash execution
./orchestrator/orchestrator_v2.py cloud "list files in current directory"
```

### Step 2: Test Local Mode (if using Ollama)

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull models (default local LLM is gemma4)
ollama pull gemma4
ollama pull nomic-embed-text

# Test
./orchestrator/orchestrator_v2.py local "what time is it"
```

### Step 3: Test Voice Mode

```bash
# Test wake word detection
./jarvis

# Say "Hey Jarvis"
# Then ask a question

# If no wake word detection:
# - Check microphone device in config
# - Test: arecord -D hw:3,0 -f cd -d 5 test.wav
# - Adjust volume: alsamixer
```

### Step 4: Test API Server

```bash
# Check API is running
curl http://localhost:8880/api/health

# Test reminders endpoint
curl http://localhost:8880/api/reminders | jq

# Create test reminder
curl -X POST http://localhost:8880/api/reminders \
  -H "Content-Type: application/json" \
  -d '{"title":"Test","trigger_time":"2025-12-01T10:00:00Z"}'
```

### Step 5: Test Email Tool

```bash
./orchestrator/orchestrator_v2.py cloud "send email to boss with subject Test and body Hello from restored Jarvis"

# Check your email inbox
```

### Step 6: Test Google Calendar Sync

```bash
# Create reminder (should sync to calendar)
./orchestrator/orchestrator_v2.py cloud "remind me tomorrow at 3pm to test calendar sync"

# Wait 1 minute, then check Google Calendar
# Should see event "[Jarvis] Test calendar sync"

# Or create event in Google Calendar
# Wait 1 minute, then check:
curl http://localhost:8880/api/reminders | jq
```

### Step 7: Run Deterministic Tests

```bash
# No provider calls or active-database replacement
~/jarvis-venv/bin/python -m pytest -q \
  tests/test_docs_integrity.py tests/test_mode_plumbing_scripts.py

# Optional read-only OpenCode health check
./tests/integration/test-opencode-integration.sh --health cloud
```

---

## UFW Firewall Configuration

If you're using UFW (recommended), here are the ports Jarvis needs:

### Required ports (internal network)

```bash
# SSH (if remote access needed)
sudo ufw allow 22/tcp

# Jarvis API (webhooks, alerts, reminders)
sudo ufw allow 8880/tcp

# Web UIs
sudo ufw allow 5001/tcp   # Jarvis Web UI
sudo ufw allow 5002/tcp   # Memory Browser
sudo ufw allow 5003/tcp   # Intelligence Dashboard
sudo ufw allow 8890/tcp   # Canvas Viewer

# Optional services
sudo ufw allow 5050/tcp   # UniFi Protect webhook receiver
sudo ufw allow 9090/tcp   # Prometheus (if monitoring enabled)
sudo ufw allow 3000/tcp   # Grafana (if monitoring enabled)
sudo ufw allow 5678/tcp   # N8N
```

### If Ollama is on another server

```bash
# On the Ollama server, allow from Jarvis
sudo ufw allow from localhost to any port 11434
```

### Minimal config (API only)

If you only need the API for external services:

```bash
sudo ufw allow 8880/tcp
sudo ufw enable
```

### Check status

```bash
sudo ufw status verbose
```

---

## Troubleshooting

### Audio Issues

**NOTE: You will have to tweak mic settings based on your mic and enviroment**

- Needs silence to stop wake word and continue on, this would be fine tuning based on hardware

**Microphone not detected:**
```bash
# List devices
arecord -l

# Test with different device
arecord -D plughw:CARD=Device,DEV=0 -f cd -d 3 test.wav

# Check permissions
groups | grep audio
sudo usermod -aG audio "$USER"
```

**Speaker not working:**
```bash
# Test all devices
for card in $(aplay -l | grep "^card" | cut -d: -f1 | cut -d' ' -f2); do
    echo "Testing card $card"
    speaker-test -D hw:$card,0 -c 2 -t wav -l 1
done

# Adjust volume
alsamixer  # Use F6 to select card, arrow keys to adjust
```

**Wake word not detecting:**
```bash
# Check mic sensitivity
arecord -D hw:3,0 -f cd -d 5 test.wav
aplay test.wav  # Should be clear, not too quiet

# Adjust sensitivity in config
nano config/cloud.env
# Look for OPENWAKEWORD_THRESHOLD (default 0.5, try 0.3 for more sensitive)
```

### Service Issues

**Service fails to start:**
```bash
# Check tmux session status
./bin/start --list

# Attach to session and check errors
tmux attach -t jarvis-api

# Test API manually
cd "$HOME/jarvis-voice"
source ~/jarvis-venv/bin/activate
python api/main.py  # Should start API
```

**Permission denied:**
```bash
# Make scripts executable
chmod +x "$HOME/jarvis-voice/bin/wake-jarvis.py"
chmod +x "$HOME/jarvis-voice/bin/wake-jarvis-local.py"
chmod +x "$HOME/jarvis-voice/skills/"*.py
chmod +x "$HOME/jarvis-voice/bin/"*
```

### Database Issues

**Database locked:**
```bash
# Check for stale connections
lsof | grep jarvis_memory.db

# Restart services
./bin/start --stop
./bin/start
```

**Corrupted database:**
```bash
# Check integrity
sqlite3 data/jarvis_memory.db "PRAGMA integrity_check;"

# Restore from backup
cp data/jarvis_memory.db data/jarvis_memory.db.broken
rsync -avz backup-server:/backup/jarvis_memory.db data/
```

### n8n Issues

**Workflows not triggering:**
```bash
# Check n8n container
docker ps | grep n8n
docker logs n8n --tail 50

# Restart n8n
docker restart n8n

# Check workflows are active (green toggle in UI)
```

**OAuth expired:**
```bash
# Google Calendar OAuth expires
# In n8n UI: Credentials → Google Calendar → Re-authenticate
```

**Webhook not found (404):**
```bash
# Workflow must be ACTIVE for production webhooks
# Check webhook URL matches config
# Format: http://localhost:5678/webhook/endpoint-name
```

### API Key Issues

**"API key not found" errors:**
```bash
# Check keys are set
source ~/jarvis-venv/bin/activate
cd "$HOME/jarvis-voice"
python3 << 'TEST'
import sys
sys.path.insert(0, 'lib')
from config_loader import load_config, get_config_value
load_config('cloud')
print(f"XAI: {get_config_value('XAI_API_KEY')[:10]}...")
print(f"OpenAI: {get_config_value('OPENAI_API_KEY')[:10]}...")
TEST
```

**Keys not loading:**
```bash
# Verify .env file format (no quotes around values unless needed)
head -20 config/cloud.env
```

### Network Issues

**Can't reach n8n:**
```bash
# Check n8n is running
curl http://localhost:5678

# Check firewall
sudo ufw status
sudo ufw allow 5678/tcp

# Check Docker networking
docker network ls
docker inspect n8n | grep IPAddress
```

**Jarvis API unreachable:**
```bash
# Check API is running (tmux session)
./bin/start --list
tmux attach -t jarvis-api

# Test API health
curl http://localhost:8880/api/health

# Restart API
tmux kill-session -t jarvis-api
./bin/start api
```

### Memory/Performance Issues

**High memory usage:**
```bash
# Check processes
htop

# Restart services
./bin/start --stop
./bin/start

# Adjust LLM context window in config
nano config/cloud.env
# Reduce MAX_CONTEXT_WINDOW if needed
```

**Slow responses:**
```bash
# Check LLM provider latency
# xAI Grok is fastest (100-200ms)
# Claude is medium (300-500ms)
# Local Ollama depends on hardware

# Monitor
tail -f logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl
```

---

## Post-Installation Checklist

After the core installation is complete, verify:

- [ ] Voice mode responds to "Hey Jarvis"
- [ ] A basic voice or web query returns a response
- [ ] Memory system stores and recalls information
- [ ] API health responds at `http://localhost:8880/api/health`
- [ ] Web UI opens at `http://localhost:5001`
- [ ] Core tmux sessions report healthy in **Service Status** or `./bin/start --list`
- [ ] Runtime logs are being written under `logs/`
- [ ] **Stop All Services** brings the tmux-managed stack down cleanly

---

## Quick Reference Commands

### Start/Stop Services
```bash
# Start all (tmux sessions)
./bin/start

# Stop all
./bin/start --stop

# Check status
./bin/start --list

# View dashboard
./bin/jarvis-dashboard

# Restart API only
tmux kill-session -t jarvis-api
./bin/start api

# Attach to session for debugging
tmux attach -t jarvis-api
tmux attach -t jarvis-web
# Detach: Ctrl+B then D
```

### View Logs
```bash
# API logs (attach to tmux session)
tmux attach -t jarvis-api

# Web UI logs
tmux attach -t jarvis-web

# Tool execution logs
tail -f logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl

# n8n logs
docker logs n8n --tail 100 -f

# OpenCode logs (if using systemd service)
sudo journalctl -u opencode-jarvis.service -f
```

### Test Audio
```bash
# Record 5 seconds
arecord -D hw:3,0 -f cd -d 5 test.wav

# Playback
aplay test.wav

# Speaker test
speaker-test -D hw:0,0 -c 2 -t wav -l 1
```

### Database Operations
```bash
# Enter SQLite shell
sqlite3 data/jarvis_memory.db

# Quick queries
.tables
SELECT COUNT(*) FROM memories;
SELECT COUNT(*) FROM conversations;
.quit

# Backup database
cp data/jarvis_memory.db data/jarvis_memory.db.backup-$(date +%Y%m%d)
```

### n8n Operations
```bash
# Restart n8n
docker restart n8n

# View logs
docker logs n8n --tail 50

# Stop/start
docker stop n8n
docker start n8n
```

---

## Backup Strategy

**Current backup methods:**
1. **Git repository** - Code, docs, scripts
2. **rsync backup** - Full `$HOME` directory
3. **Database backups** - Manual or cron

**Recommended cron jobs:**

```bash
# Edit crontab
crontab -e

# Add these lines:

# Jarvis watchdog - restart self_healing_daemon if it crashes (native only — skip if using Docker)
# */5 * * * * $HOME/jarvis-voice/bin/watchdog-services.sh >> $HOME/jarvis-voice/logs/watchdog.log 2>&1

# Daily database backup at 2 AM
0 2 * * * cp $HOME/jarvis-voice/data/jarvis_memory.db $HOME/jarvis-voice/data/backups/jarvis_memory-$(date +\%Y\%m\%d).db

# Weekly rsync to backup server at 3 AM Sunday
0 3 * * 0 rsync -avz $HOME/ backup-server:/backup/jarvis-home/

# Keep only last 30 days of database backups
0 4 * * * find $HOME/jarvis-voice/data/backups/ -name "jarvis_memory-*.db" -mtime +30 -delete

# Jarvis weekly cleanup (logs 60d, audio 30d, images 120d,
# unreferenced uploads 60d, policy-based stash TTL)
0 3 * * 0 $HOME/jarvis-voice/bin/cleanup-all >> $HOME/jarvis-voice/logs/cleanup.log 2>&1

# Monthly profile reconcile report, review-only, no auto-write
0 9 1 * * cd $HOME/jarvis-voice && . $HOME/jarvis-venv/bin/activate && ./bin/reconcile-profile > logs/profile-reconcile-$(date +\%Y\%m\%d).md 2>&1
```

---

## Version Information

**Last Updated:** 2026-06-29
**Verified against Jarvis:** v2.53.0 (2026-06-29)
**Tested On:** Ubuntu 24.04 LTS
**Python Version:** 3.12+
**Package Manager:** uv (recommended) or pip

---

## Additional Resources

### Getting It Running

- **Main README:** [`README.md`](../README.md)
- **Documentation Index:** [`docs/README.md`](README.md)
- **Quickstart Guide:** [`docs/QUICKSTART.md`](QUICKSTART.md)
- **Config Guide:** [`config/README.md`](../config/README.md)
- **Web UI Guide:** [`docs/JARVIS_WEB_UI.md`](JARVIS_WEB_UI.md)
- **Service README:** [`docs/service/README.md`](service/README.md)
- **Testing Guide:** [`docs/TESTING.md`](TESTING.md)

### Optional Integrations

- **Webhook System:** [`docs/WEBHOOK_SYSTEM.md`](WEBHOOK_SYSTEM.md)
- **Google Calendar Sync:** [`docs/n8n/docs/GOOGLE_CALENDAR_SYNC.md`](n8n/docs/GOOGLE_CALENDAR_SYNC.md)
- **n8n Integration:** [`docs/n8n/n8n-mcp.md`](n8n/n8n-mcp.md)
- **OpenCode:** [`docs/opencode/OPENCODE.md`](opencode/OPENCODE.md)
- **Service Architecture FAQ:** [`docs/service/SERVICE_ARCHITECTURE_FAQ.md`](service/SERVICE_ARCHITECTURE_FAQ.md)

---

**Need Help?** Use this guide with an LLM (Claude, GPT-5, etc.) to walk through each section step-by-step. The LLM can help troubleshoot issues and adapt commands to your specific hardware/environment.
