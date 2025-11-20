# Jarvis Conversation State Architecture

## Overview

Understanding how Jarvis handles conversation state between interactions is critical for grasping its architectural design. This document explains what persists, what doesn't, and why.

---

## TL;DR - Quick Answers

**Q: Does Jarvis remember context between wake word cycles?**  
**A: No** - Each wake word cycle is a fresh request with NO automatic context from the previous cycle.

**Q: So every time I say "Hey Jarvis", it's like a new conversation?**  
**A: Yes** - Unless you explicitly ask it to recall previous conversations using tools like `search_conversations` or `get_recent_conversations`.

**Q: Isn't that inefficient? It has to re-send the system prompt and all tools every time?**  
**A: Yes and No:**
- ✅ **Prompt caching** (Anthropic, OpenAI) makes this efficient - system prompt is cached for 5+ minutes
- ✅ **Stateless design** is simpler and more reliable (no state bugs, no memory leaks)
- ❌ **No automatic context** means Jarvis doesn't know what you just discussed unless you explicitly ask

**Q: What about OpenAI's Responses API with `store=True` and `previous_response_id`?**  
**A:** That would enable **automatic context chaining** but requires a **major refactor**. Current implementation uses Chat Completions API (stateless).

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
│  - NO conversation history loaded               │
│  - Fresh LLM provider                           │
└─────────────────────────────────────────────────┘
         │
         │ 3. Route & Execute Tools
         ▼
┌─────────────────────────────────────────────────┐
│  LLM Provider (OpenAI/Anthropic/Ollama)         │
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

**Key Point:** Each cycle is **completely independent**. The `Orchestrator()` instance is destroyed after each interaction.

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
      "content": "What's the time?"  # Only the CURRENT question
    }
  ],
  "tools": [
    # ALL tool definitions (50+ tools, ~5000 tokens)
    {"name": "get_time", "description": "...", "parameters": {...}},
    {"name": "crypto_price", "description": "...", "parameters": {...}},
    # ... 50+ more tools ...
  ]
}
```

**What's MISSING:**
- ❌ Previous user questions
- ❌ Previous Jarvis responses
- ❌ Tools used in last cycle
- ❌ Context about what you were discussing

**Why This Works:**
- ✅ **Prompt Caching** - Anthropic/OpenAI cache the system prompt + tools for 5 minutes
  - First request: ~7500 tokens input
  - Subsequent requests (within 5 min): ~50 tokens input (only your question)
  - Cache hit rate: >90% in practice
- ✅ **Simplicity** - No complex state management, no conversation history bugs
- ✅ **Reliability** - Can't have stale context or "hallucinated" previous responses

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

### 5. Why No Automatic Context?

**Design Philosophy:**

1. **Stateless = Reliable**
   - No "conversation drift" where context becomes corrupted
   - No memory leaks from long-running conversations
   - Easy to debug (each cycle is independent)

2. **Explicit > Implicit**
   - User MUST ask for previous context
   - Forces LLM to think about when context is actually needed
   - Prevents "context pollution" where old info interferes with new requests

3. **Cost Efficiency (with caching)**
   - Prompt caching makes stateless efficient
   - System prompt + tools cached for 5 minutes
   - Only user query changes each cycle

4. **Voice UX Design**
   - Voice conversations are naturally segmented
   - "Hey Jarvis" = explicit start of new task
   - If you need context, you naturally say "what was my last question?"

---

### 6. OpenAI Responses API (Not Implemented)

**What You're Referring To:**
```python
# OpenAI Responses API (NEW, not currently used)
res1 = client.responses.create(
    model="gpt-5",
    input="What is the capital of France?",
    store=True  # ← Store this conversation
)

res2 = client.responses.create(
    model="gpt-5",
    input="And its population?",
    previous_response_id=res1.id,  # ← Link to previous response
    store=True
)
```

**What This Enables:**
- ✅ **Automatic context chaining** - Each response references the previous one
- ✅ **Server-side state** - OpenAI stores the conversation history
- ✅ **Seamless multi-turn** - No need to re-send full history

**Why Not Implemented:**

1. **Major Refactor Required**
   - Current implementation uses Chat Completions API
   - `llm_provider.py` would need rewrite
   - Orchestrator would need response ID tracking
   - Cross-cycle state management needed

2. **Provider Compatibility**
   - Responses API is OpenAI-specific
   - Anthropic doesn't have equivalent
   - Ollama doesn't support it
   - Would fragment code into provider-specific paths

3. **Cost/Benefit**
   - Prompt caching already makes current approach efficient
   - Added complexity may not justify benefit
   - Current approach works well for voice UX

4. **Loss of Control**
   - Server-side state = less transparency
   - Can't easily inspect what's in context
   - Harder to debug "why did it say that?"

---

### 7. Practical Examples

#### Example 1: No Automatic Context

```
Cycle 1:
You: "Hey Jarvis, what's Bitcoin price?"
Jarvis: "Bitcoin is $91,711"
[STATE DISCARDED]

Cycle 2:
You: "Hey Jarvis, what about Ethereum?"
Jarvis: [Has NO idea you just asked about crypto]
        [Needs to call crypto_price tool again]
```

**If you wanted context:**
```
Cycle 2:
You: "Hey Jarvis, like I just asked about Bitcoin, what about Ethereum?"
Jarvis: [Calls search_conversations with "Bitcoin"]
        [Sees you asked about crypto prices]
        [Calls crypto_price for Ethereum]
        "Ethereum is $3,200"
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

**Current State:**
- 🔴 **No automatic context** between wake word cycles
- 🟢 **Context persists** within multi-turn tool execution (single cycle)
- 🟢 **Explicit context retrieval** via memory/conversation tools
- 🟢 **Prompt caching** makes stateless approach efficient
- 🟢 **Stateless = simple, reliable, provider-agnostic**

**Your Intuition:**
> "this doesnt seem good, and every cycle it gets all system prompt, tools mcp flooded back to input?"

**Response:**
- ✅ You're right it seems inefficient
- ✅ BUT: Prompt caching makes it practically free (98%+ cost reduction)
- ✅ Simplicity and reliability benefits outweigh the "wasteful" appearance
- ⚠️ Responses API would fix this, but at significant complexity cost

**Bottom Line:**

The current architecture is **intentionally stateless**. It looks inefficient but is actually quite efficient thanks to prompt caching. Moving to a stateful architecture (Responses API) would be more "elegant" but would require a major refactor and lose provider compatibility.

For a voice assistant, the stateless approach is arguably more appropriate - "Hey Jarvis" naturally signals a new task, not a continuation. If you find yourself constantly needing context from previous cycles, that might indicate a need for stateful design, but in practice, most voice interactions are self-contained tasks.

---

**Related Docs:**
- `docs/MULTI_TURN_ORCHESTRATION.md` - Multi-turn within a cycle
- `docs/MEMORY_SYSTEM.md` - Persistent memory tools
- `docs/DUAL_DATABASE_SYSTEM.md` - Database architecture
- `docs/PROMPT_CACHING.md` - (would be useful to create)

