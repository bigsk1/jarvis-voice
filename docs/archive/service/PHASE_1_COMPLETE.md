# ⚠️ HISTORICAL — Proactive assistant Phase 1 milestone

**Current guides:** [PROACTIVE_ASSISTANT_SYSTEM.md](../../service/PROACTIVE_ASSISTANT_SYSTEM.md) · [READY_TO_USE.md](../../api/READY_TO_USE.md)

---

# 🎉 Jarvis Proactive Assistant - Phase 1 Complete!

## What You Now Have

### ✅ Foundation (API + Database)

**New Files Created:**
```
api/
├── __init__.py
├── server.py                    # FastAPI application
├── models/
│   ├── __init__.py
│   ├── alert.py                 # Alert data models
│   └── reminder.py              # Reminder data models
├── managers/
│   ├── __init__.py
│   ├── alert_manager.py         # Alert business logic
│   └── reminder_manager.py      # Reminder business logic
└── routes/
    ├── __init__.py
    ├── alerts.py                # Alert endpoints
    ├── reminders.py             # Reminder endpoints
    ├── health.py                # Health/status endpoints
    └── voice.py                 # TTS endpoint

bin/
├── jarvis-api                   # API server startup script
└── migrate-proactive-db.py      # Database migration

docs/
├── PROACTIVE_ASSISTANT_SYSTEM.md  # Full architecture
└── API_QUICK_START.md             # Quick start guide
```

**Database Changes:**
- ✅ `alerts` table added (both cloud & local DBs)
- ✅ `reminders` table added (both cloud & local DBs)
- ✅ `long_form` column added to `knowledge_base`
- ✅ Auto-sync updated to handle new tables

**Dependencies Added:**
- ✅ FastAPI
- ✅ Uvicorn
- ✅ Pydantic 2.x

---

## How to Use It

### Start the API Server

```bash
# Cloud mode (default - uses OpenAI/Anthropic TTS)
./bin/jarvis-api

# Local mode (offline - uses Kokoro TTS)
./bin/jarvis-api --local
```

**Run both together:**
```bash
# Terminal 1: API server
./bin/jarvis-api         # or ./bin/jarvis-api --local

# Terminal 2: Reactive Jarvis
./jarvis                 # or ./jarvis-local
```

Both run simultaneously! Reactive voice mode + proactive API webhooks.

### Send a Test Alert

```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test Alert",
    "description": "Testing the proactive system",
    "severity": "high",
    "source": "test"
  }'
```

**What happens:**
1. API receives webhook
2. Alert saved to database
3. **Jarvis speaks**: "Boss, urgent alert! Test Alert"
4. Alert shows as "pending" in database

### View Alerts

```bash
# List all alerts
curl http://localhost:8880/api/alerts | jq

# Acknowledge alert #1
curl -X PUT http://localhost:8880/api/alerts/1/acknowledge

# List only pending
curl http://localhost:8880/api/alerts?status=pending | jq
```

### API Documentation

**Interactive docs**: http://localhost:8880/docs

---

## Real-World Examples

### Uptime Kuma Webhook

**Configure in Uptime Kuma:**
```
Webhook URL: http://localhost:8880/api/alerts
Method: POST
Body:
{
  "title": "{{name}} is {{status}}",
  "description": "{{msg}}",
  "severity": "high",
  "source": "uptime_kuma",
  "auto_resolve_url": "{{url}}",
  "metadata": {"url": "{{url}}"}
}
```

**Result**: Jarvis speaks when servers go down and auto-checks if they come back up.

### Custom Disk Space Monitor

```bash
#!/bin/bash
# /etc/cron.hourly/disk-alert

USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')

if [ "$USAGE" -gt 90 ]; then
  curl -X POST http://localhost:8880/api/alerts \
    -H "Content-Type: application/json" \
    -d "{
      \"title\": \"Disk Space Low\",
      \"description\": \"Root at ${USAGE}%\",
      \"severity\": \"medium\",
      \"source\": \"cron_disk_check\"
    }"
fi
```

### Coolify Deployment Webhook

```bash
# Coolify webhook on deployment failure
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Deployment Failed",
    "description": "myapp failed to deploy",
    "severity": "high",
    "source": "coolify"
  }'
```

---

## Architecture Benefits

### 1. **Generic & Flexible**
- Works with ANY webhook source
- No hard-coded integrations
- Only requires `title` and `source`

### 2. **Embedded, Not External**
- Uses existing Jarvis database
- Uses existing TTS (say.sh)
- Shares configuration (cloud.env/local.env)
- No separate services to manage

### 3. **Hybrid Mode**
```
Reactive (Voice):
  "Hey Jarvis, what time is it?" → Normal operation

Proactive (Webhooks):
  Server down → Jarvis interrupts to alert you
```

### 4. **Cloud/Local Compatible**
- Alerts sync between modes
- Works with both anthropic and ollama
- Auto-detects current mode

---

## What's NOT Done Yet (Phase 2) ( so i assume this is all run behind the scenes and my terminal will still been running listening for wake word to start jarvis and this is done via jarvis-services or api mode? )

These are **optional enhancements** for the future:

### 1. Intel Management Tool
**What**: Sandboxed tool to create/edit `.md` files in `jarvis-intel/`

**Why**: So Jarvis can programmatically create structured docs:
```python
# Example: Jarvis creates docker-issue.md after you explain a problem
{
  "title": "Create intel about Coolify Docker issue",
  "tool": "manage_intel",
  "args": {
    "action": "create",
    "path": "servers/coolify-docker-issue.md",
    "content": "# Docker v29 Issue\n...",
    "auto_ingest": true
  }
}
```

**Status**: Not critical - you can manually create intel files for now ( which i currently do to proide jarvis with info i want him to know about see existing docs in jarvis-intel folder, i add docs and manually run ingest_intel.py to add to db or just ask jarvis to ingest intel files and he runs the ingest_intel.py tool)

### 2. Follow-Up System
**What**: Background daemon that re-alerts if not acknowledged

**Why**: Persistent notifications
```
Alert → Speak → 15 min later → Still pending? → Speak again
```

**Status**: Not critical - alerts stay in DB, you can check manually

### 3. Self-Healing Daemon
**What**: Background service that checks `auto_resolve_url` ( need to limit tools calls here max is 10 by default but for this action a lower number might be best)

**Why**: Auto-cancel alerts when issues resolve
```
Server down → Alert → 5 min later → Check URL → Back up? → Cancel alert
```

**Status**: Not critical - you can manually acknowledge

### 4. Jarvis Voice Tools
**What**: Tools so you can say:
```
"Hey Jarvis, list pending alerts"
"Hey Jarvis, clear all alerts"
```

**Why**: Control alerts via voice (convenience)

**Status**: Not critical - you have the API endpoints

---

## Current Capabilities (Phase 1)

| Feature | Status | How to Use |
|---------|--------|------------|
| **Receive webhooks** | ✅ Ready | POST to `/api/alerts` |
| **Proactive TTS** | ✅ Ready | Speaks on high/critical severity |
| **Store alerts** | ✅ Ready | Saved to database |
| **View alerts** | ✅ Ready | GET `/api/alerts` |
| **Acknowledge** | ✅ Ready | PUT `/api/alerts/{id}/acknowledge` |
| **Auto-resolve check** | ✅ Ready | POST `/api/alerts/{id}/check` |
| **Reminders** | ✅ Ready | POST `/api/reminders` (manual trigger for now) |
| **Cloud/Local sync** | ✅ Ready | Auto-syncs on mode switch |
| **Interactive docs** | ✅ Ready | http://localhost:8880/docs |

---

## Quick Start Commands

```bash
# 1. Start API server
./bin/jarvis-api

# 2. Send test alert (in another terminal)
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"title": "Test", "source": "test", "severity": "high"}'

# 3. List alerts
curl http://localhost:8880/api/alerts | jq

# 4. Acknowledge alert #1
curl -X PUT http://localhost:8880/api/alerts/1/acknowledge

# 5. View interactive docs
xdg-open http://localhost:8880/docs
```

---

## Configuration

**No configuration needed!** The system:
- Auto-detects cloud vs. local mode
- Uses existing `config/cloud.env` or `config/local.env`
- Uses existing databases (with new tables)
- Uses existing TTS scripts

---

## Next Steps (Your Choice)

### Option A: Use Phase 1 Now
Start integrating webhooks from your monitoring systems:
- Uptime Kuma
- Coolify
- Custom bash scripts
- Cron jobs

**Benefit**: Immediate value, proactive notifications

### Option B: Continue to Phase 2
Build the enhancements:
- Intel management tool
- Voice control tools
- Follow-up daemon
- Self-healing daemon

**Benefit**: Full vision realized, max automation

### Option C: Wait and See
Keep Phase 1 running, decide later if you need Phase 2.

**Benefit**: No commitment, already functional

---

## Documentation

- **Quick Start**: `docs/API_QUICK_START.md` (API usage examples)
- **Architecture**: `docs/service/PROACTIVE_ASSISTANT_SYSTEM.md` (full system design)
- **Main README**: `README.md` (updated with proactive mode link)

---

## Summary

**Phase 1 delivers a working proactive notification system:**
- ✅ Receive webhooks from any source
- ✅ Jarvis speaks urgent alerts
- ✅ Track alert status in database
- ✅ Query/acknowledge via REST API
- ✅ Works alongside existing reactive voice mode
- ✅ Cloud and local mode compatible

**You can start using it RIGHT NOW** - just start the API server and configure your monitoring systems to send webhooks!

---

**Want to continue to Phase 2?** Let me know and I'll build:
1. `manage_intel.py` tool (sandboxed CRUD)
2. Voice control tools (`list_alerts`, `acknowledge_alerts`)
3. Background daemons (follow-up, self-healing)

**Or use it as-is** - Phase 1 is production-ready! 🚀

