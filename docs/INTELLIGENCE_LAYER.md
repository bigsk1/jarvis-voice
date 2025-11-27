# Jarvis Intelligence Layer

**Status**: Active / Prototype  
**Created**: 2025-11-27  
**Location**: `lib/intelligence.py`, `lib/intelligence_hooks.py`

## Overview

The Intelligence Layer is Jarvis's self-learning system. It observes interactions, reflects on what worked and what didn't, and applies learned insights to improve future routing decisions.

**Key Principle**: Everything is continuous (vectors), not discrete rules. Learning generalizes through semantic similarity.

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

## How It Works (Simple)

```
┌─────────────────────────────────────────────────────────────────┐
│                      USER ASKS QUESTION                         │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. CHECK LEARNED INSIGHTS                                      │
│     "Have I seen similar queries before?"                       │
│     → If yes, inject insights into routing context              │
│     → Bias tool selection based on past success                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. ROUTE & EXECUTE (normal Jarvis flow)                        │
│     Router picks tools → Executor runs them → Response          │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. RECORD EXPERIENCE                                           │
│     What query? What tools? Success? How many turns?            │
│     → Stored as embeddings for semantic matching                │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. REFLECT (async/background)                                  │
│     LLM thinks: "What worked? What didn't? Why?"                │
│     → Extracts generalizable insights                           │
│     → Stores in vector space for future matching                │
└─────────────────────────────────────────────────────────────────┘
```

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

data/
├── jarvis_intelligence.db       # Cloud learning database
├── jarvis_intelligence_local.db # Local learning database

config/
├── cloud.env   # JARVIS_INTELLIGENCE=true/false
├── local.env   # JARVIS_INTELLIGENCE=true/false
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

## Future Enhancements

- [ ] Automatic reflection scheduling
- [ ] Integration with sequential thinking MCP
- [ ] Meta-cognition dashboard
- [ ] Export/import learned insights
- [ ] Cross-mode insight sharing
- [ ] Confidence decay over time
- [ ] A/B testing learned vs naive routing

---

## Related Documentation

- [KNOWLEDGE_GRAPH_MEMORY_EXPLORATION.md](KNOWLEDGE_GRAPH_MEMORY_EXPLORATION.md) - Vision doc
- [MEMORY_SYSTEM.md](MEMORY_SYSTEM.md) - Main memory system
- [MEMORY_SYSTEM_TUNING.md](MEMORY_SYSTEM_TUNING.md) - Memory optimization

