# Embedding Health Checks

## Overview

Jarvis uses different embedding models for cloud and local modes, which generate vectors of different dimensions:

- **Cloud Mode (OpenAI)**: 1536 dimensions (`text-embedding-3-small`)
- **Local Mode (Ollama)**: 768 dimensions (`nomic-embed-text`)

**Why this matters**: If embeddings in the database don't match the expected dimensions for the current mode, semantic search will **silently fail** (returning 0 results) because the vector similarity calculation breaks with mismatched dimensions.

## Two Different Failure Modes

There are **two separate embedding health concerns** in Jarvis:

1. **Stored embeddings in the database**
   - Memories in `knowledge_base.embedding`
   - Tool vectors in `tool_definitions.embedding`
   - Intelligence embeddings in the intelligence DB
   - These are what the health-check scripts validate

2. **Runtime query embeddings**
   - Generated fresh for each semantic search / tool search request
   - Used by:
     - `semantic_recall`
     - auto memory injection
     - Tool RAG / tool retrieval
     - parts of deep memory search and memory-update fallback
   - These are **not saved in the DB**

This distinction matters because you can have:
- **healthy stored embeddings** in the DB
- but a **temporary runtime embedding failure** on a single request

That means DB health checks can pass while one live query still degrades semantically.

## The Problem

Embedding dimension mismatches can occur when:

1. **Wrong embedding model used during ingestion**
   - Intel ingested in cloud mode but running in local mode
   - Config changed but embeddings not regenerated

2. **Database synced without regenerating embeddings**
   - Manually copying database files between modes
   - Sync script failing silently

3. **Config changes affecting embedding provider**
   - `LLM_PROVIDER` changed in `.env` file
   - Environment variable override not matched by embeddings

4. **Runtime embedding provider failures**
   - OpenAI embedding quota/credit issue
   - missing API key
   - Ollama unavailable or overloaded
   - timeout / connection failure
   - input too large for Ollama embedding context

These runtime failures do **not** corrupt stored DB embeddings, but they can make a live semantic request behave poorly for that turn.

## Runtime Fallback Behavior

When the real embedding provider fails, Jarvis falls back to a **deterministic hash-based vector**.

Properties of the fallback embedding:
- Same text → same vector
- Different text → different vector
- It preserves continuity, **not semantic meaning**
- Cosine similarity still runs, but ranking quality is degraded

This is intentionally a **continuity mechanism**, not a quality mechanism.

### What uses runtime fallback?

Potentially affected:
- `semantic_recall`
- auto memory injection
- Tool RAG / tool retrieval
- semantic parts of `deep_memory_search`
- semantic fallback inside `update_memory`

Not affected:
- `search_memory` (FTS5/BM25 only, no embeddings)

## Visibility and Logging

### Stored embeddings

Use the health-check scripts to verify DB state:

```bash
./bin/check-embeddings-health.py cloud
./bin/check-embeddings-health.py local
./bin/check-intelligence-health.py --both
```

If these are healthy, your saved vectors in the DB are likely fine.
The health probe requires a real provider embedding; a same-dimension hash
fallback is reported as provider-unavailable rather than healthy.

### Runtime fallback

Runtime fallback is now surfaced in tool results and logs for embedding-backed memory tools.

Fallback remains available for query-time retrieval so a temporary provider
outage does not block requests. Persistent writers use
`get_persistable_embedding()` instead: tracked hash fallbacks are rejected and
are never written as valid memory, Tool RAG, sync, or Intelligence vectors.

Tool log behavior:
- `fallback_embeddings: true` → runtime fallback occurred for that tool call
- `fallback_embeddings: null` → no fallback detected for that tool call

Today this appears for:
- `semantic_recall`
- `deep_memory_search` when semantic memory search is used
- `update_memory` when semantic lookup fallback is used

Important caveat:
- `search_memory` will always log `fallback_embeddings: null` because it does **not** use embeddings

### Non-tool semantic paths

Auto memory injection and Tool RAG are not tool calls, so they do not appear in `logs/tools/tool-calls-*.jsonl`.

When `TOOL_RAG_TRACE_ENABLED=true`, Tool RAG selection itself is logged separately in `logs/tool-rag/tool-rag-YYYY-MM-DD.jsonl`. Those trace rows show the compact retrieval query, `signal_source`, active similarity threshold, final tools sent to the LLM, ranked near misses, and rough schema token estimates.

When runtime fallback happens there, Jarvis now emits warning lines such as:
- `[SEMANTIC_SEARCH] Fallback embeddings used for query: ...`
- `[TOOL_SEARCH] Fallback embeddings used for query: ...`

These are process/runtime warnings, not DB corruption.

## The Solution: Automated Health Checks

### 1. Health Check Script

```bash
# Check single mode
./bin/check-embeddings-health.py cloud
./bin/check-embeddings-health.py local

# Check both modes
./bin/check-embeddings-health.py --both

# JSON output (for scripts)
./bin/check-embeddings-health.py local --json
```

**What it checks:**
- ✅ Embedding dimensions in `knowledge_base` table (memories)
- ✅ Embedding dimensions in `tool_definitions` table (Tool RAG)
- ✅ Current config generates correct dimensions for the mode
- ✅ Reports **Embedding Provider** as the effective vector backend (`openai` vs `ollama`), matching `lib/embeddings.get_embedding()` — not the chat LLM brand. If chat and embedding backends differ (e.g. xAI chat + OpenAI embeddings), a second line shows **LLM Provider (chat)**.

These checks validate **stored embeddings**, not every transient runtime query embedding.

**Example output (healthy):**
```
╔════════════════════════════════════════════════════════════╗
║  Embedding Health Check - LOCAL Mode                         ║
╚════════════════════════════════════════════════════════════╝

✅ All embeddings are healthy!

Expected Dimensions: 768
Current Config Generates: 768
Embedding Provider: ollama
Embedding Model: nomic-embed-text

(In cloud mode with a non-Ollama chat provider, **Embedding Provider** is typically `openai` and **Embedding Model** `text-embedding-3-small`. If the chat LLM differs, **LLM Provider (chat):** may appear on the next line.)

Knowledge Base:
  Checked: 64 memories
  ✓ All OK

Tool Definitions:
  Checked: 32 tools
  ✓ All OK
```

**Example output (unhealthy):**
```
╔════════════════════════════════════════════════════════════╗
║  Embedding Health Check - LOCAL Mode                         ║
╚════════════════════════════════════════════════════════════╝

❌ Embedding dimension mismatch detected!

Expected Dimensions: 768
Current Config Generates: 1536  ← WRONG!
Embedding Provider: openai
Embedding Model: text-embedding-3-small

Knowledge Base:
  Checked: 64 memories
  Issues: 64

    ✗ Memory #1 (Agent Modes info...): 1536D (expected 768D)
    ✗ Memory #2 (Servers - Mini-AI...): 1536D (expected 768D)
    ... and 62 more

🔧 Recommended Actions:
  1. Config issue: Current embedding model generates wrong dimensions
     Check config/local.env for correct LLM_PROVIDER and embedding model

  2. Memory embeddings are wrong - regenerate them:
     ./bin/sync-memory-db.py --from cloud --to local

  3. Tool embeddings are wrong - regenerate them:
     ./bin/sync-tools.py local

⚠️  Semantic search will fail until embeddings are fixed!
```

### 2. Automatic Health Checks on Startup

Both `jarvis-services` and `jarvis-api` now run automatic health checks:

```bash
./bin/jarvis-services          # Auto-checks cloud embeddings
./bin/jarvis-services --local  # Auto-checks local embeddings

./bin/jarvis-api          # Auto-checks cloud embeddings
./bin/jarvis-api --local  # Auto-checks local embeddings
```

**Startup sequence:**
1. Sync memories between modes (`sync-memory-db.py`)
2. Sync tool definitions (`sync-tools.py`)
3. **Health check embeddings** (`check-embeddings-health.py`)
4. Start services/API

**If health check fails:**
- ❌ Warning displayed
- 🛠️ Remediation steps shown
- ⚠️ Service still starts (with warning)

## Expected Dimensions by Mode

| Mode | Embedding Model | Dimensions | Use Case |
|------|----------------|------------|----------|
| **Cloud** | `text-embedding-3-small` (OpenAI) | **1536** | High accuracy, API-based |
| **Local** | `nomic-embed-text` (Ollama) | **768** | Privacy-first, offline |

## Fixing Dimension Mismatches

### Scenario 1: Config Generates Wrong Dimensions

**Symptom**: "Current Config Generates: 1536" in local mode (or vice versa)

**Fix**:
```bash
# Check config
cat config/local.env | grep LLM_PROVIDER

# Should be:
LLM_PROVIDER="ollama"  # For local mode

# If wrong, fix it and reload
source config/local.env
export LLM_PROVIDER="ollama"
```

### Scenario 2: Database Has Wrong Embeddings

**Symptom**: "Memory #X: 1536D (expected 768D)"

**Fix**: Regenerate embeddings by syncing
```bash
# Local mode with wrong embeddings
./bin/sync-memory-db.py --from cloud --to local

# Cloud mode with wrong embeddings
./bin/sync-memory-db.py --from local --to cloud

# Verify fix
./bin/check-embeddings-health.py local
```

### Scenario 3: Tool Embeddings Corrupt

**Symptom**: "Tool XYZ: 1536D (expected 768D)"

**Fix**: Re-sync tools for that mode. Use **`--force`** if you need every tool re-embedded (e.g. after a model change), not only changed definitions:
```bash
# Local mode
./bin/sync-tools.py local
# or full re-embed:
./bin/sync-tools.py local --force

# Cloud mode
./bin/sync-tools.py cloud
./bin/sync-tools.py cloud --force

# Verify fix
./bin/check-embeddings-health.py local
```

### Scenario 4: Fresh Database Setup

**After creating a fresh database:**
```bash
# 1. Ingest intel (will use current mode's embedding model)
./skills/ingest_intel.py '{"path":"jarvis-intel"}'

# 2. Sync tools
./bin/sync-tools.py local  # or cloud

# 3. Verify health
./bin/check-embeddings-health.py local
```

## Integration with Test Scripts

After an intentional fresh test database is created in an isolated temporary path, initialize and inspect that temporary database explicitly. Automated tests must not reset active mode databases.

```bash
#!/bin/bash
# Inspect existing mode databases without replacing them
./bin/check-embeddings-health.py --both --json
```

Deterministic database tests use temporary SQLite paths and mocked embedding providers. Use focused modules such as `tests/test_memory_db_update_sync.py` and `tests/test_memory_sync_health.py`.

See: `docs/TESTING.md` for details.

## Monitoring in Production

### Daily Health Check (Cron)

Add to crontab for daily validation:
```bash
# Check embeddings daily at 2 AM
0 2 * * * cd ~/jarvis-voice && ./bin/check-embeddings-health.py --both --json | logger -t jarvis-embeddings
```

### Runtime Degradation Checks

If you suspect semantic retrieval is acting strangely but DB health checks are clean:

1. Check recent memory-tool logs:
```bash
./skills/check_tool_logs.py '{"tool_name":"semantic_recall","limit":5}'
```

2. Look for `fallback_embeddings: true` in:
```bash
logs/tools/tool-calls-YYYY-MM-DD.jsonl
```

3. Check server/runtime output for:
- `[SEMANTIC_SEARCH] Fallback embeddings used`
- `[TOOL_SEARCH] Fallback embeddings used`

### API Health Endpoint

The Jarvis API health endpoint does not include embedding status. Use the dedicated script instead:

```bash
# API liveness (no embedding details)
curl http://localhost:8880/api/health

{
  "status": "ok",
  "service": "jarvis-api",
  "version": "...",
  "startup_mode": "cloud"
}

# Embedding health (recommended)
./bin/check-embeddings-health.py
```

## Troubleshooting

### Q: Health check says embeddings are wrong, but semantic search works?

**A**: Check if you're only searching recently-added memories. Old memories might have wrong dimensions, but if your search only hits recent ones (with correct dimensions), it appears to work.

Run `check-embeddings-health.py` to see the full picture.

### Q: Health checks are clean, but a semantic query still feels wrong?

**A**: That usually points to a **runtime query embedding issue**, not bad stored embeddings.

Examples:
- temporary OpenAI credit/quota issue
- transient Ollama timeout
- local embedding server hiccup

In that case:
- stored DB vectors can still be healthy
- only that live request degraded
- tool logs or runtime warnings will show fallback usage if it occurred

### Q: Does runtime fallback get saved back into the DB?

**A**: No. Query embeddings are generated per request and are **not** stored. Persistent embedding writers reject tracked fallback vectors; updates preserve their previous real vectors where one exists, and sync operations report the provider failure instead of committing fallback data.

### Q: Can I mix embedding dimensions in one database?

**A**: No. Cosine similarity requires consistent dimensions. Even one mismatched embedding will cause that memory to be skipped (with no error message).

### Q: What if I switch embedding models (e.g., OpenAI → Cohere)?

**A**: You must regenerate ALL embeddings:
1. Update config to new embedding model
2. Run `sync-memory-db.py` to regenerate memory embeddings
3. Run `./bin/sync-tools.py <cloud|local> --force` to regenerate **all** tool embeddings (normal sync may skip unchanged tools via `embedding_input_hash`)
4. Run health check to verify

### Q: How often should I run health checks?

**A**:
- **Startup**: Automatic (via `jarvis-services`/`jarvis-api`)
- **After config changes**: Manual
- **After database operations**: Manual
- **In production**: Daily cron job

## Technical Details

### Embedding Serialization

Embeddings are stored in SQLite as blobs in two formats:

1. **JSON** (newer, default):
   ```python
   embedding_blob = json.dumps(embedding_vector).encode('utf-8')
   ```

2. **Pickle** (legacy, backward-compatible):
   ```python
   embedding_blob = pickle.dumps(embedding_vector)
   ```

Both formats are supported by `memory_db.py`'s deserialization logic.

### Dimension Detection

The health check deserializes embeddings and checks `len(embedding_vector)`:
- OpenAI: `len(embedding) == 1536`
- Ollama/Nomic: `len(embedding) == 768`

If dimensions don't match expectations for the mode, the health check fails.

## Related Documentation

- `docs/DUAL_DATABASE_SYSTEM.md` - Why we have separate databases
- `docs/MEMORY_SYSTEM.md` - How semantic search works
- `docs/TOOL_RAG_STRATEGY.md` - How Tool RAG uses embeddings
- `docs/TESTING.md` - Test script requirements

---

**Key Takeaway**: Run `./bin/check-embeddings-health.py --both` after ANY database operation or config change to ensure semantic search will work correctly.
