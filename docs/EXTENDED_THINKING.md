# Extended Thinking for Jarvis

**Status**: Research & Planning Phase

## Overview

Extended thinking allows the LLM to explicitly reason through complex decisions before responding. This makes AI decision-making more transparent and potentially more accurate.

## What is Extended Thinking?

### Claude Sonnet 4.5 Extended Thinking

**Yes, Sonnet 4.5 supports extended thinking!** Two methods:

#### Method 1: Extended Thinking Parameter (Anthropic API)
```python
response = anthropic.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=8096,
    thinking={
        "type": "enabled",
        "budget_tokens": 2000  # Tokens allocated for thinking
    },
    messages=[...]
)

# Response includes thinking block:
# response.thinking = "Let me think through this..."
# response.content = "Based on my reasoning..."
```

**How it works**:
- Model gets extra tokens for internal reasoning
- Thinking is separate from response
- You can see the reasoning process
- More accurate for complex decisions

**Cost**: Thinking tokens count toward input (but cheaper than regenerating)

#### Method 2: Sequential Thinking MCP Server

**What is it?**
An MCP server that provides structured thinking tools to the LLM.

**Tools it provides**:
- `think_step`: Break down problem into steps
- `analyze_options`: Compare multiple choices
- `reason_through`: Explicit chain-of-thought
- `make_decision`: Structured decision-making

**Advantages**:
- Works with any LLM (not just Claude)
- Structured reasoning (steps, options, pros/cons)
- Can be logged/audited
- Helps LLM make better decisions

## Current Jarvis Thinking

**Q**: "What is Jarvis doing when making decisions?"

**A**: Currently, Jarvis thinks "internally" (not visible):

```
User: "I'm excited about the Predator movie, don't want to miss it"
   ↓
[INTERNAL THINKING - Not Visible]
- Is this a question or a request?
- Do I need to search for info? → Yes
- Which tool? → duckduckgo_search
- Should I save this? → Hmm, public info, probably not needed
- User seems interested but didn't explicitly ask to remember
   ↓
[VISIBLE ACTIONS]
- Call mcp_duckduckgo_search
- Respond with date
- Don't call remember
```

**Problem**: We can't see why it decided not to save!

## Proposed Enhancements

### Option 1: Enable Extended Thinking (Anthropic Only)

**Where to add**: `lib/llm_provider.py` → `AnthropicProvider.chat_with_tools()`

```python
def chat_with_tools(..., enable_thinking: bool = False):
    if enable_thinking:
        params['thinking'] = {
            "type": "enabled",
            "budget_tokens": 2000
        }
    
    response = self.client.messages.create(**params)
    
    # Extract thinking if present
    if hasattr(response, 'thinking') and response.thinking:
        thinking_text = response.thinking[0].text
        # Log it or return it
        logger.info(f"LLM Thinking: {thinking_text}")
```

**Pros**:
- See exact reasoning for decisions
- Better understand grey area choices
- Can log thinking for analysis
- May improve accuracy

**Cons**:
- Only works with Anthropic models
- Adds latency (~1-2 seconds)
- Increases cost (thinking tokens)
- More complex to implement

### Option 2: Add Sequential Thinking MCP Server

**Installation**:
```bash
# Install sequential-thinking MCP server
npm install -g @modelcontextprotocol/server-sequential-thinking
# Or if it's a different package, install that

# Add to config/mcp-servers.json
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
      "enabled": true
    }
  }
}
```

**How Jarvis would use it**:

```
User: "Should I save the Predator release date?"
   ↓
Jarvis calls: think_step("Should I save movie release date to memory?")
   ↓
Thinking tool returns:
{
  "steps": [
    "1. Is this personal data? → No (public movie date)",
    "2. Did user express importance? → Yes (excited, don't want to miss)",
    "3. Will user need this later? → Maybe (future event)",
    "4. Is it easily re-searchable? → Yes (public info)",
    "5. Decision: Borderline - lean toward NO but offer to save"
  ]
}
   ↓
Jarvis responds: "Nov 7, 2025. Would you like me to remember this?"
```

**Pros**:
- Works with any LLM (OpenAI, Anthropic, Ollama)
- Structured reasoning (auditable)
- Can be toggled on/off per query
- Helps with complex decisions

**Cons**:
- Requires MCP server installation
- Adds extra tool call (latency)
- LLM has to decide when to use it
- May not always trigger

### Option 3: Conversation-Context Priority (Simplest)

**Enhancement to memory-first rule**:

```python
# In router_v2.py system prompt:

**CONVERSATION-CONTEXT RULE (NEW)**:
Before searching the web or calling external tools for factual questions:
1. FIRST check: search_conversations (did we just discuss this?)
2. THEN check: search_memory or semantic_recall (do I have this stored?)
3. ONLY IF NOT FOUND → use web search or other tools

Example:
User: "When does that movie come out?" (just discussed Predator)
→ Call search_conversations("movie") FIRST
→ Find it in recent context
→ Respond without re-searching web
```

**Pros**:
- Simple prompt enhancement
- No new dependencies
- Works immediately
- Reduces redundant web searches

**Cons**:
- Still relies on LLM following guidance
- Doesn't show reasoning
- Won't help with complex grey area decisions

## Recommendation: Hybrid Approach

### Phase 1: Quick Win (Do Now)
- ✅ Add conversation-context priority rule (Option 3)
- ✅ Update system prompt with future event guidance
- ✅ Test with more grey area scenarios

### Phase 2: Add Observability (Next Week)
- Add optional `--debug-thinking` flag to orchestrator
- When enabled, use Anthropic extended thinking
- Log LLM reasoning to `logs/thinking/`
- Analyze decision patterns

### Phase 3: Consider Sequential Thinking (Future)
- Test sequential-thinking MCP server on dev machine
- Evaluate if it improves grey area decisions
- If beneficial, add to production config

## Testing Extended Thinking

**Test Command**:
```bash
# If we enable extended thinking
./orchestrator/orchestrator_v2.py cloud --debug-thinking "I'm excited about the Predator movie, remember the date"

# Output would show:
# 🧠 LLM Thinking:
#    "User expressed excitement and said 'remember the date'
#     - Excitement signal: moderate importance
#     - Explicit 'remember': strong save signal
#     - Decision: SAVE with category='personal', importance=7"
#
# 🔧 Calling tool: remember
# 💬 Response: "Saved! Predator: Badlands releases November 7th."
```

## Cost Analysis

### Extended Thinking Costs

**Anthropic Pricing** (as of Nov 2025):
- Input tokens: $3.00 per 1M tokens
- Thinking tokens: $3.00 per 1M tokens (same as input)
- Output tokens: $15.00 per 1M tokens

**Example cost for auto-save decision**:
- System prompt + tools: ~12,000 tokens (cached)
- User query: ~50 tokens
- Thinking: ~500 tokens ($0.0015)
- Response: ~100 tokens ($0.0015)
- **Total added cost**: ~$0.003 per decision (~0.3 cents)

**With caching**:
- Cache hit on system prompt: 90% off
- Thinking tokens: Still full price
- **Effective cost**: ~$0.0015 per decision

**Conclusion**: Very cheap (under a cent) to enable thinking for complex decisions.

## Implementation Checklist

If we decide to implement extended thinking:

- [ ] Add `enable_thinking` parameter to `AnthropicProvider`
- [ ] Add thinking extraction in response parsing
- [ ] Add `--debug-thinking` flag to orchestrator
- [ ] Create `logs/thinking/` directory
- [ ] Update system prompt to request thinking for grey area decisions
- [ ] Add thinking display in verbose mode
- [ ] Test with 10-20 grey area scenarios
- [ ] Document thinking patterns
- [ ] Decide if it should be always-on or opt-in

## Questions for User

1. **Do you want to see LLM thinking?** (debugging/transparency)
2. **Should thinking be always-on or opt-in?** (performance vs insight)
3. **Should we try sequential-thinking MCP server?** (requires setup)
4. **Is the cost acceptable?** (~0.3 cents per complex decision)

---

**Next Steps**: Await user feedback on which approach to pursue.

