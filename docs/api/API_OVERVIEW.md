# Jarvis Proactive API - Overview

## What Is It?

Jarvis Proactive API transforms Jarvis from **reactive** (waits for commands) to **proactive** (receives events and notifies you). It also provides programmatic access to all Jarvis features.

**Example**: Instead of asking "Are there any issues?", Jarvis tells you: *"Boss, urgent alert! Container stopped on your server"*

---

## API Documentation

| URL | Description |
|-----|-------------|
| http://localhost:8880/docs/dark | **Swagger UI (Dark Mode)** 🌙 |
| http://localhost:8880/docs | Swagger UI (Light) |
| http://localhost:8880/redoc | ReDoc (Alternative) |

---

## Quick Start

```bash
# Start API server (cloud mode)
./bin/jarvis-api

# Start API server (local mode)
./bin/jarvis-api --local

# Check API status
./bin/jarvis-api --status

# Stop API server
./bin/jarvis-api --stop

# Restart API server
./bin/jarvis-api --restart

# Start background services
./bin/jarvis-services

# Start canvas
./bin/jarvis-canvas

# Start dashboard
./bin/jarvis-dashboard

# Send test alert
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test Alert",
    "source": "test",
    "severity": "medium"
  }'
```

Jarvis will immediately speak the alert!

---

## How It Works

```
External System → Webhook → Jarvis API → TTS Notification
     (Uptime Kuma,       (port 8880)      "Boss, alert!"
      Docker monitor,
      Security camera)
```

### Two Auto-Resolve Methods

**1. URL-Based** (for web services):
```json
{
  "title": "API Down",
  "auto_resolve_url": "https://api.example.com/health"
}
```
→ Self-healing daemon checks URL, auto-resolves when responding

**2. Agent-Based** (for containers, services, processes):
- Monitoring agent detects recovery
- Calls `POST /api/alerts/{id}/resolve`
- Jarvis speaks: "Boss, good news! kokoro-cpu is back up"

---

## Components

### API Server (`jarvis-api`)
- Port 8880
- Receives webhooks from ANY source
- Speaks alerts via TTS
- Manages alert lifecycle

### Background Services (`jarvis-services`)
Three daemons running 24/7:
- **Follow-up daemon**: Re-notifies about unacknowledged alerts
- **Self-healing daemon**: Auto-resolves via URL checks
- **Reminder scheduler**: Time-based reminders

### Monitoring Agents
Deploy anywhere to send alerts:
- Docker containers (template: `code-examples/docker/`)
- Systemd services (template: `code-examples/python/process_monitor.py`)
- Disk space (template: `code-examples/python/disk_space_smart_monitor.py`)
- Custom webhooks (template: `code-examples/python/ubiquiti_camera_webhook.py`)

---

## Use Cases

### 1. Remote Server Monitoring
Monitor Docker containers, services, disk space from anywhere

**Setup**: Deploy Docker agent + Tailscale
**Result**: Alerts when issues occur, auto-resolves when fixed

### 2. Security Cameras
Receive webhooks from Ubiquiti/other cameras on person detection

**Setup**: Flask webhook handler
**Result**: Jarvis alerts during specified hours

### 3. Application Health
Your apps send webhooks when issues occur

**Setup**: Add `POST /api/alerts` to your app
**Result**: Instant notifications via Jarvis

### 4. Cron Jobs
Simple alerts from bash scripts

**Setup**: Call curl from cron
**Result**: Jarvis speaks task results

---

## Documentation

**Getting Started:**
- [Ready to Use](READY_TO_USE.md) - Quick start guide
- [API Quick Start](API_QUICK_START.md) - API endpoint reference
- [Code Examples](code-examples/) - Ready-to-use templates

**Setup & Integration:**
- [Remote Monitoring](REMOTE_MONITORING.md) - Monitor remote servers
- [Security Options](SECURITY_OPTIONS.md) - Tailscale, VPN setup
- [Alert Scenarios](code-examples/ALERT_SCENARIOS.md) - Complete examples

**Architecture & Services:**
- [Proactive System Architecture](../service/PROACTIVE_ASSISTANT_SYSTEM.md)
- [Service Architecture FAQ](../service/SERVICE_ARCHITECTURE_FAQ.md)
- [Service Logging](../service/SERVICE_LOGGING.md)

**History:**
- [Fixes Log](../archive/api/FIXES_LOG.md) - All fixes applied

---

## Quick Reference

### Send Alert
```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Alert Title",
    "description": "Details",
    "severity": "high",
    "source": "my-source"
  }'
```

### List Alerts
```bash
curl http://localhost:8880/api/alerts
```

### Voice Commands
```
"Hey Jarvis, list pending alerts"
"Hey Jarvis, clear all pending alerts"
```

---

## What's Working

✅ Alert creation & management
✅ URL-based auto-resolve (web services)
✅ Agent-based auto-resolve (containers, services)
✅ Follow-up reminders
✅ Time-based reminders (multi-day, daily recurring)
✅ TTS notifications
✅ Voice control
✅ Remote monitoring via Docker
✅ 10+ ready-to-use code examples
✅ Complete documentation
✅ Intelligence API endpoints
✅ Self-learning metrics & logs
✅ API start/stop/status management
✅ Insight tracking (times_applied, helpful/failed)
✅ Maintenance jobs (decay, anomaly, meta-cognition)
✅ Meta-knowledge table & API
✅ Reflection queue management (list, cancel) 
✅ Memory API (CRUD, keyword search, semantic search) 
✅ Query/Chat API (programmatic Jarvis access) 
✅ Conversations API (read-only history access) 
✅ Stash API (read-only artifacts access) 
✅ Canvas API (read-only pages access) 
✅ Intel API (CRUD for knowledge files)
✅ Image Generation & Editing API (Gemini, OpenAI, xAI)
✅ Video Generation & Editing API (xAI Grok + Gemini Veo)
✅ Dark mode Swagger UI 

---

**Status**: Production Ready ✅  
**Last Updated**: January 25, 2026

See [READY_TO_USE.md](READY_TO_USE.md) for detailed setup instructions.
