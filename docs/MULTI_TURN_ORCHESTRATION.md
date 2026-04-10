# Multi-Turn Orchestration

**Status:** ✅ Implemented & Tested (Nov 2025)

Jarvis now supports **multi-turn conversations** where the LLM can chain multiple tool calls to complete complex tasks.

## Problem Solved

### Before (Single-Turn)
```
User: "Send webhook to X and save the URL"
→ Jarvis calls send_webhook ✅
→ Jarvis says "I'll save that URL" ❌ (but never calls remember)
→ Later: User searches memory → Nothing found 😞
```

**Issue:** Jarvis would promise to do things but only execute ONE tool, leaving tasks incomplete.

### After (Multi-Turn)
```
User: "Send webhook to X and save the URL"
→ Turn 1: Calls send_webhook ✅
→ Turn 2: Calls remember (saves URL) ✅
→ Turn 3: Q&A response "Done! Webhook sent and URL saved." ✅
→ Later: User searches memory → URL found! 🎉
```

## How It Works

1. **Loop Structure**
   - Orchestrator enters a loop (max 10 turns)
   - Each iteration: LLM decides to call a tool OR finish
   - Context from previous tools feeds into next decision

2. **Context Tracking**
   - Every tool result is stored in `conversation_context`
   - LLM sees: Original query + all previous tool results
   - Enables intelligent chaining (e.g., "build then verify")

3. **Completion Signal**
   - When LLM returns `intent: "qa"` → Task complete
   - Final response summarizes all actions taken
   - Returns: `tools_used` array + accumulated data

4. **Safety Limits**
   - Max 10 turns per request (prevents infinite loops)
   - Each tool failure can trigger retry logic
   - Total execution bounded by timeouts

## Real-World Examples

### Example 1: Webhook + Memory
```bash
$ ./orchestrator_v2.py cloud "send webhook to X and save URL"

🔧 Executing tool: send_webhook
✅ Tool succeeded

🔧 Executing tool: remember (turn 2)
✅ Tool succeeded

💬 Task complete after 2 tool(s):
   "Webhook sent to X (status 200) and URL saved to memory as 'webhook_url'"
```

### Example 2: OpenCode + Verify
```bash
$ ./orchestrator_v2.py cloud "use opencode to build tetris, then check if files exist"

🔧 Executing tool: opencode
✅ Tool succeeded (built: ~/jarvis-workspace/tetris/)

🔧 Executing tool: execute_bash (turn 2)
✅ Tool succeeded (ls shows: tetris.py, README.md)

💬 Task complete after 2 tool(s):
   "Tetris game built! Verified: 2 files created in workspace."
```

### Example 3: Complex Research Flow
```bash
$ ./orchestrator_v2.py cloud "search for rust frameworks, summarize top 3, save to memory"

🔧 Executing tool: mcp_duckduckgo_search
✅ Tool succeeded (found 10 results)

🔧 Executing tool: remember (turn 2)
✅ Tool succeeded (saved: "top rust frameworks")

💬 Task complete after 2 tool(s):
   "Found and saved: Actix-web, Rocket, Axum. Details stored in memory."
```

## Technical Details

### Files Modified

#### 1. `orchestrator/orchestrator_v2.py`
**Key Changes:**
- Added `max_turns = 10` loop in `process()`
- Added `conversation_context` list to track tool results
- Added `_build_turn_context()` helper to format context for LLM
- Modified return structure to include `tools_used` array

**New Code Structure:**
```python
def process(self, transcript: str) -> Dict[str, Any]:
    max_turns = 10
    conversation_context = []
    tools_used = []
    accumulated_data = {}
    
    for turn_num in range(max_turns):
        # Build context for this turn
        if turn_num == 0:
            turn_input = transcript
        else:
            turn_input = self._build_turn_context(transcript, conversation_context)
        
        # Route and execute
        route = self.router.route(turn_input)
        
        if route["intent"] == "tool":
            # Execute tool, add to context, continue
            result = self.executor.execute(...)
            conversation_context.append({"tool": ..., "result": ...})
            continue
        
        elif route["intent"] == "qa":
            # Task complete - return summary
            return {"speech": ..., "tools_used": tools_used, ...}
    
    # Max turns reached
    return {"speech": "Complexity limit reached", ...}
```

#### 2. `orchestrator/router_v2.py`
**System Prompt Updates:**
- Added "MULTI-TURN CONVERSATIONS" section
- Provided examples of chaining tools
- Emphasized: "Call tools, don't just promise"
- Explained completion signal (Q&A intent = done)

**Key Prompt Addition:**
```
MULTI-TURN CONVERSATIONS (NEW):
You can now call MULTIPLE tools in sequence! After each tool executes:
1. Review the result
2. Decide if you need to call another tool OR if the task is complete
3. If complete, respond with Q&A intent to summarize results

EXAMPLES:
User: "Send webhook to X and save the URL"
→ Turn 1: Call 'send_webhook' 
→ Turn 2: Call 'remember' to save the URL
→ Turn 3: Q&A response "Done! Webhook sent and URL saved."
```

### Context Building

The `_build_turn_context()` method formats previous tool results for the LLM:

```python
def _build_turn_context(self, original_query: str, conversation_context: list) -> str:
    context_parts = [f"Original user request: {original_query}\n"]
    context_parts.append("Tools executed so far:")
    
    for i, ctx in enumerate(conversation_context, 1):
        tool_name = ctx["tool"]
        result_summary = self._build_llm_result_context_preview(tool_name, ctx["result"])
        context_parts.append(f"\n{i}. {tool_name}")
        context_parts.append("   Result Meta: ok=..., result_truncated=..., result_chars_shown=..., result_chars_total=...")
        context_parts.append("   Result or Result Preview: valid JSON shown to the LLM")
    
    context_parts.append("\n\nDetermine if you need to:")
    context_parts.append("1. Call another tool to complete the request")
    context_parts.append("2. Respond directly (task complete)")
    
    return "\n".join(context_parts)
```

Notes:
- Full prior tool results are still kept in `conversation_context`.
- The preview builder only changes how those results are presented back to the LLM on later turns.
- Large results are now shown as valid JSON previews instead of raw sliced `json.dumps(...)` fragments, which reduces malformed-context issues during multi-turn tool recovery.

### Return Structure

**Single-Turn (Old):**
```json
{
  "speech": "...",
  "ok": true,
  "tool_used": "send_webhook",
  "data": {...}
}
```

**Multi-Turn (New):**
```json
{
  "speech": "...",
  "ok": true,
  "tools_used": ["send_webhook", "remember"],
  "data": {
    "send_webhook": {...},
    "remember": {...}
  }
}
```

## Configuration

No configuration needed! Multi-turn is enabled by default for all modes (cloud/local).

**Environment Variables (Optional):**
```bash
# Response style (affects final response formatting)
JARVIS_RESPONSE_STYLE="casual"   # Default: natural conversational
# JARVIS_RESPONSE_STYLE="detailed"  # Raw tool outputs
# JARVIS_RESPONSE_STYLE="auto"      # Smart mode based on tool
```

## Safety & Limits

1. **Max Turns:** 10 iterations per request
   - Prevents infinite loops
   - Logs warning if limit reached
   - Returns partial results + explanation

2. **Tool Timeouts:** Each tool has its own timeout
   - `opencode`: 180 seconds
   - Most tools: 30 seconds
   - Total request bounded by sum of tool timeouts

3. **Retry Logic:** Still works within multi-turn
   - Failed tool can retry (max 1 retry)
   - LLM can try different approach
   - Can use `check_tool_logs` to debug

4. **Memory Safety:** Tools can't interfere with each other
   - Each tool runs in isolation
   - Results passed via JSON (immutable)
   - No shared state except context object

## Testing

### Run Multi-Turn Tests

```bash
# Test webhook + memory
./orchestrator/orchestrator_v2.py cloud \
  "send webhook to https://webhook.site/test and save the URL"

# Verify memory
./orchestrator/orchestrator_v2.py cloud \
  "search memory for webhook"

# Test OpenCode + verify
./orchestrator/orchestrator_v2.py cloud \
  "use opencode to create hello world script, then run it with bash"
```

### Expected Output

Look for these indicators of multi-turn execution:

```
🔧 Executing tool: send_webhook
✅ Tool succeeded

🔧 Executing tool: remember (turn 2)  ← Turn number shown
✅ Tool succeeded

💬 Task complete after 2 tool(s):     ← Summary of tools used
```

## Debugging

### View Tool Call Logs

```bash
# Check what tools were called
tail logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl | jq

# Look for multi-turn sequences
grep -A2 "turn_num" logs/tools/*.jsonl
```

### Common Issues

**Problem:** LLM calls unnecessary tools
```
Solution: Adjust system prompt to be more conservative
Location: orchestrator/router_v2.py (self.system_prompt)
```

**Problem:** Max turns reached too often
```
Solution: Increase max_turns in orchestrator_v2.py
Current: 10 turns (should be plenty for 99% of tasks)
```

**Problem:** Context too large (LLM slow)
```
Solution: Reduce context summary in _build_turn_context()
Current: 300 chars per tool result (adjustable)
```

## Future Enhancements

- [ ] Parallel tool execution (if tools are independent)
- [ ] Conversation branching (A/B decision trees)
- [ ] Tool dependency graph (optimize execution order)
- [ ] Streaming responses (show progress in real-time)
- [ ] User confirmation for sensitive multi-tool chains
- [ ] Cost tracking (LLM calls per multi-turn request)

## Related Documentation

- [Tool System](TOOL_SYSTEM.md) - How tools work
- [Router](ROUTER.md) - LLM-based routing logic
- [Memory System](MEMORY_SYSTEM.md) - Persistent knowledge
- [OpenCode Integration](OPENCODE.md) - Complex task agent

---

**Questions?** Check logs or review the test scenarios above.
