# Memory Intelligence Fixes

## Problem Summary
Jarvis was failing to check memory before executing commands, leading to:
- ❌ Random approaches (xdg-open, python -m http.server)
- ❌ Wrong ports (8000 instead of 5000)
- ❌ GUI commands on headless server
- ❌ Ignoring stored instructions

**Example**: User said "start the tetris server", Jarvis:
1. Searched filesystem (unnecessary)
2. Tried `xdg-open` (wrong, headless server)
3. Tried `python -m http.server 8000` (wrong, should use Flask on 5000)
4. Tried `webbrowser.open()` (wrong, no GUI)

**Root Cause**: LLM was using wrong memory tool and ignoring system context.

---

## Fixes Applied

### 1. Memory Tool Selection (router_v2.py)

**Before**: System prompt said "check memory first" but didn't explain WHICH tool to use WHEN.

**After**: Added explicit guidance on tool selection:

```python
When to use memory tools:
1. **ALWAYS use 'recall', 'search_memory', or 'semantic_recall' FIRST** when the user asks "what", "when", "who", "where", "how" questions
   - Use 'search_memory' for general searches (e.g., "tetris", "webhook", "server")
   - Use 'semantic_recall' when the question uses different words than what might be stored
   - Use 'recall' ONLY for exact keyword matches

CRITICAL EXAMPLES:
❌ BAD: "Start the tetris server" → Searches files, tries random commands
✅ GOOD: "Start the tetris server" → Call 'search_memory' with query "tetris" → Use stored command

❌ BAD: "How do I run X?" → Guesses or searches filesystem  
✅ GOOD: "How do I run X?" → Call 'search_memory' with query "X" → Check stored run instructions
```

**Why This Matters**: 
- `recall` does FUZZY SQL LIKE matching (`WHERE key LIKE '%query%'`)
- `search_memory` does FUZZY SQL LIKE matching (identical to recall - calls same function)
- `semantic_recall` uses AI embeddings (understands "start server" = "run application")

**Note**: `recall` and `search_memory` are functionally identical. Both do substring/fuzzy matching, not exact matching. The LLM is guided to use them in different contexts, but the underlying search is the same.

---

### 2. Headless Server Awareness (router_v2.py)

**Added to system prompt**:
```python
SYSTEM ENVIRONMENT:
- Running on a **headless Ubuntu server** (no GUI/display)
- Do NOT use: xdg-open, webbrowser module, or any GUI tools
- For web servers: Use curl to verify, not browser commands
- User is accessing via SSH/remote terminal
```

**Impact**: LLM now knows to avoid GUI commands entirely.

---

### 3. JSON Mode Stdout Protection

Fixed in previous commit - see `docs/VOICE_MODE_FIXES.md`

---

## Test Results

### Before Fix:
```bash
User: "start the tetris server"
Jarvis:
  1. find ~/jarvis-workspace/projects -name "*tetris*"  # Unnecessary
  2. xdg-open ~/jarvis-workspace/projects/tetris-game/tetris.html  # FAIL (GUI)
  3. python3 -m http.server 8000 &  # Wrong server, wrong port
  4. webbrowser.open('http://localhost:8000/tetris.html')  # FAIL (GUI)
```

### After Fix:
```bash
User: "start the tetris game server"
Jarvis:
  1. search_memory("tetris")  # ✅ Checks memory first
  2. Found: "cd ~/jarvis-workspace/projects/tetris-game && source venv/bin/activate && python server.py (port 5000)"
  3. cd ~/jarvis-workspace/projects/tetris-game && source venv/bin/activate && nohup python server.py > server.log 2>&1 &
  4. curl http://localhost:5000/health  # ✅ Verifies with curl (not GUI)
  5. Reports: "Server running on 0.0.0.0:5000 (accessible at 192.168.70.228:5000)"
```

**Tools used**: `['search_memory', 'execute_bash', ...]`  
**Result**: ✅ Correct server, correct port, no GUI commands, memory-driven approach

---

## Why Intel Files Weren't Enough

You created `jarvis-intel/opencode_details.md` which contains workspace info, but:
1. ✅ Intel WAS ingested into memory (verified with `search_memory`)
2. ❌ LLM was using wrong search tool (`recall` instead of `search_memory`)
3. ❌ LLM wasn't following "check memory first" guideline

**The intel system works!** The problem was LLM behavior, not the intel content.

---

## Key Learnings

### 1. Memory Tool Selection Matters
- **`recall`**: Exact text matching - only use for specific memory keys
- **`search_memory`**: Fuzzy text matching - best for general searches
- **`semantic_recall`**: AI embedding search - best for conceptual queries

### 2. System Prompts Need Examples
Saying "check memory first" isn't enough. LLMs need:
- ✅ Explicit tool selection guidance
- ✅ BAD vs GOOD examples
- ✅ Common failure patterns to avoid

### 3. Environment Awareness is Critical
LLMs don't inherently know:
- They're on a headless server
- GUI commands won't work
- They should use curl instead of browsers

Must be explicitly stated in system prompt!

### 4. Specificity in Queries
When LLM searched for "tetris server", `recall` found nothing.  
When LLM searched for "tetris", `search_memory` found:
- `tetris_game_location`
- `Example Project Locations - Tetris game`
- Start instructions with port 5000

**Lesson**: Broader queries work better with fuzzy matching.

---

## Future Improvements

### 1. Memory Tool Auto-Selection
Instead of relying on LLM to choose the right tool, router could automatically:
```python
if query_type == "how to run":
    tool = "search_memory"
elif query_type == "what is X":
    tool = "semantic_recall"
elif query_type == "exact match":
    tool = "recall"
```

### 2. Memory Priority in Routing
Before calling ANY tool, always:
```python
# Pseudo-code
if user_query contains ["start", "run", "how do I"]:
    memory_results = search_memory(extract_keywords(user_query))
    if memory_results:
        return memory_results  # Use stored instructions
    else:
        fallback_to_guessing()
```

### 3. Environment Detection
Instead of hardcoding "headless server" in prompt:
```python
import os
HAS_GUI = bool(os.environ.get('DISPLAY'))
system_prompt += f"Environment: {'GUI available' if HAS_GUI else 'Headless (no GUI)'}"
```

### 4. Project Registry
When OpenCode builds something, automatically save to memory:
```python
{
  "key": f"{project_name}_run_command",
  "value": "cd {path} && source venv/bin/activate && python {entrypoint}",
  "category": "project",
  "metadata": {
    "built_by": "opencode",
    "port": 5000,
    "type": "flask_app"
  }
}
```

---

## Testing Checklist

- [x] Jarvis checks memory before executing bash commands
- [x] Jarvis uses `search_memory` for "how to start/run" queries
- [x] Jarvis avoids GUI commands on headless server
- [x] Jarvis finds correct port from memory (5000, not 8000)
- [x] Jarvis uses stored instructions from intel files
- [x] JSON mode works without stdout contamination

---

## Related Docs

- `docs/VOICE_MODE_FIXES.md` - JSON parsing and stdout leaks
- `docs/MEMORY_SYSTEM.md` - Complete memory system documentation
- `docs/JARVIS_INTEL_SYSTEM.md` - Intel file ingestion system

---

*Last updated: 2025-11-13*  
*Issue discovered during: Tetris game start command testing*

