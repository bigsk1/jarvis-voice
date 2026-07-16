# Auto-Context Payload Structure

## Overview

This document shows **exactly** what gets sent to the LLM when auto-context is enabled.

---

## The Complete Flow

```
┌─────────────────────────────────────────────────────────┐
│ 1. User says: "Hey Jarvis"                             │
│    Transcript: "Did you just check Ethereum?"          │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 2. Orchestrator.process(transcript)                    │
│    if auto_context_enabled:                            │
│       enhanced = _build_conversation_context(transcript)│
│    # delegates to ContextAssembler                     │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 3. Query Database (last 3 conversations, 10 min)       │
│    SELECT * FROM conversations                          │
│    WHERE timestamp > NOW() - 10 minutes                 │
│    ORDER BY timestamp DESC LIMIT 3                      │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 4. Build Enhanced Transcript (see below)               │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 5. Send to LLM Provider (Anthropic/OpenAI/Ollama)      │
│    router.route(enhanced_transcript)                    │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 6. LLM Processes:                                       │
│    - System Prompt (with auto-context instructions)    │
│    - Tool Definitions (selected Tool RAG set)           │
│    - Enhanced Transcript (with context)                 │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 7. LLM Responds                                         │
│    - Understands "Did you check Ethereum?" refers to    │
│      previous conversation                              │
│    - Answers from context (no tool call needed)        │
└─────────────────────────────────────────────────────────┘
```

---

## Exact Payload Structure

Built by `ContextAssembler.build_conversation_context` in `orchestrator/context_assembler.py`.

### Full Enhanced Transcript (Real Example)

```
=== RECENT CONVERSATION HISTORY ===
Last 3 conversation(s) in past 10 minutes

[Previous Exchange 1]
User: What is Ethereum price?
Assistant: Ethereum is currently priced at $3,031, down 2.7% today.
Tools used: crypto_price
Status: Success
Model: claude-sonnet-4-5-20250929, Tools called: 1

[Previous Exchange 2]
User: What is Ethereum price?
Assistant: Ethereum is $3,031, down 2.7% today.
Status: Success
Model: claude-sonnet-4-5-20250929, Tools called: 0

[Previous Exchange 3]
User: Did you just check Ethereum?
Assistant: Yes, Ethereum is $3,031, down 2.7% today.
Status: Success
Model: claude-sonnet-4-5-20250929, Tools called: 0

=== CURRENT USER QUERY ===
Search for Python tutorials

Instructions:
- Use the conversation history to provide context-aware responses
- Reference previous topics naturally when relevant
- Continue multi-step workflows seamlessly
```

---

## Payload with FAILED Conversation

When a conversation was stored with `success=false`, the status line is marked FAILED and suggests `check_tool_logs`:

```
=== RECENT CONVERSATION HISTORY ===
Last 2 conversation(s) in past 10 minutes

[Previous Exchange 1]
User: Install Redis
Assistant: Installation failed with permission denied
Tools used: execute_bash
Status: FAILED - Task did not complete successfully
Consider using check_tool_logs to understand why
Model: claude-sonnet-4-5-20250929, Tools called: 1

[Previous Exchange 2]
User: Try again
Assistant: Redis installed successfully
Tools used: check_tool_logs, execute_bash
Status: Success
Model: claude-sonnet-4-5-20250929, Tools called: 2

=== CURRENT USER QUERY ===
Is Redis running now?

Instructions:
- Use the conversation history to provide context-aware responses
- Reference previous topics naturally when relevant
- Continue multi-step workflows seamlessly
```

**Key Points:**
- FAILED status is clearly marked with `Status: FAILED - Task did not complete successfully`
- Includes suggestion: `Consider using check_tool_logs to understand why`
- LLM can see what failed and proactively investigate

---

## Structure Breakdown

### 1. Header Section
```
=== RECENT CONVERSATION HISTORY ===
Last 3 conversation(s) in past 10 minutes
```
- **Purpose**: Plain-text separator; shows how many conversations and the time window

### 2. Conversation Blocks (repeated for each)
```
[Previous Exchange 1]
User: {user_query}
Assistant: {jarvis_response}
Tools used: {tools_used_list}
Status: Success  (or Status: FAILED - Task did not complete successfully)
Model: {model_name}, Tools called: {count}
```

**Fields Included:**
- `user_query` - Exact question asked
- `jarvis_response` - Exact response given
- `tools_used` - List of tool names (e.g., `crypto_price, remember`) when present
- `success` - Boolean (`true` → `Status: Success`, `false` → FAILED + check_tool_logs hint)
- `metadata` - Model used, tool count (when present)

**Ordering**: Oldest first (Exchange 1), newest last — chronological order after reversing the DB result set

### 3. Current Query Section
```
=== CURRENT USER QUERY ===
{current_transcript}
```
- **Purpose**: Clear separation between context and current request
- **No ambiguity**: LLM knows this is what user just asked

### 4. Instructions Section
```
Instructions:
- Use the conversation history to provide context-aware responses
- Reference previous topics naturally when relevant
- Continue multi-step workflows seamlessly
```
- **Purpose**: Remind LLM how to use the context
- **Consistent**: Always included when auto-context injects history

---

## Token Count Impact

### Without Auto-Context:
```
System Prompt:   2,500 tokens (cached)
Tools:           5,000 tokens (cached)
User Query:         50 tokens
────────────────────────────────────
Total Input:     7,550 tokens
Actual Cost:        50 tokens (with cache)
```

### With Auto-Context (3 conversations):
```
System Prompt:   2,500 tokens (cached)
Tools:           5,000 tokens (cached)
Context Block:     400 tokens (3 conversations)
User Query:         50 tokens
────────────────────────────────────
Total Input:     7,950 tokens
Actual Cost:       450 tokens (with cache)
```

**Cost Increase:** 9x tokens (50 → 450)
**Actual Cost:** ~$0.0009 per request (negligible!)

---

## LLM's Perspective

When the LLM receives this, it sees:

1. **System Prompt** (from `router_v2.py`):
   - Instructions on how to be Jarvis
   - Tool usage rules
   - **Auto-context instructions** (NEW!)
   - Voice output formatting rules

2. **Tool Definitions** (selected Tool RAG set):
   - JSON schema for each tool
   - When to use each tool
   - Parameter requirements

3. **Enhanced Transcript** (shown above):
   - **Recent context** (what just happened)
   - **Current query** (what user wants now)
   - **Instructions** (how to use context)

**Result:** LLM has full awareness of recent interactions!

---

## Code Location

### Where Context is Built:
**Routing entry point:** `orchestrator/orchestrator_v2.py`

**Actual implementation:** `orchestrator/context_assembler.py`

```python
def _build_conversation_context(self, current_query: str) -> str:
    # Orchestrator compatibility wrapper
    return self._get_context_assembler().build_conversation_context(current_query)
```

The helper module also owns:
- web `conversation_history` formatting via `_format_conversation_context(...)`
- multi-turn tool context assembly via `_build_turn_context(...)`
- result preview shaping used when prior tool data is carried into the next turn

### Where Context is Injected:
**File:** `orchestrator/orchestrator_v2.py`

```python
def process(self, transcript: str, ...):
    # Auto-inject context
    if self.auto_context_enabled:
        enhanced_transcript = self._build_conversation_context(transcript)
    else:
        enhanced_transcript = transcript

    # Route with enhanced transcript
    route = self.router.route(enhanced_transcript)
    ...
```

---

## Debugging

### Enable Debug Output:
```bash
JARVIS_DEBUG=1 python3 orchestrator/orchestrator_v2.py cloud "your query"
```

**You'll see:**
```
================================================================================
DEBUG: Enhanced Transcript Being Sent to LLM:
================================================================================
=== RECENT CONVERSATION HISTORY ===
Last 3 conversation(s) in past 10 minutes

[Previous Exchange 1]
User: ...
Assistant: ...
Status: Success
...
=== CURRENT USER QUERY ===
your query

Instructions:
- Use the conversation history to provide context-aware responses
- Reference previous topics naturally when relevant
- Continue multi-step workflows seamlessly
================================================================================
```

---

## Configuration

**File:** `config/cloud.env` or `config/local.env`

```bash
# Enable/disable auto-context
AUTO_CONTEXT_ENABLED=true

# How many conversations to include
AUTO_CONTEXT_WINDOW=3

# Time window in minutes
AUTO_CONTEXT_MINUTES=10
```

---

## Summary

**What Gets Sent:**
1. ✅ System prompt (with auto-context instructions)
2. ✅ Tool definitions (selected Tool RAG set)
3. ✅ **Enhanced transcript** with:
   - Last 3 conversations (configurable)
   - User queries and Jarvis responses
   - Tools used in each conversation
   - Success/failure status
   - Model metadata
   - Current user query
   - Usage instructions

**Why It Works:**
- Clear plain-text section headers
- Chronological ordering (oldest first)
- Explicit status indicators (`Status: Success` / `Status: FAILED`)
- Instructions at the end (how to use context)
- Separation between context and current query

**Result:**
- LLM understands recent interactions
- Avoids redundant tool calls
- Learns from failures
- Catches contradictions
- Continues workflows naturally

---

**Related Docs:**
- `AUTO_CONTEXT_SYSTEM.md` - Feature overview
- `CONVERSATION_STATE_ARCHITECTURE.md` - Architecture design
- `MEMORY_SYSTEM.md` - Long-term memory tools
