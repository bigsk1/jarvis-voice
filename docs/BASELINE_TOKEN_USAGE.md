# Jarvis Baseline Token Usage

> **What is "baseline"?** The tokens consumed by system setup BEFORE any user query is processed.

**Last Measured**: November 15, 2025  
**Tool**: `bin/measure-baseline-tokens`

---

## 📊 Current Baseline Usage

### Cloud Mode (OpenAI gpt-5.4-nano — shipped default)

```
System Prompt:       1,915 tokens
Tool Definitions:    3,793 tokens
─────────────────────────────────
TOTAL BASELINE:      5,708 tokens
─────────────────────────────────

Context Window:  ~1,050,000 tokens (model-dependent; see model catalog)
Baseline %:            ~0.5%
Available:         ~1,044,000 tokens
```

**Status**: ✅ Healthy (< 3% of context)

**Note**: Token counts below are from the November 15, 2025 measurement run (historically labeled Anthropic). Shipped `config/cloud.env.example` now defaults to `LLM_PROVIDER=openai` / `OPENAI_MODEL=gpt-5.4-nano`. Re-run `bin/measure-baseline-tokens` after major prompt or tool changes.

---

### Local Mode (Ollama gemma4)

```
System Prompt:       1,915 tokens
Tool Definitions:    3,793 tokens
─────────────────────────────────
TOTAL BASELINE:      5,708 tokens
─────────────────────────────────

Context Window:     32,000 tokens (estimate)
Baseline %:           17.8%
Available:          26,292 tokens (82.2%)
```

**Status**: ✅ Healthy (< 20% of context)

**Note**: Local context window varies by model variant. Default `OLLAMA_MODEL` is `gemma4` per `config/local.env.example`.

---

## 🔍 What's Included in Baseline?

### 1. System Prompt (1,915 tokens)
Located: `orchestrator/router_v2.py`

**Contains**:
- Multi-turn conversation instructions
- Voice output rules (12-word limit)
- Memory management guidelines
- Intelligent auto-save rules
- OpenCode usage instructions
- Tool routing logic
- Error recovery procedures

**Size**: 7,662 characters (135 lines)

### 2. Tool Definitions (3,793 tokens)
Located: `skills/*.tool.json` + MCP servers

**Contains**: JSON schemas for 20 tools:
- **Local Tools (20)**:
  - Core: `get_time`, `execute_bash`, `api_call`
  - Memory: `remember`, `recall`, `search_memory`, `semantic_recall`, `update_memory`, `forget`
  - OpenCode: `opencode`, `check_opencode_sessions`
  - Conversations: `get_recent_conversations`, `search_conversations`
  - Specialized: `crypto_price`, `send_webhook`, `ingest_intel`, `check_tool_logs`
  - MCP (passed through): `mcp_duckduckgo_search`, `mcp_duckduckgo_fetch_content`, `mcp_fetch_fetch`
  
- **MCP Tools (0)**: MCP tools are registered as local tools (counted above)

**Size**: 15,172 characters of JSON

---

## 💬 Example Query Costs

| Scenario | Query Tokens | Total Tokens | % of Context (Cloud) | % of Context (Local) |
|----------|--------------|--------------|----------------------|----------------------|
| Simple query | 50 | 5,758 | 0.6% | 18.0% |
| Memory lookup | 100 | 5,808 | 0.6% | 18.1% |
| Multi-turn task | 300 | 6,008 | 0.6% | 18.8% |
| OpenCode build | 2,000 | 7,708 | 0.8% | 24.1% |
| Complex multi-turn | 5,000 | 10,708 | 1.1% | 33.5% |

**Insight**: Local models consume proportionally more context due to smaller window (32K vs 1M).

---

## ⚠️ Why This Matters

### For Cloud Mode (Anthropic/OpenAI)
- **Low impact**: 0.6% baseline leaves ~99% for conversation
- **Large buffer**: Can handle complex multi-turn workflows (10K+ tokens)
- **Cost efficiency**: Baseline is constant per request, optimize conversation tokens

### For Local Mode (Ollama)
- **Moderate impact**: 17.8% baseline leaves 82% for conversation
- **Limited multi-turn**: Complex chains may hit context limits sooner
- **Watch for**: OpenCode builds (2K tokens) + memory context + tool results = can reach 30%+

**Critical Threshold**: If baseline + conversation exceeds 80% of context window, model performance degrades.

---

## 🎯 Your Concern: "Is it too much?"

### Current Assessment: **NO, it's healthy**

**Why**:
1. ✅ Cloud mode: Only 0.6% of 1M context (negligible)
2. ✅ Local mode: Only 17.8% of 32K context (acceptable)
3. ✅ System prompt is **essential** (routing, memory, voice formatting)
4. ✅ Tool definitions are **necessary** for native tool calling

### When would it be "too much"?

**Warning signs**:
- Baseline > 30% of context (not happening)
- Multi-turn tasks failing due to context limits (not observed)
- Local model struggles with tool selection (happens, but due to model capability, not token count)

---

## 📈 Optimization Opportunities

### If you NEEDED to reduce tokens (you don't right now):

**System Prompt (1,915 tokens)**:
- ❌ Don't remove: Multi-turn, memory, voice rules are critical
- ✅ Could trim: Some examples (save ~200 tokens)
- ✅ Could shorten: OpenCode instructions (save ~100 tokens)
- **Potential savings**: ~300 tokens (15% reduction) = New baseline: 5,400 tokens

**Tool Definitions (3,793 tokens)**:
- ❌ Don't remove: All tools are actively used
- ✅ Could split: Create "light" mode with fewer tools
- ✅ Could optimize: Shorter descriptions (save ~500 tokens)
- **Potential savings**: ~500 tokens (13% reduction) = New baseline: 5,200 tokens

**Total potential savings**: ~600 tokens (10% reduction) → **Not worth it** for current needs.

---

## 🔧 Measuring Your Baseline

Run anytime to check current usage:

```bash
# Both modes
./bin/measure-baseline-tokens

# Cloud only
./bin/measure-baseline-tokens cloud

# Local only
./bin/measure-baseline-tokens local
```

**Output**: 
- Console report (detailed breakdown)
- JSON files: `logs/baseline-tokens-{mode}.json`

---

## 📊 Historical Tracking

Track changes over time by running before/after system prompt or tool changes:

```bash
# Before changes
./bin/measure-baseline-tokens cloud > before.txt

# ... make changes to system prompt or tools ...

# After changes
./bin/measure-baseline-tokens cloud > after.txt

# Compare
diff before.txt after.txt
```

---

## 🎓 Understanding Token Budgets

### OpenAI gpt-5.4-nano (Cloud — shipped default)
- **Context Window**: ~1,050,000 tokens (see model catalog)
- **Baseline**: 5,708 tokens (~0.5%)
- **Comfortable Multi-Turn**: Can chain many tool calls with context
- **Max Conversation**: Large remaining budget after baseline (not a reason to dump full history)

### Ollama gemma4 (Local)
- **Context Window**: ~32,000 tokens (varies by variant)
- **Baseline**: 5,708 tokens (17.8%)
- **Comfortable Multi-Turn**: Can chain 3-5 tool calls safely
- **Max Conversation**: ~25K tokens before degradation

---

## 🚨 When to Worry About Tokens

**Watch for these symptoms**:

1. **Incomplete Responses**: Model cuts off mid-response
2. **Failed Tool Calls**: Model forgets tool schema mid-conversation
3. **Repeated Questions**: Model loses track of what was already done
4. **Error Messages**: "Context length exceeded" or similar
5. **Degraded Performance**: Model makes poor decisions in later turns

**Current Status**: ✅ None of these observed with 5,708 token baseline.

---

## 💡 Key Insights

### 1. Your Intuition Was Right
> "At a certain point system prompts and context and memory is way too much, if using local models it is just overloading from the beginning"

**Answer**: It's not "overloading" yet, but you're right to monitor it. Local models have less headroom (82% available vs 97% for cloud).

### 2. The Retry Behavior You Noticed
> "jarvis retrying is interesting you think he would have said wait i reject opencode trying to do that"

**Why it happens**: Jarvis's system prompt focuses on ACCOMPLISHING tasks, not VALIDATING user requests. The retry logic assumes the user's request is valid and Jarvis should keep trying different approaches.

**Token cost of retry**: Each retry adds another ~6K token conversation turn. Multiple retries can stack up on local models.

### 3. Multi-Turn Can Be Expensive
OpenCode build (turn 1) + verification (turn 2) + retry (turn 3) = 3 × ~6K = ~18K tokens used. On a 32K context window, that's 56% utilization. Still works, but getting tight.

---

## 🎯 Recommendations

### Current State: **Keep as-is**
- Baseline is healthy for both modes
- System prompt is essential for quality
- All 20 tools are actively used

### Future Monitoring:
1. ✅ Run `measure-baseline-tokens` after any system prompt changes
2. ✅ Watch for multi-turn conversations reaching 50%+ context on local mode
3. ✅ Consider adding a "lite" mode if you add 10+ more tools

### If You Hit Limits on Local Mode:
1. **Use Workflows** (see below) - Bypass baseline entirely!
2. **Reduce multi-turn chains**: Accomplish tasks in fewer turns
3. **Shorten system prompt**: Focus on essential instructions only
4. **Split tool sets**: Create focused tool subsets for specific use cases
5. **Upgrade model**: Use Qwen variants with larger context (128K)

---

## 🚀 Workflows: Zero-Baseline Execution

> **Game-changer for local models**: Workflows bypass the entire baseline overhead!

### The Problem with Normal LLM Routing

Every normal chat requires loading:
```
System Prompt:      ~5,000 tokens
Tool Definitions:  ~30,000 tokens
MCP Descriptions:   ~1,000 tokens
───────────────────────────────────
TOTAL BASELINE:    ~35,000 tokens
```

For a 32K context model, this **already exceeds** the limit before you even ask a question!

### The Workflow Solution

Workflows execute tools **deterministically** - no LLM routing overhead:

```
Normal LLM Chat:    35,000+ tokens baseline
Workflow:                 0 tokens baseline*
───────────────────────────────────────────
Savings:               99%+ reduction!
```

*LLM tokens only used for optional `llm_prompt` parameter filling

### Real Example: `/quick_note` Workflow

```bash
# This workflow: get_time → remember → canvas
./orchestrator/orchestrator_v2.py cloud "/note buy milk"

# Token usage comparison:
Normal LLM routing: ~35,583 tokens
Workflow execution:     ~244 tokens  ← 99.3% savings!
```

### Why Workflows Bypass Baseline

| Component | Normal Chat | Workflow |
|-----------|-------------|----------|
| System prompt | Required | **Skipped** |
| 57 tool definitions | Required | **Skipped** |
| MCP server info | Required | **Skipped** |
| LLM routing decision | Required | **Skipped** (deterministic) |
| Tool execution | Via LLM | **Direct execution** |

### Impact on Local Models

| Model Context | Normal Chat Feasibility | With Workflows |
|---------------|------------------------|----------------|
| 8K (small) | ❌ Impossible (35K > 8K) | ✅ Works perfectly |
| 32K (Qwen3) | ⚠️ Overflow risk | ✅ 99%+ headroom |
| 128K (large) | ✅ Works | ✅ Even more headroom |

### When to Use Workflows vs Normal Chat

| Use Case | Recommendation |
|----------|----------------|
| Simple Q&A | Normal chat (needs LLM reasoning) |
| Multi-tool tasks with known steps | **Workflow** (deterministic, efficient) |
| Complex research needing judgment | Normal chat (needs LLM decisions) |
| Repetitive tasks (daily reports, backups) | **Workflow** (reliable, cheap) |
| Local model with limited context | **Workflow** (essential!) |

### Creating Workflows

See: `docs/WORKFLOW_ORCHESTRATION.md` and `data/workflows/AGENTS.md`

```bash
# Quick test
./orchestrator/orchestrator_v2.py cloud "/note test"
./orchestrator/orchestrator_v2.py local "/note test"  # Works even on 8K models!
```

---

## 📝 Technical Notes

### Token Counting Method
- **Approximation**: 1 token ≈ 4 characters (typical for Claude/GPT)
- **Actual**: May vary by model and tokenizer
- **Accuracy**: ±10% (good enough for monitoring trends)

### What's NOT Included in Baseline
- User query text
- Tool execution results
- Multi-turn conversation context
- Memory recall results
- LLM's own responses

These are added PER CONVERSATION and vary by task.

---

## 🔗 Related Files

- **Measurement Tool**: `bin/measure-baseline-tokens`
- **System Prompt**: `orchestrator/router_v2.py` (line 49-183)
- **Tool Registry**: `lib/tool_schema.py`
- **Tool Definitions**: `skills/*.tool.json`
- **MCP Config**: `config/mcp-servers.json`

---

**Last Updated**: January 23, 2026  
**Measured By**: `bin/measure-baseline-tokens`

### Recent Updates
- Added workflow token efficiency section (99%+ savings vs normal chat)
- Documented workflow bypass of system prompt and tool definitions
- Added local model guidance for using workflows

