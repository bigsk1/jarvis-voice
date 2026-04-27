# Dual Database System for Cloud and Local Modes

## Overview

Jarvis uses separate memory databases for cloud and local modes, each optimized for its embedding model:

```
data/jarvis_memory.db        → Cloud mode (OpenAI embeddings, 1536 dims)
data/jarvis_memory_local.db  → Local mode (nomic-embed-text, 768 dims)
```

## Why Separate Databases?

**Problem**: Embedding models create vectors in different "spaces"
- OpenAI `text-embedding-3-small`: 1536 dimensions
- Ollama `nomic-embed-text`: 768 dimensions
- **Can't search one model's embeddings with another!**

**Solution**: Each mode has its own database with appropriate embeddings

## Auto-Sync System

### How It Works

**At Startup** (`orchestrator_v2.py`):
1. Detects current mode (cloud or local)
2. Checks if other mode's DB has newer data
3. Auto-syncs if needed (one-way: other → current)
4. Regenerates embeddings for current mode's model

### Sync Direction

```
Starting CLOUD mode:
  If local DB is newer → Sync local → cloud (with OpenAI embeddings)

Starting LOCAL mode:
  If cloud DB is newer → Sync cloud → local (with nomic embeddings)
```

### Manual Sync

```bash
# Sync cloud to local
./bin/sync-memory-db.py --from cloud --to local

# Sync local to cloud
./bin/sync-memory-db.py --from local --to cloud
```

## What Gets Synced

### ✅ Always Synced

- **knowledge_base** table (all memories)
  - Keys, values, categories, importance
  - Timestamps (created_at, updated_at)
  - **Embeddings regenerated** for target mode
- **conversations** table (last 100)
  - User queries and responses
  - Tools used, session IDs
  - No embeddings (plain text)

### ❌ Not synced by `sync-memory-db.py`

- **`tool_definitions`** (Tool RAG) lives in the same SQLite files (`jarvis_memory.db` / `jarvis_memory_local.db`) but **is not copied** between cloud and local by `./bin/sync-memory-db.py`. Each mode’s DB keeps its own tool rows and embeddings (1536-dim vs 768-dim). After changing tools, run **`./bin/sync-tools.py cloud`** and/or **`./bin/sync-tools.py local`** as needed. Unchanged tools skip re-embedding when `embedding_input_hash` matches (see `docs/SYNC_ARCHITECTURE.md`); use **`--force`** on that script to re-embed everything.

### 🔄 Sync Behavior

- **New memories**: Inserted into target DB
- **Updated memories**: Updated if source is newer
- **Deleted memories**: Not removed from target (manual)
- **Conflicts**: Source wins (last-write wins)

## Tool Compatibility

All memory tools work seamlessly:

### Write Tools (Auto-Sync Next Startup)
- `remember` → Saves to current mode's DB
- `update_memory` → Updates current mode's DB
- `forget` → Deletes from current mode's DB
- `ingest_intel` → Ingests to current mode's DB

### Read Tools (Always Current)
- `recall` / `search_memory` → SQL fuzzy search (no embeddings)
- `semantic_recall` → Uses current mode's embeddings
- `search_conversations` → Text search (no embeddings)
- `get_recent_conversations` → Direct query (no embeddings)

## Database Schema

Both databases have identical schema:

```sql
CREATE TABLE knowledge_base (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    importance INTEGER DEFAULT 5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source TEXT,
    metadata TEXT,
    embedding BLOB  -- Format: JSON (not pickle)
);

CREATE TABLE conversations (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_query TEXT,
    jarvis_response TEXT,
    tools_used TEXT,
    session_id TEXT,
    success BOOLEAN DEFAULT 1
);
```

## Embedding Format

**New Format** (JSON, both modes):
```python
embedding_blob = json.dumps(embedding).encode('utf-8')
```

**Legacy Format** (Pickle, supported for backward compatibility):
```python
embedding_blob = pickle.dumps(embedding)
```

The `semantic_search` function auto-detects format.

## Example Workflow

### Scenario 1: Use Cloud, Then Local

```bash
# 1. Use cloud mode
./orchestrator/orchestrator_v2.py cloud "Remember my server is at 192.168.1.100"
# Saved to: data/jarvis_memory.db (with OpenAI embedding)

# 2. Switch to local mode
./orchestrator/orchestrator_v2.py local "What's my server IP?"
# Auto-sync: cloud → local (regenerates with nomic embedding)
# Result: Finds server IP ✅
```

### Scenario 2: Use Local, Then Cloud

```bash
# 1. Use local mode
./orchestrator/orchestrator_v2.py local "Remember my API key is abc123"
# Saved to: data/jarvis_memory_local.db (with nomic embedding)

# 2. Switch to cloud mode
./orchestrator/orchestrator_v2.py cloud "What's my API key?"
# Auto-sync: local → cloud (regenerates with OpenAI embedding)
# Result: Finds API key ✅
```

### Scenario 3: Both Modes Active

```bash
# 1. Cloud adds memory
./orchestrator/orchestrator_v2.py cloud "Remember: production port is 8443"

# 2. Local mode syncs on next startup
./orchestrator/orchestrator_v2.py local "What port is production on?"
# Auto-sync runs (cloud → local)
# Result: Finds 8443 ✅

# 3. Local adds memory
./orchestrator/orchestrator_v2.py local "Remember: dev port is 3000"

# 4. Cloud mode syncs on next startup
./orchestrator/orchestrator_v2.py cloud "What port is dev on?"
# Auto-sync runs (local → cloud)
# Result: Finds 3000 ✅
```

## Performance

### Sync Speed

- **First sync**: ~30 seconds (15 memories with embedding generation)
- **Subsequent syncs**: ~5 seconds (only changed memories)
- **No sync needed**: ~0.1 seconds (just timestamp check)

### Disk Usage

```
Cloud DB:  ~500 KB (15 memories + OpenAI embeddings)
Local DB:  ~400 KB (15 memories + nomic embeddings)
Total:     ~900 KB (both databases)
```

Small cost for full compatibility!

## Troubleshooting

### Sync Not Working

```bash
# Check DB timestamps
ls -lh data/*.db

# Force manual sync
./bin/sync-memory-db.py --from cloud --to local

# Check for errors
./bin/sync-memory-db.py --from cloud --to local --verbose
```

### Embeddings Incompatible

```bash
# Regenerate all embeddings for current mode
rm data/jarvis_memory_local.db
./orchestrator/orchestrator_v2.py local "test"
# Auto-sync will recreate with correct embeddings
```

### Missing Memories

```bash
# Check which DB is newer
stat data/jarvis_memory.db
stat data/jarvis_memory_local.db

# Sync manually if needed
./bin/sync-memory-db.py --from <newer> --to <older>
```

## Configuration

### Cloud Mode (config/cloud.env)

```bash
LLM_PROVIDER="anthropic"
# Chat LLM is separate from embeddings: non-Ollama providers use OpenAI for vectors
# (see lib/embeddings.py — only LLM_PROVIDER=ollama uses Ollama embeddings)
```

`./bin/check-embeddings-health.py` reports **Embedding Provider** as the effective vector backend (`openai` vs `ollama`), not the chat brand (e.g. xAI). If they differ, it prints **LLM Provider (chat)** on a second line.

### Local Mode (config/local.env)

```bash
LLM_PROVIDER="ollama"
OLLAMA_EMBEDDING_MODEL="nomic-embed-text"
OLLAMA_BASE_URL="http://localhost:11434"
```

### Semantic Search Threshold

```bash
# Both modes (default: 0.40)
SEMANTIC_SIMILARITY_THRESHOLD=0.40

# Can be different per mode:
# cloud.env: 0.40 (OpenAI embeddings are higher quality)
# local.env: 0.35 (nomic embeddings slightly more lenient)
```

## Benefits

✅ **No conflicts**: Each mode uses its own embedding space
✅ **Auto-sync**: Always have latest data
✅ **Transparent**: Tools work same in both modes
✅ **Bidirectional**: Changes sync both ways
✅ **Fast**: Only syncs when needed
✅ **Reliable**: Falls back to keyword search if embeddings fail

## See also

- `docs/EMBEDDING_HEALTH_CHECKS.md` — dimensions, health script output (embedding vs chat LLM), and `sync-tools.py --force` when re-embedding everything.
- `docs/SYNC_ARCHITECTURE.md` — memory sync vs tool sync, `embedding_input_hash` behavior.

## Summary

The dual-database system ensures:
1. **Cloud mode** works with high-quality OpenAI embeddings
2. **Local mode** works with fast offline nomic embeddings
3. **Both modes** stay in sync automatically
4. **No user intervention** needed - just use either mode!

---

**Key Insight**: Different embedding models = different vector spaces
**Solution**: Separate databases, auto-sync, regenerate embeddings
**Result**: Seamless experience in both cloud and local modes! 🎯
