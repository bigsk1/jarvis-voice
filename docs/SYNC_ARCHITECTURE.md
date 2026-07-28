# Sync Architecture

## Overview

Jarvis uses a **three-tier sync system** to maintain consistency across cloud and local modes:

1. **Memory Sync** (`sync-memory-db.py`) - Syncs memories between databases
2. **Tool Sync** (`sync-tools.py`) - Syncs tool definitions for Tool RAG
3. **Health Check** (`check-embeddings-health.py`) - Validates embedding dimensions

This document explains how these systems work together and when they run.


![cloud-vs-local-sync](images/sync-info-graph.jpeg)

---

## 1. Memory Database Sync (`sync-memory-db.py`)

### Purpose
Synchronizes **memories** (`knowledge_base`), **conversations**, and the structured **`user_model`** between cloud and local databases, while **regenerating memory embeddings** to match the target mode's embedding model.

### What it Syncs
- ✅ Knowledge base entries (memories from `remember` and `ingest_intel`)
- ✅ Conversations (recent 100 exchanges)
- ✅ User model traits (compact behavioral profile, no embeddings)
- ✅ Alerts (proactive system notifications)
- ✅ Reminders
- ❌ Scheduled tasks and run history (owned by the mode that created them)
- ❌ Tool definitions (synced separately by `sync-tools.py`)

Scheduled tasks stay mode-local because cloud and local modes can expose
different providers, tools, credentials, and workflows. Switching modes does not
copy, merge, or replay the other mode's schedules.

### Key Feature: Embedding Regeneration

**Critical**: When syncing memories between modes, embeddings are **regenerated** because:
- Cloud mode uses OpenAI embeddings (1536 dimensions)
- Local mode uses Nomic embeddings (768 dimensions)
- **Copying embeddings directly would break semantic search**

**How it works:**
```python
# For each memory being synced:
text = f"{key}: {value}"
embedding = get_embedding(text)  # Uses target mode's embedding model
embedding_blob = json.dumps(embedding).encode('utf-8')

# Insert/update with new embedding
cursor.execute("INSERT OR REPLACE INTO knowledge_base (..., embedding) VALUES (..., ?)",
               (..., embedding_blob))
```

### When it Runs

**Automatically:**
- On `jarvis-services` startup
- On `jarvis-api` startup

**Direction:**
- Cloud mode: Syncs `local → cloud` (if local DB exists)
- Local mode: Syncs `cloud → local` (if cloud DB exists)

**Manually:**
```bash
# Sync cloud to local
./bin/sync-memory-db.py --from cloud --to local

# Sync local to cloud
./bin/sync-memory-db.py --from local --to cloud
```

### Use Cases

1. **After ingesting intel in one mode**: Sync to other mode
   ```bash
   # Ingested intel in local mode, sync to cloud
   ./bin/sync-memory-db.py --from local --to cloud
   ```

2. **After manual database changes**: Propagate updates
   ```bash
   # Updated memories in cloud DB, sync to local
   ./bin/sync-memory-db.py --from cloud --to local
   ```

3. **Fresh database setup**: Populate from existing DB
   ```bash
   # New local DB, populate from cloud
   ./bin/sync-memory-db.py --from cloud --to local
   ```

### Fresh-Install Behavior

`sync-memory-db.py` now doubles as a repair step for newly recreated local databases:
- Creates missing target tables for `conversations`, `alerts`, and `reminders`
- Backfills missing `conversations.metadata` on target DBs created from older schemas
- Reads conversation metadata from the source DB when present, or safely substitutes `NULL` for older source databases

The scheduled-task manager creates its own mode-local task and run tables when
that mode starts.

This means a clean local rebuild can usually be repopulated with:

```bash
./bin/sync-memory-db.py --from cloud --to local
```

---

## 2. Tool Definition Sync (`sync-tools.py`)

### Purpose
Populates the `tool_definitions` table with all available tool schemas and their embeddings, enabling **Tool RAG** (dynamic tool retrieval).

### What it Syncs
- ✅ Tool names, descriptions, and JSON schemas (OpenAI function format)
- ✅ Tool embeddings (for semantic search)
- ✅ Enabled/disabled status in the DB (`enabled=0` for tools no longer in the registry)
- ✅ MCP tool definitions (dynamically discovered)
- ❌ Manifest `availability` metadata (evaluated at registry load only; not stored in `schema_json` or embeddings)

### Credential-aware filtering (before sync)

`ToolRegistry` evaluates each manifest's optional `availability` block against the
active mode **before** tools enter the sync loop. Manifest `enabled` and the
active `JARVIS_TOOL_PROFILE` overlay are applied first; profile values win over
manifest defaults. Tools with missing env keys, config files, or webhook
registry entries are listed as unavailable and their existing DB rows are
disabled by the stale-tools pass — they are not embedded or upserted on that
run.

Adding the missing configuration and re-running sync re-enables them without
manifest edits. This is separate from `embedding_input_hash`: availability-only
manifest changes do not change the hash (name + description + parameter schema
only). See `docs/TOOL_MANAGEMENT.md` → **Enabled vs available**.

### Why This is Separate from Memory Sync

Tool definitions are **mode-specific** metadata, not user data:
- Tools available in cloud mode may differ from local mode
- Tool descriptions are fixed (don't change based on user activity)
- Tool embeddings need regenerating when tools are added/modified

**Memory sync** is about user data (memories, conversations).
**Tool sync** is about system capabilities (available tools).

The resulting `tool_definitions` table is the semantic ranking index, not the
runtime capability authority. Routing, Intelligence insight filtering, and
workflow admission intersect ranking results with
`ToolRegistry.list_tools()` and request exclusions. A stale enabled DB row
cannot resurrect a manifest-disabled, profile-disabled, unavailable, or
Web/request-blocked tool.

### How it Works

1. **Discovery**: Scans `skills/*.tool.json` and MCP servers
2. **Embedding**: Generates embedding for each tool's description
3. **Storage**: Upserts to `tool_definitions` table
4. **Cleanup**: Removes tools no longer present

```python
# For each tool:
text = f"Tool {name}: {description}"
embedding = get_embedding(text)  # Uses current mode's embedding model

db.upsert_tool(
    name=name,
    description=description,
    schema_json=json.dumps(schema),
    enabled=tool.enabled
)
```

### When it Runs

**Automatically:**
- On `jarvis-services` startup
- On `jarvis-api` startup
- After memory sync (in startup flow)

**Manually:**
```bash
# Sync tools for cloud mode
./bin/sync-tools.py cloud

# Sync tools for local mode
./bin/sync-tools.py local
```

### Use Cases

1. **After adding a new tool**: Make it discoverable
   ```bash
   # Created new skills/my_tool.py and my_tool.tool.json
   ./bin/sync-tools.py cloud
   ```

2. **After modifying tool description**: Update embeddings
   ```bash
   # Changed crypto_price.tool.json description
   ./bin/sync-tools.py cloud
   ```

3. **After adding MCP server**: Register new MCP tools
   ```bash
   # Added new MCP server to config
   ./bin/sync-tools.py local
   ```

4. **After fresh database creation**: Populate tool table
   ```bash
   # Created new database
   ./bin/sync-tools.py cloud
   ```

### Implemented: content-hash skip

**Behavior:** `MemoryDB.upsert_tool()` stores **`embedding_input_hash`** (SHA-256 of name, description, schema JSON, and enabled flag). On each sync, if the row already has a non-null embedding and the hash matches, the embedding step is **skipped** (no API / local embed call). New tools, missing embeddings, missing hash, or hash mismatch still embed as before.

**Schema:** `tool_definitions.embedding_input_hash` is created on **new databases** (`MemoryDB._init_db`) and added to existing files via **`_ensure_column`** on open—same pattern as other additive migrations. Fresh clones that create the DB through `MemoryDB` (including `./bin/setup-memory-db.sh` for an empty file, `sync-tools.py`, and first service startup) get the column automatically.

| Piece | Implementation |
|--------|----------------|
| **Fingerprint** | `_tool_definition_content_hash()` — UTF-8 payload with null separators so fields cannot alias. |
| **Storage** | Column `embedding_input_hash TEXT` on `tool_definitions`. |
| **Skip path** | If `embedding IS NOT NULL`, stored hash equals computed hash, and `force_reembed` is false → skip `get_embedding()` and reuse stored blob. |
| **Always embed** | New row, null embedding, null/mismatched hash, or **`./bin/sync-tools.py cloud|local --force`** (`force_reembed=True`). |
| **Provider failure** | Storage rejects hash fallback vectors. A changed tool retries (`PERSISTENT_EMBEDDING_MAX_ATTEMPTS`, default `3`), then exits with status `4` without replacing the previous row or advancing `embedding_input_hash`. |

**Manual workflow unchanged:** Run `./bin/sync-tools.py cloud|local` after changing tools; use **`--force`** when you need a full re-embed (e.g. after switching embedding model/dimensions or debugging). Startup sync in `jarvis-services` / `jarvis-api` benefits from fewer redundant embedding calls when nothing changed. Native startup logs failed sync details to `logs/tool-sync-<mode>.log` and continues with the last good index. Docker withholds its completed-sync marker and retries on the next container start.

Each completed sync attempt also writes an atomic, per-mode status file under
`data/.tool_sync_status_<mode>.json`. Jarvis Web displays a persistent warning
for a recorded failed attempt and tells the operator whether a previous usable
index remains. The warning is dismissed per failure event, so a later failure
appears again. A successful startup sync or manual
`./bin/sync-tools.py <mode>` run records success and clears the warning on the
next Web status poll.

The status file is a health marker only. It records outcome/count information,
not an authoritative list of enabled tools. In particular, workflow
availability must check the live effective registry and complete component-tool
set rather than infer eligibility from `.tool_sync_status_<mode>.json`.

The browser does not infer sync health from its WebSocket connection. A server
disconnect, failed `/api/status` request, missing status file, or malformed
status file cannot create a Tool RAG warning; only a valid persisted failed
sync record can do so.

**Benefit skew:** **Cloud** embeddings save the most in cost and latency; **local** mode saves mainly time on large tool sets.

**Out of scope:** Tool RAG retrieval logic and merging tool sync with memory sync are unchanged.

---

## 3. Embedding Health Check (`check-embeddings-health.py`)

### Purpose
Validates that embeddings in the database match the expected dimensions for the current mode, preventing **silent semantic search failures**.

### What it Checks
- ✅ Knowledge base embedding dimensions
- ✅ Tool definition embedding dimensions
- ✅ Current config generates correct dimensions
- ✅ Embedding provider matches expected model

### Why This is Necessary

**The Problem:**
- Cloud mode expects 1536-dim embeddings (OpenAI)
- Local mode expects 768-dim embeddings (Nomic)
- If dimensions mismatch, cosine similarity breaks → 0 results

**Silent failures occur when:**
- Config changed but embeddings not regenerated
- Manual database copy without sync
- Wrong embedding model used during ingestion
- Sync script failed silently

### How it Works

1. **Determine expected dimensions** based on mode
2. **Sample embeddings** from database (100 memories, 50 tools)
3. **Deserialize and check dimensions** of each embedding
4. **Test current config** by generating a test embedding
5. **Report mismatches** with remediation steps

### When it Runs

**Automatically:**
- On `jarvis-services` startup (after memory + tool sync)
- On `jarvis-api` startup (after memory + tool sync)
- **Non-blocking**: Service starts even if check fails (with warnings)

**Manually:**
```bash
# Check single mode
./bin/check-embeddings-health.py cloud
./bin/check-embeddings-health.py local

# Check both modes
./bin/check-embeddings-health.py --both

# JSON output (for scripts)
./bin/check-embeddings-health.py local --json
```

### Use Cases

1. **After config changes**: Verify embeddings still match
   ```bash
   # Changed LLM_PROVIDER in config
   ./bin/check-embeddings-health.py local
   ```

2. **Debugging semantic search**: Check if dimension mismatch
   ```bash
   # semantic_recall returns 0 results
   ./bin/check-embeddings-health.py local
   ```

3. **After manual database operations**: Ensure consistency
   ```bash
   # Manually edited database
   ./bin/check-embeddings-health.py --both
   ```

4. **Production monitoring**: Daily validation
   ```bash
   # Cron job
   0 2 * * * /path/to/check-embeddings-health.py --both --json | logger
   ```

---

## Startup Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  jarvis-services (cloud/local) OR jarvis-api (cloud/local)  │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │  1. MEMORY DATABASE SYNC     │
              │  sync-memory-db.py           │
              │                              │
              │  • Syncs memories            │
              │  • Syncs conversations       │
              │  • REGENERATES embeddings    │
              │  • Direction: cloud↔local    │
              └──────────────┬───────────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │  2. TOOL DEFINITION SYNC     │
              │  sync-tools.py               │
              │                              │
              │  • Discovers tools           │
              │  • Generates embeddings      │
              │  • Populates tool_definitions│
              └──────────────┬───────────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │  3. EMBEDDING HEALTH CHECK   │
              │  check-embeddings-health.py  │
              │                              │
              │  • Validates dimensions      │
              │  • Tests 100 memories        │
              │  • Tests 50 tools            │
              │  • Shows warnings if fail    │
              └──────────────┬───────────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │  4. START SERVICES/API       │
              │                              │
              │  • Follow-up daemon          │
              │  • Reminder scheduler        │
              │  • OR API server             │
              └──────────────────────────────┘
```

---

## Expected Dimensions by Mode

| Mode | Provider | Embedding Model | Dimensions | Database File |
|------|----------|----------------|------------|---------------|
| **Cloud** | OpenAI | `text-embedding-3-small` | **1536** | `jarvis_memory.db` |
| **Local** | Ollama | `nomic-embed-text` | **768** | `jarvis_memory_local.db` |

---

## Common Scenarios

### Scenario 1: Fresh Setup (No Database)

**First run:**
```bash
./jarvis  # or ./jarvis-local
```

**What happens:**
1. Memory sync: Skipped (no source DB)
2. Tool sync: Creates `tool_definitions` table, populates tools
3. Health check: ✅ Pass (no embeddings to check yet)
4. Service starts

**After ingesting intel:**
```bash
# Embeddings generated with correct model for current mode
./skills/ingest_intel.py '{"path":"jarvis-intel"}'

# Health check confirms dimensions
./bin/check-embeddings-health.py local
```

### Scenario 2: Switch from Cloud to Local

**Workflow:**
```bash
# 1. Currently using cloud mode, has data
./jarvis

# 2. Switch to local mode
./jarvis-local

# What happens automatically:
# - Memory sync: cloud → local (regenerates 1536→768 dims)
# - Tool sync: local (generates 768-dim tool embeddings)
# - Health check: ✅ Pass (all 768-dim)
```

### Scenario 3: Manual Database Copy (WRONG)

**⚠️ Don't do this:**
```bash
# WRONG: Direct copy without regenerating embeddings
cp data/jarvis_memory.db data/jarvis_memory_local.db
./jarvis-local
```

**What goes wrong:**
- Embeddings are 1536-dim (from cloud)
- Local mode expects 768-dim (from Nomic)
- Health check: ❌ Fail
- Semantic search: 0 results

**✅ Correct approach:**
```bash
# Sync with embedding regeneration
./bin/sync-memory-db.py --from cloud --to local
./jarvis-local
```

### Scenario 4: Test Script Database Reset

**Test scripts should:**
```bash
#!/bin/bash
# 1. Reset database
rm -f data/jarvis_memory_local.db

# 2. Initialize (creates tables)
./orchestrator/orchestrator_v2.py local "test query"

# 3. Sync tools (populates tool embeddings)
./bin/sync-tools.py local

# 4. Health check (validate)
./bin/check-embeddings-health.py local || exit 1

# 5. Run tests
...
```

See: `docs/TESTING.md` for updated test patterns.

### Scenario 5: Production Monitoring

**Daily health check:**
```bash
# Crontab entry
0 2 * * * cd ~/jarvis-voice && ./bin/check-embeddings-health.py --both --json | logger -t jarvis-embeddings
```

**API health endpoint:**
```bash
curl http://localhost:8880/api/health
# Returns API status/version/mode (not embedding coverage)
# For embedding health, use ./bin/check-embeddings-health.py above
```

---

## Troubleshooting

### Q: Sync scripts run, but health check fails?

**A**: Check if sync completed successfully. Look for errors in output:
```bash
# Verbose sync
./bin/sync-memory-db.py --from cloud --to local

# Should show:
# ✅ Sync Complete!
#    Synced: X
#    Errors: 0
```

If errors occurred, memories may have wrong embeddings.

### Q: Health check passes, but semantic search still fails?

**A**:
1. Check if search query is too specific (adjust `SEMANTIC_SIMILARITY_THRESHOLD`)
2. Verify memories actually exist: `sqlite3 data/jarvis_memory_local.db "SELECT COUNT(*) FROM knowledge_base"`
3. Check if embeddings exist: `SELECT COUNT(*) FROM knowledge_base WHERE embedding IS NOT NULL`

### Q: Can I skip health checks for faster startup?

**A**: Not recommended. Health checks are fast (< 1 second) and prevent hours of debugging later. But if needed:
```bash
# Comment out health check in bin/jarvis-services or bin/jarvis-api
```

### Q: How often should I manually sync?

**A**: **Only when needed:**
- After ingesting intel in one mode
- After manual database modifications
- After config changes affecting embeddings
- When switching modes (automatic)

Routine startup syncs handle everything else.

---

## Performance Considerations

### Sync Speed

| Operation | Typical Time | Notes |
|-----------|-------------|-------|
| Memory sync (100 entries) | 5-10 sec | Embedding generation is slow |
| Tool sync (32 tools) | 2-3 sec | One-time per startup |
| Health check | < 1 sec | Fast sampling |

### Optimization Tips

1. **Sync on startup only**: Don't sync on every query
2. **Batch ingestion**: Ingest multiple files at once, sync once
3. **Parallel startup**: Services and API can start simultaneously
4. **Cache embeddings**: Already done (stored in DB)

---

## Related Documentation

- `docs/EMBEDDING_HEALTH_CHECKS.md` - Detailed health check guide
- `docs/DUAL_DATABASE_SYSTEM.md` - Why we have separate databases
- `docs/TOOL_RAG_STRATEGY.md` - How tool sync enables Tool RAG
- `docs/TESTING.md` - Test script patterns with sync

---

## 4. Intelligence Database Sync (`sync-intelligence-db.py`)

### Purpose
Synchronizes the **intelligence layer** (self-learning system) between cloud and local modes, including experiences, insights, insight evidence, and pending reflections.

### What it Syncs
- ✅ **Experiences** - Raw interaction data (queries, tools used, outcomes)
- ✅ **Insights** - Learned patterns (positive/negative constraints, tool preferences, and specific `preferred_workflow_id` associations)
- ✅ **Insight Evidence** - Audit trail linking insights back to source experiences/web conversations, including the workflow identity that earned a preference
- ✅ **Reflection Queue** - Pending reflections awaiting processing
- ✅ Regenerates all embeddings for target mode dimensions
- ❌ **Meta Knowledge** - Deliberately not copied. Each cloud/local Intelligence database keeps its own maintenance history and meta-cognition findings.

### Important Behavior

- **Default sync is additive merge**: source rows are copied only when they are missing in the target DB. Target-only learning is preserved, so running local for a while and later syncing cloud → local will not delete local-only insights or experiences.
- **Use `--replace` for the old full-mirror behavior** when you intentionally want the target DB to match the source DB and discard target-only intelligence rows.
- **Insight timestamps are preserved** during sync:
  - `created_at`
  - `updated_at`
  - `last_applied`
- **Only pending reflection queue rows are synced**. Processed queue history is not copied across modes.
- **`meta_knowledge` stays separate for each database**. It records facts about that specific database, including when its decay job last ran, blind spots derived from its recent experiences, and learning-quality findings. Copying those rows could make one database skip maintenance because maintenance ran only against the other database. After learning data is synced, each database can derive its own current findings.
- **Ollama embedding requests now use context-aware safeguards**:
  - `OLLAMA_EMBEDDING_CONTEXT_WINDOW` when set
  - otherwise `OLLAMA_CONTEXT_WINDOW`
  - automatic compact-and-retry for oversized raw text before fallback embeddings are used

### Why Intelligence Syncs
Unlike provider-specific configurations, **learned insights are universal**:
- "Use `crypto_price` for price queries" applies to ANY LLM
- "Don't use `search_memory` for server status" helps ALL providers
- Only the vector embeddings need regeneration for dimension compatibility

### How it Works

```python
# For each experience/insight being synced:
# 1. Copy text content (query, description, pattern)
# 2. Regenerate embeddings with target mode's model
query_embedding = get_embedding(query)  # 1536-dim (cloud) or 768-dim (local)
# 3. Reuse matching target rows or insert missing rows with new IDs
# 4. Remap insight_evidence rows to target insight/experience IDs
# 5. Remap pending reflection_queue rows to target experience IDs
```

### When to Run

**Manually** (not automatic like memory/tool sync):
```bash
# Sync from cloud → local (after using cloud mode)
./bin/sync-intelligence-db.py local

# Sync from local → cloud (after using local mode)
./bin/sync-intelligence-db.py cloud

# Preview what would sync
./bin/sync-intelligence-db.py --dry-run local

# Replace target with source mirror, discarding target-only intelligence rows
./bin/sync-intelligence-db.py --replace local

# Reset (delete) intelligence DB
./bin/sync-intelligence-db.py --reset local
```

---

## 5. Prompt Evolution Sync (`sync-evolution-db.py`)

### Purpose
Synchronizes active `prompt_versions` between cloud and local memory databases so prompt-evolution improvements can move between environments.

### What it Syncs
- ✅ Active prompt versions from `prompt_versions`
- ✅ Optional tool-description file refresh via `--update-files`
- ❌ Does not regenerate tool embeddings by itself; run `sync-tools.py` after updating tool files when needed

### Fresh-Install Behavior

`sync-evolution-db.py` now supports newly recreated target databases:
- Creates `prompt_versions`, `prompt_evolution_log`, and `prompt_backups` on the target if missing
- Exits cleanly with a warning if the source DB has not been initialized with `prompt_versions` yet

### When to Run

```bash
# Sync from cloud → local
./bin/sync-evolution-db.py local

# Preview before applying changes
./bin/sync-evolution-db.py local --dry-run

# Sync and refresh local tool description files
./bin/sync-evolution-db.py local --update-files
```

### Use Cases

1. **After extended cloud session**: Sync learnings to local
   ```bash
   # Used cloud mode for a week, want local to benefit
   ./bin/sync-intelligence-db.py local
   ```

2. **Before switching modes**: Ensure continuity
   ```bash
   # About to switch from local to cloud
   ./bin/sync-intelligence-db.py cloud
   ./jarvis  # Start cloud mode with all learnings
   ```

3. **Fresh local setup**: Populate from cloud learnings
   ```bash
   # New local environment, populate from cloud
   ./bin/sync-intelligence-db.py local
   ```

4. **After reflection processing**: Share new insights
   ```bash
   # Processed reflections in cloud, share with local
   ./bin/sync-intelligence-db.py local
   ```

### Database Files

| Mode | Database | Embedding Dimensions |
|------|----------|---------------------|
| Cloud | `data/jarvis_intelligence.db` | 1536 (OpenAI) |
| Local | `data/jarvis_intelligence_local.db` | 768 (Nomic) |

### Health Check Integration

Use `check-intelligence-health.py` to validate:
```bash
./bin/check-intelligence-health.py cloud
./bin/check-intelligence-health.py local
```

---

## Complete Startup Flow (Updated)

```
┌─────────────────────────────────────────────────────────────┐
│  jarvis-services (cloud/local) OR jarvis-api (cloud/local)  │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
              ┌──────────────────────────────────┐
              │  1. MEMORY DATABASE SYNC         │
              │  sync-memory-db.py               │
              │                                  │
              │  • Syncs memories                │
              │  • Syncs conversations           │
              │  • REGENERATES embeddings        │
              │  • Direction: cloud↔local        │
              └──────────────┬───────────────────┘
                             │
                             ▼
              ┌──────────────────────────────────┐
              │  2. TOOL DEFINITION SYNC         │
              │  sync-tools.py                   │
              │                                  │
              │  • Discovers tools               │
              │  • Generates embeddings          │
              │  • Populates tool_definitions    │
              └──────────────┬───────────────────┘
                             │
                             ▼
              ┌──────────────────────────────────┐
              │  3. EMBEDDING HEALTH CHECK       │
              │  check-embeddings-health.py      │
              │                                  │
              │  • Validates dimensions          │
              │  • Tests 100 memories            │
              │  • Tests 50 tools                │
              │  • Shows warnings if fail        │
              └──────────────┬───────────────────┘
                             │
                             ▼
              ┌──────────────────────────────────┐
              │  4. INTELLIGENCE LAYER INIT      │
              │  (automatic on first use)        │
              │                                  │
              │  • Creates intelligence.db       │
              │  • Loads existing insights       │
              │  • Injects into routing          │
              └──────────────┬───────────────────┘
                             │
                             ▼
              ┌──────────────────────────────────┐
              │  5. START SERVICES/API           │
              │                                  │
              │  • Follow-up daemon              │
              │  • Reminder scheduler            │
              │  • OR API server                 │
              └──────────────────────────────────┘

Note: Intelligence sync is MANUAL (run when switching modes)
      Memory/Tool sync is AUTOMATIC (runs on startup)
```

---

## Sync Scripts Summary

| Script | Syncs | Auto on Startup? | Regenerates Embeddings? |
|--------|-------|------------------|------------------------|
| `sync-memory-db.py` | Memories, conversations | ✅ Yes | ✅ Yes |
| `sync-tools.py` | Tool definitions | ✅ Yes | ✅ Yes |
| `sync-intelligence-db.py` | Experiences, insights, queue | ❌ Manual | ✅ Yes |
| `check-embeddings-health.py` | N/A (validation only) | ✅ Yes | N/A |
| `check-intelligence-health.py` | N/A (validation only) | ❌ Manual | N/A |

---

## Related Documentation

- `docs/EMBEDDING_HEALTH_CHECKS.md` - Detailed health check guide
- `docs/DUAL_DATABASE_SYSTEM.md` - Why we have separate databases
- `docs/TOOL_RAG_STRATEGY.md` - How tool sync enables Tool RAG
- `docs/INTELLIGENCE_LAYER.md` - Self-learning system details
- `docs/TESTING.md` - Test script patterns with sync

---

**Summary**: Four-tier sync system ensures cloud and local modes stay consistent:
1. **Memory sync** - User data (memories, conversations)
2. **Tool sync** - System capabilities (available tools)
3. **Health check** - Validation (embedding dimensions)
4. **Intelligence sync** - Learned patterns (manual, when switching modes)
