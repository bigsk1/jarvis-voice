# Jarvis Memory System

Jarvis has an intelligent memory system that allows it to remember important information, recall past interactions, and learn from experience.

## Database Location

```
/home/boss/jarvis-voice/data/memory.db
```

**Note:** The database file is `memory.db`, and the table is called `knowledge_base` (not `memories`).

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

## Memory Tools

Jarvis has 5 memory management tools that it uses intelligently:

### `remember`
Stores important information proactively.
```bash
# Jarvis decides when to use this automatically
# Example: "My favorite restaurant is Thai Bloom"
# Jarvis will remember this without being asked
```

### `recall`
Searches for specific memories by category and key.
```bash
# Ask: "What's my favorite restaurant?"
# Jarvis uses recall tool to find the answer
```

### `search_memory`
Keyword search across all memories.
```bash
# Ask: "What do you know about restaurants?"
# Jarvis finds all restaurant-related memories
```

### `semantic_recall`
AI-powered search that understands meaning, not just keywords.
```bash
# Ask: "Where do I like to eat?"
# Finds memories about restaurants even without exact words
```

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

### View Memory Stats

```bash
cd /home/boss/jarvis-voice
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

**Cloud Mode:**
- Uses OpenAI `text-embedding-3-small`
- 1536 dimensions

**Local Mode:**
- Uses Ollama `nomic-embed-text`
- 768 dimensions

**Similarity Threshold:** 0.45 (configurable in `lib/memory_db.py`)

## Configuration

Memory system is configured in:
- `config/cloud.env` - Cloud settings
- `config/local.env` - Local settings

**Key Settings:**
```bash
# Embedding provider (auto-detected from LLM_PROVIDER)
EMBEDDING_PROVIDER="openai"  # or "ollama"

# Ollama embedding model (local only)
OLLAMA_EMBEDDING_MODEL="nomic-embed-text"
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

## Future Enhancements

See `FUTURE_ENHANCEMENTS.md` for planned improvements:
- Multi-user support (separate memory per user)
- Import/export memories
- Memory expiration policies
- Contextual importance scoring
- Memory visualization dashboard

