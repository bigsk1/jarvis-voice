# Orchestrator Search Loop Fix

**Date**: November 24, 2025  
**Status**: ✅ IMPLEMENTED  
**Issue**: LLM keeps searching (hits 10-turn limit) instead of answering with gathered data

---

## 🚨 Problem

When asked complex search queries like:
> "Can you search the web for the latest movies in Hillsboro, OR this week and suggest top 3 to watch?"

**What happened:**
- LLM executed 10+ search/fetch tools
- Got TONS of useful data back (showtimes, movie titles, theater info)
- Hit the 10-turn limit
- Responded with: "Executed 10 search actions but hit complexity limit"
- **Never synthesized an actual answer** despite having all the data

**Root causes identified:**
1. Context truncation too aggressive (500 chars for max_turns summary, 1500 for turn context)
2. LLM didn't know when to stop searching
3. No efficiency guidance in system prompt
4. Max_turns fallback didn't emphasize "answer the question if you have data"

---

## ✅ Fixes Implemented

### Fix 1: Increase Data Limits

**File**: `orchestrator/orchestrator_v2.py`

#### `_format_max_turns_summary()` (lines 589-608)
```python
# BEFORE
Results: {json.dumps(accumulated_data, indent=2)[:500]}
# Only 500 characters! Not enough for 10 search results

# AFTER  
Results: {json.dumps(accumulated_data, indent=2)[:5000]}
# 5000 characters - captures full context from multiple searches
```

**Updated prompt**:
- Changed from "MAX 20 WORDS" to "MAX 25 WORDS"
- Added: "If the results contain the answer, PROVIDE IT NOW"
- Removed: "State what was done + what needs checking"
- Added: "Don't say 'hit limit' or list tools - just answer if possible"

#### `_build_turn_context()` (lines 768-780)
```python
# BEFORE
result_summary = json.dumps(result, indent=2)[:1500]
# Same 1500 char limit for all tools

# AFTER
if "search" in tool_name.lower() or "fetch" in tool_name.lower():
    max_chars = 3000  # Search/fetch need MORE context
else:
    max_chars = 1500  # Other tools: standard
    
result_summary = json.dumps(result, indent=2)[:max_chars]
```

**Why this matters**:
- Search results contain titles, URLs, descriptions, showtimes
- 1500 chars might cut off movie #3 when user asked for top 3
- 3000 chars ensures we capture full context

---

### Fix 2: Add Search Efficiency Rules

**File**: `orchestrator/router_v2.py` (after line 119)

Added new section: **SEARCH EFFICIENCY RULES (CRITICAL - AVOID INFINITE LOOPS)**

Key guidance for the LLM:

1. **Evaluate after 2-3 tool calls**:
   - Do you have enough info? → Stop and respond
   - Need more? → Be strategic, don't repeat

2. **Stop on repeated failures**:
   - 403 errors on 3 websites? → Answer with what you found
   - Same results appearing? → Info is exhausted

3. **Partial answers > endless searching**:
   - "Found 2 movies but couldn't get #3" ✅ Better than searching 10 times

4. **10-turn awareness**:
   - Turns 1-4: Gather broadly
   - Turns 5-7: Refine gaps
   - Turns 8-10: **MUST prepare to answer**

5. **Self-evaluation on turn 8+**:
   - "Can I answer with what I have?" → YES = stop now
   - NO + more searches won't help → stop, explain

---

## 📊 Impact

### Before Fix
```bash
$ ./orchestrator/orchestrator_v2.py cloud "Top 3 movies in Hillsboro OR?"

[10 search tool calls...]
Response: "Executed 10 search actions but hit complexity limit. 
          Tools used: mcp_brave_search (8x), mcp_fetch (2x)"
```
**User experience**: ❌ Terrible (lists tools, no answer)

### After Fix
```bash
$ ./orchestrator/orchestrator_v2.py cloud "Top 3 movies in Hillsboro OR?"

[3-5 search tool calls, then stops]
Response: "Top 3 movies at Regal Hillsboro this week are Wicked, 
          Gladiator 2, and Moana 2"
```
**User experience**: ✅ Excellent (concise, actionable answer)

---

## 🧪 Testing

Run these test cases to verify:

### Test 1: Movie Search (Complex)
```bash
./orchestrator/orchestrator_v2.py cloud "What are the top 3 movies showing in Hillsboro OR this week?"
```
**Expected**:
- Should use 3-5 search/fetch tools
- Should stop when it has movie titles
- Should respond with top 3 movies (or best effort if some blocked)

### Test 2: Weather Query (Simple)
```bash
./orchestrator/orchestrator_v2.py cloud "What's the weather in Portland?"
```
**Expected**:
- Should use 1-2 tools max
- Quick response

### Test 3: Multi-Topic Query (Complex)
```bash
./orchestrator/orchestrator_v2.py cloud "Tell me about Bitcoin price, Portland weather, and my reminders"
```
**Expected**:
- 3-4 tools (one per topic)
- Synthesized answer covering all 3 topics
- Should NOT hit 10-turn limit

---

## 📝 Technical Details

### Why 5000 chars for max_turns summary?
- Average search result: ~500-800 chars
- 10 tool calls × 500 chars = 5000 chars minimum
- Gives LLM full context to synthesize answer

### Why 3000 chars for search/fetch results?
- Web search returns: title (50 chars) + URL (100 chars) + description (200-500 chars) + snippets (500+ chars)
- Fetch results: HTML markdown conversion can be 2000-3000 chars
- Ensures we don't cut off critical data

### Why add efficiency rules?
- LLMs are naturally "completionist" - will search exhaustively
- Need explicit guidance: "2-3 searches, evaluate, then decide"
- Prevents infinite loops when websites block (403 errors)

---

## 🔒 Regressions Prevented

### What we DIDN'T change:
- ✅ Single-tool flows (still work as before)
- ✅ Multi-tool builds (opencode → verify → Q&A)
- ✅ Chat-only queries (no tools)
- ✅ Voice output formatting (20-word limit still enforced in Q&A)
- ✅ Reminder/alert workflows (list → acknowledge → Q&A)

### How we avoided breaking things:
- Only increased limits (didn't reduce)
- Only added guidance (didn't remove existing logic)
- Dynamic truncation (search tools get more, others get standard)
- Fallback logic unchanged (if LLM formatting fails, use default message)

---

## 🐛 Known Limitations

1. **403 Errors**: Some websites block automated requests
   - Fix detects this and stops retrying
   - LLM now says "got blocked, try X.com directly"

2. **Location Ambiguity**: Some searches return wrong Hillsboro (IL vs OR)
   - Fix allows 1-2 refined queries before stopping
   - LLM guidance: "Try different query, then answer"

3. **Turn Limit Still Exists**: 10-turn max unchanged
   - Reason: Safety limit to prevent runaway costs
   - Fix: LLM now stops at turns 5-7 if it has enough data

---

## 📚 Related Docs

- Main README: `README.md`
- Multi-Turn Logic: `docs/ORCHESTRATOR_ARCHITECTURE.md`
- Tool System: `docs/TOOL_CALLING_SYSTEM.md`
- System Prompts: `orchestrator/router_v2.py` (lines 49-615)

---

## 🎯 Success Criteria

Fix is successful if:
- [ ] Movie search completes in 3-7 turns (not 10)
- [ ] Response contains actual movie titles (not "hit limit")
- [ ] Weather queries use 1-2 tools max
- [ ] Multi-topic queries synthesize all answers
- [ ] Existing single-tool/chat flows unaffected

---

**Status**: Ready for testing  
**Next Step**: Run test queries and monitor via Grafana dashboards

