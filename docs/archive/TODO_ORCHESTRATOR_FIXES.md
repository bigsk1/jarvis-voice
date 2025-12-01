# Orchestrator Fixes - COMPLETED ✅

**Status**: ✅ IMPLEMENTED  
**Date Identified**: November 24, 2025  
**Date Completed**: November 24, 2025  
**Implementation Details**: See `docs/ORCHESTRATOR_SEARCH_LOOP_FIX.md`

---

## 🚨 Issue: LLM Looping Without Final Answer

### Problem
When asked: **"What are the top 3 movies in Portland, OR?"**

**What happened:**
```bash
Turn 1-10: mcp_brave_search_brave_web_search (8 times), mcp_fetch_fetch (2 times)
Result: "Reached complexity limit after 10 actions. Tools used: [long list]..."
```

**Issue**: The response lists ALL tool calls used (very verbose for voice output!)

**Expected**: A proper answer like "The top 3 movies are X, Y, Z" OR at minimum "I found showtimes at Regal Movies but couldn't get specific titles. Try checking their website directly."

### Root Causes

1. **No "Force Final Answer" Logic**
   - Orchestrator hits max_turns (10) and just stops
   - Never asks LLM to synthesize an answer from gathered data
   - Returns generic "complexity limit" message

2. **Voice Output Issues**
   - CLI mode speaks the full response through speakers
   - Listing 10 tool names is terrible UX for voice
   - Response style (auto/casual/detailed) not being applied to max_turns response

3. **Context Truncation**
   - `conversation_context` truncated to 1500 chars
   - Movie titles/showtimes might be cut off
   - LLM doesn't see full data from previous searches

### Proposed Fixes (DO LATER)

#### Fix 1: Add "Final Answer" Turn
```python
# In orchestrator_v2.py, around line 116 (inside the loop)
for turn_num in range(max_turns):
    # BEFORE routing, check if this is the last turn
    if turn_num == max_turns - 1:
        # Force final answer mode
        final_answer_prompt = f"""
IMPORTANT: This is your FINAL turn. You MUST provide a direct answer now.

Original question: {transcript}

Review all the tool results you've gathered and provide the best answer you can.
If you don't have perfect information, give a partial answer or explain what you found.

DO NOT call any more tools. Just respond directly.
"""
        turn_input = self._build_turn_context(final_answer_prompt, conversation_context)
        route = self.router.route(turn_input, force_qa=True)  # New parameter
```

#### Fix 2: Better Max Turns Response
```python
# In orchestrator_v2.py, when max_turns is reached
if turn_num == max_turns - 1 and route["intent"] == "tool":
    # LLM still wants to call tools, but we're out of turns
    # Force a summary response instead of listing tools
    
    tools_summary = f"used {len(set(tools_used))} tools"
    
    # Apply response style
    response_style = os.environ.get('JARVIS_RESPONSE_STYLE', 'casual').lower()
    
    if response_style == 'casual':
        final_speech = "I searched extensively but ran into complexity limits. Can you try asking in a different way?"
    elif response_style == 'detailed':
        final_speech = f"I executed {len(tools_used)} searches but hit the 10-turn limit before finding a complete answer. Please try rephrasing your question or being more specific."
    else:  # auto
        # For voice: keep it SHORT
        if sys.stdout.isatty():
            final_speech = f"I searched but hit limits. Details: {tools_summary}"
        else:
            final_speech = "I couldn't complete that search. Can you be more specific?"
```

#### Fix 3: Increase Context for Search Tools
```python
# In _build_turn_context(), increase limit for search results
def _build_turn_context(self, original_query, context):
    # ...existing code...
    
    for item in context:
        tool_name = item.get("tool")
        result_json = json.dumps(item.get("result"), ensure_ascii=False)
        
        # Larger truncation for search tools
        if tool_name in ["mcp_brave_search_brave_web_search", "mcp_fetch_fetch"]:
            max_chars = 3000  # More space for search results
        else:
            max_chars = 1500  # Default
        
        context_text += f"\nTool: {tool_name}\nResult: {result_json[:max_chars]}\n"
```

#### Fix 4: System Prompt Update (router_v2.py)
Add to system prompt:
```
EFFICIENCY RULES:
- After 3-4 tool calls, seriously evaluate if you can answer with what you have
- If a website blocks you (403), don't retry - move on or answer with what you found
- It's better to give a partial answer than to search endlessly
- If you're close to the turn limit, provide your best answer now
```

---


```

---

## Testing Checklist (Before Marking Complete)

- [ ] Ask: "What are the top 3 movies in Hillsboro?"
  - Should provide an answer (even if partial)
  - Should NOT list all 10 tool calls in voice output
  - Should NOT speak in CLI mode

- [ ] Ask: "What's the weather?" (simple query)
  - Should complete in 1-2 turns
  - Should provide direct answer

- [ ] Ask: "Tell me about Bitcoin, the stock market, and quantum computing" (complex)
  - May hit turn limit
  - Should synthesize a response from gathered data
  - Should not just say "complexity limit reached"

---


