# Auto Mode - Smart Adaptive Response Formatting


![speech-modes-info-graph](images/speech-modes-info-graph.jpeg)
---

## The 3 Modes Explained

### 1. `JARVIS_RESPONSE_STYLE="casual"` (Voice-Friendly)
**Always** condenses responses for voice output using word limits.

**Word Limits:**
- Q&A responses: `JARVIS_QA_WORD_LIMIT` (default: 75 words)
- Multi-turn summaries: `JARVIS_MULTI_TURN_WORD_LIMIT` (default: 50 words)
- Tool confirmations: 35 words (hardcoded)

**Also strips from speech:**
- `stash://` references
- Long URLs (>30 chars)
- File paths (simplified to filename)

**Examples**:
```
"What time is it?" 
→ "It's 12:34 AM on November 13th"

"Start the tetris server"
→ "Tetris server started successfully with PID 128712"

"Generate an image of a cat"
→ "Image generated and saved to stash"  (NOT stash://space_xxx/f_xxx)
```

**When to use**: Voice mode - everything spoken through speakers should be concise.

---

### 2. `JARVIS_RESPONSE_STYLE="detailed"` (Best for CLI/Debugging)
**Always** uses full LLM response with complete context.

**Examples**:
```
"What time is it?"
→ "The current time is 12:34 AM on Wednesday, November 13th, 2025. 
   I've retrieved this information from the system clock."

"Start the tetris server"
→ "The tetris server has been successfully started!

   Here's what was done:
   1. Located project at ~/jarvis-workspace/projects/tetris-game/
   2. Activated Python virtual environment
   3. Started Flask server in background (PID: 128712)
   4. Verified server responding on port 5000
   
   Server accessible at http://localhost:5000"
```

**When to use**: CLI testing, debugging, log review - when you need full technical context including URLs and stash refs.

---

### 3. `JARVIS_RESPONSE_STYLE="auto"` (RECOMMENDED - Smart Adaptive)
**Intelligently decides** based on tool type and complexity.

#### **Auto Mode Logic**:

```python
# Multi-turn (turn_num > 0) → Always format summary
if turn_num > 0:
    return _format_multi_turn_summary()  # 50 word limit, strips refs

# Search tools → Always format for voice
if tool in SEARCH_TOOLS:
    return _format_single_turn_casual()  # Remove URLs, summarize

# Simple data tools → Keep if short, condense if long
elif tool in SIMPLE_TOOLS:
    if response_length <= 25 words:
        return AS_IS  # Already short, keep it
    else:
        return _format_single_turn_casual()  # Condense

# Complex/action tools → Keep detailed if long response
elif tool in COMPLEX_TOOLS:
    if response_length > 50 words:
        return AS_IS  # Keep full context (GAP: may include stash refs)
    else:
        return _format_single_turn_casual()  # Condense short results

# Default (unlisted tools) → Condense
else:
    return _format_single_turn_casual()
```

---

## Tool Categories

### SEARCH_TOOLS (always formatted, URLs stripped):
```python
SEARCH_TOOLS = {
    'search_memory', 'semantic_recall', 'recall', 'search_conversations',
    'brave_search', 'mcp_duckduckgo_search', 'mcp_fetch_fetch',
    'get_recent_conversations'
}
```

### SIMPLE_TOOLS (keep if <25 words):
```python
SIMPLE_TOOLS = {
    'get_time', 'crypto_price', 'get_weather', 'calculate',
    'get_system_info', 'get_disk_usage'
}
```

### COMPLEX_TOOLS (keep detailed if >50 words):
```python
COMPLEX_TOOLS = {
    'opencode', 'execute_bash', 'send_webhook', 'api_call',
    'generate_image', 'canvas_operations'
}
```

**Known GAP:** Complex tools with >50 word responses bypass stash/URL stripping. TODO in code.

---

## Auto Mode Examples

**Simple Query (Short Response)**:
```
"What time is it?"  
Tool: get_time
Response length: 8 words
→ "It's 12:34 AM on November 13th"  (kept as-is, already short)
```

**Search Query (Always Formatted)**:
```
"Search memory for webhook info"
Tool: search_memory  
→ "Found 3 webhook memories: URL, logger endpoint, and server port"  
   (formatted for voice, URLs removed)
```

**Simple Action (Short Response)**:
```
"Start the tetris server"
Tool: execute_bash
Response length: ~15 words
→ "Tetris server started on port 5000"  (condensed)
```

**Complex Build (Detailed Response)**:
```
"Build me a complete e-commerce website"
Tool: opencode
Response length: 80+ words
→ FULL DETAILED RESPONSE (kept as-is because >50 words)
```

**Multi-Turn (Always Formatted)**:
```
"Start the tetris server and save the URL to memory"
Turn 1: search_memory → find instructions
Turn 2: execute_bash → start server
Turn 3: remember → save URL
→ "Tetris server started on port 5000, URL saved to memory"  
   (always formatted for multi-turn, summarizes ALL tools)
```

---

## When to Use Each Mode

| Mode | Best For | Word Limits | Strips Technical Refs |
|------|----------|-------------|----------------------|
| **casual** | Voice mode | Q&A: 75, Multi: 50, Tool: 35 | Yes |
| **detailed** | CLI, debugging | No limit | No |
| **auto** | Smart assistant | Varies by tool | Mostly (see GAP) |

---

## Configuration

### Set in config (permanent)
```bash
# Edit config/cloud.env or config/local.env
JARVIS_RESPONSE_STYLE="auto"

# Optional: Customize word limits
JARVIS_QA_WORD_LIMIT=75
JARVIS_MULTI_TURN_WORD_LIMIT=50
```

### Env var override (one-off testing)
```bash
JARVIS_RESPONSE_STYLE=auto ./jarvis
# or
JARVIS_RESPONSE_STYLE=auto ./orchestrator/orchestrator_v2.py cloud "query" --speak
```

---

## Testing Auto Mode

```bash
# Simple query - should be short
JARVIS_RESPONSE_STYLE=auto ./orchestrator/orchestrator_v2.py cloud "what time is it" --json | jq -r '.speech'

# Search query - should be formatted (no URLs)
JARVIS_RESPONSE_STYLE=auto ./orchestrator/orchestrator_v2.py cloud "search memory for webhook" --json | jq -r '.speech'

# Simple action - should be short
JARVIS_RESPONSE_STYLE=auto ./orchestrator/orchestrator_v2.py cloud "start tetris server" --json | jq -r '.speech'

# Complex build - should be detailed (if response >50 words)
JARVIS_RESPONSE_STYLE=auto ./orchestrator/orchestrator_v2.py cloud "use opencode to build a flask API" --json | jq -r '.speech'
```

---

## Summary

| Mode | Behavior | Best For |
|------|----------|----------|
| `casual` | Always condense with word limits | Voice mode |
| `detailed` | Always full response | CLI/debugging |
| `auto` | Smart: short for simple, detailed for complex | Mixed usage |

**Auto mode gives you the best of both worlds:**
- Simple tasks → Short responses
- Complex builds (>50 words) → Detailed responses  
- Search queries → Always formatted (no URLs)
- Multi-turn operations → Formatted summaries of ALL tools

---

**Related Docs:**
- `docs/CASUAL_VS_DETAILED_MODE.md` - Detailed comparison
- `config/cloud.env` - Configuration options

---

*Last updated: 2026-02-02*  
*Updated: Corrected word limits, added stash/URL stripping info, documented GAP*
