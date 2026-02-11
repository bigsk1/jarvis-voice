# Jarvis Voice Assistant - Disaster Recovery Guide

Complete rebuild guide. Follow these steps **in order** from top to bottom.

**Note:** This project assumes a user named `boss` with paths like `/home/boss/jarvis-voice`. Adapt to your setup if different.

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
9. [Step 8: Install OpenCode Plugins](#step-8-install-opencode-plugins)
10. [Step 9: Setup Aliases](#step-9-setup-aliases)
11. [Step 10: Verify and Start](#step-10-verify-and-start)
12. [Database Restoration](#database-restoration)
13. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Server Requirements
- **OS:** Ubuntu Server 24.04 LTS (fresh install recommended)
- **RAM:** 8GB minimum, 16GB+ if running local LLMs
- **Storage:** 50GB+ SSD
- **Network:** Static IP recommended
- **User:** Admin user named `boss` with sudo access

### Hardware
- USB microphone or audio interface
- Speakers or audio output
- Ethernet preferred over WiFi

---

## Step 1: Create User

If you didn't create `boss` during Ubuntu install:

```bash
sudo useradd -m -s /bin/bash boss
sudo passwd boss
sudo usermod -aG sudo boss
sudo usermod -aG docker boss  # Optional: if using Docker for n8n

# Switch to boss for remaining steps
su - boss
cd ~
```

---

## Step 2: Clone Repository

```bash
cd /home/boss
git clone https://github.com/bigsk1/jarvis-voice.git
cd jarvis-voice
```

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

# Install all packages from lockfile (exact versions)
cd ~/jarvis-voice
uv sync
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
cp config/local.env.example config/local.env

# Secure permissions
chmod 600 config/cloud.env config/local.env

# Edit cloud config with your API keys
nano config/cloud.env
nano config/local.env
```

**Minimum required settings in cloud.env:**
```bash
# LLM Provider (at least one)
XAI_API_KEY=your-xai-key
# or ANTHROPIC_API_KEY=your-anthropic-key
# or OPENAI_API_KEY=your-openai-key

# TTS Provider (at least one)
ELEVENLABS_API_KEY=your-elevenlabs-key
# or use OPENAI_API_KEY for OpenAI TTS

# Audio devices (configure after Step 7)
SPEAKER_DEVICE_NAME=plughw:CARD=Device,DEV=0
MIC_DEVICE_NAME=plughw:CARD=Microphone,DEV=0
```

---

## Step 6: Run Setup Scripts

Now run the setup scripts **in this order**:

```bash
cd ~/jarvis-voice
source ~/jarvis-venv/bin/activate

# 1. Initial setup (creates directories, permissions, symlinks)
./setup.sh

# 2. Verify everything is configured
./verify-env.sh

# 3. Sync tools to database (registers all 60+ skills)
./setup_tools.sh

# 4. Create OpenCode workspace (for autonomous coding) install opencode first see docs/opencode/OPENCODE.md
./setup_opencode_workspace.sh
```

### Script Reference

| Script | Purpose |
|--------|---------|
| `setup.sh` | Creates audio dirs, symlinks, permissions |
| `verify-env.sh` | Validates config files and dependencies |
| `setup_tools.sh` | Syncs tool definitions to SQLite database |
| `setup_opencode_workspace.sh` | Creates ~/jarvis-workspace for OpenCode projects |
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

**Test audio:**
```bash
# Test speakers (should hear white noise)
speaker-test -D plughw:CARD=Device,DEV=0 -c 2 -t wav

# Test microphone (record 5 seconds)
arecord -D plughw:CARD=Microphone,DEV=0 -f cd -d 5 test.wav
aplay test.wav  # Play it back
rm test.wav
```

**Update config/cloud.env with your device names:**
```bash
SPEAKER_DEVICE_NAME=plughw:CARD=YourSpeaker,DEV=0
MIC_DEVICE_NAME=plughw:CARD=YourMic,DEV=0
```

---

## Step 8: Install OpenCode Plugins

If using OpenCode for autonomous coding:

```bash
# Create plugin directory
mkdir -p ~/.config/opencode/plugin

# Copy safety plugins from repo
cp ~/jarvis-voice/docs/opencode/plugin/*.js ~/.config/opencode/plugin/
cp ~/jarvis-voice/docs/opencode/plugin/README.md ~/.config/opencode/plugin/

# Verify
ls ~/.config/opencode/plugin/
# Should show: 00-workspace-protection.js  README.md
```

---

## Step 9: Setup Aliases

Add convenient bash aliases:

```bash
cd ~/jarvis-voice

# Run alias setup script
./update-aliases.sh

# Reload bashrc
source ~/.bashrc
```

**Available aliases after setup:**
| Alias | Command |
|-------|---------|
| `jarvis` | Start wake word listener (cloud mode) |
| `jarvis-local` | Start wake word listener (local mode) |
| `jarvis-d` | Open TUI dashboard |
| `jarvis-web` | Start web UI |
| `jarvis-api` | Start API server |
| `jarvis-cd` | cd to jarvis-voice directory |
| `jarvis-env` | Activate Python venv |

---

## Step 10: Verify and Start

**Final verification:**
```bash
cd ~/jarvis-voice
source ~/jarvis-venv/bin/activate

# Check everything
./verify-env.sh

# Start all services
./bin/start

# Check status
./bin/start --list
```

**Test voice mode:**
```bash
# Start wake word listener
./jarvis
# Say "Hey Jarvis" followed by a question

# Or use dashboard for TUI
./bin/jarvis-dashboard
```

**Test web UI:**
```bash
# Start web UI (if not already running)
./bin/start web

# Open in browser: http://localhost:3000
```

---

## Quick Reference

### Directory Structure
```
/home/boss/
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
| `config/web_config.json` | Web UI settings |

---

## API Key Reference

Get API keys from:
- **xAI**: https://console.x.ai/
- **Anthropic**: https://console.anthropic.com/
- **OpenAI**: https://platform.openai.com/api-keys
- **ElevenLabs**: https://elevenlabs.io/
- **Brave Search**: https://api.search.brave.com/

**Verify keys are set:**
```bash
grep "API_KEY" config/cloud.env | grep -v "^#"
```

---

## Database Restoration

### Step 1: Verify Databases

```bash
cd /home/boss/jarvis-voice/data

# Check databases exist
ls -lh jarvis_memory.db jarvis_memory_local.db

# Verify integrity
sqlite3 jarvis_memory.db "SELECT COUNT(*) FROM memories;"
sqlite3 jarvis_memory.db "SELECT COUNT(*) FROM conversations;"
sqlite3 jarvis_memory_local.db "SELECT COUNT(*) FROM memories;"
```

**If databases missing or corrupted:**

```bash
# They'll be auto-created on first run, but you'll lose history
# Better: Restore from your latest rsync backup! if availible
```

### Step 2: Test Database Access

```bash
source ~/jarvis-venv/bin/activate
cd /home/boss/jarvis-voice

python3 << 'TEST'
import sys
sys.path.insert(0, 'lib')
from memory_db import MemoryDB
from config_loader import load_config

load_config('cloud')
db = MemoryDB()
count = db.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
print(f"✓ Database loaded: {count} memories")
TEST
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
  -e N8N_HOST=OLLAMA_BASE_URL \
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
# Workflows are in docs/n8n/workflows/ (if you backed them up)
# Or export from old n8n before disaster

# In n8n UI:
# 1. Click "Workflows" → "Import from File"
# 2. Select JSON file
# 3. Update credentials (OAuth, SMTP)
# 4. Update webhook URLs if IPs changed
# 5. Activate workflow
```

**Required workflows if using these systems:**
1. **Jarvis → Send Email** - Email sending via SMTP
2. **Jarvis → Google Calendar Sync** - Reminder to calendar
3. **Google Calendar → Jarvis Sync** - Calendar to reminder (with update/delete)

### Step 6: Generate n8n API Key

1. In n8n: Settings → API → "Create API Key"
2. Copy the key
3. Add to Jarvis config:

```bash
nano /home/boss/jarvis-voice/config/cloud.env
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
cd /home/boss/jarvis-voice
source ~/jarvis-venv/bin/activate

# Start all services
./bin/start

# Or start specific services
./bin/start api        # API server only
./bin/start web        # Web UI only
./bin/start --ui-only  # Web, Canvas, Memory (no API)

# Check status
./bin/start --list

# Stop all
./bin/start --stop
```

**tmux session names:**
- `jarvis-api` - Main API server (port 5050)
- `jarvis-services` - Background services
- `jarvis-web` - Web UI (port 3000)
- `jarvis-canvas` - Canvas service (port 5001)
- `jarvis-memory` - Memory service (port 5002)
- `jarvis-intelligence` - Intelligence service (port 5003)

### Service Watchdog (Cron)

After starting services, install the watchdog cron job. This ensures the
self-healing daemon (which monitors all other background services) auto-restarts
if it crashes unexpectedly.

```bash
# Add watchdog cron entry
(crontab -l 2>/dev/null; echo "# Jarvis watchdog - restart self_healing_daemon if it crashes"; echo "*/5 * * * * /home/boss/jarvis-voice/bin/watchdog-services.sh >> /home/boss/jarvis-voice/logs/watchdog.log 2>&1") | crontab -
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

For monitoring all services:
```bash
./bin/jarvis-dashboard
# Or with alias:
jarvis-d
```

### Systemd Service (Optional - OpenCode Only)

Only one systemd service exists for OpenCode server:

```bash
# Install (if using OpenCode integration)
sudo cp /home/boss/jarvis-voice/systemd/opencode-jarvis.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable opencode-jarvis.service
sudo systemctl start opencode-jarvis.service

# Check status
sudo systemctl status opencode-jarvis.service
sudo journalctl -u opencode-jarvis.service -n 50 --no-pager
```

**Note:** The main Jarvis services (API, Web, etc.) run via tmux, not systemd.
This allows easy log viewing, debugging, and manual restarts during development.
could always run on systemd later

---

## Final Validation

### Step 1: Test Cloud Mode

```bash
cd /home/boss/jarvis-voice
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

# Pull models
ollama pull qwen3:14b
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

### Step 7: Test All Tools

```bash
# Run comprehensive test suite
./test-all-tools.sh

# Should see most/all tests pass
# Note: Some may fail if external services unavailable
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
sudo ufw allow 8090/tcp   # Canvas Viewer

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
sudo usermod -aG audio boss
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
cd /home/boss/jarvis-voice
source ~/jarvis-venv/bin/activate
python api/main.py  # Should start API
```

**Permission denied:**
```bash
# Make scripts executable
chmod +x /home/boss/jarvis-voice/jarvis
chmod +x /home/boss/jarvis-voice/jarvis-local
chmod +x /home/boss/jarvis-voice/skills/*.py
chmod +x /home/boss/jarvis-voice/bin/*
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
cd /home/boss/jarvis-voice
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

# Should be:
# XAI_API_KEY=xai-abc123...
# NOT:
# XAI_API_KEY="xai-abc123..."
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
curl http://localhost:5050/api/health

# Restart API
./bin/start --stop
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

## Post-Recovery Checklist

Once everything is working, verify:

- [ ] Voice mode responds to "Hey Jarvis"
- [ ] Can query time, weather, etc. via voice
- [ ] Memory system stores and recalls information
- [ ] Reminders sync to Google Calendar
- [ ] Email tool sends emails successfully
- [ ] API server responds on port 8880
- [ ] All tmux sessions running (./bin/start --list)
- [ ] n8n workflows active and webhooks responding
- [ ] Logs being written to logs/ directory
- [ ] OpenCode can create projects in ~/jarvis-workspace
- [ ] OpenCode plugins installed (~/.config/opencode/plugin/)

**Optional but recommended:**
- [ ] Install watchdog cron (`bin/watchdog-services.sh`) for self-healing daemon
- [ ] Set up cron job for daily database backups
- [ ] Configure rsync to backup /home/boss nightly
- [ ] Test disaster recovery on a VM (validate these docs!)
- [ ] Document any hardware-specific changes you made
- [ ] Update this doc with lessons learned

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
./bin/start --stop
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

## Hardware-Specific Notes

**Document YOUR specific hardware here:**

### Audio Devices
```
Microphone: hw:___,___ (Model: _______________)
Speaker:    hw:___,___ (Model: _______________)
USB Audio:  plughw:CARD=_____
```

### Network
```
Jarvis server IP: 192.168.70.___
n8n server IP:    192.168.70.___
Router IP:        192.168.70.___
```

### Tweaks/Adjustments Made
```
- 
- 
- 
```

---

## Backup Strategy

**Current backup methods:**
1. **Git repository** - Code, docs, scripts
2. **rsync backup** - Full /home/boss directory
3. **Database backups** - Manual or cron

**Recommended cron jobs:**

```bash
# Edit crontab
crontab -e

# Add these lines:

# Jarvis watchdog - restart self_healing_daemon if it crashes
*/5 * * * * /home/boss/jarvis-voice/bin/watchdog-services.sh >> /home/boss/jarvis-voice/logs/watchdog.log 2>&1

# Daily database backup at 2 AM
0 2 * * * cp /home/boss/jarvis-voice/data/jarvis_memory.db /home/boss/jarvis-voice/data/backups/jarvis_memory-$(date +\%Y\%m\%d).db

# Weekly rsync to backup server at 3 AM Sunday
0 3 * * 0 rsync -avz /home/boss/ backup-server:/backup/jarvis-home/

# Keep only last 30 days of database backups
0 4 * * * find /home/boss/jarvis-voice/data/backups/ -name "jarvis_memory-*.db" -mtime +30 -delete
```

---

## Version Information

**Last Updated:** 2026-01-25  
**Jarvis Version:** v2.39  
**Tested On:** Ubuntu 24.04 LTS  
**Python Version:** 3.12+  
**Package Manager:** uv (recommended) or pip

---

## Additional Resources

- **Main README:** [`README.md`](../README.md)
- **Documentation Index:** [`docs/README.md`](README.md)
- **Quickstart Guide:** [`docs/QUICKSTART.md`](QUICKSTART.md)
- **Webhook System:** [`docs/WEBHOOK_SYSTEM.md`](WEBHOOK_SYSTEM.md)
- **Google Calendar Sync:** [`docs/n8n/docs/GOOGLE_CALENDAR_SYNC.md`](n8n/docs/GOOGLE_CALENDAR_SYNC.md)
- **Service Architecture:** [`docs/service/SERVICE_ARCHITECTURE_FAQ.md`](service/SERVICE_ARCHITECTURE_FAQ.md)

---

**Need Help?** Use this guide with an LLM (Claude, GPT-4, etc.) to walk through each section step-by-step. The LLM can help troubleshoot issues and adapt commands to your specific hardware/environment.

**🚨 IMPORTANT:** Test this guide on a VM or spare machine BEFORE you need it! Update this doc with any corrections or hardware-specific notes.

