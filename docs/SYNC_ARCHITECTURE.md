# Sync Architecture

## Overview

Jarvis uses a **three-tier sync system** to maintain consistency across cloud and local modes:

1. **Memory Sync** (`sync-memory-db.py`) - Syncs memories between databases
2. **Tool Sync** (`sync_tools.py`) - Syncs tool definitions for Tool RAG
3. **Health Check** (`check-embeddings-health.py`) - Validates embedding dimensions

This document explains how these systems work together and when they run.

---

## 1. Memory Database Sync (`sync-memory-db.py`)

### Purpose
Synchronizes **memories** (knowledge_base) and **conversations** between cloud and local databases, while **regenerating embeddings** to match the target mode's embedding model.

### What it Syncs
- ✅ Knowledge base entries (memories from `remember` and `ingest_intel`)
- ✅ Conversations (recent 100 exchanges)
- ✅ Alerts (proactive system notifications)
- ❌ Tool definitions (synced separately by `sync_tools.py`)

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

---

## 2. Tool Definition Sync (`sync_tools.py`)

### Purpose
Populates the `tool_definitions` table with all available tool schemas and their embeddings, enabling **Tool RAG** (dynamic tool retrieval).

### What it Syncs
- ✅ Tool names, descriptions, and JSON schemas
- ✅ Tool embeddings (for semantic search)
- ✅ Enabled/disabled status
- ✅ MCP tool definitions (dynamically discovered)

### Why This is Separate from Memory Sync

Tool definitions are **mode-specific** metadata, not user data:
- Tools available in cloud mode may differ from local mode
- Tool descriptions are fixed (don't change based on user activity)
- Tool embeddings need regenerating when tools are added/modified

**Memory sync** is about user data (memories, conversations).  
**Tool sync** is about system capabilities (available tools).

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
./bin/sync_tools.py cloud

# Sync tools for local mode
./bin/sync_tools.py local
```

### Use Cases

1. **After adding a new tool**: Make it discoverable
   ```bash
   # Created new skills/my_tool.py and my_tool.tool.json
   ./bin/sync_tools.py cloud
   ```

2. **After modifying tool description**: Update embeddings
   ```bash
   # Changed crypto_price.tool.json description
   ./bin/sync_tools.py cloud
   ```

3. **After adding MCP server**: Register new MCP tools
   ```bash
   # Added new MCP server to config
   ./bin/sync_tools.py local
   ```

4. **After fresh database creation**: Populate tool table
   ```bash
   # Created new database
   ./bin/sync_tools.py cloud
   ```

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
              │  sync_tools.py               │
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
./bin/sync_tools.py local

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
0 2 * * * cd /home/boss/jarvis-voice && ./bin/check-embeddings-health.py --both --json | logger -t jarvis-embeddings
```

**API health endpoint:**
```bash
curl http://localhost:8091/health
# Returns embedding health status
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

**Summary**: Three-tier sync (memory → tools → health) ensures cloud and local modes stay consistent while using their optimal embedding models.

