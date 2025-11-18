# Fixes Log - Jarvis Proactive Assistant

## ✅ Database Sync Not Running on Startup (Latest - Nov 18, 2025)

**Issue**: When running `./bin/jarvis-api --local` or `./bin/jarvis-services --local`, the database sync script was not being executed, causing reminders and alerts to not be synced between cloud and local databases.

**Root Cause**: 
- `jarvis-api` and `jarvis-services` scripts only ran migration (`migrate-proactive-db.py`) to create tables
- They never called `sync-memory-db.py` to actually sync data between cloud and local databases
- This meant reminders/alerts created in cloud mode wouldn't appear in local mode, and vice versa

**Fix**: 
Added database sync logic to both startup scripts:

```bash
# Sync databases between cloud and local modes
if [ "$MODE" == "local" ]; then
    # Running in local mode - sync from cloud to local if cloud DB exists
    if [ -f "$PROJECT_ROOT/data/jarvis_memory.db" ]; then
        echo -e "${BLUE}🔄 Syncing data: cloud → local...${NC}"
        "$PROJECT_ROOT/bin/sync-memory-db.py" --from cloud --to local
        echo ""
    fi
else
    # Running in cloud mode - sync from local to cloud if local DB exists
    if [ -f "$PROJECT_ROOT/data/jarvis_memory_local.db" ]; then
        echo -e "${BLUE}🔄 Syncing data: local → cloud...${NC}"
        "$PROJECT_ROOT/bin/sync-memory-db.py" --from local --to cloud
        echo ""
    fi
fi
```

**Files Changed**:
- `/home/boss/jarvis-voice/bin/jarvis-api` (added lines 62-77)
- `/home/boss/jarvis-voice/bin/jarvis-services` (added lines 161-176)

**Result**: 
- ✅ Running `./bin/jarvis-api --local` now syncs cloud → local automatically
- ✅ Running `./bin/jarvis-api` (cloud mode) syncs local → cloud if local DB exists
- ✅ Same behavior for `./bin/jarvis-services`
- ✅ Reminders, alerts, and knowledge_base entries are now kept in sync across modes
- ✅ Zero manual intervention required

**Testing**:
```bash
# Test sync manually
./bin/sync-memory-db.py --from cloud --to local

# Or start API/services and sync happens automatically
./bin/jarvis-api --local
./bin/jarvis-services --local
```

---

## ✅ Container Auto-Resolve Fix (Nov 18, 2025)

**Issue**: Docker container alerts couldn't auto-resolve
- Container stopped → Alert sent ✓
- Container started → No notification sent ✗
- `auto_resolve_url` = NULL (containers don't have URLs)
- Self-healing daemon skipped (no URL to check)
- Required manual "clear alerts" command

**Fix**:
1. Added `POST /api/alerts/{id}/resolve` endpoint
2. Monitoring agent now queries Jarvis API when container comes back up
3. Agent calls `/resolve` to programmatically resolve alerts
4. Improved TTS: "Boss, good news! {source} is back up and running!"

**Files modified**:
- `api/routes/alerts.py` - Added `/resolve` endpoint
- `api/managers/alert_manager.py` - Better TTS message
- `docs/api/code-examples/docker/monitor.py` - Agent-based resolve

**Update instructions**:
```bash
# Restart API (adds /resolve endpoint)
./bin/restart-api

# Update Docker agent (on remote server)
cd ~/jarvis-monitor
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# Clear stuck alerts
curl -X POST http://localhost:8880/api/alerts/acknowledge-all
```

**See**: `docs/api/CONTAINER_AUTO_RESOLVE_FIX.md` for full details.

---

## ✅ Monitoring Agent Fixes (Nov 18, 2025)

**Issues**:
1. Docker health check failed (tried to reach Jarvis API from remote)
2. Unwanted "Monitoring Agent Started" alerts with follow-ups
3. Slow auto-resolve (5 minutes)
4. Generic auto-resolve TTS messages

**Fixes**:
1. **Health check**: Changed to use local file (`/tmp/monitor_healthy`)
2. **Startup alerts**: Removed `ALERT_ON_START` feature entirely
3. **Auto-resolve**: Reduced from 300s to 60s (configurable via `AUTO_RESOLVE_INTERVAL`)
4. **TTS message**: Changed from "Alert resolved: {title}" to "Boss, good news! {source} is back up!"

**Files modified**:
- `docs/api/code-examples/docker/Dockerfile`
- `docs/api/code-examples/docker/monitor.py`
- `docs/api/code-examples/docker/docker-compose.yml`
- `services/self_healing_daemon.py`

**Update instructions**:
```bash
# Restart services (applies TTS fix)
./bin/restart-services

# Update Docker agent (on remote server)
cd ~/jarvis-monitor
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

**See**: `docs/api/MONITORING_AGENT_FIXES.md` for full details.

---

## ✅ long_form Column Schema Fix (Nov 17, 2025)

**Issue**: The `long_form` column in `knowledge_base` table was not being created consistently

**Fix**: 
1. Added `long_form TEXT` column to `lib/memory_db.py` schema definition
2. Updated `bin/sync-memory-db.py` to include `long_form` in sync operations

**Verification**:
```bash
sqlite3 data/jarvis_memory.db "PRAGMA table_info(knowledge_base);" | grep long_form
```

---

## ✅ Mode Detection Fixed (Nov 17, 2025)

**Issue**: `--local` flag wasn't being respected, both modes used cloud database

**Fix**: Updated `AlertManager` and `ReminderManager` to read `JARVIS_API_MODE` environment variable

**Verification**:
```bash
./bin/jarvis-api
curl http://localhost:8880/api/status | jq '.mode, .database'
```

---

## Summary of All Fixes

| Date | Fix | Impact | Update Required |
|------|-----|--------|-----------------|
| Nov 18 | Container auto-resolve | ⭐⭐⭐ High | API + Agent |
| Nov 18 | Monitoring agent improvements | ⭐⭐⭐ High | Services + Agent |
| Nov 17 | long_form column | ⭐⭐ Medium | Automatic |
| Nov 17 | Mode detection | ⭐⭐ Medium | Automatic |

---

## Quick Update Commands

### Update Everything
```bash
# On Jarvis server
./bin/restart-api
./bin/restart-services

# On remote monitoring servers
cd ~/jarvis-monitor
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Clear Stuck Alerts
```bash
# Via API
curl -X POST http://localhost:8880/api/alerts/acknowledge-all

# Via voice
"Hey Jarvis, clear all pending alerts"
```

---

## Detailed Documentation

- **[Container Auto-Resolve Fix](CONTAINER_AUTO_RESOLVE_FIX.md)** - Complete explanation
- **[Monitoring Agent Fixes](MONITORING_AGENT_FIXES.md)** - Agent improvements
- **[Remote Monitoring Guide](REMOTE_MONITORING.md)** - Setup guide
- **[Integration Summary](INTEGRATION_SUMMARY.md)** - FAQs answered

