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
- [Fixes Log](FIXES_LOG.md) - All fixes applied

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
✅ Dark mode Swagger UI 

---

**Status**: Production Ready ✅  
**Last Updated**: January 25, 2026

See [READY_TO_USE.md](READY_TO_USE.md) for detailed setup instructions.

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

### Intelligence (Self-Learning) ⭐ ENHANCED

```bash
# === STATS & MONITORING ===

# Get intelligence statistics
GET /api/intelligence/stats
# Returns: total experiences, insights, pending reflections, avg confidence

# Health check for intelligence databases
GET /api/intelligence/health
# Returns: embedding dimension checks, insight statistics

# Prometheus-format metrics
GET /api/intelligence/metrics
# Returns: metrics for Grafana/Prometheus integration

# === DATA ACCESS ===

# List all insights (learned patterns)
GET /api/intelligence/insights?limit=50
# Returns: positive/negative constraints, tool preferences

# List recent experiences
GET /api/intelligence/experiences?limit=20
# Returns: recent interactions and outcomes

# Get recent intelligence logs
GET /api/intelligence/logs/recent?limit=50
# Returns: reflection events, insight creation, etc.

# View meta-knowledge findings (learning system health)
GET /api/intelligence/meta-knowledge
# Returns: blind spots, over-generalization issues, learning quality

# === REFLECTION QUEUE ===

# List pending reflections
GET /api/intelligence/reflections?limit=50
# Returns: experiences waiting for insight generation

# Cancel a pending reflection (don't process it)
DELETE /api/intelligence/reflections/{id}
# Use when testing tools or have known bad data

# Cancel ALL pending reflections
DELETE /api/intelligence/reflections
# Clears the entire reflection queue

# === ACTIONS ===

# Manually trigger reflection processing
POST /api/intelligence/reflect?batch_size=5
# Processes pending reflections and creates insights

# Evaluate a query against learned insights
POST /api/intelligence/evaluate
Body: {"query": "What's the Bitcoin price?"}
# Returns: relevant insights and tool biases

# === MAINTENANCE JOBS ===

# Run decay job (reduce stale insight confidence)
POST /api/intelligence/maintenance/decay
# Returns: { decayed: N, boosted: N, pruned: N }

# Run anomaly detection (flag unusual experiences)
POST /api/intelligence/maintenance/anomaly
# Returns: { anomalies_found: N, details: [...] }

# Run meta-cognition (analyze learning health)
POST /api/intelligence/maintenance/meta-cognition
# Returns: { findings: [...], quality_stats: {...} }

# Run ALL maintenance jobs at once
POST /api/intelligence/maintenance/all
# Returns: { decay: {...}, anomaly: {...}, meta_cognition: {...} }
```

**Maintenance Job Details:**

| Job | What It Does | When to Run |
|-----|--------------|-------------|
| **Decay** | Reduces confidence of unused/failed insights, prunes <0.15 | Every 2 weeks (auto-protected) |
| **Anomaly** | Flags experiences with unusually high turns or failures | Weekly or on-demand |
| **Meta-Cognition** | Detects blind spots, over-generalization, learning issues | Weekly for health check |

### Memory 

```bash
# === CRUD Operations ===

# Create/update a memory
POST /api/memory
Body: {
  "category": "technical",
  "key": "project_location",
  "value": "Flask API at ~/projects/flask-api",
  "importance": 8,
  "source": "user"
}

# List all memories
GET /api/memory
GET /api/memory?category=personal&limit=50

# Get specific memory
GET /api/memory/{id}

# Update memory
PUT /api/memory/{id}
Body: { "value": "Updated value", "importance": 9 }

# Delete memory (forget)
DELETE /api/memory/{id}

# === Search ===

# Keyword search (FTS5, fast)
GET /api/memory/search/keyword?q=flask&limit=10
# Good for: 1-3 word searches

# Semantic search (AI embeddings)
GET /api/memory/search/semantic?q=Where%20is%20my%20web%20project?&limit=5
# Good for: Natural language questions

# === Utility ===

# List categories with counts
GET /api/memory/categories

# Get memory statistics
GET /api/memory/stats

# Rebuild FTS index
POST /api/memory/rebuild-fts
```

**Memory Categories:**
- `personal` - User info, preferences
- `technical` - Code, configs, projects
- `contact` - People, addresses
- `project` - Project locations, status
- `fact` - General knowledge
- `location` - Places, addresses

### Query/Chat 

Programmatically send queries to Jarvis (for n8n, scripts, integrations).

```bash
# Full query with options
POST /api/query
Body: {
  "query": "What's the weather like?",
  "mode": "cloud",
  "session_id": "n8n-workflow-123"
}
# Returns: { ok, speech, response, tools_used, session_id }

# Quick query (JSON body)
POST /api/query/quick
Body: { "query": "What time is it?", "mode": "cloud" }

# Quick query via GET (for testing)
GET /api/query/quick?q=What+is+the+weather&mode=cloud
```

**Example n8n integration:**
```json
{
  "query": "Check if my servers are healthy",
  "mode": "cloud",
  "session_id": "n8n-health-check"
}
```

**Modes:**
- `cloud` - Uses xAI/Anthropic/OpenAI (faster, smarter)
- `local` - Uses Ollama (private, offline)

### Conversations 

Read-only access to conversation history (stored in database).

```bash
# List conversations
GET /api/conversations?limit=50&offset=0

# Get conversation stats
GET /api/conversations/stats

# Get recent conversations (last N minutes)
GET /api/conversations/recent?minutes=60&limit=20

# Search conversation text
GET /api/conversations/search?q=weather&limit=10

# Get specific conversation
GET /api/conversations/{id}

# List unique sessions
GET /api/conversations/sessions
```

See [CONVERSATIONS.md](./CONVERSATIONS.md) for detailed documentation.

### Stash 

Read-only access to stashed artifacts (images, PDFs, music, etc.).

```bash
# Stash statistics
GET /api/stash/stats

# List spaces (with filters)
GET /api/stash?limit=50
GET /api/stash?label=generated_images
GET /api/stash?tool=generate_image

# List labels with counts
GET /api/stash/labels

# Recent spaces
GET /api/stash/recent?limit=10

# Search stash
GET /api/stash/search?q=bitcoin

# Get space with files
GET /api/stash/space/{space_id}

# Get file info
GET /api/stash/space/{space_id}/file/{file_id}

# Download file
GET /api/stash/space/{space_id}/file/{file_id}/download
```

See [STASH.md](./STASH.md) for detailed documentation.

### Canvas 

Read-only access to canvas pages (markdown documents with embedded images).

```bash
# Canvas statistics
GET /api/canvas/stats

# List pages (with filters)
GET /api/canvas?limit=50
GET /api/canvas?tag=status
GET /api/canvas?search=bitcoin

# List tags with counts
GET /api/canvas/tags

# List source tools with counts
GET /api/canvas/tools

# Recent pages
GET /api/canvas/recent?limit=10

# Search pages
GET /api/canvas/search?q=bitcoin

# Get page with content
GET /api/canvas/{page_id}
```

See [CANVAS.md](./CANVAS.md) for detailed documentation.

### Images (Cloudflare CDN) ⭐ NEW

Upload images to Cloudflare Images CDN for permanent, public hosting.

```bash
# Upload image (file, URL, base64, or stash reference)
POST /api/images
{
  "source": "https://example.com/image.jpg",
  "source_type": "url",
  "uploader": "jarvis",
  "category": "status",
  "prompt": "Dashboard visualization",
  "tags": ["status", "generated"]
}

# Upload base64 (convenience endpoint)
POST /api/images/base64
{
  "image": "data:image/png;base64,iVBORw0KGgo...",
  "uploader": "samantha",
  "category": "generated"
}

# Check credentials configured
GET /api/images/health
```

**Response:**
```json
{
  "ok": true,
  "url": "https://imagedelivery.net/xxx/jarvis/2026-01-27/status/dashboard_abc123/public",
  "image_id": "jarvis/2026-01-27/status/dashboard_abc123",
  "custom_path": "jarvis/2026-01-27/status/dashboard_abc123",
  "uploader": "jarvis"
}
```

**Path Organization:** `{uploader}/{date}/{category}/{filename}_{hash}`

**⚠️ Privacy:** Uploaded images are publicly accessible. Do NOT upload screenshots, personal photos, or sensitive documents.

See [IMAGES.md](./IMAGES.md) for detailed documentation.

### Intel (Knowledge Files) 

CRUD operations for `jarvis-intel/` knowledge files with ingestion support.

```bash
# === Statistics ===

# Get intel folder stats
GET /api/intel/stats
# Returns: total_files, total_size, total_facts_ingested, pending files

# === CRUD Operations ===

# List all intel files
GET /api/intel
GET /api/intel?include_stats=true   # Include fact counts

# Create intel file
POST /api/intel
Body: {
  "filename": "my-notes.md",
  "content": "# My Notes\n\n## Facts\n- Key: Value",
  "auto_ingest": true  # Optional: ingest immediately
}

# Get file content
GET /api/intel/{filename}

# Update file (re-ingests if auto_ingest=true)
PUT /api/intel/{filename}
Body: {
  "content": "Updated content",
  "auto_ingest": true
}

# Delete file and its memories
DELETE /api/intel/{filename}

# === Ingestion ===

# Trigger manual ingestion
POST /api/intel/ingest?async_mode=true   # Background
POST /api/intel/ingest?async_mode=false  # Wait for completion
```

**Use Cases:**
- Automated knowledge import from external systems
- Webhook-triggered intel updates
- Batch import scripts
- Programmatic RAG content management

See [INTEL.md](./INTEL.md) for detailed documentation.

### Prices 

Direct price retrieval without LLM routing - fast, free, silent. Perfect for n8n workflows.

```bash
# Stock/Futures price (direct, no LLM)
GET /api/prices/stock/TSLA
GET /api/prices/stock/GC=F    # Gold futures
GET /api/prices/stock/AAPL

# Crypto price (direct, no LLM)
GET /api/prices/crypto/BTC
GET /api/prices/crypto/SOL

# Batch prices
GET /api/prices/batch?stocks=TSLA,GC=F&crypto=BTC,SOL
```

**Response:**
```json
{
  "ok": true,
  "data": {
    "symbol": "TSLA",
    "company": "Tesla, Inc.",
    "price_usd": 437.50,
    "change_today_percent": -0.46,
    "change_emoji": "📉"
  }
}
```

**Benefits over `/api/query`:**
- ~2s vs ~20s (no LLM routing)
- No token usage
- No speech output (silent)

See [PRICES.md](./PRICES.md) for detailed documentation.

### Config 

Serve configuration files to external systems (n8n workflows).

```bash
# Get price alert config (for n8n)
GET /api/config/price-alerts

# Get thresholds only
GET /api/config/price-alerts/thresholds
```

**Response:**
```json
{
  "ok": true,
  "settings": { "check_interval_minutes": 10 },
  "watchlist": {
    "crypto": [{ "symbol": "BTC", "conditions": [...] }],
    "stocks": [{ "symbol": "TSLA", "conditions": [...] }]
  },
  "source": "config/price-alerts.yaml"
}
```

**Single Source of Truth**: Edit `config/price-alerts.yaml`, n8n fetches via this API.

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

| URL | Description |
|-----|-------------|
| http://localhost:8880/docs/dark | **Swagger UI (Dark Mode)** 🌙 Recommended |
| http://localhost:8880/docs | Swagger UI (Light) |
| http://localhost:8880/redoc | ReDoc (Alternative) |

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

# `/announce` Endpoint - Quick Summary

## TL;DR

**You already had this feature!** I just added a simpler alias for external integrations.

---

## Architecture Quick Reference

```
┌──────────────────────────────────────────────────────────┐
│             JARVIS HAS 3 MODES                           │
└──────────────────────────────────────────────────────────┘

┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  1. TERMINAL    │  │  2. WEB UI      │  │  3. PROACTIVE   │
│     (Local)     │  │  (Browser)      │  │     (API)       │
├─────────────────┤  ├─────────────────┤  ├─────────────────┤
│ wake_jarvis.py  │  │ port 5001       │  │ port 8880       │
│                 │  │                 │  │                 │
│ "Hey Jarvis"    │  │ Chat + Tools    │  │ Webhooks ← NEW! │
│ → Q&A + Tools   │  │ Type or speak   │  │                 │
│                 │  │ Browser TTS     │  │ /announce       │
│ System speakers │  │                 │  │ /speak          │
└─────────────────┘  └─────────────────┘  │ /alerts         │
                                           │ /reminders      │
                                           └─────────────────┘
```

---

## What `/announce` Does

**Simple HTTP endpoint for making Jarvis speak:**

```bash
POST http://localhost:8880/api/voice/announce
{
  "message": "Package delivered at front door"
}
```

**→ Jarvis speaks through system speakers immediately**

---

## Use Cases

### ✅ Home Assistant
```yaml
# Motion detected → Jarvis announces
automation:
  - trigger:
      platform: state
      entity_id: binary_sensor.front_door
      to: "on"
    action:
      service: rest_command.jarvis_announce
      data:
        message: "Motion at front door"
```

### ✅ Monitoring Systems
```bash
# Server down → Jarvis alerts you
curl -X POST http://192.168.1.100:8880/api/voice/announce \
  -d '{"message": "Web server is offline"}'
```

### ✅ IFTTT / n8n / Custom Scripts
```python
# From any script
requests.post(
    "http://localhost:8880/api/voice/announce",
    json={"message": "Build complete"}
)
```

---
  

## Only Requires:

✅ Jarvis API running (`./bin/jarvis-api`)  
✅ Network access (local or remote)  

---

## What Changed

**Before (you already had this):**
```bash
POST /api/voice/speak
{
  "message": "Test",
  "mode": "cloud"  # or "local"
}
```

**After (new simpler alias):**
```bash
POST /api/voice/announce
{
  "message": "Test"
  # mode auto-detected from LLM_PROVIDER env var
}
```

**That's it!** Just a simpler endpoint for external systems.

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

