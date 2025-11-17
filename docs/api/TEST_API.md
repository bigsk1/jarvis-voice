# 🧪 API Testing Guide

## Quick Test Commands

### 1. Start API Server

**Cloud Mode:**
```bash
./bin/jarvis-api
```

**Local Mode (Offline):**
```bash
./bin/jarvis-api --local
```

### 2. Run Comprehensive Tests

```bash
./tests/test-api-endpoints.sh
```

**This tests:**
- ✅ Health check
- ✅ System status
- ✅ Create alerts (low, high, critical severity)
- ✅ List alerts (all, pending, by severity)
- ✅ Get specific alert
- ✅ Acknowledge alerts (single and bulk)
- ✅ Create reminders
- ✅ List reminders
- ✅ Manual TTS
- ✅ Auto-resolve functionality

### 3. Manual Tests

**Create a test alert:**
```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test Alert",
    "description": "Testing webhooks",
    "severity": "high",
    "source": "test"
  }'
```

**List all alerts:**
```bash
curl http://localhost:8880/api/alerts | jq
```

**Acknowledge alert #1:**
```bash
curl -X PUT http://localhost:8880/api/alerts/1/acknowledge
```

**Clear all pending alerts:**
```bash
curl -X POST http://localhost:8880/api/alerts/acknowledge-all
```

**Create reminder:**
```bash
curl -X POST http://localhost:8880/api/reminders \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Check something",
    "description": "Reminder description",
    "trigger_time": "2025-11-17T06:31:00"
  }'
```

**Manual TTS test:**
```bash
curl -X POST http://localhost:8880/api/voice/speak \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Testing text to speech!",
    "mode": "cloud"
  }'
```

### 4. Test Auto-Sync

**Scenario**: Create alert in cloud mode, switch to local mode, verify it synced.

**Steps:**
```bash
# 1. Start cloud API
./bin/jarvis-api

# 2. Create alert
curl -X POST http://localhost:8880/api/alerts \
  -d '{"title": "Sync Test", "source": "test"}' \
  -H "Content-Type: application/json"

# 3. Stop cloud API (Ctrl+C)

# 4. Start local API
./bin/jarvis-api --local

# 5. List alerts (should see "Sync Test")
curl http://localhost:8880/api/alerts | jq '.alerts[] | {title, source}'
```

**Expected:** Alert syncs automatically between databases.

### 5. Test Reminder (Manual Trigger)

**Note**: Background daemon not implemented yet, so manual trigger required.

```bash
# 1. Create reminder for 1 minute from now
TRIGGER_TIME=$(date -u -d '+1 minute' '+%Y-%m-%dT%H:%M:%S')
curl -X POST http://localhost:8880/api/reminders \
  -H "Content-Type: application/json" \
  -d "{
    \"title\": \"Test Reminder\",
    \"description\": \"Should trigger in 1 minute\",
    \"trigger_time\": \"${TRIGGER_TIME}\"
  }"

# 2. Wait 1 minute

# 3. Check if due
curl http://localhost:8880/api/reminders | jq '.reminders[] | select(.status == "scheduled")'

# 4. Manual trigger (Phase 2 will automate this)
# For now, reminders are stored but need manual processing
```

### 6. Test Different Severities

**Low (no TTS):**
```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"title": "Low Priority", "severity": "low", "source": "test"}'
```

**Medium (no TTS):**
```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"title": "Medium Priority", "severity": "medium", "source": "test"}'
```

**High (WITH TTS 🔊):**
```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"title": "High Priority", "severity": "high", "source": "test"}'
```

**Critical (WITH TTS 🔊):**
```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"title": "CRITICAL ALERT", "severity": "critical", "source": "test"}'
```

### 7. Test Auto-Resolve

```bash
# Create alert with auto-resolve URL
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Server Down (example.com)",
    "severity": "high",
    "source": "test",
    "auto_resolve_url": "https://example.com"
  }'

# Get alert ID from response, then manually check
curl -X POST http://localhost:8880/api/alerts/1/check

# If example.com is reachable (200 OK), alert auto-resolves
```

### 8. Test Interactive Docs

Visit: http://localhost:8880/docs

- Try each endpoint interactively
- See request/response schemas
- Test directly in browser

### 9. Test Query Filters

**By status:**
```bash
curl "http://localhost:8880/api/alerts?status=pending" | jq
curl "http://localhost:8880/api/alerts?status=acknowledged" | jq
```

**By severity:**
```bash
curl "http://localhost:8880/api/alerts?severity=high" | jq
curl "http://localhost:8880/api/alerts?severity=critical" | jq
```

**By source:**
```bash
curl "http://localhost:8880/api/alerts?source=uptime_kuma" | jq
curl "http://localhost:8880/api/alerts?source=test" | jq
```

**Combined:**
```bash
curl "http://localhost:8880/api/alerts?status=pending&severity=high" | jq
```

### 10. Test Error Handling

**Invalid severity:**
```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"title": "Test", "severity": "invalid", "source": "test"}'
# Should return 422 validation error
```

**Missing required field:**
```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"description": "Missing title"}'
# Should return 422 validation error
```

**Non-existent alert:**
```bash
curl http://localhost:8880/api/alerts/99999
# Should return 404
```

## Expected Behavior

### TTS Triggers
- ✅ **High** severity → Jarvis speaks immediately
- ✅ **Critical** severity → Jarvis speaks immediately
- ❌ **Medium** severity → No TTS (silent)
- ❌ **Low** severity → No TTS (silent)

### Database Storage
- ✅ All alerts stored in database
- ✅ All reminders stored in database
- ✅ Alerts sync between cloud/local DBs
- ✅ Reminders sync between cloud/local DBs

### Auto-Resolve
- ✅ Checks configured URL (HTTP GET)
- ✅ 2xx/3xx response → Auto-resolves
- ✅ 4xx/5xx or timeout → Stays active

## Troubleshooting

**Server not responding:**
```bash
# Check if running
lsof -i :8880

# Check logs (if background)
tail -f logs/api.log
```

**TTS not working:**
```bash
# Test TTS directly
./bin/say.sh "Test"           # Cloud
./bin/say-local.sh "Test"     # Local

# Check say.sh script
ls -la bin/say*.sh
```

**Database issues:**
```bash
# Check if migrated
sqlite3 data/jarvis_memory.db "SELECT name FROM sqlite_master WHERE type='table' AND name='alerts'"

# Run migration
./bin/migrate-proactive-db.py
```

**Wrong mode:**
```bash
# Verify which config is loaded
cat /proc/$(lsof -t -i :8880)/environ | tr '\0' '\n' | grep LLM_PROVIDER
```

## Success Criteria

✅ All 14 tests pass in `test-api-endpoints.sh`  
✅ TTS works for high/critical alerts  
✅ Alerts stored in database  
✅ Query filters work  
✅ Auto-sync works between modes  
✅ Interactive docs accessible  
✅ Both cloud and local modes work  

---

**Ready to test?** Run:
```bash
./bin/jarvis-api
./tests/test-api-endpoints.sh
```

