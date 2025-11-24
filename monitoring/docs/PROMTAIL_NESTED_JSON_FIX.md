# Promtail Nested JSON Extraction Issue

**Date**: November 24, 2025  
**Status**: ⚠️ IN PROGRESS  
**Issue**: Cost and token data from LLM logs not accessible in Grafana dashboards

---

## 🚨 Problem

Grafana dashboard panels showing "No data" for:
- Total Cost (24h)
- Total Tokens Used (24h)
- Cost by Provider

**Root Cause**: Promtail's `json` stage doesn't properly extract nested fields like `usage.cost_usd`.

---

## 📊 Data Structure

**LLM log entry** (`logs/llm-calls-*.jsonl`):
```json
{
  "timestamp": "2025-11-24T02:30:10.123456",
  "provider": "anthropic",
  "model": "claude-sonnet-4-5-20250929",
  "usage": {
    "input_tokens": 655,
    "output_tokens": 14,
    "total_tokens": 669,
    "cost_usd": 0.002175
  }
}
```

**Current Promtail config**:
```yaml
- json:
    expressions:
      total_tokens: usage.total_tokens  # ❌ Doesn't work for nested fields
      cost_usd: usage.cost_usd          # ❌ Doesn't work for nested fields
```

**Problem**: Promtail's `json` stage can extract nested fields, but they're not properly structured for LogQL `unwrap` operations.

---

## ✅ Solution 1: Flatten JSON in llm_logger.py (RECOMMENDED)

**Change**: Modify `lib/llm_logger.py` to flatten the usage object at the top level.

**Before**:
```python
log_entry = {
    "timestamp": datetime.now().isoformat(),
    "provider": provider,
    "model": model,
    "usage": {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "cost_usd": usage.get("cost_usd")
    }
}
```

**After**:
```python
log_entry = {
    "timestamp": datetime.now().isoformat(),
    "provider": provider,
    "model": model,
    # Flatten usage fields for easier querying
    "input_tokens": usage.get("input_tokens") if usage else None,
    "output_tokens": usage.get("output_tokens") if usage else None,
    "total_tokens": usage.get("total_tokens") if usage else None,
    "cost_usd": usage.get("cost_usd") if usage else None,
    # Keep nested for backwards compatibility
    "usage": usage if usage else {}
}
```

**Pros**:
- ✅ Simpler LogQL queries
- ✅ Better performance (no nested parsing)
- ✅ Backwards compatible (keeps `usage` object)

**Cons**:
- Slightly larger log files (duplicate data)

---

## ✅ Solution 2: Use Promtail's `json` stage correctly

**Change**: Update `monitoring/promtail-config.yml` to use a two-stage approach.

**Current**:
```yaml
- json:
    expressions:
      total_tokens: usage.total_tokens
      cost_usd: usage.cost_usd
```

**Fixed**:
```yaml
- json:
    expressions:
      usage: usage  # Extract usage object first
      
- json:
    source: usage  # Parse the usage object
    expressions:
      input_tokens:
      output_tokens:
      total_tokens:
      cost_usd:
```

**Pros**:
- No code changes needed
- Works with existing logs

**Cons**:
- More complex Promtail config
- Slightly slower parsing

---

## ✅ Solution 3: Use structured metadata (Loki 2.9+)

**Not recommended** - overly complex for this use case.

---

## 🎯 Recommended Action

**Implement Solution 1** - Flatten JSON in `llm_logger.py`:

1. **Edit** `lib/llm_logger.py` (line ~67):
   ```python
   log_entry = {
       "timestamp": datetime.now().isoformat(),
       "mode": mode,
       "provider": provider,
       "model": model,
       "prompt_type": prompt_type,
       "user_query": user_query,
       "messages_count": len(messages),
       
       # Flatten usage for easier querying
       "input_tokens": usage_info.get("input_tokens") if usage_info else None,
       "output_tokens": usage_info.get("output_tokens") if usage_info else None,
       "total_tokens": usage_info.get("total_tokens") if usage_info else None,
       "cost_usd": usage_info.get("cost_usd") if usage_info else None,
       
       "response": {
           "type": "tool_call" if tool_call else ("text" if response_text else "error"),
           "text_preview": response_text[:200] if response_text else None,
           "tool_name": tool_call.get("name") if tool_call else None,
           "has_thinking": thinking is not None
       },
       "duration_ms": round(duration_ms, 2),
       "success": error is None,
       "error": error
   }
   ```

2. **Update** `monitoring/promtail-config.yml` (line ~85-86):
   ```yaml
   - json:
       expressions:
         timestamp: timestamp
         model: model
         provider: provider
         mode: mode
         prompt_type: prompt_type
         duration_ms: duration_ms
         success: success
         error: error
         input_tokens: input_tokens      # ✅ Flat field
         output_tokens: output_tokens    # ✅ Flat field
         total_tokens: total_tokens      # ✅ Flat field
         cost_usd: cost_usd              # ✅ Flat field
         response_type: response.type
         tool_name: response.tool_name
   ```

3. **Restart** services:
   ```bash
   # Restart Promtail to reload config
   cd ~/jarvis-voice/monitoring
   docker compose restart promtail
   ```

4. **Generate fresh logs**:
   ```bash
   cd ~/jarvis-voice
   source ~/jarvis-venv/bin/activate
   ./orchestrator/orchestrator_v2.py cloud "test query"
   ```

5. **Verify** in Grafana:
   - Total Cost should now show data
   - Total Tokens should show data

---

## 🧪 Testing Queries

After implementing the fix:

```bash
# Test total cost
curl -s -G 'http://192.168.70.228:3100/loki/api/v1/query' \
  --data-urlencode 'query=sum(sum_over_time({job="jarvis", log_type="llm"} | json | unwrap cost_usd [1h]))' | \
  jq '.data.result[0].value[1]'

# Expected: A number like "0.015" (total USD cost)

# Test total tokens
curl -s -G 'http://192.168.70.228:3100/loki/api/v1/query' \
  --data-urlencode 'query=sum(sum_over_time({job="jarvis", log_type="llm"} | json | unwrap total_tokens [1h]))' | \
  jq '.data.result[0].value[1]'

# Expected: A number like "15234" (total tokens)
```

---

## 📝 Status

- ✅ LLM logs are being created (`logs/llm-calls-*.jsonl`)
- ✅ Promtail is reading LLM logs (94 entries found)
- ❌ Nested `usage` fields not accessible in LogQL
- ⏳ Awaiting implementation of Solution 1

---

**Next Step**: Implement Solution 1 (flatten JSON in llm_logger.py)

