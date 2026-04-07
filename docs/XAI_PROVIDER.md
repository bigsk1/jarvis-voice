# xAI (Grok) Provider - The Best Cloud Option for Jarvis

> **TL;DR**: xAI Grok offers a **2M context window** at **10-15x lower cost** than competitors, with automatic caching, reasoning mode, and native function calling. It's currently the **best cloud provider** for Jarvis.

---

## Table of Contents

1. [Why xAI Grok?](#why-xai-grok)
2. [Pricing Comparison](#pricing-comparison)
3. [Key Features](#key-features)
4. [Configuration](#configuration)
5. [Available Models](#available-models)
6. [Automatic Caching](#automatic-caching)
7. [Reasoning Mode](#reasoning-mode)
8. [Performance Characteristics](#performance-characteristics)
9. [Cost Examples](#cost-examples)
10. [Migration Guide](#migration-guide)

---

## Why xAI Grok?

xAI's Grok models offer the **best value proposition** for Jarvis:

| Feature | xAI Grok | Anthropic Claude | OpenAI GPT |
|---------|----------|------------------|------------|
| **Context Window** | **2M tokens** 🏆 | 200K tokens | 128K tokens |
| **Input Cost** | **$0.20/1M** 🏆 | $3.00/1M | $1.25-3.00/1M |
| **Output Cost** | **$0.50/1M** 🏆 | $15.00/1M | $10.00-12.00/1M |
| **Caching** | **90% discount** 🏆 | 90% discount | 50% discount |
| **Reasoning Mode** | ✅ No extra cost | ✅ $3/$15 | ❌ |
| **Function Calling** | ✅ Native | ✅ Native | ✅ Native |
| **Typical Query Cost** | **$0.0052** 🏆 | $0.0646 | $0.0308 |

**Bottom Line**: xAI is **10-15x cheaper** with **10x larger context**, making it perfect for Jarvis's tool-heavy workload.

---

## Pricing Comparison

### Per 1M Tokens (USD)

```
┌─────────────────────────────────────────────────────────────────┐
│ MODEL                              INPUT    OUTPUT   CONTEXT    │
├─────────────────────────────────────────────────────────────────┤
│ xAI grok-4-fast (any variant)      $0.20    $0.50    2M    🏆  │
│ xAI grok-code-fast-1               $0.20    $1.50    256K      │
│ xAI grok-4 (premium)               $3.00    $15.00   256K      │
│                                                                 │
│ Anthropic Claude Sonnet 4.5        $3.00    $15.00   200K      │
│ OpenAI GPT-5.1                     $1.25    $10.00   128K      │
│ OpenAI GPT-4o                      $3.00    $12.00   128K      │
└─────────────────────────────────────────────────────────────────┘
```

### Real-World Cost Example

**Query**: "What time is it?" (typical Jarvis request with full tool context)
- **Input**: ~26,000 tokens (system prompt + tools + query)
- **Output**: ~30 tokens (response)

| Provider | Cost per Query | Monthly Cost (1000 queries) |
|----------|---------------|----------------------------|
| **xAI Grok-4-fast** | **$0.0052** | **$5.20** 🏆 |
| Anthropic Claude | $0.0646 | $64.60 |
| OpenAI GPT-5.1 | $0.0308 | $30.80 |

**Savings**: Use xAI and save **$59.40/month** vs Claude or **$25.60/month** vs OpenAI (for 1000 queries).

---

## Key Features

### 1. **Massive 2M Context Window**

- Handle **10x more tools** than competitors
- Include entire conversation history
- Pass large documents without chunking
- Perfect for Jarvis's 24+ tools with detailed descriptions

**Example**: Jarvis system prompt + 24 tools = ~25K tokens. With 2M context, you can include:
- Full tool context: 25K tokens
- Recent conversations: 10K tokens
- Long documents: 100K+ tokens
- Still have 1.8M+ tokens left!

### 2. **Automatic Prompt Caching (90% Discount)**

Unlike Anthropic (requires explicit `cache_control`), xAI caching is **automatic**:

- No configuration needed
- Caches repeated prompt prefixes automatically
- Cache hits can be **90%+** for Jarvis (repeated system prompt + tools)
- **$0.02/1M** for cached tokens vs **$0.20/1M** regular (90% savings!)

**Jarvis Benefit**: Since system prompt and tools are repeated every request:
- First request: $0.0052 (full cost)
- Subsequent requests: ~$0.0010 (cached system prompt + tools)
- **80% cost reduction** after first query!

### 3. **Reasoning Mode at No Extra Cost**

- Reasoning models: `grok-4-1-fast-reasoning-latest`
- **Same price** as non-reasoning models ($0.20/$0.50)
- Better decision-making for complex tasks
- Reasoning is integrated into response (not exposed separately like Claude)

**Comparison**:
- xAI: Reasoning = $0.20/$0.50 (no premium)
- Claude: Thinking mode = $3.00/$15.00 (same as regular)
- OpenAI: No reasoning mode

### 4. **Native Function Calling**

- OpenAI-compatible tool format
- Supports multiple tool calls in sequence
- Structured outputs
- Works perfectly with Jarvis's tool registry

### 5. **Built-in Server-Side Tools (Agent Tools API)** 

Enable Grok's native tools via `XAI_SEARCH=true`:

```bash
# In config/cloud.env
XAI_SEARCH=true   # Enable live search (default: true)
```

**How It Works** (Updated January 2026):
- Uses xAI's **Agent Tools API** with server-side tools
- Model autonomously decides when to use each tool
- Server-side tools execute automatically on xAI servers (no round-trip!)
- Returns synthesized answers with citations from web + X posts
- **Hybrid approach**: Combines with your custom client-side tools seamlessly

**Server-Side Tools Available**:
| Tool | Description | Features |
|------|-------------|----------|
| `web_search` | Real-time web search + browsing | Image understanding via native `view_image` |
| `x_search` | X/Twitter search (keyword, semantic, user) | Image + video understanding |
| `code_execution` | Python REPL for math, data analysis, plotting | numpy, pandas, sympy, matplotlib |

**Architecture**:
```
┌─────────────────────────────────────────────────────────────┐
│                   xAI Agent Tools API                        │
├─────────────────────────────────────────────────────────────┤
│  Server-Side Tools (executed by xAI automatically):         │
│    • web_search - Web search with native view_image support │
│    • x_search - X search with image/video understanding     │
│    • code_execution - Python REPL for math/analysis         │
│                                                             │
│  Client-Side Tools (your custom tools):                     │
│    • crypto_price, weather, spotify, etc.                   │
│    • Returned as tool_calls for Jarvis to execute           │
└─────────────────────────────────────────────────────────────┘
```

**Benefits**:
- Real-time web and X post data with citations
- Model decides: use search OR your tools (not both unless needed)
- No external Brave Search tool calls for current events
- Cleaner context (search handled server-side)
- Works transparently alongside all existing Jarvis tools

**Image Understanding Note**:
- `XAI_IMAGE_UNDERSTANDING=true` enables xAI's native `view_image` server-side tool during web/X search.
- When xAI uses it, Jarvis will pass through `SERVER_SIDE_TOOL_VIEW_IMAGE` in `server_side_tools`.
- Per xAI docs, enabling image understanding for `web_search` also enables it for `x_search` when both tools are included.

**Example**:
```
Query: "What are people saying on X about Grok 4?"

Response includes:
  • Synthesized answer from X posts
  • Citations: https://x.com/i/status/...
  • No external tool calls!

Query: "What's the current Bitcoin price?"

Response uses:
  • crypto_price tool (more accurate for prices)
  • Model decides best tool for the job
```

**Requirements**:
- xai-sdk >= 1.6.1 (video generation requires 1.6.0+)
- Supports Grok 4 models (grok-4, grok-4-fast, grok-4-1-fast)

**Cost**: Standard token pricing + search tool invocations (see xAI pricing)

### 6. **Image Generation**

- see [video/README.md](video/README.md)

### 7. **Video Generation** ✅ NEW

Generate AI videos using **Grok Imagine Video**:

```bash
# Via Jarvis
jarvis cloud "Generate a video of a cat playing with a ball"

# Via API
curl -X POST http://localhost:8880/api/generated-videos/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "A cat playing with a ball", "duration": 5}'
```

**Configuration** (config/cloud.env):
```bash
VIDEO_TOOL_PROVIDER="xai"
XAI_VIDEO_MODEL="grok-imagine-video"
```

**xAI Grok Video Parameters**:

| Parameter | Options | Default | Description |
|-----------|---------|---------|-------------|
| `duration` | 1-15 seconds | 5 | Video length (continuous range) |
| `aspect_ratio` | `16:9`, `4:3`, `1:1`, `9:16`, `3:4`, `3:2`, `2:3` | `16:9` | Video shape (7 options) |
| `resolution` | `720p`, `480p` | `720p` | Video quality |
| `image_url` | URL | - | Generate from image (image-to-video) |
| `video_url` | URL | - | Edit existing video (≤8.7s source) |

**Generation Modes**:
1. **Text-to-Video**: Generate from text prompt
2. **Image-to-Video**: Animate an existing image
3. **Video Edit**: Modify an existing video (xAI only)

**xAI Grok Strengths**:
- Flexible duration: 1-15 seconds (any value)
- 7 aspect ratio options
- Video editing capability

**Generation Time**: 30-120+ seconds depending on duration

**File Size**: ~3-5 MB per 5 seconds (720p)

**Requirements**: xai-sdk >= 1.6.1 (video support added in 1.6.0)

**Alternative**: Gemini Veo 3.1 is also supported with native audio, higher resolution (up to 4k), but limited duration (4/6/8s). See [Video Generation Docs](video/README.md) for comparison.

**Storage**: Videos saved to `data/generated_videos/` and indexed in stash.

See [Video Generation Docs](video/README.md) for full details.

---

## Configuration

### Setup (config/cloud.env)

```bash
# Use xAI as primary provider
LLM_PROVIDER="xai"

# xAI API Key (get from https://console.x.ai)
XAI_API_KEY="xai-..."

# Model Selection
# Recommended: grok-4-1-fast-non-reasoning (reasoning + 2M context)
XAI_MODEL="grok-4-1-fast-non-reasoning"

# Native Web Search (NEW!)
# When true: Grok searches web + X posts internally (no external tool calls)
# When false: Uses external tools (Brave Search) like before
XAI_SEARCH=true

# Alternative models:
# XAI_MODEL="grok-4-1-fast-non-reasoning-latest"  # No reasoning
# XAI_MODEL="grok-code-fast-1"                    # Code-optimized
# XAI_MODEL="grok-4"                              # Premium (256K context)
```

### Testing

```bash
# Simple test
./orchestrator/orchestrator_v2.py cloud "What time is it?"

# With thinking mode (note: xAI doesn't expose reasoning separately)
./orchestrator/orchestrator_v2.py cloud "Complex query" --debug-thinking

# Voice mode
./jarvis  # Uses cloud.env settings
```

---

## Available Models

### Grok 4 Fast Series (2M Context) - **RECOMMENDED**

| Model | Context | Use Case | Reasoning |
|-------|---------|----------|-----------|
| `grok-4-1-fast-non-reasoning` | 2M | **Best overall** | ✅ Yes |
| `grok-4-1-fast-reasoning-latest` | 2M | Latest reasoning | ✅ Yes |
| `grok-4-fast-non-reasoning-latest` | 2M | Fast, no reasoning | ❌ No |
| `grok-4-1-fast-non-reasoning-latest` | 2M | Latest, no reasoning | ❌ No |

**Pricing**: All grok-4-fast models: **$0.20 input / $0.50 output**

**Recommendation**: Use `grok-4-1-fast-non-reasoning` - same price, better quality.

### Grok Code Fast (256K Context)

| Model | Context | Use Case | Output Cost |
|-------|---------|----------|-------------|
| `grok-code-fast-1` | 256K | Code generation | $1.50/1M |

**Pricing**: $0.20 input / $1.50 output (3x higher output cost for code quality)

### Grok 4 Premium (256K Context)

| Model | Context | Use Case | Pricing |
|-------|---------|----------|---------|
| `grok-4` | 256K | Premium quality | $3.00 / $15.00 |

**Note**: Same price as Claude/GPT but smaller context. Use `grok-4-fast` instead.

---

## Automatic Caching

### How It Works

xAI automatically caches **repeated prompt prefixes**:

1. **First Request**: Full cost ($0.20/1M input)
   ```
   System prompt (10K tokens) + Tools (15K tokens) + Query (1K tokens) = 26K tokens
   Cost: 26K × $0.20/1M = $0.0052
   ```

2. **Second Request** (same system + tools):
   ```
   Cached: System + Tools (25K tokens) @ $0.02/1M
   New: Query (1K tokens) @ $0.20/1M
   Cost: (25K × $0.02/1M) + (1K × $0.20/1M) = $0.0005 + $0.0002 = $0.0007
   ```

**Savings**: **86% cost reduction** on subsequent requests!

### Cache Monitoring

xAI returns usage stats in API response:

```json
{
  "usage": {
    "prompt_tokens": 26000,
    "cached_prompt_tokens": 25000,  // 90%+ cache hit!
    "completion_tokens": 30
  }
}
```

Jarvis automatically tracks and displays cache metrics in cost reports.

### Cache Invalidation

Cache expires after:
- **5 minutes** of inactivity (typical)
- Model changes
- Prompt prefix changes

**Jarvis Behavior**: With continuous use, cache stays hot → massive savings!

---

## Reasoning Mode

### What Is It?

Reasoning models (`*-reasoning-*`) perform extended internal thinking before responding:

- Analyze the problem deeply
- Consider multiple approaches
- Verify logic before answering
- Better for complex decisions

### Differences from Anthropic

| Feature | xAI Grok | Anthropic Claude |
|---------|----------|------------------|
| **API Field** | No separate field | Separate `thinking` field |
| **Visibility** | Reasoning not exposed | Can see thinking process |
| **`--debug-thinking`** | No effect | Shows thinking blocks |
| **Pricing** | Same as regular | Same as regular |
| **Quality** | Better answers | Better answers |

### When to Use Reasoning Models

✅ **Use reasoning** (`grok-4-1-fast-non-reasoning`):
- Complex multi-step tasks
- Financial decisions (e.g., "Should I invest?")
- Code debugging
- Tool selection for ambiguous queries
- **No cost penalty** - same price!

❌ **Skip reasoning** (`grok-4-fast-non-reasoning-latest`):
- Simple facts ("What time is it?")
- Quick lookups
- When speed > quality (though difference is minimal)

**Recommendation**: **Always use reasoning models** - no downside, better quality.

---

## Performance Characteristics

### Speed

- **Latency**: 1-3 seconds (similar to Claude/GPT)
- **Throughput**: High (scales well)
- **2M context**: No significant slowdown vs 200K

### Reliability

- **Uptime**: Enterprise-grade (99.9%+)
- **Rate Limits**: Generous (check console.x.ai)
- **Error Handling**: Standard OpenAI-compatible errors

### Quality

- **Function Calling**: Excellent (on par with Claude/GPT)
- **Tool Selection**: Accurate routing
- **Multi-Tool**: Handles sequences well
- **Reasoning**: High quality (when using reasoning models)

---

## Cost Examples

### Typical Jarvis Workloads

#### 1. Simple Query (No Cache)

**Query**: "What time is it?"
- Input: 26K tokens (system + tools + query)
- Output: 30 tokens

**Cost**:
- xAI: $0.0052
- Claude: $0.0646 (12x more)
- GPT-5.1: $0.0308 (6x more)

#### 2. Multi-Tool Complex Query (No Cache)

**Query**: "What time is it and what's the Bitcoin price?"
- Input: 39K tokens
- Output: 100 tokens

**Cost**:
- xAI: $0.0078
- Claude: $0.1170 (15x more)
- GPT-5.1: $0.0486 (6x more)

#### 3. Daily Usage (1000 queries with caching)

Assuming 90% cache hit rate after first query:

**Cost Breakdown**:
- First query: $0.0052 (no cache)
- Queries 2-1000: $0.0010 avg (cached)
- **Total**: $0.0052 + (999 × $0.0010) = **$1.00**

**Comparison**:
- Claude: $64.60 (**64x more expensive**)
- GPT-5.1: $30.80 (**30x more expensive**)

**Monthly Savings**: ~$63.60 vs Claude, ~$29.80 vs GPT!

---

## Migration Guide

### From Anthropic Claude

1. **Update config/cloud.env**:
   ```bash
   # Change from:
   LLM_PROVIDER="anthropic"
   ANTHROPIC_MODEL="claude-sonnet-4-5-20250929"
   
   # To:
   LLM_PROVIDER="xai"
   XAI_MODEL="grok-4-1-fast-non-reasoning"
   XAI_API_KEY="xai-..."  # Get from console.x.ai
   ```

2. **Test basic functionality**:
   ```bash
   ./orchestrator/orchestrator_v2.py cloud "What time is it?"
   ```

3. **Differences to note**:
   - `--debug-thinking` won't show reasoning (API limitation)
   - Caching is automatic (no `cache_control` needed)
   - 10x larger context window (2M vs 200K)
   - 12x cheaper per query

### From OpenAI GPT

1. **Update config/cloud.env**:
   ```bash
   # Change from:
   LLM_PROVIDER="openai"
   OPENAI_MODEL="gpt-5.1-chat-latest"
   
   # To:
   LLM_PROVIDER="xai"
   XAI_MODEL="grok-4-1-fast-non-reasoning"
   XAI_API_KEY="xai-..."
   ```

2. **Test**:
   ```bash
   ./orchestrator/orchestrator_v2.py cloud "What time is it?"
   ```

3. **Differences**:
   - 15x larger context (2M vs 128K)
   - 6x cheaper
   - Better reasoning (if using reasoning models)

### No Code Changes Required!

Jarvis's `LLMProvider` abstraction means **zero code changes** needed. Just update config and go!

---

## FAQ

### Q: Is xAI as good as Claude/GPT?

**A**: For Jarvis's use case (tool calling, structured tasks), yes! xAI Grok-4 performs on par with Claude Sonnet 4.5 and GPT-5.1 for function calling, while being 10-15x cheaper with 10x larger context.

### Q: What about thinking mode?

**A**: xAI reasoning models DO extended thinking internally, but don't expose it via API (unlike Claude). You get better answers without seeing the reasoning process. `--debug-thinking` has no effect with xAI.

### Q: Does caching really work?

**A**: Yes! xAI automatically caches prompt prefixes. For Jarvis, this means system prompt + tools (90%+ of input) get cached after first request, reducing costs by ~80-90% on subsequent queries.

### Q: Should I use reasoning or non-reasoning models?

**A**: **Always use reasoning models** (`grok-4-1-fast-non-reasoning`). They're the same price, same speed, but give better quality answers. There's literally no downside.

### Q: What about rate limits?

**A**: Check your xAI console (console.x.ai) for current limits. For typical Jarvis usage (<1000 queries/day), limits are generous.

### Q: Can I use xAI for OpenCode?

**A**: Yes! Set `OPENCODE_PROVIDER="xai"` in cloud.env. However, Claude is still recommended for OpenCode due to its superior code generation quality and explicit thinking mode.

### Q: What if xAI is down?

**A**: Keep backup providers in cloud.env. Switch by changing `LLM_PROVIDER`:
```bash
LLM_PROVIDER="anthropic"  # Fallback to Claude
# or
LLM_PROVIDER="openai"     # Fallback to GPT
```

---

## Best Practices

1. **Use reasoning models by default** - no cost penalty, better quality
2. **Monitor cache hit rates** in usage stats (should be 90%+)
3. **Keep system prompt + tools under 1M tokens** (plenty of headroom with 2M context)
4. **Test fallback providers** (Claude/GPT) in case xAI has issues
5. **Track monthly costs** vs previous provider (should see 10-15x savings)

---

## Summary

xAI Grok is **currently the best cloud provider for Jarvis**:

✅ **2M context window** (10x larger)  
✅ **10-15x cheaper** than competitors  
✅ **Automatic caching** (90% discount)  
✅ **Reasoning mode** at no extra cost  
✅ **Native function calling**  
✅ **Built-in live search** (XAI_SEARCH=true)   
✅ **Drop-in replacement** (no code changes)  

**Monthly Savings**: $60-80 vs Claude, $25-35 vs GPT (for typical usage)

**Setup Time**: 5 minutes (update config, get API key, test)

**Recommendation**: **Use xAI Grok for production Jarvis workloads.**

---

**Last Updated**: 2026-01-24  
**Version**: 1.3 (Added code_execution + image/video understanding)

**See Also**:
- [AGENTS.md](../AGENTS.md) - Coding guidelines
- [QUICKSTART.md](QUICKSTART.md) - Getting started
- [MEMORY_SYSTEM.md](MEMORY_SYSTEM.md) - Memory features
- [xAI Docs](https://docs.x.ai) - Official xAI documentation
