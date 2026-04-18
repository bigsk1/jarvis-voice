# Jarvis Intelligence Layer

**Status**: Active / Phase 1.5 Complete  
**Created**: 2025-11-27  
**Updated**: 2026-04-18 (feedback metadata in experiences; tool traces; presentation artifact learning)
**Location**: `lib/intelligence.py`, `lib/intelligence_hooks.py`

## Overview

The Intelligence Layer is Jarvis's self-learning system. It observes interactions, reflects on what worked and what didn't, and applies learned insights to improve future routing decisions.

![Intelligence Layer Info Graph](images/intelligence-info-graph.jpeg)

**Key Principles**:
- Everything is continuous (vectors), not discrete rules
- Learning generalizes through semantic similarity
- **Phase 1**: Positive AND negative constraints (what to do AND what NOT to do)
- **Phase 1**: Fact vs Procedural classification (only skills stored, not facts)
- **Phase 1**: Generalizability filtering (low-value insights filtered out)

---

## Quick Start

### Enable/Disable

Edit `config/cloud.env` or `config/local.env`:

```bash
# Enable (default)
JARVIS_INTELLIGENCE=true

# Disable for testing/debugging
JARVIS_INTELLIGENCE=false

# Uses current LLM_PROVIDER and related MODEL when you run it
```

When disabled:
- No experiences are recorded
- No insights are applied to routing
- Jarvis works normally (just without learning)
- Database remains intact for when re-enabled

### Check Status

```bash
source ~/jarvis-venv/bin/activate
cd ~/jarvis-voice
python3 -c "
from lib.intelligence import get_intelligence_layer
import json
print(json.dumps(get_intelligence_layer().get_stats(), indent=2))
"
```

---

## Phase 1 Features (Implemented)

### 1. Positive & Negative Constraints

The system now learns BOTH what to do AND what NOT to do:

```
=== LEARNED STRATEGIES (WHAT TO DO) ===
✅ Use mcp_fetch_fetch for real-time server status queries
   → Applies to: System and server health check queries

=== KNOWN FAILURES - AVOID THESE ===
⚠️  These approaches have FAILED in the past:
❌ Avoid search_memory for current Bitcoin prices due to stale data.
   → DO NOT use: search_memory
   → Why: search_memory provided outdated data, leading to retry

=== TOOL PREFERENCES ===
  ✅ PREFER: mcp_fetch_fetch (+0.64)
  ❌ AVOID: search_memory (-0.31)
```

### 2. Fact vs Procedural Classification

The reflection engine now classifies insights:
- **Factual** (e.g., "Server IP is 10.0.0.1") → Sent to Memory DB, NOT stored here
- **Procedural** (e.g., "Use fetch for status queries") → Stored in Intelligence DB

### 3. Generalizability Filtering

Insights are scored for generalizability:
- **High**: "Always use crypto_price for price queries" → Stored
- **Medium**: "Use X for Y in context Z" → Stored with lower weight
- **Low**: "The weather was rainy today" → NOT stored (too specific)

### 4. Decay Tracking (ACTIVE)

Fields that track insight health are now **actively updated**:
- `times_applied` - How often this insight is used ✅ Updated automatically
- `times_helpful` - Success count when applied ✅ Updated automatically
- `times_failed` - Failure count when applied ✅ Updated automatically
- `consecutive_failures` - Rapid decay trigger ✅ Updated automatically
- `last_outcome` - Most recent result (`helpful`/`not_helpful`) ✅ Updated automatically

### 5. Feedback → Intelligence Bridge (Enhanced 2026-04-18)

The feedback system now **retroactively enriches and corrects** experience outcomes based on LLM grading:

```
Flow:
1. Experience recorded with outcome_success = True (default)
2. Feedback LLM grades the interaction (rating 1-5)
3. All ratings store compact feedback metadata in raw_data.feedback.latest
4. If rating ≤ 2: Experience CORRECTED to outcome_success = False
5. Reflection queue priority bumped to 0.8 (high) for failures

Rating Logic:
- Rating 4-5 → Marks user_satisfied when no hard Completion Guard failure exists
- Rating 3   → Ambiguous (left as-is)
- Rating 1-2 → FAILURE (retroactively corrected)
```

**Why this matters**: Previously, `ok: True` was set whenever the LLM responded, even if:
- No tools were called for an action request
- The LLM hallucinated information
- The task wasn't actually completed

Now the feedback system (the nuanced judge with full context) makes the final call on success/failure and preserves the QA reason for reflection.

Feedback is stored alongside, not instead of, Completion Guard metadata:

```json
{
  "feedback": {
    "latest": {
      "rating": 2,
      "summary": "The answer did not provide requested locations and hours.",
      "issues": [{"category": "other", "description": "Missing requested fields"}],
      "tool_ratings": {"serpapi_yelp_search": {"rating": 3}},
      "completion_guard_status": "auto_accepted",
      "updated_at": "2026-04-18T04:30:34"
    },
    "history": []
  }
}
```

The bridge is conservative around Completion Guard:

- Low feedback (`1-2`) can still downgrade a settled answer to failed.
- High feedback (`4-5`) can mark satisfaction but does not erase `had_to_retry`, repaired status, or Completion Guard notes.
- Hard guard outcomes (`unresolved`, `ticket_created`, `error`) are not softened by later high feedback.

### 6. Completion Guard → Intelligence Bridge (2026)

When Jarvis Web runs [Completion Guard](./COMPLETION_GUARD.md), outcomes are written back onto the **same** experience row (no duplicate “repair-only” experiences). `lib/intelligence_hooks.py` provides `update_experience_from_completion_guard()`:

- **`accepted` / `auto_accepted`**: treat the user as satisfied with the settled answer.
- **`repaired`**: count as eventual success with `had_to_retry` and fold corrected speech, tools, and tool results into `raw_data` for reflection (compare first pass vs fix); bumps reflection queue priority (0.85).
- **`unresolved` / `ticket_created` / `error`**: mark failure for learning; higher reflection priority (0.95). **`cancelled`** uses a medium bump (0.7).
- **`expired` / `superseded`**: record neutral manual prompt settlement metadata on the original experience without changing success, satisfaction, retry flags, or reflection priority.

Explicit feedback collection in Web UI is **gated** until guard settlement so grades align with this record. Orchestrator-side random feedback sampling is temporarily disabled while Web Completion Guard is active to avoid pre-collected random feedback racing the guard state. See also [FEEDBACK_SYSTEM.md](./FEEDBACK_SYSTEM.md).

### 7. Tool Trace + Argument Recovery in Reflection (2026-04-18)

Experience context now stores a sanitized `tool_trace` so reflection can inspect attempted tool calls, not just final tool names.

Captured per attempt:

- tool name
- sanitized arguments
- success/failure
- duration
- short error/speech preview

Sensitive keys such as `api_key`, `authorization`, `password`, `secret`, and `token` are redacted before storage. Long strings and large lists/dicts are truncated.

This lets reflection learn reusable lessons such as:

```text
Tool argument values must be concrete user/query values, not JSON schema objects like {"type": "string"}.
```

It also improves insight scoring: a positive insight that recommends a tool is not counted as helpful when that preferred tool failed and a later tool recovered the task.

### 8. Presentation Artifact Learning (2026-04-18)

Experience context now records response presentation metadata:

- `response_style`
- `qa_word_limit`
- `multi_turn_word_limit`
- artifact tools available to the original LLM (`canvas`, `stash` when present)

Reflection uses this to separate evidence failures from presentation failures.

Example:

```text
User asks for multiple places with locations and hours.
Response style is auto/casual.
Artifact tool canvas is available.
```

Reflection may learn:

```text
Use the spoken response for a concise summary and save full structured details to canvas/stash.
```

Guardrail: reflection may only recommend artifact tools that were actually available to the original route. This avoids learning “use canvas” from experiences where `canvas` was not in Tool RAG/ghost tools.

### 9. Provider-Native Tool Metadata in Reflection (2026-04-04)

When providers use native server-side tools such as xAI `x_search` / `web_search` or native code execution, the intelligence layer now treats that as **evidence metadata**, not as Jarvis routing behavior.

- Reflection can see provider-native tool usage so it does **not** misread an empty `tools_used` list as a zero-tool hallucination.
- Completion Guard also treats those native tools as real evidence during audits.
- These native provider tools are **not** converted into `preferred_tool` / `avoided_tool` insights, so Jarvis does not start preferring provider-specific internals over normal Jarvis tools.

---

## Phase 1.5 Features (Implemented 2025-11-28)

### 1. Enhanced Reflection Context

The reflection LLM now receives **complete context** about each interaction:

```
**User Query**: Is my server running?
**Tools Used (in order)**: ["mcp_fetch_fetch"]
**Turns Taken**: 1
**Final Tool**: mcp_fetch_fetch
**Outcome Status**: SUCCESS

**AVAILABLE TOOLS** (what the LLM could choose from):
search_memory, recall, semantic_recall, remember, mcp_fetch_fetch, execute_bash...

**TOOL CATEGORIES**:
MEMORY TOOLS (check FIRST per memory-first rule): search_memory, recall, semantic_recall
ACTION TOOLS (use after memory): mcp_fetch_fetch, execute_bash, api_call, send_webhook

**Tool Results** (what the tools returned):
{"mcp_fetch_fetch": {"status": 200, "body": "Ollama is running..."}}

**LLM Response** (what was said to the user):
"Yes, your Ollama server is running and healthy."

CRITICAL EVALUATION:
1. Did the tool(s) return relevant data for the query? YES/NO
2. Did the response accurately use the tool data? YES/NO
3. Did the response actually answer the user's question? YES/NO
```

**Why this matters**: The reflection LLM can now evaluate **content quality**, not just tool success.

### 2. Content Quality Evaluation

New reflection output fields:
```json
{
  "tool_returned_relevant_data": true,
  "response_matched_tool_data": true,
  "response_answered_query": true,
  "content_quality_notes": "Prices rounded and formatted correctly"
}
```

### 3. Insight Tracking (Now Active!)

When an insight matches a query:
1. `times_applied` incremented
2. After interaction completes:
   - Success → `times_helpful` +1, `consecutive_failures` = 0
   - Failure → `times_failed` +1, `consecutive_failures` +1
   - `last_outcome` updated to `helpful` or `not_helpful`

### 4. Maintenance Jobs

Three automated maintenance jobs keep the intelligence layer healthy:

#### Decay Job
```bash
# Config
INTELLIGENCE_DECAY_RATE=0.95           # 5% decay per week unused
INTELLIGENCE_DECAY_INTERVAL_DAYS=14    # Minimum days between decay runs
```

**What it does**:
- Checks each insight's `last_applied` timestamp
- If unused >7 days: `confidence *= DECAY_RATE`
- If has failures: extra decay `confidence *= 0.9^consecutive_failures`
- If successful (>80% helpful): slight boost
- If confidence drops below 0.15: **auto-pruned**

**⚠️ IMPORTANT**: The decay job tracks when it was last run and **skips if run within the minimum interval** (default: 14 days). This prevents accidental double-decay from compounding confidence reductions. Use `--force` to bypass if needed.

#### Anomaly Detection
```bash
# Config
INTELLIGENCE_ANOMALY_THRESHOLD=2.5  # Z-score threshold
```

**What it does**:
- Calculates baseline: average turns, standard deviation
- Flags experiences with z-score > threshold
- Flags failed multi-turn (>3 turns) experiences
- Logged for review but NOT auto-corrected

#### Meta-Cognition
**What it does**:
- **Blind spot detection**: Tools with >30% failure rate
- **Over-generalization**: Insights that fail when applied
- **Learning quality**: Low avg confidence, unused insights
- Stores findings in `meta_knowledge` table for analysis

### 5. New Log Events

All logged to `logs/intelligence/intelligence-YYYY-MM-DD.jsonl`:

| Event | When | Key Fields |
|-------|------|------------|
| `maintenance_run` | After any maintenance job | `job_type`, `stats` |
| `decay_applied` | Insight confidence reduced | `insight_id`, `old_confidence`, `new_confidence`, `reason` |
| `insight_pruned` | Insight removed (conf < 0.15) | `insight_id`, `reason` |
| `anomaly_detected` | Unusual experience flagged | `experience_id`, `anomaly_type`, `details` |
| `meta_cognition` | Meta-knowledge finding | `meta_type`, `observation`, `conclusion`, `action_taken` |

---

## How It Works (Detailed Architecture)

### Overview Flow (Simple)

```
USER QUERY → Check Insights → Route & Execute → Record Experience → Reflect (async)
                                                      ↑
                                            Feedback / Completion Guard updates?
                                                      ↓
                                            Attach metadata and correct outcome when needed
```

### Detailed Flow: Python vs LLM Calls

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              USER ASKS QUESTION                                 │
│                          "Is my server running?"                                │
└────────────────────────────────┬────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  1. CHECK LEARNED INSIGHTS (Python + Embedding API)                             │
│  ────────────────────────────────────────────────────────────────────────────── │
│  [PYTHON] get_routing_insights(query)                                           │
│     │                                                                           │
│     ├─▶ [EMBEDDING API] get_embedding(query)  ← OpenAI/Ollama call              │
│     │      Returns: 1536/768-dim vector                                         │
│     │                                                                           │
│     ├─▶ [PYTHON] Cosine similarity search in insights DB                        │
│     │      Finds: matching insights by pattern_embedding                        │
│     │                                                                           │
│     └─▶ [LOG] logs/intelligence/intelligence-YYYY-MM-DD.jsonl                   │
│            Event: "insights_applied"                                            │
│                                                                                 │
│  Output: { tool_biases: {mcp_fetch: +0.85, search_memory: -0.53}, ... }        │
└────────────────────────────────┬────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  2. INJECT INTO ROUTING CONTEXT (Python)                                        │
│  ────────────────────────────────────────────────────────────────────────────── │
│  [PYTHON] format_insights_for_prompt(insights)                                  │
│     │                                                                           │
│     └─▶ Prepends to transcript:                                                 │
│         "=== LEARNED STRATEGIES ===                                             │
│          ✅ Use mcp_fetch for status queries                                    │
│          === KNOWN FAILURES ===                                                 │
│          ❌ Avoid search_memory for real-time data"                             │
└────────────────────────────────┬────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  3. ROUTE & EXECUTE (Main LLM - same provider as config)                        │
│  ────────────────────────────────────────────────────────────────────────────── │
│  [LLM CALL] router.route(enhanced_transcript)  ← xAI/Anthropic/OpenAI/Ollama   │
│     │       Uses: LLM_PROVIDER from config                                      │
│     │       This is the MAIN routing LLM (same as normal Jarvis)                │
│     │                                                                           │
│     ├─▶ [LOG] logs/llm-calls-YYYY-MM-DD.jsonl                                   │
│     │                                                                           │
│     └─▶ Tool execution → Result                                                 │
│                                                                                 │
│  Output: { intent: "tool", tool: "mcp_fetch_fetch", ... }                      │
└────────────────────────────────┬────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  4. RECORD EXPERIENCE (Python + Embedding API)                                  │
│  ────────────────────────────────────────────────────────────────────────────── │
│  [PYTHON] record_experience(query, tools_used, outcome)                         │
│     │                                                                           │
│     ├─▶ [EMBEDDING API] get_embedding(query)                                    │
│     ├─▶ [EMBEDDING API] get_embedding(outcome_description)                      │
│     │      (This is why you see 2 embedding calls!)                             │
│     │                                                                           │
│     ├─▶ [PYTHON] INSERT INTO experiences (SQLite)                               │
│     ├─▶ [PYTHON] INSERT INTO reflection_queue                                   │
│     │                                                                           │
│     └─▶ [LOG] Event: "experience_recorded"                                      │
│                                                                                 │
│  Output: experience_id = 8                                                      │
└────────────────────────────────┬────────────────────────────────────────────────┘
                                 │
                                 ▼  (async/on-demand)
┌─────────────────────────────────────────────────────────────────────────────────┐
│  5. REFLECT ON EXPERIENCE (SEPARATE LLM CALL - same provider)                   │
│  ────────────────────────────────────────────────────────────────────────────── │
│  [PYTHON] reflect_on_experience(experience_id)                                  │
│     │                                                                           │
│     ├─▶ [LOG] Event: "reflection_started"                                       │
│     ├─▶ [LOG] Event: "reflection_prompt" (preview of what's sent)               │
│     │                                                                           │
│     ├─▶ [LLM CALL] provider.chat(reflection_prompt)  ← SEPARATE LLM SESSION    │
│     │      Provider: Same as LLM_PROVIDER (xAI/Anthropic/OpenAI/Ollama)         │
│     │      System: "You are a self-reflective AI analyzing your behavior..."    │
│     │      Prompt: "Analyze this interaction... Was first tool optimal?..."     │
│     │                                                                           │
│     ├─▶ [LOG] Event: "reflection_response" (provider, model, JSON result)       │
│     │                                                                           │
│     └─▶ [PYTHON] Parse JSON response → Store insight                            │
│                                                                                 │
│  Output: { constraint_type: "positive", insight: "Use mcp_fetch...", ... }     │
└────────────────────────────────┬────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  6. STORE INSIGHT (Python + Embedding API)                                      │
│  ────────────────────────────────────────────────────────────────────────────── │
│  [PYTHON] _store_insight(reflection, experience)                                │
│     │                                                                           │
│     ├─▶ [PYTHON] Filter: is_procedural? generalizability != 'low'?              │
│     │      If factual → [LOG] "insight_skipped" → return                        │
│     │                                                                           │
│     ├─▶ [EMBEDDING API] get_embedding(insight_text)                             │
│     ├─▶ [EMBEDDING API] get_embedding(pattern_text)                             │
│     │                                                                           │
│     ├─▶ [PYTHON] INSERT INTO insights (SQLite)                                  │
│     │                                                                           │
│     └─▶ [LOG] Event: "insight_created" or "insight_updated"                     │
│                                                                                 │
│  Output: insight_id = 5                                                         │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────┐
│  7. META-COGNITION (Python only - NO LLM)                                       │
│  ────────────────────────────────────────────────────────────────────────────── │
│  [PYTHON] evaluate_learning_quality()                                           │
│     │                                                                           │
│     ├─▶ [PYTHON] Query insights table for stats                                 │
│     │      - Average confidence                                                 │
│     │      - Evidence counts                                                    │
│     │      - Pattern diversity                                                  │
│     │                                                                           │
│     └─▶ [PYTHON] Return analysis with potential_issues                          │
│                                                                                 │
│  Output: { avg_confidence: 0.85, potential_issues: [...] }                     │
│  NOTE: This is PURE PYTHON - no LLM call! Just database analysis.              │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Summary: What Calls What

| Step | Python | Embedding API | LLM Call | Log Event |
|------|--------|---------------|----------|-----------|
| 1. Check insights | ✅ | ✅ (1 call) | ❌ | `insights_applied` |
| 2. Format prompt | ✅ | ❌ | ❌ | - |
| 3. Route & execute | ✅ | ❌ | ✅ **Main LLM** | `llm-calls-*.jsonl` |
| 4. Record experience | ✅ | ✅ (2 calls) | ❌ | `experience_recorded` |
| 5. Reflect | ✅ | ❌ | ✅ **Reflection LLM** | `reflection_*` |
| 6. Store insight | ✅ | ✅ (2 calls) | ❌ | `insight_created` |
| 7. Meta-cognition | ✅ | ❌ | ❌ | `meta_cognition` |
| 8. Decay job | ✅ | ❌ | ❌ | `maintenance_run`, `decay_applied` |
| 9. Anomaly detection | ✅ | ❌ | ❌ | `maintenance_run`, `anomaly_detected` |

**Key Insight**: The reflection uses the **same LLM provider** as your main config, but it's a **separate session/call** with a different system prompt focused on self-analysis.

### Cost Analysis

| Operation | LLM Calls | Embedding Calls | DB Operations |
|-----------|-----------|-----------------|---------------|
| Per user query | 1 main LLM | 1 (query embed) | 2 reads, 2 writes |
| Per reflection | 1 reflection LLM | 2 (insight + pattern) | 1-2 writes |
| Per maintenance run | 0 | 0 | N reads/writes |

**Tip**: Batch reflections (trigger 5-10 at a time) to reduce overhead. Maintenance jobs are pure Python—no external API calls.

---

## Database Files

### Cloud Mode
```
data/jarvis_intelligence.db
```

### Local Mode
```
data/jarvis_intelligence_local.db
```

**Why separate?** Embeddings use different models:
- Cloud: OpenAI embeddings (1536 dimensions)
- Local: Ollama/nomic embeddings (768 dimensions)

### Database Recreation

If the database is deleted or doesn't exist, it will be **automatically created** on next run with empty tables. No data loss to the main system—Jarvis continues to work, just without learned insights.

```bash
# Backup
cp data/jarvis_intelligence.db data/jarvis_intelligence.db.backup

# Reset (start fresh)
rm data/jarvis_intelligence.db
# Next query will recreate it empty
```

---

## Compatibility

### Cloud vs Local Mode ✅

| Mode | Works? | Notes |
|------|--------|-------|
| Cloud (OpenAI/Anthropic/xAI) | ✅ Yes | Uses cloud embeddings |
| Local (Ollama) | ✅ Yes | Uses local embeddings |
| Switching modes | ✅ Yes | Separate databases |

### Tools & MCP Servers ✅

| Scenario | Effect | Notes |
|----------|--------|-------|
| Disable a tool | ✅ Works | Old insights still valid, tool just won't be selected |
| Enable a tool | ✅ Works | New experiences will include it |
| Add new tool | ✅ Works | System learns about it naturally |
| Remove tool | ✅ Works | Insights filtered at prompt time (won't recommend unavailable tools) |
| Block tool via `BLOCKED_TOOLS` | ✅ Works | Tool skipped during sync, insights filtered |
| Disable MCP server | ✅ Works | MCP tools unavailable, learning continues |
| Add new MCP server | ✅ Works | New tools discovered, learning includes them |

**Why it's resilient**: Insights are stored as **semantic embeddings**, not exact tool names. If a tool is removed, similar tools may still match the learned patterns.

#### Tool Blocklist (BLOCKED_TOOLS)

Block specific tools from being synced to the database:

```bash
# In config/cloud.env or config/local.env
BLOCKED_TOOLS="mcp_blinko_webSearch,mcp_blinko_webExtra"
```

**Precedence** (highest to lowest):
1. `BLOCKED_TOOLS` in `.env` → Always skipped during sync
2. `enabled=false` in `.tool.json` → Skipped (local skills)
3. MCP discovered / `enabled=true` → Synced normally

After editing `BLOCKED_TOOLS`, run `./bin/sync_tools.py cloud` (or `local`).

#### Insight Filtering for Unavailable Tools

When insights are formatted for the LLM prompt, the orchestrator builds the **allowed tool set** as:

1. `enabled = 1` rows in `tool_definitions` (same DB as Tool RAG)
2. Minus **Web UI** blocked tools (`excluded_tools` from the chat request)
3. Minus **`JARVIS_TOOL_PROFILE` overrides** where the value is `false`

Then:

1. **Positive** insights are dropped if **`preferred_tools`** references any tool not in that set
2. Insight text is scanned only for **tool-like names** (contains `_` or starts with `mcp_`) so plain English words such as “weather” are not confused with the `weather` tool when `preferred_tools` is empty
3. **Negative** insights are kept (failure patterns)
4. **tool_biases** are filtered to allowed tools only

This ensures:
- **Cross-mode safety**: Cloud insights synced to local won't recommend cloud-only tools ( most are for both modes)
- **Blocked + profiles**: Web UI blocks and profile overlays align with learned-strategy injection
- **No wasted tokens**: LLM only sees recommendations for tools it can actually call

---

## What Gets Learned

### Experience Recording
Every interaction records:
- Query (as embedding)
- Tools used (in order)
- Turns taken
- Success/failure
- User satisfaction signals

### Insights Generated
After reflection, insights capture:
- **Pattern**: "Status queries need real-time tools"
- **Applies to**: "Server health, uptime checks"
- **Preferred approach**: "Use fetch tools directly"
- **Confidence**: 0.0-1.0

### How Insights Apply
When a new query comes in:
1. Generate query embedding
2. Find similar insights (cosine similarity)
3. Weight by confidence and relevance
4. Inject into routing context

---

## File Locations

```
lib/
├── intelligence.py         # Core intelligence layer
├── intelligence_hooks.py   # Orchestrator integration hooks
├── embeddings.py           # Embedding generation (with fallback)

bin/
├── check-intelligence-health.py    # Health check script
├── sync-intelligence-db.py         # Sync between cloud/local
├── run-intelligence-maintenance.py # Run decay/anomaly/meta-cognition jobs
├── re-embed-insight                # Re-embed insight after manual edit
├── re-embed-experience             # Re-embed experience after manual edit

api/routes/
├── intelligence.py         # REST API endpoints for intelligence

data/
├── jarvis_intelligence.db       # Cloud learning database (1536-dim)
├── jarvis_intelligence_local.db # Local learning database (768-dim)

config/
├── cloud.env   # JARVIS_INTELLIGENCE=true/false + tuning params
├── local.env   # JARVIS_INTELLIGENCE=true/false + tuning params

logs/intelligence/
├── intelligence-YYYY-MM-DD.jsonl  # Daily intelligence logs

tests/integration/
├── test_intelligence_integration.py  # Integration tests
```

---

## Configuration

### Environment Variables

```bash
# Enable/disable intelligence (default: true)
JARVIS_INTELLIGENCE=true

# Learning parameters (advanced, optional)
INTELLIGENCE_LEARNING_RATE=0.1          # How fast to update confidence on new evidence
INTELLIGENCE_DECAY_RATE=0.95            # Decay multiplier per week unused (0.95 = 5% decay)
INTELLIGENCE_DECAY_INTERVAL_DAYS=14     # Minimum days between decay runs (prevents double-decay)
INTELLIGENCE_ANOMALY_THRESHOLD=2.5      # Z-score threshold for outlier detection
INTELLIGENCE_MIN_CONFIDENCE=0.3         # Minimum confidence to apply insight to routing
INTELLIGENCE_NEGATIVE_WEIGHT=1.5        # Multiplier for negative constraints (higher = stronger)
```

### Parameter Tuning Guide

| Parameter | Low Value | High Value | Recommendation |
|-----------|-----------|------------|----------------|
| `LEARNING_RATE` | 0.05 (slow learning) | 0.3 (fast adaptation) | Start at 0.1 |
| `DECAY_RATE` | 0.8 (aggressive pruning) | 0.99 (persistent) | 0.95 is balanced |
| `ANOMALY_THRESHOLD` | 1.5 (flag more) | 3.5 (flag less) | 2.5 catches outliers |
| `MIN_CONFIDENCE` | 0.1 (use weak insights) | 0.5 (only strong) | 0.3 is balanced |
| `NEGATIVE_WEIGHT` | 1.0 (equal to positive) | 2.0 (strong penalty) | 1.5 makes negatives win |

**NEGATIVE_WEIGHT explained**: When multiple insights conflict (e.g., 2 positive + 1 negative for same tool), this multiplier ensures negative constraints are respected. At 1.5, a single negative insight can outweigh multiple weak positives.

### Adding to Config Files

Add to `config/cloud.env` and `config/local.env`:

```bash
# ===== Intelligence Layer =====
# Enable self-learning from interactions
JARVIS_INTELLIGENCE=true
```

---

## Integration Points

### In Orchestrator (`orchestrator_v2.py`)

```python
# BEFORE routing (line ~90)
learning_context = self._get_learning_insights(transcript)
if learning_context:
    enhanced_transcript = f"{learning_context}\n\n{enhanced_transcript}"

# AFTER completion (line ~300)
self._record_learning_experience(transcript, tools_used, response, conversation_context)
```

### Hooks Available (`intelligence_hooks.py`)

```python
from intelligence_hooks import (
    record_interaction,      # Record an experience, returns experience_id
    update_experience_from_feedback,  # Correct experience based on feedback rating
    update_experience_from_completion_guard,  # Attach guard status/repair metadata
    get_routing_insights,    # Get insights for a query
    format_insights_for_prompt,  # Format for LLM context
    trigger_reflection,      # Process pending reflections
    get_learning_stats,      # Get current stats
    evaluate_learning        # Meta-cognition check
)
```

**Note**: `record_interaction()` now returns the `experience_id` (int) instead of bool. This enables linking feedback ratings back to experiences for retroactive correction.

---

## Benefits

### With Intelligence Layer

| Aspect | Benefit |
|--------|---------|
| **Tool Selection** | Learns which tools work for which query types |
| **Efficiency** | Reduces multi-turn loops by learning optimal paths |
| **Personalization** | Adapts to YOUR query patterns |
| **Resilience** | Gracefully handles outliers/bad sessions |
| **Transparency** | Can inspect what was learned |

### Without Intelligence Layer

| Aspect | Impact |
|--------|--------|
| **Tool Selection** | Always starts fresh, no memory |
| **Efficiency** | May repeat same mistakes |
| **Personalization** | Same behavior for everyone |
| **Resources** | Slightly lower (no embedding calls for learning) |

---

## Reflection Process

### When Does Reflection Happen?

Currently: **On-demand** via `trigger_reflection()`

Future options:
- After every N interactions
- At end of session
- Background async process
- Scheduled (cron)

### Manual Reflection

```bash
source ~/jarvis-venv/bin/activate
cd ~/jarvis-voice
python3 -c "
from lib.intelligence_hooks import trigger_reflection
processed = trigger_reflection(batch_size=5)
print(f'Processed {processed} reflections')
"
```

### What Reflection Does

1. Takes a recorded experience
2. Asks LLM: "What worked? What didn't? Why?"
3. Extracts generalizable insight
4. Stores as embedding for future matching

---

┌─────────────────────────────────────────────────────────────────┐
│  EVERY USER INTERACTION                                         │
├─────────────────────────────────────────────────────────────────┤
│  1. User asks question                                          │
│  2. LLM routes → Tools execute → Response                       │
│  3. Experience recorded to `experiences` table                  │
│  4. Entry added to `reflection_queue` (processed=0)  ← QUEUED   │
│                                                                 │
│  ❌ NO automatic reflection! Just queued.                       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  WHEN YOU TRIGGER REFLECTION (manually or scheduled)            │
├─────────────────────────────────────────────────────────────────┤
│  trigger_reflection(batch_size=3)                               │
│     │                                                           │
│     ├─▶ Fetch 3 pending from queue                              │
│     │                                                           │
│     ├─▶ For EACH experience:                                    │
│     │      └─▶ SEPARATE LLM CALL (reflection prompt)            │
│     │           - Analyze what worked/didn't                    │
│     │           - Generate insight JSON                         │
│     │           - Store in `insights` table                     │
│     │           - Mark as processed=1                           │
│     │                                                           │
│     └─▶ Return count processed                                  │
└─────────────────────────────────────────────────────────────────┘


Why It's Not Automatic
Currently, reflection is on-demand because:
Each reflection = 1 LLM API call = cost
Reflection can be slow (2-5 seconds per experience)
You might want to batch them (cheaper, less interruption)

```bash
# Manual trigger (process 5 at a time)
source ~/jarvis-venv/bin/activate && cd ~/jarvis-voice
python3 -c "
from lib.intelligence_hooks import trigger_reflection
processed = trigger_reflection(batch_size=5)
print(f'Processed {processed} reflections')
"

# Or via API
curl -X POST "http://localhost:8880/api/intelligence/reflect?batch_size=5"
```

Let me check the code to explain exactly how the reflection queue works:

[3 tools called]

## How the Reflection Queue Works

### Current Behavior

```
┌─────────────────────────────────────────────────────────────────┐
│  EVERY USER INTERACTION                                         │
├─────────────────────────────────────────────────────────────────┤
│  1. User asks question                                          │
│  2. LLM routes → Tools execute → Response                       │
│  3. Experience recorded to `experiences` table                  │
│  4. Entry added to `reflection_queue` (processed=0)  ← QUEUED   │
│                                                                 │
│  ❌ NO automatic reflection! Just queued.                       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  WHEN YOU TRIGGER REFLECTION (manually or scheduled)            │
├─────────────────────────────────────────────────────────────────┤
│  trigger_reflection(batch_size=3)                               │
│     │                                                           │
│     ├─▶ Fetch 3 pending from queue                              │
│     │                                                           │
│     ├─▶ For EACH experience:                                    │
│     │      └─▶ SEPARATE LLM CALL (reflection prompt)            │
│     │           - Analyze what worked/didn't                    │
│     │           - Generate insight JSON                         │
│     │           - Store in `insights` table                     │
│     │           - Mark as processed=1                           │
│     │                                                           │
│     └─▶ Return count processed                                  │
└─────────────────────────────────────────────────────────────────┘
```

### What "3 Pending" Means

- **You've had 3 interactions** that recorded experiences
- **None have been reflected on yet** (LLM hasn't analyzed them)
- The experiences are **waiting** for you to trigger reflection

### Why It's Not Automatic

Currently, reflection is **on-demand** because:
1. Each reflection = 1 LLM API call = cost
2. Reflection can be slow (2-5 seconds per experience)
3. You might want to batch them (cheaper, less interruption)

### How to Process the Queue

```bash
# Manual trigger (process 5 at a time)
source ~/jarvis-venv/bin/activate && cd ~/jarvis-voice
python3 -c "
from lib.intelligence_hooks import trigger_reflection
processed = trigger_reflection(batch_size=5)
print(f'Processed {processed} reflections')
"

# Or via API
curl -X POST "http://localhost:8880/api/intelligence/reflect?batch_size=5"
```

### Future Options

Could add automatic reflection in the future:

| Option | Trigger | Pros | Cons |
|--------|---------|------|------|
| **After every N interactions** | Every 5 queries | Fresh insights | More LLM calls |
| **End of session** | When Jarvis goes idle | Batched, efficient | Delayed learning |
| **Cron job** | Every hour | Predictable | Could be stale |
| **Background daemon** | Continuous | Always learning | Resource usage |

Could also tell jarvis to send api to ( leave details in intel file?)

source ~/jarvis-venv/bin/activate && cd ~/jarvis-voice/monitoring && curl -X POST "http://localhost:8880/api/intelligence/reflect?batch_size=5"
Results
{"status":"ok","processed":3,"message":"Processed 3 pending reflections"}

---


## Maintenance Jobs

### Running Maintenance

**CLI (Recommended)**:
```bash
# Run ALL jobs with log tail (watch mode)
./bin/run-intelligence-maintenance.py --watch

# Individual jobs
./bin/run-intelligence-maintenance.py --decay
./bin/run-intelligence-maintenance.py --anomaly
./bin/run-intelligence-maintenance.py --meta

# Specify mode
./bin/run-intelligence-maintenance.py --mode local --watch

# Force decay run (bypasses minimum interval check - use with caution!)
./bin/run-intelligence-maintenance.py --decay --force
```

**⚠️ Decay Job Interval Protection**: The decay job tracks when it was last run and will **skip** if run within `INTELLIGENCE_DECAY_INTERVAL_DAYS` (default: 14 days). This prevents accidental double-decay which compounds confidence reductions incorrectly. Use `--force` only if you understand the implications.

**API Endpoints**:
```bash
# Run all maintenance jobs
curl -X POST http://localhost:8880/api/intelligence/maintenance/all

# Individual jobs
curl -X POST http://localhost:8880/api/intelligence/maintenance/decay
curl -X POST http://localhost:8880/api/intelligence/maintenance/anomaly
curl -X POST http://localhost:8880/api/intelligence/maintenance/meta-cognition

# View meta-knowledge findings
curl http://localhost:8880/api/intelligence/meta-knowledge
```

### What Each Job Does

#### 1. Decay Job (`--decay`)
**Purpose**: Keep insight pool fresh by decaying unused/failed insights

**⚠️ Interval Protection**: The decay job tracks when it was last run in the `meta_knowledge` table. If run within `INTELLIGENCE_DECAY_INTERVAL_DAYS` (default: 14 days), it will **skip** with status `"skipped"`. Use `--force` to bypass.

**Why?** Running decay multiple times compounds the reduction incorrectly:
- First run: 1.0 → 0.95 (correct: 5% decay)
- Second run same day: 0.95 → 0.9025 (wrong: double decay!)

**Algorithm**:
```
1. Check if decay ran within minimum interval
   If yes: SKIP (unless --force)

2. For each insight:
   a. If last_applied > 7 days ago:
      confidence *= DECAY_RATE  (default 0.95 = 5% decay)
   
   b. If consecutive_failures > 0:
      confidence *= 0.9 ^ consecutive_failures
   
   c. If helpful_ratio > 80%:
      confidence *= 1.02  (2% boost)
   
   d. If confidence < 0.15:
      DELETE insight (pruned)

3. Record run timestamp in meta_knowledge table
```

**Log Events**:
- `decay_applied` - When confidence reduced
- `insight_pruned` - When insight deleted
- `maintenance_run` with `job_type: "decay_job"`

**Understanding the Two Boost Systems**:

There are TWO separate mechanisms that can boost insight confidence:

| System | When | Boost Amount | Conditions |
|--------|------|--------------|------------|
| **Real-Time** | After each interaction | **+5% flat** | Insight was shown to LLM AND interaction succeeded |
| **Maintenance** | During decay job | **×1.02 (2%)** | Insight applied 3+ times AND >80% success rate |

```python
# Real-time boost (in record_insight_usage)
# Happens IMMEDIATELY after each successful use
if was_helpful:
    new_confidence = min(1.0, old_confidence + 0.05)  # +5% flat

# Maintenance boost (in run_decay_job)  
# Only during maintenance, AFTER time-decay applied
if times_applied > 3 and success_rate > 80%:
    new_confidence = min(1.0, new_confidence * 1.02)  # ×1.02
```

**Key insight**: The maintenance boost (1.02×) is applied AFTER the time-decay, so it mitigates but cannot prevent decay for rarely-used insights. See "Rare-But-Valid Insights Decay Problem" in Known Limitations.

#### 2. Anomaly Detection (`--anomaly`)
**Purpose**: Flag unusual experiences for manual review

**Algorithm**:
```
1. Calculate baseline:
   avg_turns = mean(all experience turns)
   std_dev = stddev(all experience turns)

2. For each experience:
   z_score = (turns - avg_turns) / std_dev
   
   If z_score > ANOMALY_THRESHOLD:
     FLAG as "high_turns" anomaly
   
   If turns > 3 AND success = false:
     FLAG as "failed_multi_turn" anomaly
```

**Log Events**:
- `anomaly_detected` - When unusual experience found
- `maintenance_run` with `job_type: "anomaly_detection"`

#### 3. Meta-Cognition (`--meta`)
**Purpose**: Analyze learning health and identify issues

**Detects**:
| Issue Type | Detection | Example |
|------------|-----------|---------|
| **Blind Spots** | Tool fails >30% of time | "mcp_fetch fails often for server queries" |
| **Over-Generalization** | Insight fails >50% when applied | "This insight doesn't work in practice" |
| **Learning Quality** | Low avg confidence, many unused | "Parameters may need tuning" |

**Log Events**:
- `meta_cognition` - When finding recorded
- `maintenance_run` with `job_type: "meta_cognition"`

**Database**: Findings stored in `meta_knowledge` table:
```sql
SELECT * FROM meta_knowledge ORDER BY created_at DESC;
```

### Recommended Schedule

```bash
# Add to crontab for daily maintenance
0 4 * * * cd ~/jarvis-voice && source ~/jarvis-venv/bin/activate && ./bin/run-intelligence-maintenance.py --mode cloud
```

Or trigger manually after heavy usage days.

---

## Health Check & Sync Tools

### Check Intelligence Health

```bash
# Check cloud mode
./bin/check-intelligence-health.py cloud

# Check local mode
./bin/check-intelligence-health.py local

# Check both modes
./bin/check-intelligence-health.py --both

# JSON output for scripting
./bin/check-intelligence-health.py --json
```

Output shows:
- Database status
- Embedding dimension validation
- Experience/insight counts
- Constraint type breakdown (positive/negative)
- Average confidence
- Warnings about stale reflections

### Sync Intelligence Between Modes

```bash
# Sync from cloud → local (regenerates 768-dim embeddings)
./bin/sync-intelligence-db.py local

# Sync from local → cloud (regenerates 1536-dim embeddings)
./bin/sync-intelligence-db.py cloud

# Reset a database (with backup)
./bin/sync-intelligence-db.py --reset cloud

# Dry run (see what would happen)
./bin/sync-intelligence-db.py --dry-run local

# Reset (delete) a database
./bin/sync-intelligence-db.py --reset local
```

Cloud learned: "Use crypto_price for price queries" (1536-dim embedding)
                          ↓
            SYNC TO LOCAL (regenerate 768-dim)
                          ↓
Local now knows: "Use crypto_price for price queries" (768-dim embedding)


**Note**: Syncing regenerates embeddings for the target mode's embedding model. This ensures dimension compatibility.

**Also preserved during sync**:
- `insights.created_at`
- `insights.updated_at`
- `insights.last_applied`
- `reflection_queue.queued_at` for pending entries

This matters because the decay job falls back to `created_at` when an insight has never been applied. Resetting timestamps would make stale insights look artificially fresh.

### Embedding Fallback

If embedding APIs fail (OpenAI down, Ollama unreachable), the system uses a **deterministic hash-based fallback**:

```
⚠️  FALLBACK EMBEDDING ACTIVE - semantic matching degraded!
```

**Fallback behavior**:
- Same text → same embedding (deterministic) ✅
- Similar text → random similarity (NO semantic meaning) ⚠️

The system continues working but insight matching quality is degraded until real embeddings return.

---

## Troubleshooting

### Intelligence Not Working

```bash
# Check if enabled
grep JARVIS_INTELLIGENCE config/cloud.env

# Check database exists
ls -la data/jarvis_intelligence*.db

# Check stats
python3 -c "
from lib.intelligence import get_intelligence_layer
print(get_intelligence_layer().get_stats())
"
```

### No Insights Being Applied

```bash
# Check if insights exist
python3 -c "
from lib.intelligence import get_intelligence_layer
intel = get_intelligence_layer()
cursor = intel.conn.cursor()
cursor.execute('SELECT COUNT(*) FROM insights')
print(f'Insights: {cursor.fetchone()[0]}')
cursor.execute('SELECT COUNT(*) FROM reflection_queue WHERE processed=0')
print(f'Pending reflections: {cursor.fetchone()[0]}')
"

# Process pending reflections
python3 -c "
from lib.intelligence_hooks import trigger_reflection
trigger_reflection(batch_size=10)
"
```

### Reset Learning

```bash
# Backup first
cp data/jarvis_intelligence.db data/jarvis_intelligence.db.backup

# Delete to start fresh
rm data/jarvis_intelligence.db

# Or clear specific tables
sqlite3 data/jarvis_intelligence.db "DELETE FROM experiences; DELETE FROM insights; DELETE FROM reflection_queue;"
```

---

## Example Flow

### Query: "Is my server running?"

**Turn 1** (without learning):
```
1. Router picks: search_memory (suboptimal)
2. search_memory returns old data
3. Router picks: mcp_fetch (correct)
4. mcp_fetch returns live status
5. Response delivered (2 turns)
```

**Experience Recorded**:
```json
{
  "query": "Is my server running?",
  "tools_used": ["search_memory", "mcp_fetch_fetch"],
  "turns": 2,
  "success": true
}
```

**Reflection Generated**:
```json
{
  "insight": "Status queries need real-time tools, not memory",
  "applies_to": "System status and health checks",
  "preferred_tool": "mcp_fetch_fetch",
  "confidence": 0.95
}
```

**Next Similar Query**: "Is Ollama up?"
```
1. Intelligence finds matching insight (similarity: 0.85)
2. Injects bias: "prefer mcp_fetch for status queries"
3. Router picks: mcp_fetch directly (1 turn!)
4. Response delivered faster
```

## Manually Editing Insights

You can edit insights directly in SQLite (e.g., using SQLite Pro, DB Browser, or command line). However, understanding what needs re-embedding is critical.

### What Needs Re-embedding?

| Field | Embedded? | Safe to Edit? | Impact |
|-------|-----------|---------------|--------|
| `preferred_tools` | ❌ No | ✅ Yes | Directly controls tool bias |
| `avoided_tools` | ❌ No | ✅ Yes | Directly controls tool penalties |
| `confidence` | ❌ No | ✅ Yes | Controls insight weight |
| `reasoning` | ❌ No | ✅ Yes | Documentation only |
| `description` | ✅ Yes (`insight_embedding`) | ⚠️ Re-embed | Affects duplicate detection |
| `applies_to_pattern` | ✅ Yes (`pattern_embedding`) | ⚠️ Re-embed | **Critical for query matching** |

### How Embeddings Work

```
Query: "curl localhost to check ollama"
         │
         ▼
    [Get query embedding]
         │
         ▼
    [Compare to pattern_embedding of each insight]  ← Uses applies_to_pattern
         │
         ▼
    [Find matches: "server health check queries"]
         │
         ▼
    [Apply preferred_tools bias: execute_bash +0.9]  ← Uses preferred_tools (not embedded)
```

### Re-embedding After Manual Edits

If you change `description` or `applies_to_pattern`, run these commands to regenerate embeddings:

**Re-embed an Insight:**
```bash
# Re-embed insight ID 2 (cloud mode - default)
./bin/re-embed-insight 2

# Re-embed insight ID 36 (local mode)
./bin/re-embed-insight 36 local

# Re-embed multiple insights
./bin/re-embed-insight 2 && ./bin/re-embed-insight 36 && ./bin/re-embed-insight 56
```

**Re-embed an Experience:**
```bash
# Re-embed experience ID 5 (cloud mode - default)
./bin/re-embed-experience 5

# Re-embed experience ID 10 (local mode)
./bin/re-embed-experience 10 local
```

**Embedding Dimensions by Mode:**

| Mode | Provider | Dimensions | Database |
|------|----------|------------|----------|
| `cloud` | OpenAI (`text-embedding-3-small`) | 1536 | `jarvis_intelligence.db` |
| `local` | Ollama (`nomic-embed-text`) | 768 | `jarvis_intelligence_local.db` |

The scripts automatically use the correct embedding provider based on the mode parameter. Cloud and local databases are **incompatible** - you cannot copy embeddings between them.

### Example: Fixing an Incorrect Insight

```bash
# 1. Edit in SQLite (or SQLite Pro)
sqlite3 data/jarvis_intelligence.db "
UPDATE insights SET 
    description = 'Use execute_bash for private network checks (192.168.x, localhost)',
    preferred_tools = '{\"execute_bash\": 0.9}'
WHERE id = 42;
"

# 2. Re-embed to update vectors
./bin/re-embed-insight 42

# 3. Verify
sqlite3 data/jarvis_intelligence.db "SELECT id, description, length(insight_embedding) FROM insights WHERE id = 42"
```

### Bottom Line

**Safe to edit directly (no re-embed needed):**
- `preferred_tools`, `avoided_tools`, `confidence`, `reasoning`, `trigger_concept`

**Must re-embed after editing:**
- `description` → run `./bin/re-embed-insight <id>`
- `applies_to_pattern` → run `./bin/re-embed-insight <id>`

---

## Grafana Monitoring (Loki + Prometheus)

The intelligence layer integrates with the existing **Loki + Prometheus + Grafana** stack.

### How It Works

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         INTELLIGENCE MONITORING                                  │
└─────────────────────────────────────────────────────────────────────────────────┘

LOGS (Loki):
  logs/intelligence/intelligence-*.jsonl
      │
      ▼ (promtail scrapes)
  Loki (port 3100)
      │
      ▼ (LogQL queries)
  Grafana Dashboard

METRICS (Prometheus):
  /metrics endpoint (port 8880)
      │
      ▼ (prometheus scrapes every 15s)
  Prometheus (port 9090)
      │
      ▼ (PromQL queries)
  Grafana Dashboard
```

### Prometheus Metrics (via `/metrics`)

Intelligence metrics are exposed on the existing `/metrics` endpoint:

```promql
# Experiences recorded
jarvis_intelligence_experiences_total{mode="cloud"}

# Insights by type
jarvis_intelligence_insights_total{mode="cloud", constraint_type="positive"}
jarvis_intelligence_insights_total{mode="cloud", constraint_type="negative"}

# Pending reflections (should be low)
jarvis_intelligence_pending_reflections{mode="cloud"}

# Average confidence
jarvis_intelligence_avg_confidence{mode="cloud"}

# Helpful ratio (times_helpful / times_applied)
jarvis_intelligence_helpful_ratio{mode="cloud"}

# Is intelligence enabled?
jarvis_intelligence_enabled{mode="cloud"}
```

**Sample curl**:
```bash
curl -s http://localhost:8880/metrics | grep jarvis_intelligence
```

### Loki Log Queries (LogQL)

Intelligence logs are scraped via promtail:

```logql
# All intelligence events
{job="jarvis", log_type="intelligence"}

# Filter by event type
{job="jarvis", log_type="intelligence"} | json | event="reflection_response"
{job="jarvis", log_type="intelligence"} | json | event="insights_applied"
{job="jarvis", log_type="intelligence"} | json | event="experience_recorded"

# Maintenance job events
{job="jarvis", log_type="intelligence"} | json | event="maintenance_run"
{job="jarvis", log_type="intelligence"} | json | event="decay_applied"
{job="jarvis", log_type="intelligence"} | json | event="anomaly_detected"
{job="jarvis", log_type="intelligence"} | json | event="meta_cognition"

# Filter by constraint type
{job="jarvis", log_type="intelligence"} | json | constraint_type="negative"
{job="jarvis", log_type="intelligence"} | json | constraint_type="positive"

# Show reflection prompts
{job="jarvis", log_type="intelligence"} | json | event="reflection_prompt"

# Find insights for specific provider
{job="jarvis", log_type="intelligence"} | json | provider="xai"

# Track tool biases over time
{job="jarvis", log_type="intelligence"} | json | event="insights_applied" | line_format "{{.tool_biases}}"
```

### Log Event Reference

| Event | Description | Key Fields |
|-------|-------------|------------|
| `insights_applied` | Insights matched for routing | `query`, `insights_count`, `tool_biases` |
| `experience_recorded` | Interaction saved | `experience_id`, `query`, `tools_used`, `success` |
| `reflection_started` | Reflection beginning | `experience_id`, `query` |
| `reflection_prompt` | What sent to LLM | `experience_id`, `prompt_preview`, `prompt_length` |
| `reflection_response` | LLM analysis result | `provider`, `model`, `response` (full JSON) |
| `insight_created` | New insight stored | `insight_id`, `constraint_type`, `description`, `confidence` |
| `insight_updated` | Existing insight modified | `insight_id`, `old_confidence`, `new_confidence` |
| `insight_skipped` | Not stored (factual/low-gen) | `reason`, `knowledge_type`, `generalizability` |
| `maintenance_run` | Job completed | `job_type`, `stats` |
| `decay_applied` | Confidence reduced | `insight_id`, `old_confidence`, `new_confidence`, `reason` |
| `insight_pruned` | Insight deleted | `insight_id`, `reason`, `final_confidence` |
| `anomaly_detected` | Unusual experience | `experience_id`, `anomaly_type`, `details` |
| `meta_cognition` | Learning finding | `meta_type`, `observation`, `conclusion`, `action_taken` |

### API Endpoints (REST)

Full REST API for intelligence management:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/intelligence/stats` | GET | Basic stats |
| `/api/intelligence/health` | GET | Health check |
| `/api/intelligence/insights` | GET | Recent insights (last 20) |
| `/api/intelligence/experiences` | GET | Recent experiences (last 20) |
| `/api/intelligence/logs/recent` | GET | Today's log entries |
| `/api/intelligence/reflect` | POST | Trigger reflection manually |
| `/api/intelligence/evaluate` | GET | Meta-cognition evaluation |
| `/api/intelligence/meta-knowledge` | GET | View meta_knowledge findings |
| `/api/intelligence/maintenance/decay` | POST | Run decay job |
| `/api/intelligence/maintenance/anomaly` | POST | Run anomaly detection |
| `/api/intelligence/maintenance/meta-cognition` | POST | Run meta-cognition |
| `/api/intelligence/maintenance/all` | POST | Run all maintenance jobs |

### Sample REST API Calls

```bash
# Health check
curl http://localhost:8880/api/intelligence/health | jq

# View insights
curl http://localhost:8880/api/intelligence/insights | jq '.insights'

# Trigger reflection
curl -X POST "http://localhost:8880/api/intelligence/reflect?batch_size=5"
```

or use to run manually

```bash
python3 -c "from lib.intelligence_hooks import trigger_reflection; trigger_reflection(10)"
```

### Grafana Dashboard Panels

The Intelligence Layer dashboard (`grafana/dashboards/jarvis-intelligence.json`) includes:

**Panel 1: Key Stats Row**
- Intelligence enabled status
- Total experiences
- Total insights (positive/negative)
- Pending reflections
- Average confidence
- Helpful ratio

**Panel 2: Constraint Type Distribution** (Pie Chart)
```promql
jarvis_intelligence_insights_total{constraint_type="positive"}
jarvis_intelligence_insights_total{constraint_type="negative"}
```

**Panel 3: Learning Growth Over Time**
```promql
jarvis_intelligence_experiences_total
sum(jarvis_intelligence_insights_total)
```

**Panel 4: Confidence Trend**
```promql
jarvis_intelligence_avg_confidence
```

**Panel 5: Pending Reflections Queue**
```promql
jarvis_intelligence_pending_reflections
```
Alert if > 10 (reflections backing up)

**Panel 6: Intelligence Event Logs** (Loki)
```logql
{job="jarvis", log_type="intelligence"} | json
```

**Panel 7: Event Type Distribution** (Bar Chart)
```logql
sum by (event) (count_over_time({job="jarvis", log_type="intelligence"} | json [24h]))
```

### LogQL Queries for Analysis

**Tool bias evolution**:
```logql
{job="jarvis", log_type="intelligence"} 
| json 
| event="insights_applied" 
| line_format "{{.tool_biases}}"
```

**Failed insights** (insights that hurt more than help):
```logql
{job="jarvis", log_type="intelligence"} 
| json 
| event="insight_updated" 
| new_confidence < old_confidence
```

**Content quality issues** (tool returned data but answer was wrong):
```logql
{job="jarvis", log_type="intelligence"} 
| json 
| event="reflection_response" 
| response_matched_tool_data=false
```

**Learning quality alerts**:
```logql
{job="jarvis", log_type="intelligence"} 
| json 
| event="meta_cognition" 
| meta_type="learning_quality"
```

### After Enabling Intelligence

Restart promtail to pick up new log config:
```bash
cd ~/jarvis-voice/monitoring
docker-compose restart promtail
```

Verify promtail sees the logs:
```bash
docker-compose logs promtail | grep intelligence
```

### Local Log Inspection

```bash
# Today's logs
cat logs/intelligence/intelligence-$(date +%Y-%m-%d).jsonl | jq

# Filter by event type
cat logs/intelligence/*.jsonl | jq 'select(.event == "reflection_response")'

# Count events by type
cat logs/intelligence/*.jsonl | jq -r '.event' | sort | uniq -c

# See maintenance results
cat logs/intelligence/*.jsonl | jq 'select(.event == "maintenance_run")'

# Find anomalies
cat logs/intelligence/*.jsonl | jq 'select(.event == "anomaly_detected")'

# Meta-cognition findings
cat logs/intelligence/*.jsonl | jq 'select(.event == "meta_cognition")'
```

### Real Log Examples

**Insights Applied** (every query):
```json
{
  "timestamp": "2025-11-28T19:54:11.212759",
  "event": "insights_applied",
  "query": "What is the price of Bitcoin?",
  "insights_count": 3,
  "insights": [
    {"id": 8, "relevance": 0.542},
    {"id": 7, "relevance": 0.518},
    {"id": 6, "relevance": 0.498}
  ],
  "tool_biases": {
    "crypto_price": 1.533,
    "search_memory": -0.162
  }
}
```

**Reflection Response** (after reflection):
```json
{
  "timestamp": "2025-11-28T20:09:31.778891",
  "event": "reflection_response",
  "provider": "xai",
  "model": "grok-4-1-fast-reasoning-latest",
  "response": {
    "is_procedural": true,
    "constraint_type": "positive",
    "trigger_signals": ["current price", "Bitcoin"],
    "first_tool_optimal": true,
    "tool_returned_relevant_data": true,
    "response_matched_tool_data": true,
    "response_answered_query": true,
    "rule": "ALWAYS use crypto_price for cryptocurrency queries",
    "preferred_tool": "crypto_price",
    "generalizability": "high",
    "confidence": 1.0
  }
}
```

**Anomaly Detected**:
```json
{
  "timestamp": "2025-11-28T20:51:48.358172",
  "event": "anomaly_detected",
  "experience_id": 57,
  "anomaly_type": "high_turns",
  "details": {
    "query": "What's the current price of Bitcoin and Ethereum...",
    "reasons": [{
      "type": "high_turns",
      "turns": 3,
      "z_score": 3.54,
      "threshold": 2.5
    }]
  }
}
```

**Meta-Cognition Finding**:
```json
{
  "timestamp": "2025-11-28T20:51:48.360232",
  "event": "meta_cognition",
  "meta_type": "learning_quality",
  "observation": "Found 2 learning quality issue(s)",
  "conclusion": "Many insights never applied - may be too specific; Low insight application rate - matching may be too strict",
  "action_taken": "review_parameters",
  "confidence": 0.6
}
```

**Maintenance Run Summary**:
```json
{
  "timestamp": "2025-11-28T20:51:48.357178",
  "event": "maintenance_run",
  "job_type": "decay_job",
  "stats": {
    "total_checked": 45,
    "decayed": 0,
    "boosted": 0,
    "unchanged": 45,
    "pruned": 0
  }
}
```

---

## Known Limitations

### 1. "Last Tool = Success" Assumption ⚠️

Currently, the system assumes the **last tool used** before task completion was the "successful" one. This is **not always accurate**:

```
Example: User asks "What movies are playing?"
  Turn 1: brave_search → gets showtimes ← THIS was the answer!
  Turn 2: mcp_fetch → tries to get more details → fails
  Turn 3: brave_search → different query → partial results
  
Current behavior: Scores Turn 3's tool highest
Reality: Turn 1 had the answer
```

**Future fix**: Track which tool's output actually appeared in the final response (content attribution).

### 2. User Bias Injection - NOT YET SUPPORTED

Users cannot currently override or inject their own tool preferences. For example:
- "I prefer execute_bash with curl for server checks" 
- "Always use crypto_price, never search_memory for prices"

**Workaround**: Add explicit instructions to `jarvis-intel` files.

**Future**: User preference injection via config or dedicated preference file.

### 3. Only Tool Selection Learning

Current intelligence focuses on **tool routing**. It does NOT learn:
- When to save things to memory
- Response verbosity preferences
- Communication style (formal/casual)
- User-specific terminology

### 4. Rare-But-Valid Insights Decay Problem ⚠️

**The Issue**: Good insights that are rarely triggered decay over time, even when they're 100% correct when used.

**Example scenario**:
```
Insight: "Use crypto_price tool for cryptocurrency queries"
- Created with confidence 1.0
- Works perfectly every time (100% success rate)
- But user only asks about crypto once a month

Day 0:   confidence = 1.00
Day 14:  Decay runs → 1.00 × 0.95² = 0.90  (2 weeks decay)
Day 28:  Decay runs → 0.90 × 0.95² = 0.81
Day 42:  Decay runs → 0.81 × 0.95² = 0.73
Day 56:  Decay runs → 0.73 × 0.95² = 0.66
...eventually drops below threshold and gets pruned!
```

**Why it happens**: The decay formula `confidence *= DECAY_RATE^(days/7)` is based on time since last use, not success rate. The maintenance boost (1.02×) cannot outpace the decay (0.9025×) for rarely-used insights.

**Current design philosophy**: 
- Frequently used + helpful = valuable → stays high
- Rarely used = probably not important → fades away
- This works for common patterns but punishes niche/specialized insights

**Workarounds**:
1. **Manual fix**: Use Intelligence Dashboard UI to manually boost confidence for known-good insights
2. **Increase interval**: Set `INTELLIGENCE_DECAY_INTERVAL_DAYS=30` or higher to slow decay

**Potential future fixes** (not implemented):
- "Verified" flag to exempt insights from time decay
- Category-based decay rates (technical insights decay slower)
- Minimum confidence floor based on success rate (100% success → can't drop below 0.7)
- Success-weighted decay (high success rate reduces decay multiplier)

---

## Future Enhancements

### Phase 1 (Complete) ✅
- [x] Negative constraints (what NOT to do)
- [x] Fact vs Procedural classification  
- [x] Generalizability filtering
- [x] Decay tracking fields
- [x] Schema migration for existing DBs
- [x] Separate positive/negative in prompt formatting
- [x] Health check script (`check-intelligence-health.py`)
- [x] Sync script (`sync-intelligence-db.py`)
- [x] Embedding fallback with logging

### Phase 1.5 (Complete) ✅ - 2025-11-28
- [x] **Enhanced reflection context** - LLM response, tool results, available tools in prompt
- [x] **Content quality evaluation** - Reflection evaluates data relevance, not just tool success
- [x] **Insight tracking (active)** - times_applied, times_helpful, times_failed now updated
- [x] **Decay job** - Auto-decay unused/failed insights
- [x] **Anomaly detection** - Flag unusual experiences (high turns, failed multi-turn)
- [x] **Meta-cognition** - Blind spot detection, over-generalization, learning quality
- [x] **meta_knowledge table** - Store learning system findings
- [x] **Maintenance CLI** - `run-intelligence-maintenance.py`
- [x] **Maintenance API** - REST endpoints for all maintenance jobs
- [x] **Comprehensive logging** - All events for Grafana visibility

### Phase 2 (Planned)
- [ ] **Implicit failure detection** - Detect when user rewords query within 60s
- [ ] **Tool trashing detection** - When Tool A fails → Tool B succeeds, create negative constraint
- [ ] ~~**The Reaper service** - Periodic pruning of low-confidence insights~~ ✅ (now in decay job)
- [ ] **Conflict resolution** - When new insight contradicts old one
- [ ] **Content attribution** - Track which tool's output actually answered the query
- [ ] **User bias injection** - Allow user to specify tool preferences in config

### Phase 3 (User Profile Learning) 🧠
- [ ] **User bias injection** - Config/file to specify tool preferences
- [ ] **Behavioral learning** - Not just tool selection:
  - When to be verbose vs concise
  - When to save to memory automatically
  - Understanding vague requests ("the usual")
- [ ] **Communication style learning**:
  - Serious vs humor appropriate contexts
  - Emotional awareness (encouragement, directness)
  - User-specific terminology and shortcuts
- [ ] **Auto-parameter tuning** - Run test scenarios, adjust:
  ```bash
  INTELLIGENCE_LEARNING_RATE=0.1
  INTELLIGENCE_DECAY_RATE=0.95
  INTELLIGENCE_MIN_CONFIDENCE=0.3
  ```
  Based on measured performance

### Phase 4 (Advanced)
- [ ] **Chain caching / Macro-skills** - Learn entire workflows, not just tool preferences
- [ ] **Grafana dashboard** - Visualize learning metrics
- [ ] **Explicit user feedback** - `--thumbs-down` flag for explicit negative signal
- [ ] **A/B testing** - Compare learned vs naive routing

---

## Vision: Beyond Tool Selection

### The Bigger Picture

Current intelligence focuses narrowly on **tool routing**. But true "intelligence" means understanding:

| Current Scope | Future Scope |
|---------------|--------------|
| Which tool to use | How to respond (style, tone) |
| Avoid bad tools | Remember what's important to user |
| Learn from tool failures | Learn user's communication preferences |
| - | Understand vague/shorthand requests |
| - | Know when to be verbose vs concise |

### User Profile Learning (Exploration)

Imagine Jarvis learning:

```
User says: "Check the thing"
Jarvis knows: User means "Ollama server status" because:
  - User frequently asks about Ollama
  - "the thing" in server context = status check
  - User's jarvis-intel mentions Ollama server
  
User says: "Give me the rundown"
Jarvis knows: User wants verbose mode because:
  - User is catching up after being away
  - Previous context was complex task
  - User profile says "rundown = detailed summary"
```

### How This Could Work

1. **User Preference File** (`jarvis-intel/user_preferences.md`):
   ```markdown
   ## Communication Style
   - Default: concise (under 20 words)
   - "Give me details" → switch to verbose
   - "Quick" → extra concise, just facts
   
   ## Shortcuts
   - "the server" → Ollama at localhost
   - "the usual" → Bitcoin + Ethereum prices
   - "morning routine" → weather + reminders + calendar
   
   ## Tool Preferences
   - Server checks: prefer execute_bash with curl
   - Prices: always use crypto_price tool
   - Never: search_memory for real-time data
   ```

2. **Behavioral Learning Database**:
   - Track response style that got positive signals
   - Learn what user considers "important" to save
   - Model communication preferences over time

3. **Test Scenarios for Auto-Tuning**:
   ```bash
   ./bin/test-intelligence-scenarios.py --tune
   # Runs standard scenarios
   # Measures: correct tool %, turns needed, user satisfaction
   # Suggests parameter adjustments
   ```

### Why This Matters

The goal isn't just "call the right tool" - it's:
> **An assistant that knows YOU and adapts to YOUR way of working**

This is the difference between a tool and a true assistant.

---

## Related Documentation

- [KNOWLEDGE_GRAPH_MEMORY_EXPLORATION.md](KNOWLEDGE_GRAPH_MEMORY_EXPLORATION.md) - Vision doc
- [MEMORY_SYSTEM.md](MEMORY_SYSTEM.md) - Main memory system
- [MEMORY_SYSTEM_TUNING.md](MEMORY_SYSTEM_TUNING.md) - Memory optimization
- [FEEDBACK_SYSTEM.md](FEEDBACK_SYSTEM.md) - Feedback system
- [COMPLETION_GUARD.md](COMPLETION_GUARD.md) - Post-answer completion loop and repair
- [ADVANCED_AI_TECHNIQUES.md](ADVANCED_AI_TECHNIQUES.md) - Advanced AI techniques
