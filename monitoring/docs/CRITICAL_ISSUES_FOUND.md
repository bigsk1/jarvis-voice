# 🚨 CRITICAL ISSUES FOUND - November 24, 2025

After analyzing tool call logs and dashboard behavior, I've identified **TWO critical issues** that need immediate attention:

---

## Issue 1: LLM Looping Without Answering (max_turns_reached)

### 🐛 The Problem
When asked: **"What are the top 3 movies playing in Hillsboro, OR this week?"**

**What's happening:**
- Jarvis runs 10+ tool calls (brave_search, mcp_fetch_fetch)
- Gathers tons of relevant data about movie theaters and showtimes
- **NEVER PROVIDES AN ANSWER**
- Hits `max_turns_reached: true` limit
- Returns: "Sorry, I couldn't find what you were looking for" (or similar)

**Example from logs** (`/home/boss/jarvis-voice/logs/tools/tool-calls-2025-11-24.jsonl`):
```json
Line 8-27: 10 consecutive tool calls:
- mcp_brave_search_brave_web_search (8 times!)
- mcp_fetch_fetch (2 times)
- get_time (1 time)

Result: max_turns_reached, no answer given
```

### 🔍 Root Causes

#### Cause 1: Orchestrator Not Enforcing "Answer Now" After N Tools
**Location**: `orchestrator/orchestrator_v2.py`

The orchestrator has a `MAX_TURNS` limit (10) but doesn't **force** the LLM to provide a final answer. It just stops and returns a generic "I couldn't complete your request" message.

**Current logic**:
```python
if turn >= MAX_TURNS:
    print(f"⚠️  Reached maximum turns ({MAX_TURNS}), stopping.")
    return {
        "success": False,
        "response": "I've hit the complexity limit...",
        "max_turns_reached": True
    }
```

**Problem**: The LLM never sees the gathered data and is never asked to synthesize an answer.

#### Cause 2: LLM Not Realizing It Has Enough Data
**Location**: `orchestrator/router_v2.py` (system prompt)

The LLM keeps searching because:
1. It's not seeing the **full context** of previous tool results
2. The system prompt doesn't emphasize: **"If you have enough info, STOP and answer"**
3. The context truncation (1500 chars) might be cutting off key movie titles/showtimes

**Current context passing**:
```python
# In orchestrator_v2.py, line ~200
conversation_context.append({
    "role": "assistant",
    "content": f"Tool result: {json.dumps(result, ensure_ascii=False)[:1500]}"
})
```

**Problem**: If movie listings are in characters 1500+, they're cut off!

#### Cause 3: Wrong Tool for the Job
For "movies playing near me", web search returns **links** to theater websites, but:
- Fandango/Showtimes.com block scraping (403 errors)
- Search results don't include actual movie titles in descriptions
- LLM keeps searching hoping for better data

**What's needed**: A specialized tool like:
- Google Places API (movie_theater search)
- TMDb API (movie listings)
- Or: Accept that some queries are unsolvable and provide best-effort answer

### ✅ Proposed Fixes

#### Fix 1: Add "Final Answer" Turn
When `turn == MAX_TURNS - 1`, inject a special system message:

```python
# In orchestrator_v2.py, before router.route() call
if turn == MAX_TURNS - 1:
    # This is the last turn - force LLM to provide final answer
    conversation_context.append({
        "role": "system",
        "content": """IMPORTANT: This is your FINAL turn. You MUST provide a direct answer now based on ALL the data you've gathered so far. 

Review the tool results from previous turns and synthesize them into a helpful response. If you don't have perfect information, provide the best answer you can with what you have.

DO NOT call more tools. Just respond with your final answer."""
    })
    # Set no_tool_call=True to prevent infinite loop
    routing_result = router.route(
        transcript,
        conversation_context=conversation_context,
        no_tool_call=True  # Force text response only
    )
```

#### Fix 2: Increase Context Truncation for Search Results
```python
# In orchestrator_v2.py, increase truncation limit for specific tools
MAX_CONTEXT_CHARS = 1500  # Default
if result.get("tool") in ["mcp_brave_search_brave_web_search", "mcp_fetch_fetch"]:
    MAX_CONTEXT_CHARS = 3000  # More for search results

conversation_context.append({
    "role": "assistant",
    "content": f"Tool result: {json.dumps(result, ensure_ascii=False)[:MAX_CONTEXT_CHARS]}"
})
```

#### Fix 3: Update System Prompt
In `orchestrator/router_v2.py`, add to system prompt:

```python
EFFICIENCY_RULES:
- If you have enough information to answer, STOP calling tools and provide your answer
- After 3-4 tool calls, seriously consider if you can answer with what you have
- It's better to give a partial answer than to keep searching endlessly
- If a tool returns "403" or "Failed to fetch", don't retry the same URL
```

#### Fix 4: Add Movie/Theater Tool (Optional, Long-term)
Create a dedicated tool that uses TMDb API or Google Places to get actual movie showtimes.

---

## Issue 2: Dashboard Query Performance ("500 Too Many Outstanding Requests")

### 🐛 The Problem
Several Grafana dashboard panels show:
```
Status: 500
Message: too many outstanding requests
```

**Affected panels:**
- Total Tool Calls (24h)
- Tool Call Frequency
- Success Rate
- Others with aggregation queries

### 🔍 Root Cause
**LogQL queries are too expensive** for Loki to process quickly.

**Example problematic query**:
```logql
sum(count_over_time({job="jarvis", log_type="tools"} | json [24h]))
```

This query:
1. Scans **ALL** tool call logs from last 24 hours (1500+ entries)
2. Parses each JSON line
3. Counts them
4. Returns a single number

**Why it's slow:**
- `[24h]` range is large
- `| json` parses every log entry
- Multiple panels making similar queries simultaneously overwhelm Loki

### ✅ Proposed Fixes

#### Fix 1: Reduce Time Range for Expensive Queries
Instead of `[24h]`, use smaller ranges for high-frequency panels:

```json
{
  "expr": "sum(count_over_time({job=\"jarvis\", log_type=\"tools\"} | json [1h]))",
  "queryType": "instant",
  "refId": "A"
}
```

Then multiply result by 24 if you want 24h estimate (or just show 1h data).

#### Fix 2: Use Loki Metrics Instead of Log Queries
Loki has a `/api/v1/metrics` endpoint that tracks query performance. But for our use case, we could:

1. **Stream to Prometheus directly**: Have tools log metrics to a Prometheus endpoint
2. **Use Promtail metrics**: Promtail exposes metrics about log ingestion

But this requires code changes.

#### Fix 3: Add Query Caching
In `monitoring/loki-config.yml`, add query results cache:

```yaml
query_range:
  results_cache:
    cache:
      enable_fifocache: true
      fifocache:
        max_size_bytes: 500MB
        ttl: 1h
```

#### Fix 4: Reduce Dashboard Refresh Rate
In Grafana dashboard JSON, increase refresh interval:

```json
{
  "refresh": "1m",  // Change from "5s" to "1m"
  "timepicker": {
    "refresh_intervals": ["30s", "1m", "5m", "15m"]
  }
}
```

#### Fix 5: Optimize Queries (Use Aggregation)
Instead of:
```logql
sum(count_over_time({job="jarvis", log_type="tools"} | json [24h]))
```

Use:
```logql
count_over_time({job="jarvis", log_type="tools"}[24h])
```

Remove `| json` since we're just counting lines, not parsing fields.

---

## Issue 3: Missing LLM Logs

### 🐛 The Problem
**No `llm-calls-*.jsonl` files are being created** despite running multiple tool calls.

This is why the "LLM Performance" dashboard shows "No data" for:
- Total LLM Calls
- Total Cost
- Total Tokens Used
- Calls by Model
- Cost by Provider

### 🔍 Root Cause
The `llm_logger` integration we added to `router_v2.py` is inside a **conditional block that might not be executing**.

**Location**: `orchestrator/router_v2.py:450`
```python
from llm_logger import get_logger  # This import exists
```

But the actual logging call might be missing or not reachable.

### ✅ Fix
Need to verify the `llm_logger.log_llm_call()` is actually being called in the router's `route()` method.

---

## 🎯 Immediate Action Items

### Priority 1: Fix LLM Looping (Critical UX Issue)
1. ✅ Add "Final Answer" turn before hitting MAX_TURNS
2. ✅ Increase context truncation for search tools
3. ✅ Update system prompt with efficiency rules

### Priority 2: Fix Dashboard Performance
1. ✅ Reduce query time ranges from [24h] to [1h]
2. ✅ Remove `| json` from count-only queries
3. ✅ Increase dashboard refresh interval to 1 minute

### Priority 3: Enable LLM Logging
1. ✅ Verify `llm_logger.log_llm_call()` is being called
2. ✅ Test that `logs/llm-calls-*.jsonl` files are created
3. ✅ Populate LLM Performance dashboard

---

## 📊 New Dashboard Idea: "Final Answers" / Response Quality

You mentioned wanting a dashboard that shows:
- **Jarvis's actual responses** (the speech/answer)
- **Success vs. failure** (max_turns_reached, errors)
- **Ability to drill down** (which tools, which provider, token usage)

### Proposed: "Jarvis Response Quality" Dashboard

**Panel 1: Response Type Breakdown (Pie Chart)**
```logql
sum by (response_type) (
  count_over_time({job="jarvis", log_type="orchestrator"} | json [1h])
)
```

Where `response_type` is:
- `success` - Direct answer provided
- `max_turns_reached` - Hit tool limit
- `error` - Execution error
- `no_answer` - "Sorry, I don't know"

**Panel 2: Recent Responses (Table)**
Show last 20 responses with:
- Timestamp
- User Query (first 50 chars)
- Response Text (first 100 chars)
- Status (✅ / ❌)
- Tools Used Count
- Provider
- Total Tokens

**Panel 3: Failed Responses (Log Stream)**
```logql
{job="jarvis", log_type="orchestrator"} 
| json 
| response_type =~ "error|max_turns_reached|no_answer"
```

**Panel 4: Response Quality Over Time (Time Series)**
```logql
sum by (response_type) (
  count_over_time({job="jarvis", log_type="orchestrator"} | json [5m])
) by (response_type)
```

### Implementation Requirements

This dashboard needs a **new log file**: `logs/orchestrator-responses-*.jsonl`

**Log Entry Format**:
```json
{
  "timestamp": "2025-11-24T01:46:23.015288",
  "mode": "cloud",
  "provider": "xai",
  "model": "grok-beta",
  "user_query": "What are the top 3 movies playing in Hillsboro, OR?",
  "response_text": "I've hit the complexity limit for this request...",
  "response_type": "max_turns_reached",
  "tools_used": ["mcp_brave_search_brave_web_search", "mcp_fetch_fetch"],
  "tool_count": 10,
  "total_tokens": 15234,
  "total_cost_usd": 0.05,
  "duration_ms": 45230,
  "success": false
}
```

**Add to `orchestrator/orchestrator_v2.py`**:
```python
import json
from datetime import datetime

# At the end of orchestrate() method, before returning:
response_log = {
    "timestamp": datetime.now().isoformat(),
    "mode": mode,
    "provider": os.getenv("LLM_PROVIDER"),
    "model": os.getenv("ANTHROPIC_MODEL") if os.getenv("LLM_PROVIDER") == "anthropic" else os.getenv("OLLAMA_MODEL"),
    "user_query": transcript,
    "response_text": final_response[:500],  # Truncate to 500 chars
    "response_type": "success" if success else ("max_turns_reached" if max_turns_reached else "error"),
    "tools_used": list(set(tools_used)),  # Unique tools
    "tool_count": len(tools_used),
    "total_tokens": sum([call.get("tokens", 0) for call in llm_calls]),  # If tracked
    "total_cost_usd": sum([call.get("cost", 0) for call in llm_calls]),  # If tracked
    "duration_ms": (time.time() - start_time) * 1000,
    "success": success
}

log_file = f"logs/orchestrator-responses-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
with open(log_file, 'a') as f:
    f.write(json.dumps(response_log) + '\n')
```

---

## 📝 Summary

**3 Critical Issues**:
1. ✅ **LLM Looping** - Needs "final answer" forcing logic
2. ✅ **Dashboard Performance** - Queries are too expensive, need optimization
3. ✅ **Missing LLM Logs** - Logger not being called, dashboards empty

**Next Steps**:
1. Implement "Final Answer" turn in orchestrator
2. Optimize Grafana dashboard queries
3. Add orchestrator response logging
4. Create new "Response Quality" dashboard

**Would you like me to implement these fixes now?**

