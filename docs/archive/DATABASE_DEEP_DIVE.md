# Jarvis Database Deep Dive
*Real-World Analysis After 300+ Conversations*

---

## ⚠️ HISTORICAL DOCUMENT WARNING

**This document describes database evolution and includes references to removed/deprecated features:**
- `tool_patterns` table → **REMOVED** (never used, 0 rows)
- `preferences` table → **REMOVED** (never used, 0 rows)
- Metadata columns being NULL → **NOW POPULATED** (as of Nov 2025)
- Local model issues → **FIXED** with `local_model_corrections.py`

**Current database schema has only 2 tables:**
- `knowledge_base` - Facts, preferences, embeddings
- `conversations` - Full conversation history with metadata

**For current database documentation, see:** `MEMORY_SYSTEM.md` and `METADATA_SYSTEM.md`

---

## Overview

After extensive real-world testing, you've discovered some interesting patterns in how the database is *actually* being used vs. how it was *originally designed*. This doc explains what's working, what's not, and why.

## Table-by-Table Analysis

### 1. `knowledge_base` - ✅ ACTIVE & WORKING

**Schema:**
```sql
CREATE TABLE knowledge_base (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,          -- preference, fact, project, technical
    key TEXT NOT NULL,                -- What it's about
    value TEXT NOT NULL,              -- The actual data
    importance INTEGER DEFAULT 5,     -- 1-10 scale
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    source TEXT,                      -- How it was learned
    metadata TEXT,                    
    embedding BLOB                    -- Vector for semantic search
)
```

**Real-World Usage:** ✅ **HEAVILY USED**

This is where **ALL** memory data actually lives. The LLM intelligently categorizes information:

- **`preference`** - User preferences ("favorite_color": "blue")
- **`fact`** - General facts ("tetris_game_location": "~/...")
- **`project`** - Project-specific data from jarvis-intel docs
- **`technical`** - Technical details and configurations

**What Works:**
- ✅ LLM decides category automatically
- ✅ Embeddings enable semantic search
- ✅ Importance scoring (1-10) prioritizes results
- ✅ Source tracking ("user_conversation", "intel_ingest")


---

### 2. `conversations` - ✅ ACTIVE (LOGGING ONLY)

**Schema:**
```sql
CREATE TABLE conversations (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP,
    session_id TEXT,                  -- Groups related conversations
    user_query TEXT NOT NULL,         -- What you asked
    jarvis_response TEXT,             -- What Jarvis said
    tools_used TEXT,                  -- JSON array: ["send_webhook", "remember"]
    success BOOLEAN DEFAULT 1,        -- Did it work?
    metadata TEXT                     
)
```

**Real-World Usage:** ✅ **LOGGING ONLY**

Every conversation is automatically logged. This creates a complete audit trail of:
- What you asked
- How Jarvis responded
- Which tools were executed
- Whether it succeeded

**What Works:**
- ✅ Full conversation history (300+ entries in your case)
- ✅ Tool usage tracking (can analyze patterns)
- ✅ Session grouping (voice mode conversations)
- ✅ Success/failure tracking for debugging

**What's Missing:**
- ⚠️ `metadata` column is **ALWAYS NULL**
- No structured data like:
  - `{"response_time_ms": 1234, "model": "claude-sonnet-4", "cost_estimate": 0.02}`
  - `{"error_count": 2, "retry_attempts": 1, "final_tool": "execute_bash"}`
  - `{"voice_mode": true, "confidence": 0.87, "language": "en-US"}`

**Why Metadata Matters Here:**
You're missing valuable debugging info:
- Which model/provider was used?
- How long did it take?
- What was the cost?
- Was it voice or CLI mode?

**Current Workaround:**
Tool call logging (`logs/tools/tool-calls-YYYY-MM-DD.jsonl`) captures per-tool metadata, but not per-conversation.

---

### 3. `tool_patterns` - ❌ NEVER USED (ZOMBIE TABLE)

**Schema:**
```sql
CREATE TABLE tool_patterns (
    id INTEGER PRIMARY KEY,
    query_pattern TEXT NOT NULL,      -- "start * server", "send webhook to *"
    tool_name TEXT NOT NULL,          -- "execute_bash", "send_webhook"
    args_template TEXT,               -- JSON template for common args
    success_count INTEGER DEFAULT 0,  -- How many times it worked
    failure_count INTEGER DEFAULT 0,  -- How many times it failed
    avg_duration_ms REAL,             -- Performance tracking
    last_used TIMESTAMP,
    confidence REAL DEFAULT 0.5       -- 0-1 reliability score
)
```

**Real-World Usage:** ❌ **EMPTY (0 rows even after 300+ conversations)**

**Original Intent:**
This table was designed to be a **learning system** that would:

1. **Pattern Recognition**
   - User says: "start the tetris server" → `execute_bash` is called → Success
   - System learns: Pattern "start * server" → Use `execute_bash` tool
   - Next time: Jarvis recognizes the pattern faster

2. **Success Tracking**
   - If `send_webhook` succeeds 95% of the time → High confidence (0.95)
   - If `api_call` fails 50% of time to specific URL → Low confidence (0.5)
   - Router could prioritize high-confidence tools

3. **Performance Optimization**
   - Track `avg_duration_ms` to avoid slow tools
   - Suggest faster alternatives when available

4. **Argument Templates**
   - Learn common argument patterns:
   ```json
   {
     "pattern": "send webhook to *",
     "tool": "send_webhook",
     "args_template": {
       "url": "{captured_url}",
       "data": {"source": "jarvis", "timestamp": "{now}"}
     }
   }
   ```

**Why It Was Never Implemented:**

1. **LLM Got Too Smart**
   - Modern LLMs (GPT-4, Claude) are already excellent at pattern matching
   - The router decides tools intelligently without needing historical data
   - Tool selection is context-aware, not pattern-based

2. **Complexity vs. Benefit**
   - Would require parsing user queries into patterns
   - Would need continuous learning code
   - Adds complexity for minimal gain with smart LLMs

3. **Memory System Does This Job**
   - The `knowledge_base` table already stores "how to start tetris server"
   - Jarvis uses `search_memory` to find stored instructions
   - More flexible than rigid patterns

**Should You Use It?**

**For Local Models (Ollama):** Maybe useful! Local models like qwen3-vl can struggle with:
- Exact tool names ("send_webhook" vs "sendWebhook")
- URL formatting (missing `https://`)
- Key naming ("favorite_color" vs "favorite color")

A pattern learning system could help by:
```python
# After seeing "send webhook" fail 3 times with local model
# Auto-correct to "send_webhook" before calling LLM
pattern_corrections = {
    "send webhook": "send_webhook",
    "example.com": "https://example.com",  
    "favorite color": "favorite_color"
}

# UPDATE: Smart corrections now implemented in local_model_corrections.py!
# Automatically fixes tool names, memory keys, and URLs
```

**For Cloud Models (Claude/GPT):** Not needed - they're already accurate.

---

### 4. `preferences` - ❌ RARELY USED (SUPERSEDED)

**Schema:**
```sql
CREATE TABLE preferences (
    key TEXT PRIMARY KEY,             -- Simple key-value
    value TEXT NOT NULL,
    updated_at TIMESTAMP
)
```

**Real-World Usage:** ❌ **EMPTY (0 rows)**

**Original Intent:**
Simple key-value storage for user preferences:
```sql
INSERT INTO preferences VALUES ('voice', 'eleven_labs', '2025-11-01');
INSERT INTO preferences VALUES ('llm_provider', 'anthropic', '2025-11-02');
INSERT INTO preferences VALUES ('response_style', 'casual', '2025-11-03');
```

**Why It's Not Used:**

The `knowledge_base` table already handles preferences via the `category` field:
```sql
-- preferences table (unused):
INSERT INTO preferences VALUES ('favorite_color', 'blue');

-- knowledge_base (what actually happens):
INSERT INTO knowledge_base (category, key, value) 
VALUES ('preference', 'favorite_color', 'blue');
```

**Why knowledge_base Won:**
- ✅ Has `importance` scoring
- ✅ Has semantic embeddings
- ✅ Can attach `source` and `metadata`
- ✅ More flexible categories
- ✅ One table = simpler code

**When preferences Might Be Useful:**

System-level settings that don't belong in `knowledge_base`:
```sql
-- System preferences (not user memories):
INSERT INTO preferences VALUES ('max_retries', '3');
INSERT INTO preferences VALUES ('timeout_seconds', '90');
INSERT INTO preferences VALUES ('log_level', 'info');
```

But currently these are in ENV files (`config/cloud.env`, `config/local.env`), which is fine.

---

## The `metadata` Mystery

**The Issue:** `metadata` column exists in BOTH `knowledge_base` AND `conversations`, but is **ALWAYS NULL** in production.

**Why It's Always NULL:**

Looking at the code:

```python
# lib/memory_db.py - remember() function
cursor.execute("""
    INSERT INTO knowledge_base (category, key, value, importance, source, embedding)
    VALUES (?, ?, ?, ?, ?, ?)
""", (category, key, value, importance, source, embedding_blob))
# ⚠️ metadata is NEVER passed in!
```

```python
# lib/memory_db.py - log_conversation() function
cursor.execute("""
    INSERT INTO conversations (user_query, jarvis_response, tools_used, session_id, success)
    VALUES (?, ?, ?, ?, ?)
""", (user_query, jarvis_response, tools_json, session_id, success))
# ⚠️ metadata is NEVER passed in!
```

**What metadata COULD Store:**

### For `knowledge_base.metadata`:
```json
{
  "tags": ["server", "tetris", "flask"],
  "related_projects": ["tetris-game"],
  "expires_at": "2025-12-31",
  "confidence": 0.95,
  "learned_from": "conversation_id:1234",
  "verified": true,
  "version": 2
}
```

### For `conversations.metadata`:
```json
{
  "model": "claude-sonnet-4-20250514",
  "provider": "anthropic",
  "response_time_ms": 1234,
  "tokens_used": 450,
  "cost_estimate_usd": 0.0089,
  "voice_mode": true,
  "wake_word_confidence": 0.89,
  "retry_count": 0,
  "error_recovered": false
}
```

**Why This Matters:**

Without metadata, you can't answer questions like:
- "Which conversations cost the most?"
- "How long do multi-tool workflows take?"
- "What's my average token usage?"
- "Which memories came from intel vs. conversation?"
- "Which voice commands had low confidence?"

---

## Local Model Struggles (Observed Issues)

From your tool logs (`tool-calls-2025-11-13.jsonl`), here are the real problems:

### Issue #1: Tool Name Formatting
```jsonl
# LLM output (local model):
{"tool": "mcp_duckduckgo search"}  ❌ (should be "mcp_duckduckgo_search")

# Causes:
- Spaces instead of underscores
- Mixed case vs snake_case

# ✅ NOW FIXED: local_model_corrections.py automatically normalizes tool names
```

### Issue #2: Missing URL Scheme
```jsonl
# LLM output:
{"tool": "mcp_fetch_fetch", "arguments": {"url": "example.com"}}  ❌

# Error:
"Input should be a valid URL, relative URL without a base"

# Should be:
{"url": "https://example.com"}
```

### Issue #3: Key Naming Inconsistency
```jsonl
# User says: "my favorite color is blue"
# LLM creates: {"key": "favorite color"}  ❌ (with space)

# Later recall:
recall(query="favorite_color")  ❌ No match!

# Pattern:
- User speaks naturally with spaces
- LLM sometimes preserves spaces
- Recall expects underscores
```

**Root Cause:**

Cloud models (Claude, GPT-4) have been fine-tuned on API schemas and are very precise. Local models like qwen3-vl (8B params) are:
- Smaller (12B vs 175B+ parameters)
- Less exposure to structured API formats
- More literal with human language patterns

**Potential Solutions (Future):**

1. **Post-Processing Layer:**
   ```python
   def normalize_tool_call(llm_output):
       # Fix tool names
       tool = llm_output["tool"].replace(" ", "_").replace("-", "_")
       
       # Fix URLs
       if "url" in llm_output["arguments"]:
           url = llm_output["arguments"]["url"]
           if not url.startswith("http"):
               url = f"https://{url}"
       
       # Fix keys (snake_case)
       if "key" in llm_output["arguments"]:
           key = llm_output["arguments"]["key"].replace(" ", "_")
   ```

2. **Pattern Learning (use tool_patterns!):**
   ```python
   # After 3 failures with "favorite color"
   # Automatically map: "favorite color" → "favorite_color"
   ```

3. **Stricter Prompting:**
   ```python
   system_prompt += """
   CRITICAL FORMATTING:
   - Tool names: MUST use underscores (mcp_fetch_fetch not "mcp fetch fetch")
   - URLs: MUST include https:// (https://example.com not "example.com")
   - Memory keys: MUST use snake_case (favorite_color not "favorite color")
   """
   ```

---

## Summary: What's Actually Happening

| Table | Status | Usage | Original Intent |
|-------|--------|-------|-----------------|
| `knowledge_base` | ✅ Active | ALL memory data, heavily used | ✅ Working as designed |
| `conversations` | ✅ Active | Audit trail, 300+ logged | ✅ Working as designed |
| `tool_patterns` | ❌ Empty | Never used (0 rows) | ❌ Learning system never built |
| `preferences` | ❌ Empty | Superseded by knowledge_base | ❌ Made redundant by flexible categories |

**Metadata Columns:** ✅ **NOW POPULATED** - Model, timing, cost tracking enabled (as of 2025-11-14)

**Local Model Issues:** ✅ **NOW FIXED** with `local_model_corrections.py`:
- ✅ Post-processing corrections (tool names, keys, URLs)
- ✅ Smart URL handling (respects http:// for local network)
- ✅ Automatic normalization to snake_case

---

## Implementation Status

### ✅ Completed (2025-11-14):
1. **Metadata fields populated** - Model, provider, timing, cost tracking
   - `conversations.metadata` now includes: model, provider, execution_time_ms, token counts, cost (cloud only)
   - Ready for analytics and cost tracking
2. **Local model corrections** - `lib/local_model_corrections.py`
   - Normalizes tool names ("send webhook" → "send_webhook")
   - Smart URL fixing (respects http:// for local network, adds https:// for public domains)
   - Memory key normalization ("favorite color" → "favorite_color")
3. **Cost estimation** - `lib/cost_estimator.py`
   - Tracks tokens and costs for OpenAI/Anthropic
   - No cost tracking for Ollama (local, free)

### 🔧 Migration Available:
- **Remove zombie tables**: Run `./bin/migrate-remove-zombie-tables.sh`
  - Safely removes `tool_patterns` and `preferences`
  - Creates backup before migration
  - Reversible (can restore from backup)

### 📋 Future Enhancements:
1. **Conversation analytics** - Query patterns, tool usage stats, cost reports
2. **Memory expiration** - Cleanup strategies for stale/outdated memories
3. **Memory validation** - Check project paths still exist, URLs still valid

### ✅ Already Working (No Changes Needed):
1. `knowledge_base` table - Handles all memory needs perfectly
2. Conversation logging - Complete audit trail

---

*Last Updated: 2025-11-14*  
*Based on: 300+ conversations, real production usage*

