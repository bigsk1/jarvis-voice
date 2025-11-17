# Fixes Applied

## ✅ Mode Detection Fixed

**Issue**: `--local` flag wasn't being respected, both modes used cloud database.

**Fix**: Updated `AlertManager` and `ReminderManager` to read `JARVIS_API_MODE` environment variable set by the startup script.

**Verification**:
```bash
# Cloud mode
./bin/jarvis-api
curl http://localhost:8880/api/status | jq '.mode, .database'
# Should show: "cloud" and "jarvis_memory.db"

# Local mode
./bin/jarvis-api --local
curl http://localhost:8880/api/status | jq '.mode, .database'
# Should show: "local" and "jarvis_memory_local.db"
```

## ✅ Display Bug Fixed

**Issue**: Startup showed `sayl-local.sh` and `sayc.sh` instead of correct names.

**Fix**: Updated startup script to correctly display:
- Cloud: `say.sh (OpenAI)`
- Local: `say-local.sh (Kokoro - requires server at ...)`

## ⚠️ Local TTS Not Working

**Issue**: Local mode doesn't speak (no audio).

**Cause**: Kokoro TTS server not running at `192.168.70.226:8880`

**Options to fix:**

### Option 1: Start Kokoro TTS Server (Recommended for offline)
```bash
# On the machine at 192.168.70.226, start Kokoro server
# (You probably have this configured somewhere)
```

### Option 2: Use espeak as Fallback (Quick fix)
Update `bin/say-local.sh` to use espeak instead:

```bash
# Replace the curl/ffmpeg section with:
espeak "$TEXT" -w "$OUTFILE"
```

### Option 3: Use Cloud TTS Even in Local Mode (Hybrid)
Just use `./bin/jarvis-api` (cloud mode) even when running local Jarvis.
- LLM: Ollama (local)
- TTS: OpenAI (cloud)
- Hybrid mode!

## 📊 Database Auto-Sync

**How it works:**

Auto-sync runs **on startup** when you switch modes:

```bash
# Scenario 1: Create alert in cloud, switch to local
./bin/jarvis-api                    # Cloud mode
# Create alerts via API
# Stop server (Ctrl+C)

./bin/jarvis-api --local            # Local mode starts
# On startup: Auto-syncs FROM cloud → local
# Your alerts are now in local DB!
```

**Manual sync** (if needed):
```bash
# Sync from cloud to local
./bin/sync-memory-db.py --from cloud --to local

# Sync from local to cloud
./bin/sync-memory-db.py --from local --to cloud
```

**When sync happens:**
- ✅ On Jarvis startup (reactive mode): `./jarvis` or `./jarvis-local`
- ❌ NOT on API startup (would cause delays)
- ✅ Manually via `sync-memory-db.py`

**Solution for API auto-sync:**

If you want API to auto-sync on startup, add to `bin/jarvis-api`:

```bash
# After line 60 (after database migration check)

# Auto-sync databases before starting
if [ "$MODE" == "local" ]; then
    echo "🔄 Auto-syncing cloud → local..."
    "$PROJECT_ROOT/bin/sync-memory-db.py" --from cloud --to local --quiet
elif [ "$MODE" == "cloud" ]; then
    echo "🔄 Auto-syncing local → cloud..."
    "$PROJECT_ROOT/bin/sync-memory-db.py" --from local --to cloud --quiet
fi
```

Want me to add this?

## Summary

**Working:**
- ✅ Cloud mode with TTS
- ✅ Local mode (database and alerts)
- ✅ Mode detection and switching
- ✅ Different databases per mode

**Not working:**
- ❌ Local TTS (Kokoro server not running)

**Optional:**
- Auto-sync on API startup (can add if you want)

