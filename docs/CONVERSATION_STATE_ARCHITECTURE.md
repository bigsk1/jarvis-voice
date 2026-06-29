# Jarvis Conversation State Architecture

## Overview

Understanding how Jarvis handles conversation state between interactions is critical for grasping its architectural design. This document explains what persists, what doesn't, and why.

---

## TL;DR - Quick Answers

**Q: Does Jarvis remember context between wake word cycles?**
**A: YES (now)** - Auto-context automatically loads recent conversations when enabled.

**Q: So every time I say "Hey Jarvis", it knows what I just asked?**
**A: Yes (if within time window):**
- `AUTO_CONTEXT_ENABLED=true` (default) - loads recent conversations automatically
- `AUTO_CONTEXT_WINDOW=3` - how many recent conversations to include
- `AUTO_CONTEXT_MINUTES=10` - only include conversations from last N minutes

**Q: How does the WebUI handle context?**
**A:** WebUI maintains conversation history client-side and passes it directly to the orchestrator via `conversation_history` parameter - different from terminal auto-context.

**Q: Isn't that inefficient? It has to re-send the system prompt and all tools every time?**
**A: Usually no. Prompt caching and provider-specific continuation reduce the pain:**
- ✅ **Prompt caching** (Anthropic, OpenAI, xAI when cache hits apply) - system/tool prompts can be discounted
- ✅ **Auto-context** provides conversation continuity from Jarvis' own saved state
- ✅ **xAI in-flight continuation** can avoid resending the same Jarvis tool result during one multi-tool request
- ✅ **OpenAI Responses in-flight continuation** can do the same for OpenAI when explicitly enabled

**Q: What about OpenAI's Responses API with `store=True` and `previous_response_id`?**
**A:** OpenAI Responses is now wired as an optional routing backend, including in-flight `previous_response_id` continuation for one active Jarvis client-tool loop. It is not used as persistent Web UI conversation memory. Saved Web UI follow-ups still use Jarvis local context and follow-up extraction.

---

## Architecture Deep Dive

### 1. The Voice Loop (Wake Word Detection)

```
┌─────────────────────────────────────────────────┐
│  Wake Word Detection (jarvis / jarvis-local)   │
└─────────────────────────────────────────────────┘
         │
         │ 1. Detect "Hey Jarvis"
         ▼
┌─────────────────────────────────────────────────┐
│  Transcribe Audio (question-orchestrator.sh)   │
└─────────────────────────────────────────────────┘
         │
         │ 2. Call orchestrator with transcript
         ▼
┌─────────────────────────────────────────────────┐
│  Orchestrator (orchestrator_v2.py)              │
│  - NEW Orchestrator() instance                  │
│  - Chooses web-history vs DB auto-context path  │
│  - Fresh LLM provider                           │
└─────────────────────────────────────────────────┘
         │
         │ 3. Route & Execute Tools
         ▼
┌─────────────────────────────────────────────────┐
│  LLM Provider (xAI/OpenAI/Anthropic/Ollama)     │
│  - System prompt (FULL)                         │
│  - All tool definitions (FULL)                  │
│  - User query (ONLY current transcript)         │
└─────────────────────────────────────────────────┘
         │
         │ 4. Execute tools, get response
         ▼
┌─────────────────────────────────────────────────┐
│  Log to Database (memory_db.conversations)      │
└─────────────────────────────────────────────────┘
         │
         │ 5. Speak response & RETURN to wake word
         ▼
┌─────────────────────────────────────────────────┐
│  Back to Wake Word Detection                    │
│  ⚠️ ALL STATE DISCARDED                         │
└─────────────────────────────────────────────────┘
```

**Key Point:** Each cycle creates a new `Orchestrator()` instance, but it can still reload recent context on demand:
- `conversation_history` from the web app for web chats
- DB-backed auto-context for CLI/TUI when `AUTO_CONTEXT_ENABLED=true`

---

### 2. What Gets Sent to LLM Every Cycle

```python
# Every single wake word cycle sends:
{
  "messages": [
    {
      "role": "system",
      "content": "<FULL SYSTEM PROMPT>"  # ~2500 tokens
    },
    {
      "role": "user",
      "content": """
        === RECENT CONVERSATION HISTORY ===
        Last 3 conversation(s) in past 10 minutes

        [1] User: What's the price of bitcoin?
            Jarvis: Bitcoin is $103,664

        [2] User: And ethereum?
            Jarvis: Ethereum is $3,200

        === CURRENT REQUEST ===
        What about solana?
      """  # Auto-context prepended to current question
    }
  ],
  "tools": [
    # Full tool catalog (78 manifests at last verification; profile filters apply)
    {"name": "get_time", "description": "...", "parameters": {...}},
    {"name": "crypto_price", "description": "...", "parameters": {...}},
    # ... 50+ more tools ...
  ]
}
```

**What's NOW Included (with auto-context):**
- ✅ Previous user questions (from AUTO_CONTEXT_WINDOW)
- ✅ Previous Jarvis responses (from AUTO_CONTEXT_WINDOW)
- ✅ Time-filtered (AUTO_CONTEXT_MINUTES, default 10 min)

**Why This Works:**
- ✅ **Prompt Caching** - Anthropic/OpenAI cache the system prompt + tools for 5 minutes
  - First request: ~7500 tokens input
  - Subsequent requests (within 5 min): ~50 tokens input (only your question + context)
  - Cache hit rate: >90% in practice
- ✅ **Auto-Context** - Recent conversations automatically included
- ✅ **Configurable** - Disable if you want fully stateless behavior

---

### 3. Multi-Turn Orchestration (WITHIN a Single Cycle)

**Important:** Multi-turn tool calling happens **WITHIN** a single wake word cycle, not between cycles.

```
User: "Build a Flask API and test it"

┌──────────────────────────────────────┐
│ Single Wake Word Cycle:              │
│                                      │
│  Turn 1: Call 'opencode' tool       │
│    ↓                                 │
│  Turn 2: Call 'api_call' tool       │
│    ↓                                 │
│  Turn 3: Q&A response                │
│    "Flask API running on port 8091"  │
└──────────────────────────────────────┘

STATE DISCARDED AFTER THIS CYCLE
```

**Within-Cycle Context:**
```python
# orchestrator_v2.py - process() method
conversation_context = []  # Context WITHIN this cycle
tools_used = []            # Tools used THIS cycle

for turn_num in range(max_turns):
    # Build context from previous turns (in THIS cycle)
    turn_input = self._build_turn_context(transcript, conversation_context)

    # Route & execute
    route = self.router.route(turn_input)
    result = self.executor.execute(tool_name, arguments)

    # Add to THIS cycle's context
    conversation_context.append({
        "turn": turn_num,
        "tool": tool_name,
        "result": result
    })
```

After the cycle completes:
- `conversation_context` is discarded
- `tools_used` is logged to database
- Next wake word = fresh start

---

### 4. What IS Persistent

```
┌─────────────────────────────────────────────────┐
│  SQLite Database (data/jarvis_memory.db)        │
├─────────────────────────────────────────────────┤
│                                                 │
│  1. knowledge_base table                        │
│     - Facts, preferences, memories              │
│     - Saved via 'remember' tool                 │
│     - Retrieved via 'search_memory',            │
│       'semantic_recall' tools                   │
│                                                 │
│  2. conversations table                         │
│     - Full conversation history                 │
│     - Every question + response logged          │
│     - Retrieved via 'get_recent_conversations', │
│       'search_conversations' tools              │
│                                                 │
└─────────────────────────────────────────────────┘
```

**How to Access Previous Context:**

| Scenario | User Query | Tool Used | What Happens |
|----------|-----------|-----------|--------------|
| **Recent history** | "What did I just ask?" | `get_recent_conversations` | Gets last 10 conversations (chronological) |
| **Topic search** | "Did I mention Bitcoin?" | `search_conversations` | Searches conversation logs for keyword |
| **Recall facts** | "Where is my Flask API?" | `search_memory` or `semantic_recall` | Searches knowledge base |

---

### 5. Auto-Context Feature (Added 2025)

**Configuration (cloud.env / local.env):**
```bash
# Enable automatic conversation context loading
AUTO_CONTEXT_ENABLED=true

# How many recent conversations to include
AUTO_CONTEXT_WINDOW=3

# Only include conversations from last N minutes
AUTO_CONTEXT_MINUTES=10
```

**How It Works:**

1. **On each cycle**, orchestrator decides whether to use web history or DB auto-context
2. **Loads recent conversations** from `memory_db.conversations` table
3. **Filters by time** (only last N minutes)
4. **Prepends to user query** as "RECENT CONVERSATION HISTORY"

**WebUI vs Terminal:**
- **WebUI:** Passes `conversation_history` directly (client maintains state)
- **Terminal:** Uses auto-context from database (server loads state)

**Web thread block (`=== RECENT CONVERSATION CONTEXT ===`):** When the web app sends history, `jarvis-web/server/sockets/chat.py` builds prior turns without duplicating the **current** user message (already the live transcript). `ContextAssembler.format_conversation_context(...)` may add optional **gap timing** (local timestamp + relative time) when the anchor is unambiguous. This header is **not** the same as DB auto-context’s `=== RECENT CONVERSATION HISTORY ===`, but current Tool RAG compact extraction recognizes both web/current-request shapes and the older HISTORY + `Instructions:` auto-context shape. See `docs/TOOL_RAG_STRATEGY.md` for `signal_source` labels such as `current_request`, `trailing_request`, `original_user_request_tail`, and `legacy_history_strip`.

**Current ownership split:**
- `orchestrator/orchestrator_v2.py` selects the context path and passes the enhanced transcript into routing
- `orchestrator/context_assembler.py` owns context formatting, DB history assembly, turn-context construction, and preview shaping
- `orchestrator/response_formatter.py` owns final speech condensation after the LLM/tool phase is done

**Design Benefits:**
- ✅ Context without server-side session state
- ✅ Works across all providers (not OpenAI-specific)
- ✅ Configurable time window prevents stale context
- ✅ Can be disabled for fully stateless behavior

---

### 6. Provider-side response continuation

**The general pattern:**
```python
res1 = client.responses.create(
    model="gpt-5",
    input="What is the capital of France?",
    store=True
)

res2 = client.responses.create(
    model="gpt-5",
    input="And its population?",
    previous_response_id=res1.id,
    store=True
)
```

**What This Enables:**
- ✅ **Automatic context chaining** - Each response references the previous one
- ✅ **Server-side state** - OpenAI stores the conversation history
- ✅ **Seamless multi-turn** - No need to re-send full history

**Current Jarvis status:**

- **OpenAI Responses API:** optional for OpenAI tool-capable routing when `OPENAI_API_MODE=responses` and `OPENAI_RESPONSES_TOOLS=true`. It can also use in-flight `previous_response_id` + `function_call_output` when `OPENAI_RESPONSES_INFLIGHT_CONTINUATION=true`.
- **xAI SDK stored continuation:** wired only for in-flight Jarvis client-side tool loops. After Grok asks for a Jarvis tool and Jarvis executes it, the next router turn can send `previous_response_id` plus a structural `tool_result(...)`.
- **Saved Web UI follow-ups:** do not pass persisted provider `previous_response_id` yet. They use Jarvis recent conversation context plus compact structured follow-up data from `followup_extractor.py`.

**Why cross-request continuation is not the default yet:**

1. **Major Refactor Required**
   - The web conversation layer would need to persist provider response ids with provider, model, alias, timestamps, and expiry.
   - The orchestrator would need rules for when a same-conversation follow-up should trust provider state, when to ignore it, and when to fall back to local context.

2. **Provider Compatibility**
   - OpenAI Responses continuation is OpenAI-specific
   - xAI stored continuation is SDK-specific and time-limited
   - Anthropic doesn't have equivalent
   - Ollama doesn't support it
   - Would fragment code into provider-specific paths

3. **Cost/Benefit**
   - Prompt caching already makes current approach efficient
   - Jarvis local follow-up extraction is provider-neutral and inspectable
   - Added complexity may not justify benefit
   - Current approach works well for voice UX

4. **Loss of Control**
   - Server-side state = less transparency
   - Can't easily inspect what's in context
   - Harder to debug "why did it say that?"

---

### 7. Practical Examples

#### Example 1: Auto-Context in Action

```
Cycle 1:
You: "Hey Jarvis, what's Bitcoin price?"
Jarvis: "Bitcoin is $91,711"
[Logged to conversations table]

Cycle 2 (within 10 minutes):
You: "Hey Jarvis, what about Ethereum?"
Jarvis: [Auto-context loads: "User asked about Bitcoin → $91,711"]
        [Understands crypto context]
        [Calls crypto_price for Ethereum]
        "Ethereum is $3,200"
```

**After time window expires (10+ minutes later):**
```
Cycle 3:
You: "Hey Jarvis, what about Solana?"
Jarvis: [Auto-context is empty - too old]
        [Still calls crypto_price - tool handles it]
        "Solana is $148"
```

#### Example 2: Multi-Turn WITHIN Cycle

```
You: "Hey Jarvis, build a Flask API and test it"

SINGLE CYCLE (state persists WITHIN this cycle):
  Turn 1: Call opencode → Build Flask API
  Turn 2: Call api_call → Test endpoint
  Turn 3: Q&A → "Flask API running on port 8091, health check passed"

[All turns happen in ONE wake word cycle]
[Context is maintained WITHIN the cycle]
[After cycle ends, all state discarded]
```

#### Example 3: Using Memory Tools

```
Cycle 1:
You: "Hey Jarvis, use OpenCode to build a tetris game"
Jarvis: [Calls opencode]
        [Calls remember: "tetris_game: Built at ~/jarvis-workspace/projects/tetris on port 8091"]
        "Tetris game built and running on port 8091"
[STATE DISCARDED]

Cycle 2 (hours later):
You: "Hey Jarvis, start the tetris server"
Jarvis: [Calls search_memory with "tetris"]
        [Finds: "Built at ~/jarvis-workspace/projects/tetris on port 8091"]
        [Calls execute_bash to start server]
        "Tetris server started on port 8091"
```

**Key:** Memory tool made the information persistent across cycles.

---

### 8. Cache Mechanics (Why This Works)

**Anthropic Prompt Caching:**
```
Request 1 (00:00):
  System prompt: 2500 tokens → Cache miss, store for 5 min
  Tools: 5000 tokens → Cache miss, store for 5 min
  User query: 50 tokens
  Total input: 7550 tokens

Request 2 (00:01):
  System prompt: 2500 tokens → Cache HIT (free)
  Tools: 5000 tokens → Cache HIT (free)
  User query: 50 tokens
  Total input: 50 tokens (7500 cached)

Request 3 (00:02):
  System prompt: 2500 tokens → Cache HIT (free)
  Tools: 5000 tokens → Cache HIT (free)
  User query: 50 tokens
  Total input: 50 tokens (7500 cached)

Request 4 (05:01) [after 5 minutes]:
  System prompt: 2500 tokens → Cache miss, re-store
  Tools: 5000 tokens → Cache miss, re-store
  User query: 50 tokens
  Total input: 7550 tokens
```

**Cost Comparison:**

| Scenario | Input Tokens | Cached Tokens | Cost |
|----------|--------------|---------------|------|
| **Without caching** | 7550 per cycle | 0 | $0.003/cycle |
| **With caching (hit)** | 50 per cycle | 7500 | $0.00005/cycle |
| **Savings** | - | - | **98.4% reduction** |

**Why Stateless Works:**
- Cache hit rate in practice: >90%
- Conversations typically happen in bursts (< 5 min apart)
- Cost of stateless approach is negligible with caching

---

### 9. Comparison: Stateful vs Stateless

| Aspect | Stateful (Responses API) | Stateless (Current) |
|--------|--------------------------|---------------------|
| **Context between cycles** | ✅ Automatic | ❌ Manual (via tools) |
| **Implementation complexity** | ❌ High | ✅ Low |
| **Provider compatibility** | ❌ OpenAI only | ✅ All providers |
| **Debugging** | ❌ Server-side state, opaque | ✅ Each cycle independent |
| **Memory leaks** | ❌ Possible | ✅ Impossible |
| **Cost (with caching)** | ~Same | ~Same |
| **Voice UX fit** | ⚠️ May be too implicit | ✅ Explicit, clear |

---

### 10. When Would You Want Stateful?

**Good Use Cases:**
1. **Long coding sessions** - "Add a login page" → "Now add password reset" (context of what was built)
2. **Multi-step planning** - "Plan a trip to NYC" → "Add 2 more days" (context of plan)
3. **Debugging sessions** - "Why isn't X working?" → "Try approach Y" → "That didn't work" (full troubleshooting context)

**Current Workarounds:**
```
# Instead of automatic context:
You: "Hey Jarvis, I just asked you to build a Flask API. Now add a /users endpoint"

# Jarvis would:
# 1. Call search_conversations("Flask API")
# 2. Find previous OpenCode session
# 3. Call opencode to add endpoint
```

**Trade-off:**
- Stateful = More natural, fewer words needed
- Stateless = More explicit, clearer intent, easier to debug

---

### 11. What About Sequential Thinking MCP Tool?

**Your Observation:**
> "ok i added a mcp tool mcp_sequentialthinking and seems to work good both local and cloud, local seems to do a bit better, cloud had one thought and then stopped before proceeding thinking it could just pick it up again later"

**What's Happening:**

The sequential thinking tool allows the LLM to break down complex problems into steps. But:

1. **Cloud (Anthropic/OpenAI):**
   - May use fewer thinking steps due to higher confidence
   - Optimizes for efficiency (fewer turns = faster/cheaper)
   - May assume it can "pick up later" (expecting stateful behavior)

2. **Local (Ollama):**
   - More cautious, uses more thinking steps
   - Less confident, wants to plan more before acting
   - Better fit for complex reasoning tasks

**Implication for State Management:**

If the cloud provider expects to "pick up later", it's assuming **stateful context** exists. In current architecture:
- ❌ It CAN'T pick up later (state is discarded)
- ✅ It MUST complete thinking within current cycle

**Solution:**
- System prompt could be enhanced to emphasize "complete your thinking NOW, you won't remember it next cycle"
- OR: Implement some form of state persistence (big change)

---

### 12. Recommendations

#### If Staying Stateless (Current Approach):

**Pros:**
- ✅ Works well for voice UX
- ✅ Simple and reliable
- ✅ Provider-agnostic
- ✅ Easy to debug

**Enhancements:**
1. **Better system prompt** - Emphasize that context doesn't persist
2. **Auto-context tool** - Create a tool that automatically loads recent conversation context when beneficial
3. **Session tracking** - Group related wake word cycles into "sessions" for better conversation retrieval

#### If Going Stateful (Responses API):

**Pros:**
- ✅ More natural conversation flow
- ✅ Better for complex multi-step tasks
- ✅ Less explicit "remember what I just said" needed

**Cons:**
- ❌ Major refactor of `llm_provider.py`, `orchestrator_v2.py`
- ❌ OpenAI-specific (breaks Anthropic, Ollama)
- ❌ More complex state management
- ❌ Harder to debug

**Effort:** ~5-10 hours of development + testing

---

### 13. Summary

**Current State (Updated 2026):**
- 🟢 **Auto-context** loads recent conversations automatically (configurable)
- 🟢 **Context persists** within multi-turn tool execution (single cycle)
- 🟢 **WebUI** maintains conversation history client-side
- 🟢 **Prompt caching** makes approach efficient (98%+ cost reduction)
- 🟢 **Provider-agnostic** - works with OpenAI, Anthropic, Ollama

**Configuration:**
```bash
AUTO_CONTEXT_ENABLED=true   # Enable auto-context
AUTO_CONTEXT_WINDOW=3       # Recent conversations to include
AUTO_CONTEXT_MINUTES=10     # Time window
```

**Bottom Line:**

The architecture now provides **automatic context** via the auto-context feature while remaining provider-agnostic. The WebUI maintains its own conversation history, while terminal mode uses database-backed auto-context.

For voice assistant use, "Hey Jarvis" within the time window will have context from recent conversations. After the time window expires, it's a fresh start - which matches natural voice UX expectations.

---

**Related Docs:**
- `docs/MULTI_TURN_ORCHESTRATION.md` - Multi-turn within a cycle
- `docs/MEMORY_SYSTEM.md` - Persistent memory tools
- `docs/DUAL_DATABASE_SYSTEM.md` - Database architecture
- `docs/CASUAL_VS_DETAILED_MODE.md` - Response style modes

---

*Last updated: 2026-02-02*
*Major update: Added auto-context documentation, WebUI conversation handling*
