# Jarvis Proactive Assistant API - Quick Start


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
  "title": "Check Docker version",          # Required
  "description": "Unpin if Traefik supports it",  # Optional
  "trigger_time": "2025-11-24T10:00:00",    # Required (ISO 8601 UTC)
  "related_intel_file": "docker-notes.md",  # Optional - link to intel
  "callback_url": "https://...",            # Optional - webhook on trigger
  "metadata": {"app": "traefik"}            # Optional - any JSON data
}

# List reminders
GET /api/reminders

# List scheduled reminders only
GET /api/reminders?status=scheduled

# List by status: scheduled, triggered, acknowledged
GET /api/reminders?status=triggered

# Get specific reminder
GET /api/reminders/{id}

# Acknowledge reminder
POST /api/reminders/{id}/acknowledge

# Cancel reminder
DELETE /api/reminders/{id}
```

**Required Fields:**
- `title` - Reminder title (string)
- `trigger_time` - When to trigger, ISO 8601 format in UTC (string)

**Optional Fields:**
- `description` - Additional details (string)
- `related_intel_file` - Path to intel file in `jarvis-intel/` (string)
- `callback_url` - Webhook to call when reminder triggers (string)
- `metadata` - Any additional JSON data (object)

**Time Format:**
- Must be UTC in ISO 8601: `"2025-11-24T10:00:00"`
- Convert local time to UTC before sending
- Example: 10am EST → 3pm UTC → `"2025-11-24T15:00:00"`

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

You can **also control alerts and reminders via voice**:

```
User: "Hey Jarvis, list pending alerts"
User: "Hey Jarvis, clear all alerts"
User: "Hey Jarvis, remind me in 4 hours about dinner"
User: "Hey Jarvis, remind me every Wednesday to take out trash"
User: "Hey Jarvis, what reminders do I have?"
User: "Hey Jarvis, clear all my reminders"
```

**Voice Tools Available:**
- `create_reminder` - Natural language time parsing
- `list_reminders` - Query reminders by status
- `acknowledge_reminders` - Mark reminders as done
- `list_alerts` - Show pending/acknowledged alerts
- `acknowledge_alerts` - Clear alerts

**Supported Time Expressions:**
- "in 30 minutes", "in 4 hours", "in 2 days"
- "tomorrow at 3pm"
- "at 5pm" (today or tomorrow if passed)
- "on the 15th" (defaults to 10am)
- "every Wednesday" (weekly, 10am default)
- "every Friday at 5pm" (weekly with time)
- "every month on the 10th" (monthly, 10am default)
- "every month on the 15th at 9am" (monthly with time)

---

## External Calendar Integration

You can integrate external calendar apps to create reminders in Jarvis:

```python
# Python example - sync calendar events to Jarvis
import requests
from datetime import datetime, timezone

def sync_event_to_jarvis(event):
    # Convert event time to UTC
    trigger_time = event['start_time'].astimezone(timezone.utc)
    
    # Create reminder in Jarvis
    response = requests.post(
        'http://localhost:8880/api/reminders',
        json={
            'title': event['title'],
            'description': event['description'],
            'trigger_time': trigger_time.isoformat(),
            'metadata': {
                'calendar_id': event['id'],
                'source': 'google_calendar'
            }
        }
    )
    return response.json()

# Example usage
event = {
    'id': 'evt_123',
    'title': 'Team Meeting',
    'description': 'Weekly standup',
    'start_time': datetime(2025, 11, 20, 10, 0)  # Local time
}

result = sync_event_to_jarvis(event)
print(f"Reminder created: {result['reminder_id']}")
```

**Use Cases:**
- Sync Google Calendar → Jarvis reminders
- Sync Outlook → Jarvis reminders
- Import iCal files
- Two-way sync with `callback_url`

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

