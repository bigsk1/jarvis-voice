# Jarvis Proactive Assistant API - Quick Start

## ✅ Phase 1 Complete!

The foundational API system is now ready for webhooks and proactive notifications.

---

## What's Been Built

### 1. **Database Schema** ✅
- `alerts` table - Track notifications from external systems
- `reminders` table - Time-based notifications
- `long_form` column in `knowledge_base` - Store detailed context

### 2. **FastAPI Server** ✅
- Alert endpoints (create, list, acknowledge, cancel)
- Reminder endpoints (create, list, cancel)
- Voice/TTS endpoint (proactive speaking)
- Health/status endpoints

### 3. **Alert Manager** ✅
- Business logic for alerts
- Auto-speak for high/critical severity
- Auto-resolve checking
- Database integration

### 4. **Database Sync** ✅
- Alerts and reminders sync between cloud/local modes
- Maintains consistency across databases

---

## Starting the API Server

```bash
# Start the API server (port 8880)
./bin/jarvis-api

# Or in background
nohup ./bin/jarvis-api > logs/api.log 2>&1 &
```

The script will:
- Auto-install FastAPI/uvicorn if needed
- Run database migration if needed
- Start server on port 8880
- Show API documentation at http://localhost:8880/docs

---

## Generic Webhook Endpoint

The alert endpoint accepts webhooks from **ANY source**:

```bash
# Generic webhook (works with anything)
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Server Down",
    "description": "example.com not responding",
    "severity": "high",
    "source": "uptime_kuma"
  }'
```

### Required Fields
- `title`: Alert title (string)
- `source`: Source system name (string)

### Optional Fields
- `description`: Detailed info
- `severity`: `low`, `medium`, `high`, `critical` (default: `medium`)
- `auto_resolve_url`: URL to check for auto-resolution
- `auto_resolve_check_interval`: Seconds between checks (default: 300)
- `metadata`: JSON object with any additional data
- `related_intel_file`: Path to related intel file

---

## Example Webhook Sources

### Uptime Kuma
```json
{
  "title": "Web Server Down",
  "description": "example.com not responding (HTTP 503)",
  "severity": "high",
  "source": "uptime_kuma",
  "auto_resolve_url": "https://example.com",
  "metadata": {
    "monitor_id": "123",
    "url": "https://example.com"
  }
}
```

### Coolify
```json
{
  "title": "Deployment Failed",
  "description": "myapp build failed: Docker error",
  "severity": "high",
  "source": "coolify",
  "metadata": {
    "app": "myapp",
    "error": "Docker build failed"
  }
}
```

### Custom Bash Script
```bash
#!/bin/bash
# disk-check.sh - Monitor disk space

USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')

if [ "$USAGE" -gt 90 ]; then
  curl -X POST http://localhost:8880/api/alerts \
    -H "Content-Type: application/json" \
    -d "{
      \"title\": \"Disk Space Low\",
      \"description\": \"Root partition at ${USAGE}%\",
      \"severity\": \"medium\",
      \"source\": \"cron_disk_check\",
      \"metadata\": {\"usage\": ${USAGE}, \"disk\": \"/\"}
    }"
fi
```

### Cron Job (Backup Notification)
```bash
#!/bin/bash
# backup-notify.sh

STATUS="success"  # or "failed"
SIZE_MB=1024

curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d "{
    \"title\": \"Backup ${STATUS}\",
    \"description\": \"Database backup completed: ${SIZE_MB}MB\",
    \"severity\": \"low\",
    \"source\": \"backup_cron\",
    \"metadata\": {\"size_mb\": ${SIZE_MB}, \"status\": \"${STATUS}\"}
  }"
```

---

## API Endpoints

### Alerts

```bash
# Create alert
POST /api/alerts
Body: {"title": "Alert", "source": "system"}

# List all alerts
GET /api/alerts

# List pending alerts only
GET /api/alerts?status=pending

# List high-severity alerts
GET /api/alerts?severity=high

# Get specific alert
GET /api/alerts/{id}

# Acknowledge alert
PUT /api/alerts/{id}/acknowledge

# Acknowledge all pending alerts
POST /api/alerts/acknowledge-all

# Cancel alert
DELETE /api/alerts/{id}

# Manually check auto-resolve
POST /api/alerts/{id}/check
```

### Reminders

```bash
# Create reminder
POST /api/reminders
Body: {
  "title": "Check Docker version",
  "description": "Unpin if Traefik supports it",
  "trigger_time": "2025-11-24T10:00:00"
}

# List reminders
GET /api/reminders

# List scheduled reminders only
GET /api/reminders?status=scheduled

# Get specific reminder
GET /api/reminders/{id}

# Cancel reminder
DELETE /api/reminders/{id}
```

### Voice/TTS

```bash
# Speak message (proactive notification)
POST /api/voice/speak
Body: {
  "message": "Boss, urgent alert!",
  "mode": "cloud"
}
```

### Health

```bash
# Health check
GET /api/health

# System status
GET /api/status
```

---

## Interactive API Documentation

Once the server is running, visit:

**Swagger UI**: http://localhost:8880/docs  
**ReDoc**: http://localhost:8880/redoc

These provide interactive documentation where you can test endpoints directly in the browser.

---

## Testing the System

### 1. Start the API server
```bash
./bin/jarvis-api
```

### 2. Send a test alert
```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test Alert",
    "description": "Testing the API",
    "severity": "high",
    "source": "test"
  }'
```

**Expected**:
- ✅ Jarvis speaks: "Boss, urgent alert! Test Alert"
- ✅ Returns JSON: `{"ok": true, "alert_id": 1, ...}`

### 3. List alerts
```bash
curl http://localhost:8880/api/alerts | jq
```

### 4. Acknowledge the alert
```bash
curl -X PUT http://localhost:8880/api/alerts/1/acknowledge
```

---

## Integration with Jarvis Voice Mode

You can **also control alerts via voice**:

```
User: "Hey Jarvis, list pending alerts"
User: "Hey Jarvis, clear all alerts"
User: "Hey Jarvis, what's my system status?"
```

*(Requires creating Jarvis tools in Phase 2)*

---

## What's Next (Phase 2)

- `manage_intel.py` tool - Sandboxed CRUD for intel files
- Auto-ingestion after intel file changes
- Follow-up system (background daemon)
- Self-healing checks (background daemon)
- Jarvis tools for voice control (`list_alerts`, `acknowledge_alerts`)

---

## Troubleshooting

### Server won't start
```bash
# Check if port 8880 is in use
lsof -i :8880

# Kill existing process
kill $(lsof -t -i :8880)

# Try again
./bin/jarvis-api
```

### FastAPI not installed
```bash
pip install fastapi uvicorn pydantic
```

### Database not migrated
```bash
./bin/migrate-proactive-db.py
```

### Check logs
```bash
tail -f logs/api.log  # If running in background
```

---

## Security Notes

- API listens on `0.0.0.0:8880` (all interfaces)
- **No authentication** by default (localhost only recommended)
- For production: Add API key middleware (see architecture doc)
- CORS enabled for future web UI

---

**See Also:**
- Full architecture: `docs/PROACTIVE_ASSISTANT_SYSTEM.md`
- Main README: `README.md`

**Status**: Phase 1 Complete ✅  
**Next**: Phase 2 (Intel Management + Voice Tools)

