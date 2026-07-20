# Auto-Context System (Short-Term Conversation Memory for running in terminal mode)

## Overview

The Auto-Context System gives Jarvis **automatic short-term memory** of recent conversations, enabling natural follow-up responses, self-learning from failures, and seamless multi-step workflows **without requiring explicit tool calls**.

---

## ⚠️ IMPORTANT: Web UI vs CLI/TUI Context Systems

**These are COMPLETELY SEPARATE systems that do NOT overlap:**

| Setting | Used By | Source | Config Location |
|---------|---------|--------|-----------------|
| `AUTO_CONTEXT_WINDOW` | **CLI/TUI only** | `conversations` table in DB | `config/cloud.env` or `config/local.env` |
| `conversation.history_limit` | **Web UI only** | JSON file per chat | `jarvis-web/config/web_config.json` |

### Why They're Separate

The orchestrator uses an `if/elif` check:

```python
# In orchestrator_v2.py process():
if conversation_history:
    # Web UI ALWAYS passes this from JSON file
    enhanced_transcript = self._format_conversation_context(transcript, conversation_history)
elif self.auto_context_enabled:
    # CLI/TUI falls back to this (reads from DB)
    enhanced_transcript = self._build_conversation_context(transcript)
```

**Web UI always passes `conversation_history`** from its JSON file, so the `AUTO_CONTEXT_*` settings are never used for web requests.

Implementation note:
- `orchestrator/orchestrator_v2.py` still decides which path to use
- `orchestrator/context_assembler.py` now owns the actual context-building and formatting logic for both paths

### Practical Implications

1. **If you only use Web UI**: Set `AUTO_CONTEXT_ENABLED=false` in `.env` - it won't affect anything
2. **If you only use CLI**: Configure `AUTO_CONTEXT_WINDOW` and `AUTO_CONTEXT_MINUTES` - web settings don't matter
3. **If you use both**: Each system works independently with its own config

### Key Differences

| Aspect | CLI/TUI Auto-Context | Web UI Context |
|--------|---------------------|----------------|
| **Scope** | Cross-session (all recent conversations) | Single chat session only |
| **Source** | SQLite `conversations` table | JSON file (`data/web_conversations/<uuid>.json`) |
| **Content** | Query, response, tools, success, metadata | Role, content, tools_used per message |
| **Isolation** | Sees ALL recent convos (CLI + web) | Only sees THIS chat's history |
| **Time filter** | `AUTO_CONTEXT_MINUTES` | None (just message count) |

---

## The Problem It Solves

### Before (Awkward):
```
User: "Hey Jarvis, today is super hot!"
Jarvis: "I understand."
[3 minutes later]
User: "Hey Jarvis, it's cold today"
Jarvis: "Okay." [No memory of "hot" comment]
```

### After (Natural):
```
User: "Hey Jarvis, today is super hot!"
Jarvis: "Yeah, it's warm out."
[3 minutes later]
User: "Hey Jarvis, it's cold today"
Jarvis: "Wait, didn't you just say it was hot 3 minutes ago? What's going on?"
```

---

## How It Works

### Automatic Context Injection

Before routing each request, Jarvis automatically:

1. **Loads recent conversations** from the database (last N conversations)
2. **Filters by time window** (only conversations within X minutes)
3. **Injects context** into the request with:
   - User's previous questions
   - Jarvis's previous responses
   - Tools used
   - Success/failure status
   - Model metadata (tokens, cost, tool count)
4. **Routes enhanced request** to LLM

### What Context Includes

```
╔══════════════════════════════════════════════════════════╗
║ RECENT CONVERSATION HISTORY (for context awareness)     ║
║ Last 3 conversation(s) in past 10 minutes               ║
╚══════════════════════════════════════════════════════════╝

─── Conversation #1 ───
User asked: Build a Flask API
Jarvis replied: Flask API built and running on port 8091
Tools used: opencode, remember
✅ STATUS: Success
Model: claude-sonnet-4-5-20250929, Tools called: 2

─── Conversation #2 ───
User asked: Test the API
Jarvis replied: Health check passed, API is working
Tools used: api_call
✅ STATUS: Success
Model: claude-sonnet-4-5-20250929, Tools called: 1

─── Conversation #3 ───
User asked: Add a login endpoint
Jarvis replied: Tool opencode timed out
Tools used: opencode
⚠️  STATUS: FAILED - Task did not complete successfully
   Consider: Using check_tool_logs to understand why
Model: claude-sonnet-4-5-20250929, Tools called: 1

╔══════════════════════════════════════════════════════════╗
║ CURRENT USER QUERY (what they just asked)               ║
╚══════════════════════════════════════════════════════════╝
Fix the login endpoint

INSTRUCTIONS:
- Use the above context to provide intelligent, context-aware responses
- Reference previous topics naturally when relevant
- Learn from failed attempts (check_tool_logs if needed)
- Catch contradictions ("You just said X, now saying Y?")
- Continue multi-step workflows seamlessly
- If context window is too short, you can call get_recent_conversations tool for more history
```

---

## Configuration

### Environment Variables

**In `config/cloud.env` and `config/local.env`:**

```bash
# Auto-Context (Short-Term Conversation Memory)
# Shipped: cloud WINDOW=2 MINUTES=5; local both 0 (disabled)
AUTO_CONTEXT_ENABLED=true        # Enable/disable feature
AUTO_CONTEXT_WINDOW=2            # Number of conversations to include
AUTO_CONTEXT_MINUTES=5           # Time window (minutes)
```

### Tuning the "Sweet Spot"

| Profile | Window | Minutes | Tokens/Request | Use Case |
|---------|--------|---------|----------------|----------|
| **Conservative** (shipped cloud) | 2 | 5 | ~200 | Casual use, cost-sensitive |
| **Balanced** | 3 | 10 | ~400 | Typical voice conversations |
| **Aggressive** | 5 | 20 | ~800 | Complex multi-step tasks |
| **Disabled** | - | - | 0 | Testing, minimal mode |

**Cost Impact:**
- Without context: 50 tokens per request (with caching)
- With context (3 convos): 450 tokens per request
- **9x increase, but still <$0.001 per request**

---

## Real-World Examples

### 1. Natural Contradictions

```
Cycle 1:
User: "It's hot today"
Jarvis: "Yeah, it's warm"

Cycle 2 (3 minutes later):
User: "It's cold today"
Jarvis: [Sees context] "Wait, you just said it was hot 3 minutes ago!"
```

### 2. Seamless Workflow Continuation

```
Cycle 1:
User: "Build a Flask API"
Jarvis: [Calls opencode] "Flask API built on port 8091"

Cycle 2 (2 minutes later):
User: "Test it"
Jarvis: [Sees context: "Built Flask API on port 8091"]
        [Calls api_call with correct port]
        "Health check passed"
```

### 3. Self-Learning from Failures

```
Cycle 1:
User: "Install Redis"
Jarvis: [Calls execute_bash: apt install redis]
        [FAILS - permission denied]
        "Installation failed"

Cycle 2 (30 seconds later):
User: "Try again"
Jarvis: [Sees context: "Previous attempt failed"]
        [Calls check_tool_logs to understand error]
        [Discovers needs sudo]
        [Calls execute_bash: sudo apt install redis]
        "Redis installed successfully"
```

### 4. Avoiding Redundancy

```
Cycle 1:
User: "Ingest intel files"
Jarvis: [Calls ingest_intel] "Ingested 50 files"

Cycle 2 (1 minute later):
User: "Did you ingest the intel?"
Jarvis: [Sees context: "Just ingested 50 files"]
        "Yes, I just ingested 50 files a minute ago"
        [NO tool call needed!]
```

### 5. Multi-Step Project Awareness

```
Cycle 1:
User: "Build a tetris game"
Jarvis: [Calls opencode] "Tetris game built at ~/jarvis-workspace/projects/tetris"

Cycle 2 (5 minutes later):
User: "Add high scores"
Jarvis: [Sees context: "Built tetris game"]
        [Calls opencode to modify existing project]
        "High scores added to tetris game"
```

---

## Technical Details

### Implementation Location

**Routing entry point:** `orchestrator/orchestrator_v2.py`

**Actual context assembly:** `orchestrator/context_assembler.py`

**Delegated methods exposed by orchestrator:**
- `_build_conversation_context(current_query: str) -> str`
- `_format_conversation_context(current_query: str, conversation_history: list) -> str`
- `_build_turn_context(original_query: str, conversation_context: list) -> str`

**Flow:**
```python
def process(self, transcript: str, ...):
    # 1. Auto-inject context
    if conversation_history:
        enhanced_transcript = self._format_conversation_context(transcript, conversation_history)
    elif self.auto_context_enabled:
        enhanced_transcript = self._build_conversation_context(transcript)
    else:
        enhanced_transcript = transcript
    
    # 2. Route enhanced request
    route = self.router.route(enhanced_transcript)
    
    # 3. Execute tools...
```

`orchestrator_v2.py` keeps these wrapper methods so older call sites and tests do not need to know about the helper module directly.

### Database Query

```python
# Inside ContextAssembler.build_conversation_context(...)
db = get_memory_db()
recent = db.get_recent_conversations(limit=AUTO_CONTEXT_WINDOW)

# Filter by time window
cutoff = now_utc() - timedelta(minutes=AUTO_CONTEXT_MINUTES)
relevant = [c for c in recent if parse_utc_timestamp(c["timestamp"]) > cutoff]

# Build formatted context with:
# - user_query
# - jarvis_response
# - tools_used (JSON array)
# - success (boolean)
# - metadata (JSON with model, tokens, cost)
```

### Prompt Caching Efficiency

**Request structure:**
```
System Prompt (2500 tokens)     → Cached (5 min)
Tool Definitions (5000 tokens)  → Cached (5 min)
Auto-Context (400 tokens)       → NOT cached (changes every request)
Current Query (50 tokens)       → NOT cached (always new)
```

**Token usage:**
- First request: 7950 tokens (2500 + 5000 + 400 + 50)
- Subsequent requests (cache hit): 450 tokens (400 context + 50 query)

**Cost per request (with caching):**
- Anthropic Claude: ~$0.0009 per request
- OpenAI GPT-4: ~$0.0011 per request
- **Negligible cost increase for massive UX improvement**

---

## Benefits

### 1. Natural Conversation Flow
- No need to say "like I just asked about X"
- Jarvis automatically remembers recent context
- Feels like talking to someone who's paying attention

### 2. Self-Learning
- Jarvis sees what tools failed
- Can call `check_tool_logs` to understand errors
- Adjusts approach based on recent failures
- Example: "Last time sudo was needed, let me use it now"

### 3. Workflow Continuity
- Multi-step projects don't need re-explanation
- "Build X" → "Test it" → "Add Y" flows naturally
- Jarvis tracks in-progress work

### 4. Contradiction Detection
- Catches inconsistencies ("You just said it was hot!")
- Can ask clarifying questions
- More human-like interaction

### 5. Tool Efficiency
- Avoids redundant tool calls
- "Did you X?" → "Yes, I just did X" (no tool needed)
- Reduces API costs and latency

---

## When Context Falls Short

If the automatic context window is too short, Jarvis can **use existing tools** to load more:

```
User: "What did we discuss earlier about Bitcoin?"

Jarvis: [Auto-context only has last 3 conversations (not about Bitcoin)]
        [Calls search_conversations with "Bitcoin"]
        [Finds: "Earlier you asked about Bitcoin price, it was $91k"]
```

**Available tools for extended memory:**
- `get_recent_conversations` - Chronological history (no query needed)
- `search_conversations` - Topic-based search (requires query)
- `search_memory` - Long-term memory search
- `semantic_recall` - Semantic memory search

**This is by design:** Auto-context covers 90% of cases efficiently. For deeper history, explicit tool calls are appropriate.

---

## Comparison with Other Approaches

### Option A: Stateless (Original - Before Auto-Context)

**Pros:**
- ✅ Simplest implementation
- ✅ No context pollution
- ✅ Lowest token usage

**Cons:**
- ❌ No context between cycles
- ❌ Awkward conversation flow
- ❌ Requires explicit "remember what I said" prompts

### Option B: Stateful (OpenAI Responses API)

**Pros:**
- ✅ Server-side state management
- ✅ Automatic context chaining

**Cons:**
- ❌ OpenAI-specific (not provider-agnostic)
- ❌ Major refactor required
- ❌ Less control over context
- ❌ Harder to debug

### Option C: Redis Session Memory

**Pros:**
- ✅ Fast in-memory storage
- ✅ Structured working memory
- ✅ TTL-based cleanup

**Cons:**
- ❌ New dependency (Redis)
- ❌ More infrastructure to manage
- ❌ Serialization complexity

### Option D: Auto-Context (Current Implementation)

**Pros:**
- ✅ Natural conversation flow
- ✅ Provider-agnostic (works with all LLMs)
- ✅ No new dependencies
- ✅ Uses existing conversation logging
- ✅ Configurable (tune window size/time)
- ✅ Self-learning from failures
- ✅ Graceful degradation (if disabled, still works)

**Cons:**
- ⚠️ 9x token increase per request (mitigated by caching)
- ⚠️ Context may include irrelevant info (filtered by time)

**Winner:** Option D balances UX, implementation complexity, and cost.

---

## Testing

### Test Scenario 1: Hot/Cold Contradiction

```bash
# Terminal 1
./orchestrator/orchestrator_v2.py cloud "Today is super hot"
# Response: "I understand"

# Wait 2 minutes
./orchestrator/orchestrator_v2.py cloud "Today is cold"
# Response: "Wait, you just said it was hot 2 minutes ago!"
```

### Test Scenario 2: Workflow Continuation

```bash
# Build Flask API
./orchestrator/orchestrator_v2.py cloud "Build a Flask API"
# Response: "Flask API built on port 8091"

# Test it (context-aware)
./orchestrator/orchestrator_v2.py cloud "Test it"
# Response: "Testing port 8091... Health check passed"
```

### Test Scenario 3: Failure Learning

```bash
# First attempt (will fail)
./orchestrator/orchestrator_v2.py cloud "Install Redis"
# Response: "Installation failed - permission denied"

# Retry (learns from failure)
./orchestrator/orchestrator_v2.py cloud "Try again"
# Response: [Checks logs, uses sudo] "Redis installed successfully"
```

### Disable for Testing

```bash
# In cloud.env or local.env
AUTO_CONTEXT_ENABLED=false

# Now each cycle is stateless (original behavior)
```

---

## Troubleshooting

### Context Not Loading

**Check:**
1. `AUTO_CONTEXT_ENABLED=true` in config
2. Recent conversations exist in database:
   ```bash
   sqlite3 data/jarvis_memory.db "SELECT COUNT(*) FROM conversations WHERE timestamp > datetime('now', '-10 minutes');"
   ```
3. Time window is reasonable (`AUTO_CONTEXT_MINUTES=5` shipped cloud)

### Context Too Long/Expensive

**Solution:** Reduce window size or time:
```bash
AUTO_CONTEXT_WINDOW=2
AUTO_CONTEXT_MINUTES=5
```

### Context Missing Important Info

**Solution:** Increase window:
```bash
AUTO_CONTEXT_WINDOW=5
AUTO_CONTEXT_MINUTES=15
```

Or use explicit tools:
```
User: "What did we discuss earlier about X?"
Jarvis: [Calls get_recent_conversations or search_conversations]
```

### Debug Mode

```bash
export JARVIS_DEBUG=1
./orchestrator/orchestrator_v2.py cloud "test query"
# Will show context loading in stderr
```

---

## Future Enhancements

### Potential Improvements

1. **Semantic Relevance Scoring**
   - Only inject context if semantically related to current query
   - Reduces token waste on unrelated conversations

2. **Session Grouping**
   - Auto-detect related conversation clusters
   - "Build tetris" + "Test it" + "Add scores" = one session

3. **Structured Working Memory**
   - Extract key facts from context into structured format
   - Example: `{"active_project": "Flask API", "port": 8091, "status": "running"}`

4. **Redis Cache Layer**
   - Cache recent conversations in Redis for faster access
   - SQLite query can be slow for high-frequency requests

5. **Context Summarization**
   - Summarize long conversations before injecting
   - Reduces token count while preserving meaning

---

## Related Documentation

- `CONVERSATION_STATE_ARCHITECTURE.md` - Overall state management
- `MEMORY_SYSTEM.md` - Long-term memory tools
- `MULTI_TURN_ORCHESTRATION.md` - Multi-turn within single cycle
- `DUAL_DATABASE_SYSTEM.md` - Database architecture

---

## Summary

The Auto-Context System transforms Jarvis from a **stateless question-answering assistant** into a **context-aware conversational partner**. 

**Key Benefits:**
- ✅ Natural conversation flow
- ✅ Self-learning from failures
- ✅ Workflow continuity
- ✅ Minimal cost increase (with prompt caching)
- ✅ No new dependencies
- ✅ Works with all LLM providers

**Configuration:**
```bash
AUTO_CONTEXT_ENABLED=true
AUTO_CONTEXT_WINDOW=2
AUTO_CONTEXT_MINUTES=5
```

**This is the "sweet spot" between stateless simplicity and stateful complexity.**
