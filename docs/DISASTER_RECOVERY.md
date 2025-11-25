# Jarvis Voice Assistant - Disaster Recovery Guide

> **Purpose:** Complete step-by-step guide to rebuild Jarvis from scratch on a new server. Follow this with an LLM assistant to restore full functionality.

**Estimated Time:** 3-4 hours (fresh Ubuntu install to fully working system)

---

## 📋 Table of Contents

1. [Prerequisites & Hardware](#prerequisites--hardware)
2. [Operating System Setup](#operating-system-setup)
3. [Directory Structure (CRITICAL)](#directory-structure-critical)
4. [Audio Configuration](#audio-configuration)
5. [Python Environment](#python-environment)
6. [Clone Repository & Restore Data](#clone-repository--restore-data)
7. [Configuration Files](#configuration-files)
8. [Database Restoration](#database-restoration)
9. [n8n Setup (Docker)](#n8n-setup-docker)
10. [Systemd Services](#systemd-services)
11. [Final Validation](#final-validation)
12. [Troubleshooting](#troubleshooting)

---

## Prerequisites & Hardware

### Server Requirements
- **OS:** Ubuntu 22.04/24.04 LTS (recommended)
- **RAM:** 8GB minimum (16GB+ for local LLM mode)
- **Storage:** 50GB+ SSD
- **Network:** Static IP on LAN (for n8n, API access)

### Hardware Checklist
- [ ] USB microphone or audio interface
- [ ] Speakers or audio output device
- [ ] Network connectivity (Ethernet preferred)

### Network Configuration
**CRITICAL:** These IPs should be static/reserved in your router:
- Jarvis server: `192.168.70.228`
- n8n server: `192.168.70.226` (Docker on same or different host)

**If IPs changed:** You'll need to update:
- `config/cloud.env` - `N8N_LOCAL_API_URL`, `N8N_JARVIS_WEBHOOK_URL`
- `config/local.env` - Same variables
- `config/webhook_registry.json` - All n8n webhook URLs
- n8n workflows - Jarvis API callback URLs

---

## Operating System Setup

### Step 1: Install Ubuntu Server

```bash
# After Ubuntu installation, update system
sudo apt update && sudo apt upgrade -y

# Install essential packages
sudo apt install -y \
  git curl wget build-essential \
  python3.11 python3.11-venv python3-pip \
  ffmpeg portaudio19-dev \
  alsa-utils pulseaudio pulseaudio-utils \
  sqlite3 \
  docker.io docker-compose \
  htop net-tools

# Add user to docker group (for n8n)
sudo usermod -aG docker $USER
```

### Step 2: Set Hostname (Optional)
```bash
sudo hostnamectl set-hostname jarvis-main
```

### Step 3: Verify Python Version
```bash
python3 --version  # Should be 3.11+
```

---

## Directory Structure (CRITICAL)

**These paths are HARDCODED everywhere. Do not change them.**

```bash
# Create user home (if needed)
sudo useradd -m -s /bin/bash boss
sudo passwd boss
su - boss  # Switch to boss user

# Create required directories
cd /home/boss
mkdir -p jarvis-voice
mkdir -p jarvis-workspace  # OpenCode workspace
mkdir -p .config/opencode

# Verify paths
echo "Home: $HOME"           # Must be /home/boss
echo "PWD: $PWD"             # Should be /home/boss
ls -la jarvis-voice          # Should exist (empty for now)
```

**Why these paths matter:**
- `/home/boss/jarvis-voice` - Main codebase, referenced in systemd services
- `/home/boss/jarvis-venv` - Python virtual environment (one level up from codebase)
- `/home/boss/jarvis-workspace` - OpenCode workspace (isolated from main code)
- Scripts use relative paths (`../`, `~/jarvis-venv`) assuming this structure

---

## Audio Configuration

### Step 1: Detect Audio Devices

```bash
# List all audio devices
aplay -l    # Playback devices
arecord -l  # Recording devices

# Example output:
# card 0: PCH [HDA Intel PCH], device 0: ALC887-VD Analog [...]
# card 3: Device [USB Audio Device], device 0: USB Audio [...]

# Note the card and device numbers!
# Format: hw:CARD_NUMBER,DEVICE_NUMBER
```

**Record your devices:**
- Microphone: `hw:___,___` or `plughw:CARD=___`
- Speaker: `hw:___,___` or `plughw:CARD=___`

### Step 2: Test Audio

```bash
# Test microphone (record 5 seconds)
arecord -D hw:3,0 -f cd -d 5 test.wav

# Test playback
aplay test.wav

# Test speaker directly
speaker-test -D hw:0,0 -c 2 -t wav
```

### Step 3: Configure ALSA (if needed)

Create `~/.asoundrc` if you need custom device mapping:

```bash
cat > ~/.asoundrc << 'EOF'
pcm.!default {
    type asym
    playback.pcm "plughw:0,0"
    capture.pcm "plughw:3,0"
}

ctl.!default {
    type hw
    card 0
}
EOF
```

### Step 4: Test PulseAudio

```bash
# Start PulseAudio (if not running)
pulseaudio --start

# List devices
pactl list sources short
pactl list sinks short

# Set default devices
pactl set-default-source YOUR_MIC_NAME
pactl set-default-sink YOUR_SPEAKER_NAME
```

**CRITICAL:** Note exact device names/IDs for later config.

---

## Python Environment

### Step 1: Create Virtual Environment

```bash
cd /home/boss

# Create venv (one level up from jarvis-voice)
python3 -m venv jarvis-venv

# Activate
source jarvis-venv/bin/activate

# Verify
which python  # Should show /home/boss/jarvis-venv/bin/python
python --version  # Should be 3.11+
```

### Step 2: Upgrade pip

```bash
pip install --upgrade pip setuptools wheel
```

---

## Clone Repository & Restore Data

### Step 1: Clone Repository

```bash
cd /home/boss

# Clone from your Git remote
git clone <YOUR_GIT_REMOTE_URL> jarvis-voice

# Or if using rsync backup, skip to Step 2

cd jarvis-voice
git branch  # Verify you're on main branch
```

### Step 2: Restore Data from Backup (rsync)

**If you have rsync backup of /home/boss:**

```bash
# On NEW server, sync from backup
rsync -avz --progress \
  user@backup-server:/path/to/backup/jarvis-voice/ \
  /home/boss/jarvis-voice/

# Specifically restore these:
# - data/*.db (databases)
# - config/*.env (API keys - NOT in git)
# - config/contacts.json (NOT in git)
# - config/webhook_registry.json (NOT in git)
# - logs/ (optional, for history)
```

**Important files to restore:**
```bash
# Check these exist after restore:
ls -lh /home/boss/jarvis-voice/data/jarvis_memory.db
ls -lh /home/boss/jarvis-voice/data/jarvis_memory_local.db
ls -lh /home/boss/jarvis-voice/config/cloud.env
ls -lh /home/boss/jarvis-voice/config/local.env
ls -lh /home/boss/jarvis-voice/config/contacts.json
ls -lh /home/boss/jarvis-voice/config/webhook_registry.json
```

### Step 3: Install Python Dependencies

```bash
cd /home/boss/jarvis-voice
source ~/jarvis-venv/bin/activate

# Install from requirements.txt
pip install -r requirements.txt

# Verify key packages
pip list | grep -E "openai|anthropic|ollama|faster-whisper|kokoro"
```

---

## Configuration Files

### Step 1: Verify Config Files Exist

```bash
cd /home/boss/jarvis-voice/config

# These should exist (from git or rsync backup):
ls -la cloud.env
ls -la local.env
ls -la contacts.json
ls -la webhook_registry.json
```

**If missing, create from templates:**

```bash
cp cloud.env.example cloud.env
cp local.env.example local.env
cp contacts.json.example contacts.json
cp webhook_registry.json.template webhook_registry.json
```

### Step 2: Update Audio Device Paths

**Edit `config/cloud.env` and `config/local.env`:**

```bash
nano config/cloud.env
```

Find and update these lines with YOUR audio devices:

```bash
# Audio Configuration (UPDATE THESE!)
MICROPHONE_DEVICE="hw:3,0"           # From arecord -l
SPEAKER_DEVICE="plughw:CARD=PCH"     # From aplay -l
SPEAKER_DEVICE_KOKORO="hw:0,0"       # For Kokoro TTS (local mode)
```

**Test audio paths:**
```bash
# Test mic
arecord -D hw:3,0 -f cd -d 3 test.wav && aplay test.wav

# Test speaker
speaker-test -D hw:0,0 -c 2 -t wav -l 1
```

### Step 3: Verify API Keys

**Required for cloud mode:**
```bash
grep "API_KEY" config/cloud.env | grep -v "^#"
```

Should see:
- `XAI_API_KEY` or `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
- `OPENAI_API_KEY` (for embeddings)
- `BRAVE_API_KEY` (optional, for web search)

**If missing, get from:**
- xAI: https://console.x.ai/
- Anthropic: https://console.anthropic.com/
- OpenAI: https://platform.openai.com/api-keys
- Brave: https://api.search.brave.com/

### Step 4: Update Network URLs (if IPs changed)

```bash
# In config/cloud.env and local.env
N8N_LOCAL_API_URL="http://192.168.70.226:5678"
N8N_JARVIS_WEBHOOK_URL="http://192.168.70.226:5678/webhook/jarvis-reminder"

# In config/webhook_registry.json
# Update all URLs with 192.168.70.226 to new n8n IP
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
# Better: Restore from your latest rsync backup!
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

## n8n Setup (Docker)

### Step 1: Install Docker (if not done)

```bash
sudo apt install docker.io docker-compose -y
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker $USER

# Log out and back in for group to take effect
```

### Step 2: Create n8n Container

```bash
# Create n8n data directory
mkdir -p ~/.n8n

# Run n8n container
docker run -d \
  --name n8n \
  --restart unless-stopped \
  -p 5678:5678 \
  -e N8N_HOST=192.168.70.226 \
  -e WEBHOOK_URL=http://192.168.70.226:5678/ \
  -e N8N_PROTOCOL=http \
  -v ~/.n8n:/home/node/.n8n \
  n8nio/n8n:latest

# Verify running
docker ps | grep n8n
```

### Step 3: Access n8n Web UI

Open browser: `http://192.168.70.226:5678`

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

**Option B: Import from JSON** (if you have backups):

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

**Required workflows:**
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

## Systemd Services

### Step 1: Install Service Files

```bash
cd /home/boss/jarvis-voice/systemd

# Copy to systemd directory
sudo cp jarvis-api.service /etc/systemd/system/
sudo cp reminder-scheduler.service /etc/systemd/system/
sudo cp opencode-agent.service /etc/systemd/system/
sudo cp jarvis-follow-up.service /etc/systemd/system/
sudo cp jarvis-self-healing.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload
```

### Step 2: Verify Service Paths

**CRITICAL:** Services reference `/home/boss/jarvis-voice`. Verify:

```bash
grep "WorkingDirectory" /etc/systemd/system/jarvis-api.service
# Should show: WorkingDirectory=/home/boss/jarvis-voice

grep "ExecStart" /etc/systemd/system/jarvis-api.service
# Should show: /home/boss/jarvis-venv/bin/python
```

**If paths wrong, edit services:**
```bash
sudo systemctl edit --full jarvis-api.service
# Update WorkingDirectory and ExecStart paths
```

### Step 3: Enable and Start Services

```bash
# Enable services to start on boot
sudo systemctl enable jarvis-api.service
sudo systemctl enable reminder-scheduler.service
sudo systemctl enable opencode-agent.service
sudo systemctl enable jarvis-follow-up.service
sudo systemctl enable jarvis-self-healing.service

# Start services
sudo systemctl start jarvis-api.service
sudo systemctl start reminder-scheduler.service
sudo systemctl start opencode-agent.service
sudo systemctl start jarvis-follow-up.service
sudo systemctl start jarvis-self-healing.service

# Check status
sudo systemctl status jarvis-api.service
sudo systemctl status reminder-scheduler.service
```

### Step 4: Verify Services Running

```bash
# Check all Jarvis services
systemctl list-units --type=service --state=running | grep jarvis

# Check logs
sudo journalctl -u jarvis-api.service -n 50 --no-pager
sudo journalctl -u reminder-scheduler.service -n 20 --no-pager
```

**Expected output:**
- jarvis-api.service - active (running)
- reminder-scheduler.service - active (running)
- opencode-agent.service - active (running)
- jarvis-follow-up.service - active (running)
- jarvis-self-healing.service - active (running)

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
ollama pull qwen3-vl
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
curl http://192.168.70.228:8880/health

# Test reminders endpoint
curl http://192.168.70.228:8880/api/reminders | jq

# Create test reminder
curl -X POST http://192.168.70.228:8880/api/reminders \
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
curl http://192.168.70.228:8880/api/reminders | jq
```

### Step 7: Test All Tools

```bash
# Run comprehensive test suite
./test-all-tools.sh

# Should see most/all tests pass
# Note: Some may fail if external services unavailable
```

---

## Troubleshooting

### Audio Issues

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
# Check logs
sudo journalctl -u jarvis-api.service -n 100

# Check paths
grep "WorkingDirectory\|ExecStart" /etc/systemd/system/jarvis-api.service

# Test manually
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
sudo systemctl restart jarvis-api.service
sudo systemctl restart reminder-scheduler.service
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
# Format: http://192.168.70.226:5678/webhook/endpoint-name
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
curl http://192.168.70.226:5678

# Check firewall
sudo ufw status
sudo ufw allow 5678/tcp

# Check Docker networking
docker network ls
docker inspect n8n | grep IPAddress
```

**Jarvis API unreachable:**
```bash
# Check API is running
sudo systemctl status jarvis-api.service
curl http://localhost:8880/health

# Check firewall
sudo ufw allow 8880/tcp

# Check from other machine
curl http://192.168.70.228:8880/health
```

### Memory/Performance Issues

**High memory usage:**
```bash
# Check processes
htop

# Restart services
sudo systemctl restart jarvis-api.service
sudo systemctl restart opencode-agent.service

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
- [ ] All systemd services running and enabled
- [ ] n8n workflows active and webhooks responding
- [ ] Logs being written to logs/ directory
- [ ] OpenCode can create projects in ~/jarvis-workspace

**Optional but recommended:**
- [ ] Set up cron job for daily database backups
- [ ] Configure rsync to backup /home/boss nightly
- [ ] Test disaster recovery on a VM (validate these docs!)
- [ ] Document any hardware-specific changes you made
- [ ] Update this doc with lessons learned

---

## Quick Reference Commands

### Start/Stop Services
```bash
# Start all
sudo systemctl start jarvis-api reminder-scheduler opencode-agent jarvis-follow-up jarvis-self-healing

# Stop all
sudo systemctl stop jarvis-api reminder-scheduler opencode-agent jarvis-follow-up jarvis-self-healing

# Restart API only
sudo systemctl restart jarvis-api
```

### View Logs
```bash
# API logs
sudo journalctl -u jarvis-api.service -f

# Reminder scheduler
sudo journalctl -u reminder-scheduler.service -f

# Tool execution logs
tail -f logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl

# n8n logs
docker logs n8n --tail 100 -f
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

# Daily database backup at 2 AM
0 2 * * * cp /home/boss/jarvis-voice/data/jarvis_memory.db /home/boss/jarvis-voice/data/backups/jarvis_memory-$(date +\%Y\%m\%d).db

# Weekly rsync to backup server at 3 AM Sunday
0 3 * * 0 rsync -avz /home/boss/ backup-server:/backup/jarvis-home/

# Keep only last 30 days of database backups
0 4 * * * find /home/boss/jarvis-voice/data/backups/ -name "jarvis_memory-*.db" -mtime +30 -delete
```

---

## Version Information

**Last Updated:** 2025-11-25  
**Jarvis Version:** v2.3  
**Tested On:** Ubuntu 22.04 LTS  
**Python Version:** 3.11+

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

