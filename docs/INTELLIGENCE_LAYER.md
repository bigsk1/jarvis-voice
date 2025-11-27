# Jarvis Intelligence Layer

**Status**: Active / Phase 1 Complete  
**Created**: 2025-11-27  
**Updated**: 2025-11-27 (Phase 1: Negative Constraints, Fact/Skill Classification)  
**Location**: `lib/intelligence.py`, `lib/intelligence_hooks.py`

## Overview

The Intelligence Layer is Jarvis's self-learning system. It observes interactions, reflects on what worked and what didn't, and applies learned insights to improve future routing decisions.

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

### 4. Decay Tracking

New fields track insight health:
- `times_applied` - How often this insight is used
- `times_helpful` - Success count when applied
- `times_failed` - Failure count when applied  
- `consecutive_failures` - Rapid decay trigger
- `last_outcome` - Most recent result

---

## How It Works (Detailed Architecture)

### Overview Flow (Simple)

```
USER QUERY → Check Insights → Route & Execute → Record Experience → Reflect (async)
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
| 7. Meta-cognition | ✅ | ❌ | ❌ | - |

**Key Insight**: The reflection uses the **same LLM provider** as your main config, but it's a **separate session/call** with a different system prompt focused on self-analysis.

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
| Remove tool | ✅ Works | Insights mentioning it become less relevant over time |
| Disable MCP server | ✅ Works | MCP tools unavailable, learning continues |
| Add new MCP server | ✅ Works | New tools discovered, learning includes them |

**Why it's resilient**: Insights are stored as **semantic embeddings**, not exact tool names. If a tool is removed, similar tools may still match the learned patterns.

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
├── check-intelligence-health.py  # Health check script
├── sync-intelligence-db.py       # Sync between cloud/local

data/
├── jarvis_intelligence.db       # Cloud learning database (1536-dim)
├── jarvis_intelligence_local.db # Local learning database (768-dim)

config/
├── cloud.env   # JARVIS_INTELLIGENCE=true/false + tuning params
├── local.env   # JARVIS_INTELLIGENCE=true/false + tuning params

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
INTELLIGENCE_LEARNING_RATE=0.1      # How fast to update beliefs
INTELLIGENCE_DECAY_RATE=0.95        # How fast old knowledge fades
INTELLIGENCE_ANOMALY_THRESHOLD=2.5  # Outlier detection sensitivity
INTELLIGENCE_MIN_CONFIDENCE=0.3     # Minimum confidence to apply insight
```

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
    record_interaction,      # Record an experience
    get_routing_insights,    # Get insights for a query
    format_insights_for_prompt,  # Format for LLM context
    trigger_reflection,      # Process pending reflections
    get_learning_stats,      # Get current stats
    evaluate_learning        # Meta-cognition check
)
```

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
curl -X POST "http://192.168.70.228:8880/api/intelligence/reflect?batch_size=5"
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
curl -X POST "http://192.168.70.228:8880/api/intelligence/reflect?batch_size=5"
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

source ~/jarvis-venv/bin/activate && cd ~/jarvis-voice/monitoring && curl -X POST "http://192.168.70.228:8880/api/intelligence/reflect?batch_size=5"
Results
{"status":"ok","processed":3,"message":"Processed 3 pending reflections"}

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
curl -s http://192.168.70.228:8880/metrics | grep jarvis_intelligence
```

### Loki Log Queries (LogQL)

Intelligence logs are scraped via promtail:

```logql
# All intelligence events
{job="jarvis", log_type="intelligence"}

# Filter by event type
{job="jarvis", log_type="intelligence"} | json | event="reflection_response"

# Filter by constraint type
{job="jarvis", log_type="intelligence"} | json | constraint_type="negative"

# Show reflection prompts
{job="jarvis", log_type="intelligence"} | json | event="reflection_prompt"

# Find insights for specific provider
{job="jarvis", log_type="intelligence"} | json | provider="xai"
```

### API Endpoints (REST)

Additional REST endpoints for debugging:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/intelligence/stats` | GET | Basic stats |
| `/api/intelligence/health` | GET | Health check |
| `/api/intelligence/insights` | GET | Recent insights (last 20) |
| `/api/intelligence/experiences` | GET | Recent experiences (last 20) |
| `/api/intelligence/logs/recent` | GET | Today's log entries |
| `/api/intelligence/reflect` | POST | Trigger reflection manually |
| `/api/intelligence/evaluate` | GET | Meta-cognition evaluation |

### Sample REST API Calls

```bash
# Health check
curl http://192.168.70.228:8880/api/intelligence/health | jq

# View insights
curl http://192.168.70.228:8880/api/intelligence/insights | jq '.insights'

# Trigger reflection
curl -X POST "http://192.168.70.228:8880/api/intelligence/reflect?batch_size=5"
```

### Grafana Dashboard Suggestions

**Panel 1: Experience & Insight Growth**
```promql
# Experiences over time
jarvis_intelligence_experiences_total
# Insights over time
sum(jarvis_intelligence_insights_total)
```

**Panel 2: Constraint Balance**
```promql
# Positive vs Negative pie chart
jarvis_intelligence_insights_total{constraint_type="positive"}
jarvis_intelligence_insights_total{constraint_type="negative"}
```

**Panel 3: Confidence Trend**
```promql
jarvis_intelligence_avg_confidence
```

**Panel 4: Pending Reflections (alert if > 10)**
```promql
jarvis_intelligence_pending_reflections
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

### Phase 2 (Planned)
- [ ] **Implicit failure detection** - Detect when user rewords query within 60s
- [ ] **Tool trashing detection** - When Tool A fails → Tool B succeeds, create negative constraint
- [ ] **The Reaper service** - Periodic pruning of low-confidence insights
- [ ] **Conflict resolution** - When new insight contradicts old one
- [ ] **Content attribution** - Track which tool's output actually answered the query

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
   - "the server" → Ollama at 192.168.70.228
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

