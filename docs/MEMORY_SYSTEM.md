# Jarvis Memory System

Jarvis has an intelligent memory system that allows it to remember important information, recall past interactions, and learn from experience.

![memory-info-graph](images/memory-info-graph.jpeg)

## Database Location

Cloud mode uses **`data/jarvis_memory.db`**; local mode (Ollama / smaller embeddings) uses **`data/jarvis_memory_local.db`**. Same schema; sync between them is `./bin/sync-memory-db.py` (see `docs/DUAL_DATABASE_SYSTEM.md`).

**Note:** The main store is *not* named `memory.db`. The facts table is `knowledge_base` (not `memories`).

## Memory Tables

### 1. `knowledge_base`
Stores facts, preferences, and information that Jarvis learns.

**Fields:**
- `id` - Unique identifier
- `category` - Type of memory (preference, fact, instruction, etc.)
- `key` - What the memory is about
- `value` - The actual information
- `importance` - How important this memory is (1-10)
- `created_at` - When it was created
- `updated_at` - When it was last updated
- `source` - How Jarvis learned this
- `metadata` - Additional context (JSON)
- `embedding` - Vector embedding for semantic search

### 2. `conversations`
Logs all interactions with Jarvis.

**Fields:**
- `id` - Unique identifier
- `timestamp` - When the conversation happened
- `user_query` - What you asked
- `jarvis_response` - What Jarvis replied
- `tools_used` - Which tools were executed
- `session_id` - Groups related conversations
- `success` - Whether the task completed successfully

### 3. `user_model`
Stores compact behavioral traits for how Jarvis should respond to the user over time.

This table is separate from `knowledge_base` so scalar traits like verbosity or technical depth do not pollute semantic memory recall or tool routing.

**Fields:**
- `key` - Trait name, such as `verbosity` or `technical_depth`
- `value` - Trait value as text, usually a scalar encoded as `0.0`-`1.0`
- `value_type` - `scalar`, `text`, or `json`
- `confidence` - Confidence in the trait, `0.0`-`1.0`
- `evidence` - JSON evidence refs from feedback, corrections, or memory keys
- `source` - How the trait was updated
- `metadata` - Additional context (JSON)
- `last_reconciled_at` - Last profile compaction/reconciliation timestamp
- `created_at` / `updated_at` - Timestamps

## Memory Tools

Jarvis has 6 memory management tools that it uses intelligently:

### `remember`
Stores important information proactively.
```bash
# Jarvis decides when to use this automatically
# Example: "My favorite restaurant is Thai Bloom"
# Jarvis will remember this without being asked
```

### `recall`
Legacy fuzzy keyword search (SQL LIKE substring matching).
```bash
# Implementation: WHERE key LIKE '%query%' OR value LIKE '%query%'
# Use case: Backward compatibility (prefer search_memory)
# Ask: "What's my favorite restaurant?"
# Finds: "favorite_restaurant", "restaurant_preference", etc.
```

**Note**: `recall` is kept for backward compatibility. Use `search_memory` for better performance.

### `search_memory` : FTS5 Full-Text Search
**Industry-standard full-text search with BM25 ranking** (10-100x faster than SQL LIKE).
```bash
# Implementation: SQLite FTS5 with BM25 relevance ranking
# Features:
#  • Stemming: "running" matches "run"
#  • Phrase search: "Flask API" (in quotes)
#  • Boolean operators: "flask OR express"
#  • Porter algorithm for English text
#  • BM25 ranking (better relevance than LIKE)

# Ask: "What do you know about restaurants?"
# Returns: Ranked by relevance (BM25 score) + importance
```

**Performance:**
- SQL LIKE: ~10ms, keyword-only matching
- FTS5: ~2ms, smart ranking with stemming

### `semantic_recall`
AI-powered search using vector embeddings - understands meaning, not just keywords.
```bash
# Implementation: OpenAI embeddings + cosine similarity
# Threshold: Configurable via SEMANTIC_SIMILARITY_THRESHOLD (default 0.40)
# Ask: "Where do I like to eat?"
# Finds memories about "favorite_restaurant" by understanding concepts
# Works even if query uses different words than stored memory
```

**When to use which**:
- **Natural language questions** (4+ words) → `semantic_recall`
- **Keyword searches** (1-3 words) → `search_memory` (FTS5 BM25 ranking)
- **Conversation history** → `search_conversations` (different table)
- **Legacy/backward compat** → `recall` (slower, same as old search_memory)

### `update_memory`
Modifies existing memories when information changes. **Smart search enabled** - can find memories automatically without needing the ID.

**Parameters:**
- `search_query` - Find memory by keywords (optional if you have the ID)
- `memory_id` - Direct memory ID (optional if you provide search_query)
- `new_value` - The updated information
- `category` - Optional category filter for search
- `importance` - Optional updated importance (1-10)

```bash
# Say: "Actually, my favorite restaurant is now Sushi House"
# Jarvis automatically finds the restaurant memory and updates it

# Direct tool usage examples:
# With search (automatic):
python3 skills/update_memory.py '{"search_query": "restaurant", "new_value": "Sushi House"}'

# With ID (if known):
python3 skills/update_memory.py '{"memory_id": 5, "new_value": "Sushi House"}'
```

### `forget`
Removes memories that are no longer needed or incorrect.
```bash
# Say: "Forget about my favorite restaurant"
# Jarvis deletes that memory
```

## Managing the Database

### Rebuild FTS5 Index


```bash
cd ~/jarvis-voice
source ~/jarvis-venv/bin/activate
./bin/rebuild-fts-index  # Both cloud and local DBs
```

This populates the full-text search index for existing memories.

### View Memory Stats

```bash
cd ~/jarvis-voice
source ~/jarvis-venv/bin/activate
./bin/memory stats
```

### List All Memories

```bash
./bin/memory list
```

### Search Memories

```bash
# Keyword search
./bin/memory search "restaurant"

# Semantic search (AI-powered)
./bin/memory semantic "where do I like to eat"
```

### Clear Test Data

**⚠️ Warning: This will delete all memories!**

```bash
# Clear specific category
sqlite3 data/jarvis_memory.db "DELETE FROM knowledge_base WHERE category='test';"

# Clear all memories (keep schema)
sqlite3 data/jarvis_memory.db "DELETE FROM knowledge_base;"
sqlite3 data/jarvis_memory.db "DELETE FROM conversations;"

# Reset database completely
rm data/jarvis_memory.db
./bin/setup-memory-db.sh
```

### Clear Conversation History Only

```bash
# Clear old conversations (keep knowledge)
sqlite3 data/jarvis_memory.db "DELETE FROM conversations WHERE timestamp < datetime('now', '-7 days');"

# Clear all conversations
sqlite3 data/jarvis_memory.db "DELETE FROM conversations;"
```

### Manual Memory Management

```bash
# Add a memory manually
sqlite3 data/jarvis_memory.db <<EOF
INSERT INTO knowledge_base (category, key, value, importance, source, metadata)
VALUES ('preference', 'favorite_color', 'blue', 7, 'manual', '{}');
EOF

# View specific memory
sqlite3 data/jarvis_memory.db "SELECT * FROM knowledge_base WHERE key='favorite_color';"

# Update a memory
sqlite3 data/jarvis_memory.db "UPDATE knowledge_base SET value='green' WHERE key='favorite_color';"

# Delete a memory
sqlite3 data/jarvis_memory.db "DELETE FROM knowledge_base WHERE key='favorite_color';"
```

## Auto-Memory Injection

**NEW:** Relevant memories are automatically injected into the LLM context before each request—no tool calls needed.

- **Always-include** (1–2 items): Addressing/response-style only (`how_to_address_user`, `response_tone`, etc.). E.g. "call me sir" appears in every chat.
- **Semantic search**: Topic-specific memories (dog name, Spotify playlist, etc.) only when relevant to the current query.
- **Type filter** (`AUTO_MEMORY_TYPE_FILTER_ENABLED`): Excludes `artifact` and `transient` rows (stash/canvas uploads, session scratch). Legacy rows without labels are classified on the fly; run `./bin/backfill-memory-types` once to stamp metadata.
- **Recency weighting**: Recent memories rank slightly higher; older ones fade.

Config: `AUTO_MEMORY_*` in cloud.env / local.env. See `docs/AUTO_MEMORY_INJECTION_FEATURE.md`.

## How Memory Works

### Automatic Memory
Jarvis intelligently decides what to remember based on:
- Importance of information (names, preferences, instructions)
- Context of conversation
- Whether you're correcting previous information
- If it might be useful later

### Proactive Learning
In `casual` response mode, Jarvis will:
- Remember your preferences without being asked
- Update memories when you correct information
- Ask clarifying questions before remembering ambiguous info

### Memory Integration
- Memory is used in **both cloud and local modes**
- Shared database means Jarvis remembers across modes
- Embeddings use appropriate model (OpenAI for cloud, Ollama for local)

## Response Style Impact

### Casual Mode (Default)
```bash
JARVIS_RESPONSE_STYLE="casual"
```
- Jarvis interprets memories naturally
- "I found 3 things about restaurants..."
- Conversational, voice-optimized

### Detailed Mode
```bash
JARVIS_RESPONSE_STYLE="detailed"
```
- Raw memory data
- Shows exact JSON structure
- Good for debugging

## Embedding System

Memories are converted to vector embeddings for semantic search:

**Cloud Mode (default):**
- Uses OpenAI `text-embedding-3-small` independently of the chat provider
- 1536 dimensions

**Local Mode (default):**
- Uses Ollama `nomic-embed-text`
- 768 dimensions

**Similarity Threshold:** 0.45 (configurable in `lib/memory_db.py`)

## Configuration

Memory system is configured in:
- `config/cloud.env` - Cloud settings
- `config/local.env` - Local settings

**Key Settings:**
```bash
# Embedding provider (explicit; independent of LLM_PROVIDER)
EMBEDDING_PROVIDER="openai"  # or "ollama"

# Ollama embedding model (used when EMBEDDING_PROVIDER=ollama)
OLLAMA_EMBEDDING_MODEL="nomic-embed-text"

# Auto-memory injection (inject relevant memories before each LLM call)
AUTO_MEMORY_INJECTION_ENABLED=true
AUTO_MEMORY_LIMIT=8
AUTO_MEMORY_SIMILARITY_THRESHOLD=0.38
AUTO_MEMORY_ALWAYS_INCLUDE_LIMIT=2
```

## Troubleshooting

### "sqlite3.OperationalError: no such column: embedding"
Run the migration:
```bash
./bin/setup-memory-db.sh
```

### Semantic search not working
Check embeddings are generated:
```bash
sqlite3 data/jarvis_memory.db "SELECT id, key, length(embedding) FROM knowledge_base;"
```

If embedding is NULL, regenerate:
```bash
# Implement in future if needed - for now, delete and re-remember
```

### Memory growing too large
```bash
# Check database size
du -h data/jarvis_memory.db

# Clear old conversations
sqlite3 data/jarvis_memory.db "DELETE FROM conversations WHERE timestamp < datetime('now', '-30 days');"

# Vacuum to reclaim space
sqlite3 data/jarvis_memory.db "VACUUM;"
```

## Privacy & Security

- Database is stored locally
- No memory data is sent to cloud (except for embedding generation)
- You control all data
- Can be fully cleared anytime
- No external sync or backup (you own your data)

## Multi-Turn Memory Integration

**NEW:** Jarvis can now chain memory operations with other tools!

Examples:
```bash
# Multi-turn: Action + Remember
"Send webhook to X and save the URL"
→ Turn 1: send_webhook
→ Turn 2: remember (saves URL)

# Multi-turn: Search + Update
"Find my favorite restaurant and change it to Sushi House"
→ Turn 1: search_memory (finds restaurant)
→ Turn 2: update_memory (updates value)

# Multi-turn: Recall + Action
"What's my server IP? Then SSH into it"
→ Turn 1: recall (gets IP from memory)
→ Turn 2: execute_bash (SSH command with IP)
```

See [MULTI_TURN_ORCHESTRATION.md](MULTI_TURN_ORCHESTRATION.md) for details.

## Future Enhancements

See `FUTURE_ENHANCEMENTS.md` for planned improvements:
- Multi-user support (separate memory per user)
- Import/export memories
- Memory expiration policies
- Contextual importance scoring
- Memory visualization dashboard
