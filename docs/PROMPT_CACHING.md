# Anthropic Prompt Caching Implementation

**Status**: ✅ Implemented (November 15, 2025)  
**Benefit**: 90% cost reduction on cached tokens, faster responses  
**Cache Duration**: 5 minutes of inactivity

---

## 🎯 What is Prompt Caching?

Anthropic's Prompt Caching saves **90% on repeated context** (system prompts, tool definitions).

### Without Caching
```
Request 1: System prompt (1,915 tokens) + Tools (3,793 tokens) = $0.017
Request 2: System prompt (1,915 tokens) + Tools (3,793 tokens) = $0.017
Request 3: System prompt (1,915 tokens) + Tools (3,793 tokens) = $0.017
─────────────────────────────────────────────────────────────────
Total (3 requests): $0.051
```

### With Caching (within 5 minutes)
```
Request 1: Cache WRITE (5,708 tokens × $3.75/1M) = $0.021
Request 2: Cache READ (5,708 tokens × $0.30/1M)  = $0.002
Request 3: Cache READ (5,708 tokens × $0.30/1M)  = $0.002
─────────────────────────────────────────────────────────────────
Total (3 requests): $0.025
Savings: $0.026 (51% reduction on just 3 requests!)
```

---

## 📊 Pricing Breakdown

| Token Type | Cost per 1M | Your Baseline |
|------------|-------------|---------------|
| **Regular input** | $3.00 | 5,708 tokens |
| **Cache write** | $3.75 | +25% first time |
| **Cache read** | $0.30 | 90% cheaper! |
| **Output** | $15.00 | Unchanged |

---

## 🚀 Implementation Details

### What's Cached
1. **System Prompt** (1,915 tokens)
   - All routing instructions
   - Memory management rules
   - Voice formatting guidelines
   - OpenCode instructions

2. **Tool Definitions** (3,793 tokens)
   - All 20 tool schemas
   - Descriptions, parameters, examples

### How It Works

```python
# Jarvis adds cache_control markers
system_blocks = [{
    "type": "text",
    "text": "You are Jarvis...",
    "cache_control": {"type": "ephemeral"}  # ← Cache this!
}]

tools_with_cache = [
    tool1,
    tool2,
    {
        **tool_last,
        "cache_control": {"type": "ephemeral"}  # ← Cache up to here
    }
]
```

**Anthropic's Rule**: Cache everything UP TO the last `cache_control` breakpoint.

---

## ⏰ Cache Duration & Invalidation

### Cache Duration
- **5 minutes** of inactivity
- Timer resets with each request

### Cache Invalidates When
1. **5+ minutes** pass without a request
2. **Content changes** (different system prompt, tools modified)
3. **Manual invalidation** (not exposed via API)

### Example Timeline
```
10:00:00 - Request 1: Cache WRITE ✍️
10:01:00 - Request 2: Cache HIT ✅ (within 5 min)
10:03:00 - Request 3: Cache HIT ✅ (timer reset)
10:08:00 - Request 4: Cache HIT ✅ (still valid)
10:14:00 - Request 5: Cache MISS ❌ (>5 min since last, expired)
```

---

## 💻 Usage

### Command Line Testing
```bash
# First request (cache write)
./orchestrator/orchestrator_v2.py cloud "What time is it?"

# Output shows:
# 💰 Token Usage:
#    Input: 150 tokens
#    Output: 45 tokens
#    💾 Cache WRITE: 5,708 tokens (first request)
#    💵 Total Cost: $0.0214

# Second request within 5 minutes (cache read)
./orchestrator/orchestrator_v2.py cloud "Bitcoin price?"

# Output shows:
# 💰 Token Usage:
#    Input: 120 tokens
#    Output: 38 tokens
#    💾 Cache READ: 5,708 tokens (90% cheaper!)
#    ✅ Saved: $0.0154
#    💵 Total Cost: $0.0059
```

### Voice Mode (Best Use Case)
```bash
./jarvis  # Start voice mode

# Conversation within 5 minutes:
You: "What time is it?"        # Cache WRITE
You: "Bitcoin price?"          # Cache READ (90% off!)
You: "Send a webhook to..."    # Cache READ (90% off!)
You: "Remember my birthday"    # Cache READ (90% off!)
```

**Savings**: 3 follow-up requests save ~$0.046 compared to no caching.

---

## 📈 Real-World Scenarios

### Scenario 1: Voice Mode (Ideal)
```
Session: 10 requests over 3 minutes
- Request 1: Cache write ($0.021)
- Requests 2-10: Cache reads ($0.017)
──────────────────────────────────────
Total: $0.038
Without caching: $0.170
Savings: $0.132 (78% reduction)
```

### Scenario 2: Command-Line Testing (No Benefit)
```
Test 1: 10:00 AM - Cache write
[5+ minutes pass]
Test 2: 10:15 AM - Cache MISS, new write
[5+ minutes pass]
Test 3: 10:30 AM - Cache MISS, new write
──────────────────────────────────────
No savings (cache expired between tests)
```

### Scenario 3: Development Testing (Some Benefit)
```
Rapid testing: 5 requests in 2 minutes
- Request 1: Cache write ($0.021)
- Requests 2-5: Cache reads ($0.006)
──────────────────────────────────────
Total: $0.027
Without caching: $0.085
Savings: $0.058 (68% reduction)
```

---

## 🔍 Monitoring Cache Performance

### API Response Includes Real Metrics
```json
{
  "usage": {
    "input_tokens": 150,
    "output_tokens": 45,
    "cache_creation_input_tokens": 5708,  // First request
    "cache_read_input_tokens": 0
  }
}
```

Or on cache hit:
```json
{
  "usage": {
    "input_tokens": 120,
    "output_tokens": 38,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 5708  // 90% discount!
  }
}
```

### Jarvis Automatically Shows
```
💰 Token Usage:
   Input: 120 tokens
   Output: 38 tokens
   💾 Cache READ: 5,708 tokens (90% cheaper!)
   ✅ Saved: $0.0154
   💵 Total Cost: $0.0059
```

**No guessing** - these are actual values from Anthropic's API.

---

## 🔧 OpenCode Caching

### Current Status
OpenCode uses the **OpenCode server** which has its own Anthropic client.

**For Jarvis → OpenCode caching**:
- OpenCode server would need to implement caching internally
- OR use Anthropic SDK version that supports caching
- Check OpenCode server logs to see if it's already using caching

**To Check**:
```bash
# See if OpenCode server is using caching
sudo journalctl -u opencode-jarvis.service | grep -i cache

# Or check OpenCode config
curl -s http://localhost:4096/config | jq '.provider.anthropic'
```

**Next Step**: May need to update OpenCode server's Anthropic SDK or config to enable caching.

---

## 📊 Cost Comparison

### Monthly Savings (Voice Mode Usage)
Assuming 100 conversations/day, 10 requests per conversation:

**Without Caching**:
```
1,000 requests/day × $0.017 = $17/day = $510/month
```

**With Caching** (90% cache hit rate):
```
Day 1:
  - 100 cache writes: 100 × $0.021 = $2.10
  - 900 cache reads: 900 × $0.002 = $1.80
  Total: $3.90/day = $117/month

Savings: $393/month (77% reduction)
```

### Single Session Savings
```
10-request conversation (within 5 min):
- Without caching: $0.170
- With caching: $0.038
- Savings: $0.132 per conversation
```

---

## ⚠️ When Cache Doesn't Help

### 1. **Long Gaps Between Requests**
```
Request at 10:00 AM
Request at 10:10 AM ← Cache expired
No benefit
```

### 2. **Content Changes**
```
Request 1: With tool A
[Modify tool A's description]
Request 2: With modified tool A ← New cache, different hash
No benefit
```

### 3. **Different Contexts**
Each unique combination of system prompt + tools = separate cache entry.

---

## 🎯 Best Practices

### ✅ DO Use Caching For
- **Voice mode conversations** (rapid back-and-forth)
- **Development testing** (quick iteration within 5 min)
- **Production voice assistants** (continuous usage)
- **Chat sessions** (user actively engaged)

### ❌ DON'T Expect Benefits From
- **Spaced-out CLI testing** (>5 min gaps)
- **Frequent tool updates** (invalidates cache)
- **One-off requests** (no follow-up within 5 min)

---

## 🔬 Technical Implementation

### Files Modified
1. **lib/llm_provider.py**
   - `AnthropicProvider.chat()` - Added cache_control to system prompt
   - `AnthropicProvider.chat_with_tools()` - Added cache_control to system + tools
   - Parse cache metrics from API response

2. **orchestrator/orchestrator_v2.py**
   - Accumulate cache_creation_tokens, cache_read_tokens
   - Display cache metrics in output
   - Calculate and show savings

### Cache Control Format
```python
# System prompt caching
system=[{
    "type": "text",
    "text": "Your system prompt here",
    "cache_control": {"type": "ephemeral"}
}]

# Tool caching (mark last tool)
tools=[
    tool1,
    tool2,
    {**tool_last, "cache_control": {"type": "ephemeral"}}
]
```

### API Response Parsing
```python
# Extract cache metrics
cache_creation_tokens = getattr(response.usage, 'cache_creation_input_tokens', 0)
cache_read_tokens = getattr(response.usage, 'cache_read_input_tokens', 0)

# Calculate savings
if cache_read_tokens > 0:
    cache_cost = (cache_read_tokens / 1_000_000) * 0.30
    regular_cost = (cache_read_tokens / 1_000_000) * 3.00
    savings = regular_cost - cache_cost
```

---

## 🎓 How Anthropic Caching Works

### Cache Breakpoints
- You mark specific locations with `cache_control`
- Anthropic caches everything UP TO that point
- Can have multiple breakpoints

### Example
```
[System Prompt] ← cache_control
[Tool 1]
[Tool 2]
[Tool 20] ← cache_control
[User Message]
```

**Cached**: System prompt + all 20 tools  
**Not Cached**: User message (changes every request)

### Cache Key (Hash)
- Hash of all content up to cache breakpoint
- If ANY character changes → new cache entry
- Whitespace, formatting matter!

---

## 📝 Testing Caching

### Test 1: Verify Cache Write
```bash
./orchestrator/orchestrator_v2.py cloud "test"
# Look for: "💾 Cache WRITE: 5,708 tokens"
```

### Test 2: Verify Cache Read
```bash
# Within 5 minutes of Test 1:
./orchestrator/orchestrator_v2.py cloud "test again"
# Look for: "💾 Cache READ: 5,708 tokens (90% cheaper!)"
# Look for: "✅ Saved: $0.0154"
```

### Test 3: Verify Cache Expiry
```bash
./orchestrator/orchestrator_v2.py cloud "test"
# Wait 6 minutes
./orchestrator/orchestrator_v2.py cloud "test again"
# Should show Cache WRITE again (expired)
```

---

## 🎉 Benefits Summary

✅ **90% cost reduction** on cached tokens  
✅ **Faster responses** (cached prompts process quicker)  
✅ **Transparent to LLM** (sees full context, no degradation)  
✅ **Real API metrics** (no estimates, actual cache hits)  
✅ **Zero config** (automatic, always on for Anthropic)  
✅ **Perfect for voice mode** (rapid conversations)  

---

**Implemented**: November 15, 2025  
**Branch**: `opencode-plugins`  
**Tested**: ✅ Working with Claude Sonnet 4.5

