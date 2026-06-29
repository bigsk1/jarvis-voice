# Fixes Log - Jarvis Proactive Assistant

> **Historical fix log.** This records earlier implementation changes and is
> not a current setup or troubleshooting guide. Use [API_OVERVIEW.md](../../api/API_OVERVIEW.md)
> and [TEST_API.md](../../api/TEST_API.md) for live commands. It is retained in
> `docs/archive/api/` for traceability.

## ✅ manage_intel Subfolder Creation Breaks Ingestion (Latest - Nov 19, 2025)

**Issue**: When creating intel files, the LLM would sometimes create subdirectories (e.g., `bitcoin/price-note.md`), but `ingest_intel` only scans the root level of `jarvis-intel/`, so these files were never ingested into the knowledge base.

**Example**:
```
User: "Save Bitcoin price to intel"
→ LLM creates: bitcoin/price-note-2025-11-19.md
→ ingest_intel runs, processes: network.md, recurring-tasks.md, opencode_details.md
→ bitcoin/price-note.md NOT ingested (in subfolder) ❌
```

**Root Cause**:
- `manage_intel.py`'s `validate_path()` allowed subdirectories
- `ingest_intel.py` only scans `jarvis-intel/*.md` and `jarvis-intel/*.txt` (no recursion)
- Database `source` column stores `intel/FILENAME`, not `intel/FOLDER/FILENAME`
- System breaks when files are in subfolders

**Fix**:
Modified `manage_intel.py` to **reject paths with subdirectories**:

```python
# CRITICAL: Reject paths with subdirectories
if '/' in path or '\\' in path:
    raise ValueError(
        f"Subdirectories not allowed in jarvis-intel/. "
        f"Use flat filenames only (e.g., 'bitcoin-price-2025-11-19.md' "
        f"not 'bitcoin/price-note.md')"
    )
```

**Design Decision**: Keep `jarvis-intel/` **FLAT** (no subfolders):
- ✅ Simpler ingestion (no recursion needed)
- ✅ Faster scanning (fewer files to check)
- ✅ Clearer file management (all files in one place)
- ✅ Consistent database schema (`intel/FILENAME`)

**Updated Tool Description**:
Added to `manage_intel.tool.json`:
```
IMPORTANT: jarvis-intel/ is FLAT - use simple filenames like
'bitcoin-price-2025-11-19.md', NOT subdirectories like 'bitcoin/price.md'
```

**Files Changed**:
- `~/jarvis-voice/skills/manage_intel.py` (added subdirectory check in `validate_path()`)
- `~/jarvis-voice/skills/manage_intel.tool.json` (updated description)

**Result**:
- ✅ LLM will now use flat filenames: `bitcoin-price-2025-11-19.md`
- ✅ All intel files ingested correctly
- ✅ Clear error if subfolder path attempted: "Subdirectories not allowed"
- ✅ Database consistency maintained

**Testing**:
```bash
# This will now fail with clear error:
echo '{"action": "create", "path": "bitcoin/price.md", "content": "test"}' | \
  python3 skills/manage_intel.py
# Error: Subdirectories not allowed in jarvis-intel/

# This will work:
echo '{"action": "create", "path": "bitcoin-price-2025-11-19.md", "content": "test"}' | \
  python3 skills/manage_intel.py
# Success!
```

---

## ✅ Duplicate Tool Calls in Multi-Turn Loop (Nov 19, 2025)

**Issue**: In multi-turn conversations, the LLM would call the same tool (like `ingest_intel`) multiple times in a row, wasting time and API calls. Example: `ingest_intel` was called 3 times consecutively, each taking 15 seconds.

**Root Cause**:
- Multi-turn loop continues after each successful tool execution
- LLM router doesn't recognize when a task is COMPLETE after certain tools
- No programmatic detection of duplicate/redundant tool calls
- System prompt didn't explicitly warn against repeating the same tool

**Fix**:
Two-layer solution:

**1. Router Prompt Update** (`orchestrator/router_v2.py`):
```
CRITICAL - AVOID REDUNDANT TOOL CALLS:
- Do NOT call the same tool multiple times unless explicitly needed
- After ingest_intel succeeds → task is COMPLETE, switch to Q&A
- After list/search tools succeed → task is COMPLETE, switch to Q&A
- Only repeat a tool if user asked for multiple operations or wrong parameters
```

**2. Programmatic Detection** (`orchestrator/orchestrator_v2.py`):
- Track `last_tool_call` (tool name + arguments)
- If next turn tries to call the SAME tool with SAME arguments → Force Q&A mode
- Prevent wasteful duplicate executions

**Files Changed**:
- `~/jarvis-voice/orchestrator/router_v2.py` (added redundancy warning)
- `~/jarvis-voice/orchestrator/orchestrator_v2.py` (added duplicate detection logic)

**Result**:
- ✅ No more duplicate tool calls
- ✅ `ingest_intel` runs once, then switches to Q&A
- ✅ Multi-turn loops complete faster
- ✅ Reduced API costs (fewer LLM calls, fewer embeddings)

**Example Flow (Before Fix)**:
```
Turn 1: get_recent_conversations → Success
Turn 2: manage_intel list → Success
Turn 3: ingest_intel → Success (15s)
Turn 4: ingest_intel → Success (15s) ❌ DUPLICATE
Turn 5: ingest_intel → Success (15s) ❌ DUPLICATE
Total: 45 seconds wasted!
```

**Example Flow (After Fix)**:
```
Turn 1: get_recent_conversations → Success
Turn 2: manage_intel list → Success
Turn 3: ingest_intel → Success (15s)
Turn 4: Duplicate detected → Force Q&A → "Task complete" ✅
Total: 15 seconds, no waste!
```

---

## ✅ manage_intel Timeout with auto_ingest (Nov 19, 2025)

**Issue**: When using `manage_intel` with `auto_ingest: true`, the tool would timeout after 15 seconds with "Tool manage_intel timed out. Error: Timeout", even though the file was created successfully.

**Root Cause**:
- Orchestrator gives `manage_intel` only **15 seconds** timeout (cloud mode default)
- `manage_intel` calls `ingest_intel` subprocess with **30 seconds** timeout
- `ingest_intel` can take up to **60 seconds** for large datasets (embedding generation is slow)
- Orchestrator kills `manage_intel` at 15s before ingestion completes

**Timeout Chain:**
```
Orchestrator: manage_intel timeout = 15s ❌ (too short)
  └─> manage_intel: calls ingest_intel with 30s timeout
        └─> ingest_intel: needs up to 60s for embeddings
```

**Fix**:
Added `manage_intel` to the list of tools with extended timeout in `orchestrator/executor.py`:

```python
elif tool_name == "manage_intel":
    timeout = 60  # 1 minute (can auto-ingest, which needs time for embeddings)
```

**Files Changed**:
- `~/jarvis-voice/orchestrator/executor.py` (lines 121-122)

**Result**:
- ✅ `manage_intel` with `auto_ingest: true` now completes successfully
- ✅ File creation + ingestion works in one operation
- ✅ No more timeout errors for Bitcoin price notes or other intel files

**Test**:
```bash
# This should now work without timeout:
echo '{"action": "create", "path": "test.md", "content": "Test content", "auto_ingest": true}' | \
  python3 skills/manage_intel.py
```

---

## ✅ Conversation History Tool Routing Regression (Nov 18, 2025)

**Issue**: User asked "What was the last conversation we had?" and Jarvis failed with "I need a search query. Error: Missing query parameter. I tried 2 time(s)."

**Root Cause**:
- Router incorrectly chose `search_conversations` (requires query parameter) instead of `get_recent_conversations` (chronological, no query needed)
- Tool descriptions didn't clearly distinguish TEMPORAL queries (last/recent) from TOPIC queries (search for X)
- Router prompt had an example that inadvertently taught the wrong behavior

**Fix**:
Updated three files to clarify tool selection:

**1. Tool Descriptions:**
- `get_recent_conversations.tool.json`: "ALWAYS use for: 'what was last conversation?', 'what did I just ask?'"
- `search_conversations.tool.json`: "Use ONLY for specific TOPIC search, requires query parameter"

**2. Router Prompt** (`orchestrator/router_v2.py`):
```python
**Conversation History Tools:**
❌ BAD: "What was my last question?" → search_conversations (requires query, will fail)
✅ GOOD: "What was my last question?" → get_recent_conversations (chronological)

❌ BAD: "Did I mention Bitcoin?" → get_recent_conversations (not temporal)
✅ GOOD: "Did I mention Bitcoin?" → search_conversations(query="Bitcoin")

**Rule**: TEMPORAL queries (last/recent/just asked) → get_recent_conversations
          TOPIC queries (find/search/mention X) → search_conversations
```

**Files Changed**:
- `~/jarvis-voice/skills/get_recent_conversations.tool.json`
- `~/jarvis-voice/skills/search_conversations.tool.json`
- `~/jarvis-voice/orchestrator/router_v2.py` (lines 168-175)

**Result**:
- ✅ "What was my last question?" now calls `get_recent_conversations`
- ✅ "What did I just ask?" calls `get_recent_conversations`
- ✅ "Did I mention Bitcoin?" correctly calls `search_conversations(query="Bitcoin")`
- ✅ Clear distinction between temporal vs topic queries

**Note**: The reminder creation ("every Monday and Thursday") actually worked correctly - the LLM intelligently made TWO tool calls to create both reminders since the parser can't handle multiple days in one recurrence rule.

---

## ✅ Improved LLM Routing for Proactive System Queries (Nov 18, 2025)

**Issue**: When user asked "When is my next reminder?", Jarvis said "no upcoming reminders", but "List my pending reminders" worked correctly. The LLM wasn't recognizing that natural language reminder/alert queries should call their specific tools.

**Root Cause**:
- Router system prompt focused heavily on memory tools (search_memory, semantic_recall)
- No explicit guidance that reminder/alert queries require their specific tools
- LLM tried to answer from conversation context instead of querying current state
- Tool descriptions didn't emphasize "ALWAYS use this tool for ANY reminder-related query"

**Fix**:
Added explicit routing rules in three places:

**1. Router System Prompt** (`orchestrator/router_v2.py`):
```python
PROACTIVE SYSTEM QUERIES (CRITICAL):
For questions about REMINDERS, ALERTS, or SERVICE STATUS → ALWAYS call the specific tool, NEVER answer from memory/context:
- "When is my next reminder?" → call 'list_reminders'
- "What reminders do I have?" → call 'list_reminders'
- "Any pending alerts?" → call 'list_alerts'
- "Did I miss any reminders?" → call 'list_reminders'
- "Do I have any reminders?" → call 'list_reminders' (even if you just created one!)
- "What's the status of X service?" → call 'query_service_logs'

**WHY**: These systems maintain LIVE STATE that changes independently. Memory/context may be stale. ALWAYS query the current state.
```

**2. Tool Descriptions** - Added "ALWAYS use this tool for ANY X-related query" emphasis:
- `list_reminders.tool.json` - Now lists 10+ query variations
- `list_alerts.tool.json` - Now lists 8+ query variations

**Files Changed**:
- `~/jarvis-voice/orchestrator/router_v2.py` (added PROACTIVE SYSTEM QUERIES section)
- `~/jarvis-voice/skills/list_reminders.tool.json` (strengthened description)
- `~/jarvis-voice/skills/list_alerts.tool.json` (strengthened description)

**Result**:
- ✅ "When is my next reminder?" now correctly calls `list_reminders`
- ✅ "Do I have any reminders?" calls `list_reminders`
- ✅ "Any alerts?" calls `list_alerts`
- ✅ "What's broken?" calls `list_alerts`
- ✅ LLM now understands these queries need LIVE STATE, not memory
- ✅ More intelligent routing for natural language variations

**Philosophy**:
A smart AI assistant should map user intent to available tools, not require exact phrasing. The router should be flexible enough to understand that "when is my next reminder?" clearly needs the `list_reminders` tool, even if the user didn't say "list reminders" explicitly.

**Testing**:
```bash
# All of these should now call list_reminders:
"When is my next reminder?"
"Do I have any reminders?"
"Show my reminders"
"Check reminders"
"Any upcoming reminders?"
```

---

## ✅ Reminder Creation with Word Numbers (Nov 18, 2025)

**Issue**: Creating reminders with word numbers like "in one hour" or "in thirty minutes" failed with error: `Could not parse time from: one hour`

**Root Cause**:
- The time parser regex only matched numeric digits (`\d+`)
- Word numbers like "one", "two", "thirty" weren't converted to numeric values
- User saying "remind me in one hour" would fail

**Fix**:
Added `normalize_time_words()` function to convert word numbers to digits before parsing:

```python
def normalize_time_words(text: str) -> str:
    """Convert word numbers in time expressions to digits.

    Examples:
    - "in one hour" -> "in 1 hour"
    - "in thirty minutes" -> "in 30 minutes"
    - "in two days" -> "in 2 days"
    """
```

**Supported Word Numbers**:
- one, two, three... twenty
- thirty, forty, fifty, sixty
- a, an (converted to 1)

**Files Changed**:
- `~/jarvis-voice/skills/create_reminder.py` (added `word_to_number()` and `normalize_time_words()` functions)
- `~/jarvis-voice/skills/create_reminder.tool.json` (updated description to mention recurring reminders)

**Result**:
- ✅ "Remind me in one hour" now works
- ✅ "Remind me in thirty minutes" now works
- ✅ "Remind me in two days" now works
- ✅ "Remind me in a minute" and "in an hour" work
- ✅ All word number time expressions (1-60) supported

**Testing**:
```bash
# Via voice
"Hey Jarvis, remind me in one hour to check the truck title"

# Via tool
echo '{"title": "test", "when": "in thirty minutes"}' | python3 skills/create_reminder.py
```

---

## ✅ Database Sync Not Running on Startup (Nov 18, 2025)

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
- `~/jarvis-voice/bin/jarvis-api` (added lines 62-77)
- `~/jarvis-voice/bin/jarvis-services` (added lines 161-176)

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
docker compose down
docker compose build --no-cache
docker compose up -d

# Clear stuck alerts
curl -X POST http://localhost:8880/api/alerts/acknowledge-all
```

See [REMOTE_MONITORING.md](../../api/REMOTE_MONITORING.md) for current deployment guidance.

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
docker compose down
docker compose build --no-cache
docker compose up -d
```

See [REMOTE_MONITORING.md](../../api/REMOTE_MONITORING.md) for current monitoring-agent guidance.

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
docker compose down
docker compose build --no-cache
docker compose up -d
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

- **[Remote Monitoring Guide](../../api/REMOTE_MONITORING.md)** - Setup guide
