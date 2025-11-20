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
│    - Tool Definitions (all 50+ tools)                   │
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

### Full Enhanced Transcript (Real Example)

```
╔══════════════════════════════════════════════════════════╗
║ RECENT CONVERSATION HISTORY (for context awareness)     ║
║ Last 3 conversation(s) in past 10 minutes             ║
╚══════════════════════════════════════════════════════════╝

─── Conversation #1 ───
User asked: What is Ethereum price?
Jarvis replied: Ethereum is currently priced at $3,031, down 2.7% today.
Tools used: crypto_price
✅ STATUS: Success
Model: claude-sonnet-4-5-20250929, Tools called: 1

─── Conversation #2 ───
User asked: What is Ethereum price?
Jarvis replied: Ethereum is $3,031, down 2.7% today.
✅ STATUS: Success
Model: claude-sonnet-4-5-20250929, Tools called: 0

─── Conversation #3 ───
User asked: Did you just check Ethereum?
Jarvis replied: Yes, Ethereum is $3,031, down 2.7% today.
✅ STATUS: Success
Model: claude-sonnet-4-5-20250929, Tools called: 0

╔══════════════════════════════════════════════════════════╗
║ CURRENT USER QUERY (what they just asked)               ║
╚══════════════════════════════════════════════════════════╝
Search for Python tutorials

INSTRUCTIONS:
- Use the above context to provide intelligent, context-aware responses
- Reference previous topics naturally when relevant
- Learn from failed attempts (check_tool_logs if needed)
- Catch contradictions ("You just said X, now saying Y?")
- Continue multi-step workflows seamlessly
- If context window is too short, you can call get_recent_conversations tool for more history
```

---

## Payload with FAILED Conversation

When a tool fails, it shows with ⚠️ status:

```
╔══════════════════════════════════════════════════════════╗
║ RECENT CONVERSATION HISTORY (for context awareness)     ║
║ Last 3 conversation(s) in past 10 minutes             ║
╚══════════════════════════════════════════════════════════╝

─── Conversation #1 ───
User asked: Install Redis
Jarvis replied: Installation failed with permission denied
Tools used: execute_bash
⚠️  STATUS: FAILED - Task did not complete successfully
   Consider: Using check_tool_logs to understand why
Model: claude-sonnet-4-5-20250929, Tools called: 1

─── Conversation #2 ───
User asked: Try again
Jarvis replied: Redis installed successfully
Tools used: check_tool_logs, execute_bash
✅ STATUS: Success
Model: claude-sonnet-4-5-20250929, Tools called: 2

╔══════════════════════════════════════════════════════════╗
║ CURRENT USER QUERY (what they just asked)               ║
╚══════════════════════════════════════════════════════════╝
Is Redis running now?

INSTRUCTIONS:
...
```

**Key Points:**
- ⚠️ FAILED status is **clearly marked**
- Includes suggestion: "Consider: Using check_tool_logs"
- LLM can see what failed and proactively investigate

---

## Structure Breakdown

### 1. Header Section
```
╔══════════════════════════════════════════════════════════╗
║ RECENT CONVERSATION HISTORY (for context awareness)     ║
║ Last 3 conversation(s) in past 10 minutes             ║
╚══════════════════════════════════════════════════════════╝
```
- **Purpose**: Visual separator, shows how many conversations and time window
- **Box Drawing**: Unicode characters (╔═╗║╚═╝) for clear visual separation

### 2. Conversation Blocks (repeated for each)
```
─── Conversation #1 ───
User asked: {user_query}
Jarvis replied: {jarvis_response}
Tools used: {tools_used_list}
✅ STATUS: Success  (or ⚠️ FAILED)
Model: {model_name}, Tools called: {count}
```

**Fields Included:**
- `user_query` - Exact question asked
- `jarvis_response` - Exact response given
- `tools_used` - JSON array of tool names (e.g., `["crypto_price", "remember"]`)
- `success` - Boolean (true = ✅, false = ⚠️)
- `metadata` - Model used, tool count

**Ordering**: Oldest first (#1), newest last (#3) - chronological order

### 3. Current Query Section
```
╔══════════════════════════════════════════════════════════╗
║ CURRENT USER QUERY (what they just asked)               ║
╚══════════════════════════════════════════════════════════╝
{current_transcript}
```
- **Purpose**: Clear separation between context and current request
- **No ambiguity**: LLM knows this is what user just asked

### 4. Instructions Section
```
INSTRUCTIONS:
- Use the above context to provide intelligent, context-aware responses
- Reference previous topics naturally when relevant
- Learn from failed attempts (check_tool_logs if needed)
- Catch contradictions ("You just said X, now saying Y?")
- Continue multi-step workflows seamlessly
- If context window is too short, you can call get_recent_conversations tool for more history
```
- **Purpose**: Remind LLM how to use the context
- **Consistent**: Always included, ensures proper behavior

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

2. **Tool Definitions** (50+ tools):
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
**File:** `orchestrator/orchestrator_v2.py`

```python
def _build_conversation_context(self, current_query: str) -> str:
    """Build enhanced transcript with context."""
    db = get_memory_db()
    
    # Get recent conversations
    recent = db.get_recent_conversations(limit=self.auto_context_window)
    
    # Filter by time window
    cutoff = datetime.now() - timedelta(minutes=self.auto_context_minutes)
    relevant = [c for c in recent if c['timestamp'] > cutoff]
    
    # Build formatted context
    context_parts = ["╔══════════════..."]
    context_parts.append("║ RECENT CONVERSATION HISTORY...")
    
    for i, conv in enumerate(reversed(relevant), 1):
        context_parts.append(f"─── Conversation #{i} ───")
        context_parts.append(f"User asked: {conv['user_query']}")
        context_parts.append(f"Jarvis replied: {conv['jarvis_response']}")
        
        if conv.get('tools_used'):
            context_parts.append(f"Tools used: {tools}")
        
        if conv['success']:
            context_parts.append("✅ STATUS: Success")
        else:
            context_parts.append("⚠️  STATUS: FAILED - Task did not complete successfully")
            context_parts.append("   Consider: Using check_tool_logs to understand why")
    
    context_parts.append("╔══════════════...") 
    context_parts.append("║ CURRENT USER QUERY...")
    context_parts.append(current_query)
    context_parts.append("\nINSTRUCTIONS:...")
    
    return "\n".join(context_parts)
```

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
╔══════════════════════════════════════════════════════════╗
║ RECENT CONVERSATION HISTORY (for context awareness)     ║
...
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
2. ✅ Tool definitions (50+ tools)
3. ✅ **Enhanced transcript** with:
   - Last 3 conversations (configurable)
   - User queries and Jarvis responses
   - Tools used in each conversation
   - Success/failure status
   - Model metadata
   - Current user query
   - Usage instructions

**Why It Works:**
- Clear visual structure (box drawing)
- Chronological ordering (oldest first)
- Explicit status indicators (✅/⚠️)
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

