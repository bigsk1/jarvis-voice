# Sequential Thinking Architecture - Design Document

> **Status**: **Planning / design reference** — not implemented as described below
> **Verified**: 2026-05-25 against `orchestrator/`, `lib/intelligence.py`, `config/mcp-servers.json`
> **Goal**: Enhance Jarvis's routing intelligence with conditional thinking steps for better tool selection and self-correction
> **Philosophy**: "When in doubt, think. When wrong, learn."

---

## Implementation status (read this first)

This document describes a **future architecture** for conditional multi-step reasoning inside the router. It is **not** the live orchestration path today.

### What is implemented instead

| Capability | Live doc / code | Notes |
|------------|-----------------|-------|
| **Extended thinking blocks** | [EXTENDED_THINKING.md](../EXTENDED_THINKING.md), `lib/thinking.py` | Provider-native reasoning (`reasoning_content`, `--debug-thinking`). Works on supported cloud models. |
| **Intelligence reflection** | [INTELLIGENCE_LAYER.md](../INTELLIGENCE_LAYER.md), `lib/intelligence.py` | Post-hoc LLM analysis of experiences → insights (PREFER/AVOID tools). Queued, not inline. |
| **Duplicate tool guard + freshness** | [JARVIS_WORKFLOW.md](../JARVIS_WORKFLOW.md#duplicate-tool-guard) | In-request loop prevention, not sequential MCP thinking. |
| **Profile Card + correction learning** | [USER_PROFILE_SYSTEM.md](../USER_PROFILE_SYSTEM.md) | Cross-turn user prefs and correction detection. |
| **Sequential Thinking MCP** | `config/mcp-servers.json` | **`sequentialthinking` server is disabled** — see [TOOL_MANAGEMENT.md](../TOOL_MANAGEMENT.md). |

### Partial / stubbed code paths

- `lib/intelligence.py` contains `_call_sequential_thinking()` hooks used during reflection experiments; the MCP call path is largely **commented out / non-operational**.
- `router_v2.py` does **not** invoke a separate "think then route" MCP step for normal queries.
- Meta-cognition and anomaly jobs in the intelligence layer provide **batch** analysis, not per-query sequential steps.

### When to use this doc

- Designing a future **inline** thinking step before tool selection
- Understanding the **original vision** for self-correction loops
- Comparing against [EXTENDED_THINKING.md](../EXTENDED_THINKING.md) (provider reasoning) and intelligence reflection (post-hoc learning)

### Recommended reading order

1. [JARVIS_WORKFLOW.md](../JARVIS_WORKFLOW.md) — current request pipeline
2. [EXTENDED_THINKING.md](../EXTENDED_THINKING.md) — thinking mode that works today
3. [INTELLIGENCE_LAYER.md](../INTELLIGENCE_LAYER.md) — learning after the fact
4. **This file** — historical design for conditional sequential thinking

---

## Table of Contents

1. [Overview](#overview)
2. [Current vs. Enhanced Flow](#current-vs-enhanced-flow)
3. [When to Think (Conditional Intelligence)](#when-to-think-conditional-intelligence)
4. [Implementation Patterns](#implementation-patterns)
5. [Learning Mechanisms](#learning-mechanisms)
6. [Success Metrics](#success-metrics)
7. [Implementation Phases](#implementation-phases)
8. [Examples](#examples)

---

## Overview

### The Problem

Even with excellent system prompts and tool descriptions, the LLM router can:
- Choose the wrong tool for ambiguous queries
- Fail to recognize when a tool returned no results vs. the right answer
- Not adapt from past mistakes
- Lack self-correction when initial tool selection fails

### The Solution

Add **conditional thinking steps** that:
1. **Analyze intent** before tool selection (proactive)
2. **Detect failures** and self-correct (reactive)
3. **Learn patterns** from successful vs. unsuccessful thinking outcomes
4. **Cache reasoning** for common query patterns

### Key Principle

**Not every query needs thinking** - only use it when:
- Query is ambiguous or complex
- Tool selection has low confidence
- Previous tool execution failed
- Query type is new/unseen

**Most queries (80-90%) take the fast path** with direct routing.

---

## Current vs. Enhanced Flow

### Current Flow (Simple, Fast)

```
User Query
    ↓
Router (LLM + system prompt)
    ↓
Tool Selection
    ↓
Execute Tool
    ↓
Return Result
```

**Latency**: ~800ms
**Success Rate**: ~85% (estimated)
**Self-Correction**: None

---

### Enhanced Flow: Pattern A (Pre-Thinking - Proactive)

```
User Query
    ↓
Complexity Analysis (fast heuristic)
    ↓
┌─────────────────────────────────┐
│  Simple/Clear Query             │  Ambiguous/Complex Query
│  (80-90% of queries)            │  (10-20% of queries)
└─────────────────────────────────┘
    ↓                                   ↓
Fast Path:                          Thinking Step:
Router → Tool → Execute             Analyze intent + available tools
                                        ↓
                                    Router (with thinking context)
                                        ↓
                                    Tool Selection
                                        ↓
                                    Execute Tool
    ↓                                   ↓
Return Result                       Return Result
    ↓                                   ↓
Log (success, no thinking)          Log (success, thinking used)
```

**Fast Path Latency**: ~800ms (unchanged)
**Thinking Path Latency**: ~1.8s (+1s for thinking)
**Expected Success Rate**: ~95%

---

### Enhanced Flow: Pattern B (Reactive Thinking - Error Recovery)

```
User Query
    ↓
Router → Tool Selection
    ↓
Execute Tool
    ↓
Result Analysis
    ↓
┌─────────────────────────────────────────────┐
│  Success              │  Failure/No Results │
│  (85% of queries)     │  (15% of queries)   │
└─────────────────────────────────────────────┘
    ↓                           ↓
Return Result               Thinking Step:
    ↓                       "Why did this fail?"
Log (success, no retry)         ↓
                            Analyze: Wrong tool? Missing data? Code bug?
                                ↓
                            Router (with failure context)
                                ↓
                            Tool Selection (corrected)
                                ↓
                            Execute Tool (retry)
                                ↓
                            Return Result
                                ↓
                            Log (success after retry, thinking used)
```

**First Attempt**: ~800ms
**Retry with Thinking**: +1.8s (only if first fails)
**Expected Success Rate**: ~95% (85% first try + 10% recovered)

---

### Enhanced Flow: Pattern C (Confidence-Based)

```
User Query
    ↓
Router (returns tool + confidence score)
    ↓
Confidence Check
    ↓
┌───────────────────────────────────────┐
│  High (>0.8)      │  Low (<0.8)       │
│  (80% of queries) │  (20% of queries) │
└───────────────────────────────────────┘
    ↓                       ↓
Execute Tool            Thinking Step:
    ↓                   "Which tool is really correct?"
Return Result               ↓
                        Router (with reasoning)
                            ↓
                        Execute Tool (high confidence)
                            ↓
                        Return Result
```

**Advantage**: Proactive correction before failure
**Challenge**: Need confidence scoring in router

---

## When to Think (Conditional Intelligence)

### ✅ ENGAGE Thinking Step When:

| Trigger | Example | Why Think? |
|---------|---------|------------|
| **Ambiguous Query** | "Check my status" | Multiple tools apply: `list_alerts`, `query_service_logs`, `list_reminders` |
| **Tool Failure** | Tool returns error or empty result | Wrong tool selected, need to analyze and retry |
| **Low Confidence** | Router uncertainty score < 0.7 | Multiple tools seem equally applicable |
| **Complex Multi-Step** | "Build Flask API, test it, remind me to deploy tomorrow" | Requires planning and sequencing |
| **New Domain Query** | First time asking about a new topic | No cached pattern available |
| **Contradictory Context** | "Show reminders" but conversation suggests alerts | Context mismatch needs resolution |

### ⚡ SKIP Thinking Step When:

| Situation | Example | Why Skip? |
|-----------|---------|-----------|
| **Simple, Clear Query** | "What time is it?" | Single obvious tool: `get_time` |
| **High Confidence** | "List my reminders" | Exact match to tool description |
| **Cached Pattern** | Seen this query type 100+ times | Already know the right tool |
| **Speed-Critical** | Real-time responses | User expects instant answer |
| **Single Word Keyword** | "Bitcoin" | Clear: `crypto_price` tool |

---

## Implementation Patterns

### Pattern 1: Error-Triggered Thinking (Recommended First Phase)

**Why Start Here:**
- Low risk (only engages on failure)
- High value (self-correction)
- No latency impact on successful calls
- Easy to measure improvement

**Implementation:**

```python
def execute_with_recovery(user_query, mode='cloud'):
    """Execute tool with automatic retry on failure."""

    # First attempt (normal flow)
    tool_result = route_and_execute(user_query, mode)

    # Check for failure indicators
    if is_failure(tool_result):
        # Log the failure
        log_failure(user_query, tool_result)

        # Engage thinking step
        thinking_context = analyze_failure(
            query=user_query,
            failed_tool=tool_result.tool_name,
            error=tool_result.error,
            available_tools=get_all_tools()
        )

        # Retry with thinking context
        corrected_result = route_and_execute(
            user_query,
            mode,
            context=thinking_context
        )

        # Log the correction
        log_correction(user_query, tool_result, corrected_result)

        return corrected_result

    return tool_result

def is_failure(result):
    """Detect if tool execution failed or returned no useful data."""
    return (
        result.ok == False or
        result.error is not None or
        (result.data is None and result.speech in ["I don't have that", "No results", "Not found"])
    )

def analyze_failure(query, failed_tool, error, available_tools):
    """Use LLM to reason about what went wrong."""

    thinking_prompt = f"""
    The user asked: "{query}"

    We tried tool: {failed_tool}
    Result: {error or "No results / empty response"}

    Available tools:
    {format_tools(available_tools)}

    Think step-by-step:
    1. What was the user's TRUE intent?
    2. Why did {failed_tool} fail or return nothing?
    3. Which tool should we have used instead?
    4. What arguments should we pass?

    Provide your reasoning.
    """

    # Call LLM for reasoning
    reasoning = llm_provider.think(thinking_prompt)

    return reasoning
```

**Example Flow:**

```
User: "When is my next reminder?"

First Attempt:
→ Router picks: search_memory
→ Result: "No memories found matching 'reminder'"
→ is_failure() = True ✓

Thinking Step:
→ "User asking about temporal STATE of reminders"
→ "search_memory looks in PAST stored data"
→ "For CURRENT reminders, need list_reminders tool"
→ Reasoning: "Query requires LIVE STATE, not stored memory"

Retry:
→ Router with context: list_reminders
→ Result: "You have 1 reminder in 30 minutes" ✓
→ Success!

Learning:
→ Log: "reminder temporal queries → list_reminders, not search_memory"
→ Cache this pattern for future
```

---

### Pattern 2: Confidence-Based Thinking

**When to Use:**
- After Pattern 1 is stable
- When you want proactive correction (before failure)
- Need to avoid user-facing errors

**Implementation:**

```python
def execute_with_confidence_check(user_query, mode='cloud'):
    """Route with confidence scoring."""

    # Get tool selection WITH confidence score
    selection = router.route_with_confidence(user_query, mode)

    tool = selection.tool
    confidence = selection.confidence
    reasoning = selection.reasoning  # Why this tool was chosen

    # High confidence → fast path
    if confidence >= 0.8:
        log_confidence(user_query, tool, confidence, "high")
        return execute_tool(tool)

    # Low confidence → engage thinking
    else:
        log_confidence(user_query, tool, confidence, "low")

        # Think about tool selection
        thinking_context = deep_analyze_intent(
            query=user_query,
            initial_tool=tool,
            initial_reasoning=reasoning,
            confidence=confidence,
            available_tools=get_all_tools()
        )

        # Re-route with thinking context
        corrected_selection = router.route_with_context(
            user_query,
            mode,
            thinking_context
        )

        log_correction_proactive(user_query, tool, corrected_selection.tool)

        return execute_tool(corrected_selection.tool)

def deep_analyze_intent(query, initial_tool, initial_reasoning, confidence, available_tools):
    """Deep reasoning when confidence is low."""

    thinking_prompt = f"""
    User query: "{query}"

    Initial tool selection: {initial_tool}
    Initial reasoning: {initial_reasoning}
    Confidence: {confidence:.2f} (LOW - need verification)

    Available tools:
    {format_tools(available_tools)}

    Think carefully:
    1. What is the user REALLY asking for?
    2. Is {initial_tool} the BEST choice?
    3. What other tools might be better?
    4. What's your confidence in each option?

    Provide detailed reasoning and final recommendation.
    """

    return llm_provider.think(thinking_prompt)
```

**Confidence Scoring Methods:**

```python
# Method 1: Token probability analysis
def get_confidence_from_logprobs(llm_response):
    """Use token log probabilities as confidence."""
    if hasattr(llm_response, 'logprobs'):
        avg_logprob = sum(llm_response.logprobs) / len(llm_response.logprobs)
        confidence = math.exp(avg_logprob)
        return confidence
    return 0.5  # Unknown

# Method 2: Explicit confidence request
def get_explicit_confidence(router_response):
    """Ask LLM to rate its own confidence."""
    # In system prompt: "After selecting a tool, rate your confidence 0-100"
    return router_response.confidence / 100.0

# Method 3: Tool description similarity
def get_semantic_confidence(query, tool_description):
    """Compare query embedding to tool description embedding."""
    query_emb = get_embedding(query)
    tool_emb = get_embedding(tool_description)
    similarity = cosine_similarity(query_emb, tool_emb)
    return similarity
```

---

### Pattern 3: MCP Thinking Service (Advanced)

**When to Use:**
- For truly complex multi-step reasoning
- When patterns 1 & 2 aren't sufficient
- Deep architectural decisions

**Implementation:**

```python
def execute_with_mcp_thinking(user_query, mode='cloud'):
    """Use external MCP thinking service for deep reasoning."""

    # Check if query needs deep thinking
    if not requires_deep_thinking(user_query):
        return execute_normal(user_query, mode)

    # Call MCP thinking service
    thinking_result = mcp_thinking_service.analyze(
        query=user_query,
        tools=get_all_tools(),
        context=get_conversation_history(),
        mode="sequential_reasoning"
    )

    """
    MCP Thinking Service returns:
    {
        "reasoning_steps": [
            "User wants to build and deploy a project",
            "This requires 3 sequential tools",
            "Step 1: opencode to build",
            "Step 2: api_call to test",
            "Step 3: create_reminder to schedule deployment"
        ],
        "recommended_sequence": [
            {"tool": "opencode", "args": {...}},
            {"tool": "api_call", "args": {...}},
            {"tool": "create_reminder", "args": {...}}
        ],
        "confidence": 0.92
    }
    """

    # Execute the planned sequence
    results = []
    for step in thinking_result.recommended_sequence:
        result = execute_tool(step.tool, step.args)
        results.append(result)

        # If any step fails, re-think
        if not result.ok:
            recovery = mcp_thinking_service.recover(
                failed_step=step,
                error=result.error,
                completed_steps=results
            )
            # Continue with recovery plan...

    return aggregate_results(results)
```

---

## Learning Mechanisms

### Core Concept: Learn from Thinking Outcomes

**The Learning Loop:**

```
Execute Query
    ↓
Did we use thinking? (yes/no)
    ↓
Was the result successful? (yes/no)
    ↓
Log outcome:
  - Query pattern
  - Tool selected
  - Thinking used (yes/no)
  - Success (yes/no)
  - Correction made (if applicable)
    ↓
Analyze patterns over time
    ↓
Update routing intelligence
```

---

### Learning Database Schema

```sql
CREATE TABLE thinking_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Query info
    query_text TEXT NOT NULL,
    query_embedding BLOB,
    query_category TEXT,  -- e.g., "reminder_query", "alert_query"

    -- First attempt
    first_tool TEXT,
    first_confidence REAL,
    first_success BOOLEAN,
    first_error TEXT,

    -- Thinking step (if used)
    thinking_used BOOLEAN DEFAULT 0,
    thinking_reasoning TEXT,
    thinking_duration_ms INTEGER,

    -- Correction (if made)
    correction_made BOOLEAN DEFAULT 0,
    corrected_tool TEXT,
    correction_reasoning TEXT,

    -- Final outcome
    final_success BOOLEAN,
    final_tool TEXT,
    final_result_quality TEXT,  -- "excellent", "good", "poor"

    -- Metadata
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    mode TEXT,  -- "cloud" or "local"
    llm_provider TEXT,
    llm_model TEXT,

    -- Learning signals
    user_feedback TEXT,  -- User explicitly corrected us?
    retry_count INTEGER DEFAULT 0
);

CREATE INDEX idx_thinking_query_category ON thinking_outcomes(query_category);
CREATE INDEX idx_thinking_success ON thinking_outcomes(final_success);
CREATE INDEX idx_thinking_used ON thinking_outcomes(thinking_used);
```

---

### Learning Queries (Pattern Analysis)

#### Query 1: When Does Thinking Help?

```sql
-- Compare success rates: with thinking vs. without
SELECT
    thinking_used,
    COUNT(*) as total_queries,
    SUM(CASE WHEN final_success = 1 THEN 1 ELSE 0 END) as successes,
    ROUND(100.0 * SUM(CASE WHEN final_success = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM thinking_outcomes
GROUP BY thinking_used;

-- Expected result:
-- thinking_used | total_queries | successes | success_rate
-- 0             | 8500          | 7225      | 85.00%
-- 1             | 1500          | 1425      | 95.00%
```

#### Query 2: Which Query Categories Need Thinking Most?

```sql
-- Find categories where thinking significantly improves success
SELECT
    query_category,
    COUNT(*) as total,
    -- Success rate without thinking
    ROUND(100.0 * SUM(CASE WHEN thinking_used = 0 AND final_success = 1 THEN 1 ELSE 0 END) /
          SUM(CASE WHEN thinking_used = 0 THEN 1 ELSE 0 END), 2) as success_no_thinking,
    -- Success rate with thinking
    ROUND(100.0 * SUM(CASE WHEN thinking_used = 1 AND final_success = 1 THEN 1 ELSE 0 END) /
          SUM(CASE WHEN thinking_used = 1 THEN 1 ELSE 0 END), 2) as success_with_thinking,
    -- Improvement
    ROUND(100.0 * SUM(CASE WHEN thinking_used = 1 AND final_success = 1 THEN 1 ELSE 0 END) /
          SUM(CASE WHEN thinking_used = 1 THEN 1 ELSE 0 END) -
          100.0 * SUM(CASE WHEN thinking_used = 0 AND final_success = 1 THEN 1 ELSE 0 END) /
          SUM(CASE WHEN thinking_used = 0 THEN 1 ELSE 0 END), 2) as improvement
FROM thinking_outcomes
GROUP BY query_category
HAVING COUNT(*) > 20  -- Only categories with enough data
ORDER BY improvement DESC;

-- Expected insights:
-- query_category       | success_no_thinking | success_with_thinking | improvement
-- "ambiguous_temporal" | 60%                 | 95%                   | +35%  ← NEEDS THINKING
-- "multi_step_build"   | 70%                 | 98%                   | +28%  ← NEEDS THINKING
-- "simple_keyword"     | 95%                 | 96%                   | +1%   ← SKIP THINKING
```

#### Query 3: Learn Correction Patterns

```sql
-- What corrections did thinking enable?
SELECT
    first_tool,
    corrected_tool,
    COUNT(*) as correction_count,
    GROUP_CONCAT(DISTINCT query_category) as affected_categories
FROM thinking_outcomes
WHERE correction_made = 1 AND final_success = 1
GROUP BY first_tool, corrected_tool
ORDER BY correction_count DESC
LIMIT 10;

-- Expected result:
-- first_tool      | corrected_tool  | correction_count | affected_categories
-- "search_memory" | "list_reminders"| 47               | "reminder_query,temporal_query"
-- "search_memory" | "list_alerts"   | 32               | "alert_query,status_query"
-- "recall"        | "list_reminders"| 18               | "reminder_query"
```

**Learning Action:**
```python
# Auto-generate routing hint from corrections
if correction_count > 20 and success_rate > 0.9:
    add_routing_hint(
        pattern=query_category,
        avoid_tool=first_tool,
        prefer_tool=corrected_tool,
        reasoning="Learned from 47 successful corrections"
    )
```

#### Query 4: Identify Query Patterns for Fast Path

```sql
-- Find query patterns that ALWAYS succeed without thinking
SELECT
    query_category,
    first_tool,
    COUNT(*) as attempts,
    SUM(CASE WHEN first_success = 1 AND thinking_used = 0 THEN 1 ELSE 0 END) as direct_successes,
    ROUND(100.0 * SUM(CASE WHEN first_success = 1 AND thinking_used = 0 THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM thinking_outcomes
WHERE thinking_used = 0
GROUP BY query_category, first_tool
HAVING COUNT(*) > 50 AND success_rate > 95
ORDER BY attempts DESC;

-- Expected result (candidates for fast path):
-- query_category  | first_tool    | attempts | direct_successes | success_rate
-- "time_query"    | "get_time"    | 1247     | 1245             | 99.84%  ← CACHE THIS
-- "crypto_lookup" | "crypto_price"| 532      | 528              | 99.25%  ← CACHE THIS
-- "bash_command"  | "execute_bash"| 421      | 405              | 96.20%  ← CACHE THIS
```

**Learning Action:**
```python
# Auto-add to fast path cache
if success_rate > 95 and attempts > 50:
    add_to_fast_path_cache(
        pattern=query_category,
        tool=first_tool,
        confidence_override=0.99  # Skip thinking for these
    )
```

---

### Learning Agent (Automated Improvement)

```python
class ThinkingLearningAgent:
    """Automatically learn from thinking outcomes and improve routing."""

    def __init__(self, outcomes_db_path):
        self.db = sqlite3.connect(outcomes_db_path)
        self.insights = []

    def run_daily_learning(self):
        """Run learning analysis daily to improve routing."""

        # 1. Identify categories that need thinking
        categories_need_thinking = self.find_categories_improved_by_thinking()

        # 2. Identify correction patterns
        correction_patterns = self.find_common_corrections()

        # 3. Identify fast path candidates
        fast_path_patterns = self.find_fast_path_candidates()

        # 4. Generate routing improvements
        improvements = self.generate_routing_improvements(
            categories_need_thinking,
            correction_patterns,
            fast_path_patterns
        )

        # 5. Update router configuration
        self.apply_improvements(improvements)

        # 6. Log insights
        self.log_learning_report(improvements)

    def find_categories_improved_by_thinking(self):
        """Find query categories where thinking helps significantly."""
        query = """
        SELECT
            query_category,
            -- ... (Query 2 from above)
        """
        results = self.db.execute(query).fetchall()

        # Filter for significant improvement (>20% better with thinking)
        return [
            {
                'category': row[0],
                'improvement': row[3],
                'recommendation': 'enable_thinking'
            }
            for row in results if row[3] > 20
        ]

    def find_common_corrections(self):
        """Find common tool corrections that thinking enables."""
        query = """
        -- Query 3 from above
        """
        results = self.db.execute(query).fetchall()

        return [
            {
                'wrong_tool': row[0],
                'correct_tool': row[1],
                'frequency': row[2],
                'categories': row[3].split(','),
                'recommendation': 'add_routing_hint'
            }
            for row in results if row[2] > 20
        ]

    def find_fast_path_candidates(self):
        """Find patterns that always succeed without thinking."""
        query = """
        -- Query 4 from above
        """
        results = self.db.execute(query).fetchall()

        return [
            {
                'category': row[0],
                'tool': row[1],
                'success_rate': row[4],
                'recommendation': 'add_to_fast_path'
            }
            for row in results if row[4] > 95
        ]

    def generate_routing_improvements(self, categories_need_thinking,
                                      correction_patterns, fast_path_patterns):
        """Generate concrete routing config updates."""

        improvements = {
            'thinking_triggers': [],
            'routing_hints': [],
            'fast_path_cache': []
        }

        # Add thinking triggers for categories that benefit
        for cat in categories_need_thinking:
            improvements['thinking_triggers'].append({
                'category': cat['category'],
                'confidence_threshold': 0.7,  # Lower threshold = more thinking
                'reason': f"Improves success by {cat['improvement']:.0f}%"
            })

        # Add routing hints from corrections
        for correction in correction_patterns:
            improvements['routing_hints'].append({
                'categories': correction['categories'],
                'avoid_tool': correction['wrong_tool'],
                'prefer_tool': correction['correct_tool'],
                'strength': 'high' if correction['frequency'] > 50 else 'medium',
                'reason': f"Learned from {correction['frequency']} corrections"
            })

        # Add fast path cache for reliable patterns
        for pattern in fast_path_patterns:
            improvements['fast_path_cache'].append({
                'category': pattern['category'],
                'tool': pattern['tool'],
                'confidence_override': 0.99,
                'skip_thinking': True,
                'reason': f"{pattern['success_rate']:.1f}% success rate"
            })

        return improvements

    def apply_improvements(self, improvements):
        """Update routing configuration based on learned insights."""

        # Update routing config file
        config_path = Path(__file__).parent.parent / "config" / "routing_intelligence.json"

        with open(config_path, 'r') as f:
            config = json.load(f)

        # Merge improvements
        config['thinking_triggers'].extend(improvements['thinking_triggers'])
        config['routing_hints'].extend(improvements['routing_hints'])
        config['fast_path_cache'].update({
            p['category']: {'tool': p['tool'], 'confidence': p['confidence_override']}
            for p in improvements['fast_path_cache']
        })

        # Deduplicate
        config = self.deduplicate_config(config)

        # Write back
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)

        print(f"✅ Applied {len(improvements['thinking_triggers'])} thinking triggers")
        print(f"✅ Applied {len(improvements['routing_hints'])} routing hints")
        print(f"✅ Applied {len(improvements['fast_path_cache'])} fast path patterns")
```

---

### Success Scoring System

**How to Grade Thinking Outcomes:**

```python
def score_thinking_outcome(query, first_result, final_result, thinking_used):
    """Score the quality of thinking outcome (0-100)."""

    score = 0

    # Base: Did we get the right answer?
    if final_result.ok and final_result.data:
        score += 50  # Success baseline

    # Efficiency: Did we need thinking, or waste time thinking?
    if thinking_used:
        if not first_result.ok and final_result.ok:
            score += 30  # Thinking saved us (recovery)
        elif first_result.ok:
            score -= 10  # Thinking was unnecessary (wasted time)
    else:
        if first_result.ok:
            score += 20  # Fast path worked (efficient)

    # Speed bonus
    if not thinking_used and final_result.ok:
        score += 10  # Fast AND correct

    # User satisfaction (if available)
    if has_user_feedback(query):
        if user_was_satisfied(query):
            score += 20
        else:
            score -= 20

    return max(0, min(100, score))

# Example outcomes:
# Fast path, correct: 80 points ✅
# Thinking, corrected, success: 80 points ✅
# Thinking, unnecessary (already correct): 60 points ⚠️
# No thinking, failed: 0 points ❌
```

---

## Success Metrics

### Key Performance Indicators (KPIs)

| Metric | Target | Current | How to Measure |
|--------|--------|---------|----------------|
| **Overall Success Rate** | 95% | 85% | `(successful_queries / total_queries) * 100` |
| **First Attempt Success** | 90% | 85% | `(first_try_success / total_queries) * 100` |
| **Recovery Success Rate** | 80% | N/A | `(recovered_after_thinking / failed_first_try) * 100` |
| **Thinking Efficiency** | 15% | N/A | `(queries_needing_thinking / total_queries) * 100` |
| **Fast Path Accuracy** | 98% | N/A | `(fast_path_success / fast_path_attempts) * 100` |
| **Average Latency** | <1s | 0.8s | Mean response time |
| **P95 Latency** | <2s | 1.2s | 95th percentile response time |
| **Thinking Latency** | <2s | N/A | Time spent in thinking step |
| **Learning Improvement** | +5%/month | N/A | Success rate improvement over time |

---

### Dashboard Queries

```sql
-- Daily success rate
SELECT
    DATE(timestamp) as date,
    COUNT(*) as total_queries,
    SUM(CASE WHEN final_success = 1 THEN 1 ELSE 0 END) as successes,
    ROUND(100.0 * SUM(CASE WHEN final_success = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM thinking_outcomes
GROUP BY DATE(timestamp)
ORDER BY date DESC
LIMIT 30;

-- Thinking efficiency (should stay 10-20%)
SELECT
    DATE(timestamp) as date,
    ROUND(100.0 * SUM(CASE WHEN thinking_used = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as thinking_percentage
FROM thinking_outcomes
GROUP BY DATE(timestamp)
ORDER BY date DESC
LIMIT 30;

-- Tool selection accuracy
SELECT
    first_tool,
    COUNT(*) as attempts,
    SUM(CASE WHEN first_success = 1 THEN 1 ELSE 0 END) as direct_successes,
    ROUND(100.0 * SUM(CASE WHEN first_success = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as accuracy
FROM thinking_outcomes
WHERE timestamp > datetime('now', '-7 days')
GROUP BY first_tool
ORDER BY attempts DESC;
```

---

## Implementation Phases

### Phase 1: Error-Triggered Thinking (Week 1-2)

**Goal**: Add self-correction on tool failures

**Tasks**:
1. Create `thinking_outcomes` database table
2. Implement `is_failure()` detection
3. Implement `analyze_failure()` thinking step
4. Add retry logic with thinking context
5. Log all outcomes (thinking used, success/failure)
6. Create basic dashboard

**Success Criteria**:
- Recovery success rate > 70%
- Thinking triggers on 10-15% of queries
- No regressions in fast path latency

---

### Phase 2: Learning & Optimization (Week 3-4)

**Goal**: Learn from outcomes and optimize routing

**Tasks**:
1. Implement `ThinkingLearningAgent`
2. Run daily learning analysis
3. Auto-generate routing hints from corrections
4. Build fast path cache from reliable patterns
5. Create `routing_intelligence.json` config
6. Weekly learning reports

**Success Criteria**:
- Overall success rate > 92%
- Fast path accuracy > 95%
- Automated routing improvements working

---

### Phase 3: Confidence-Based Thinking (Week 5-6)

**Goal**: Proactive correction before failure

**Tasks**:
1. Add confidence scoring to router
2. Implement confidence-based thinking triggers
3. Tune confidence thresholds per category
4. A/B test: error-triggered vs confidence-based
5. Optimize for latency vs accuracy tradeoff

**Success Criteria**:
- Overall success rate > 95%
- Reduced user-facing errors
- P95 latency < 2s

---

### Phase 4: MCP Thinking Service (Week 7+)

**Goal**: Deep reasoning for complex queries

**Tasks**:
1. Integrate MCP thinking service
2. Identify queries needing deep reasoning
3. Multi-step planning and sequencing
4. Complex query decomposition
5. Advanced self-correction

**Success Criteria**:
- Complex multi-step queries succeed
- Planning quality improves
- Long-term task management

---

## Examples

### Example 1: Reminder Query (Error Recovery)

**User Query**: "When is my next reminder?"

**Flow WITHOUT Thinking** (Current):
```
1. Router picks: search_memory
   Reasoning: "Query has 'reminder' keyword"

2. Execute search_memory(query="reminder")
   Result: "No memories found"

3. Response to user: "I don't have any reminders stored"

❌ WRONG ANSWER (reminder exists in proactive system)
```

**Flow WITH Error-Triggered Thinking** (Phase 1):
```
1. Router picks: search_memory
   Reasoning: "Query has 'reminder' keyword"

2. Execute search_memory(query="reminder")
   Result: "No memories found"

3. is_failure() → TRUE (no results)

4. Thinking step engages:
   Prompt: "User asked 'When is my next reminder?'
            Tool search_memory returned no results.
            Available tools: [list_reminders, search_memory, semantic_recall, ...]

            Think: What went wrong?"

   Reasoning:
   "- User asking about TEMPORAL STATE (when/next)
    - search_memory looks in PAST stored knowledge
    - For CURRENT reminder status, need list_reminders
    - This is a LIVE STATE query, not memory retrieval"

5. Retry: list_reminders()
   Result: "You have 1 reminder in 30 minutes: Check truck registration"

6. Response to user: "You have one reminder in 30 minutes"

✅ CORRECT ANSWER (recovered via thinking)

7. Log learning:
   {
     "query_category": "reminder_temporal_query",
     "first_tool": "search_memory",
     "first_success": false,
     "thinking_used": true,
     "correction_made": true,
     "corrected_tool": "list_reminders",
     "final_success": true,
     "score": 80
   }
```

**Learning Outcome**:
After 20+ similar corrections, agent learns:
- "reminder temporal queries" → Prefer `list_reminders` over `search_memory`
- Add routing hint: "For queries about CURRENT/UPCOMING reminders, use list_reminders"
- Update system prompt with this pattern

---

### Example 2: Ambiguous Alert Query (Confidence-Based)

**User Query**: "What's the status of my services?"

**Flow WITH Confidence-Based Thinking** (Phase 3):
```
1. Router analyzes (with confidence scoring):

   Possible tools:
   - list_alerts (external service alerts) - 40%
   - query_service_logs (Jarvis's own services) - 35%
   - execute_bash (systemctl status) - 15%
   - search_memory (past status info) - 10%

   Best guess: list_alerts (40% confidence)

2. Confidence check: 40% < 70% threshold
   → LOW CONFIDENCE → Engage thinking

3. Thinking step:
   Prompt: "User asked 'What's the status of my services?'
            Ambiguous - multiple interpretations:

            A) External services (Coolify, Docker) → list_alerts
            B) Jarvis background services → query_service_logs
            C) System services → execute_bash

            Context: User is asking about health/status.
            Recent conversation: [user recently set up Docker monitoring]

            Think: Which interpretation is most likely?"

   Reasoning:
   "- User recently configured Docker monitoring
    - 'Services' in plural suggests external systems
    - If asking about Jarvis's own services, would say 'your services'
    - Most likely: External services monitored via Docker agent
    → Use list_alerts"

4. Corrected selection: list_alerts (95% confidence)

5. Execute list_alerts()
   Result: "All services running. Kokoro-CPU: up, ComfyUI: up"

6. Response to user: "All services running"

✅ CORRECT (prevented wrong tool via thinking)

7. Log learning:
   {
     "query_category": "ambiguous_status_query",
     "first_tool": "list_alerts",
     "first_confidence": 0.40,
     "thinking_used": true,
     "thinking_boosted_confidence": 0.95,
     "final_success": true,
     "score": 85
   }
```

**Learning Outcome**:
- Query category "status of services" → Often means `list_alerts`
- Context clue "recently set up monitoring" → Increases `list_alerts` probability
- Add to confidence model training data

---

### Example 3: Complex Multi-Step (MCP Thinking)

**User Query**: "Build a Flask API for weather, test it, and remind me to deploy it tomorrow at 2pm"

**Flow WITH MCP Thinking Service** (Phase 4):
```
1. Router detects: Complex multi-step query
   Trigger: Multiple verbs (build, test, remind)

2. Engage MCP thinking service:

   Prompt: "User wants: Build Flask API + Test it + Set reminder
            Available tools: opencode, api_call, create_reminder, execute_bash, ...

            Create a sequential plan."

   MCP Reasoning:
   "This requires 3 distinct steps in sequence:

    Step 1: Build the Flask API
      Tool: opencode
      Args: {
        task: 'Build Flask API for weather',
        type: 'api',
        requirements: 'Flask, requests'
      }
      Wait for: Project location, port

    Step 2: Test the API
      Tool: api_call
      Args: Will depend on URL from Step 1
      Method: GET /weather
      Wait for: Response status

    Step 3: Create deployment reminder
      Tool: create_reminder
      Args: {
        title: 'Deploy weather API',
        when: 'tomorrow at 2pm'
      }
      Include: Project location from Step 1 in description

    Dependencies:
    - Step 2 depends on Step 1 (need URL)
    - Step 3 depends on Step 1 (need project location)
    "

3. Execute Step 1: opencode
   Result: {
     "project_path": "~/jarvis-workspace/projects/weather-api",
     "port": 5000,
     "status": "running"
   }

4. Execute Step 2: api_call
   URL: http://localhost:5000/weather
   Result: {"status": 200, "response": "Weather data"}

5. Execute Step 3: create_reminder
   Args: {
     "title": "Deploy weather API",
     "description": "Project at ~/jarvis-workspace/projects/weather-api on port 5000",
     "when": "tomorrow at 2pm"
   }
   Result: "Reminder set"

6. Aggregate response:
   "Built weather API on port 5000, tested successfully, and set reminder for tomorrow at 2pm"

✅ COMPLEX TASK COMPLETED

7. Log learning:
   {
     "query_category": "multi_step_build_test_remind",
     "thinking_used": true,
     "mcp_thinking": true,
     "steps_planned": 3,
     "steps_succeeded": 3,
     "final_success": true,
     "score": 95
   }
```

**Learning Outcome**:
- Pattern recognized: "build X, test it, remind me" → 3-step sequence
- Cache this plan template for similar queries
- Next time: Skip MCP thinking, use cached plan

---

### Example 4: Fast Path (Learned Pattern)

**User Query**: "What time is it?"

**Flow WITH Fast Path Cache** (After Learning):
```
1. Query categorization: "time_query"

2. Check fast path cache:
   {
     "time_query": {
       "tool": "get_time",
       "confidence_override": 0.99,
       "skip_thinking": true
     }
   }

3. Cache hit! Fast path:
   - Skip router (already know tool)
   - Skip confidence check
   - Skip thinking
   - Execute directly: get_time()

4. Result: "It's 7:45 PM on Tuesday, November 18th"

5. Response to user: "It's 7:45 PM"

✅ INSTANT (no LLM routing needed)

Latency: ~100ms (vs ~800ms normal, ~1800ms with thinking)

6. Log (minimal):
   {
     "fast_path": true,
     "tool": "get_time",
     "success": true
   }
```

**Learning Outcome**:
- Fast path cache proven effective (99.8% success rate)
- Similar patterns added to cache over time
- System gets faster as it learns

---

## Configuration Files

### routing_intelligence.json (Generated by Learning Agent)

```json
{
  "version": "1.2.0",
  "last_updated": "2025-11-18T19:00:00Z",

  "thinking_triggers": [
    {
      "category": "ambiguous_temporal",
      "confidence_threshold": 0.7,
      "reason": "Improves success by 35%"
    },
    {
      "category": "multi_step_build",
      "confidence_threshold": 0.65,
      "reason": "Complex sequencing needs planning"
    },
    {
      "category": "status_query",
      "confidence_threshold": 0.75,
      "reason": "Often ambiguous (alerts vs services vs system)"
    }
  ],

  "routing_hints": [
    {
      "categories": ["reminder_query", "temporal_query"],
      "avoid_tool": "search_memory",
      "prefer_tool": "list_reminders",
      "strength": "high",
      "reason": "Learned from 47 successful corrections"
    },
    {
      "categories": ["alert_query", "status_query"],
      "avoid_tool": "search_memory",
      "prefer_tool": "list_alerts",
      "strength": "high",
      "reason": "Learned from 32 successful corrections"
    },
    {
      "categories": ["service_status"],
      "prefer_tool": "query_service_logs",
      "strength": "medium",
      "reason": "Best for Jarvis's own services"
    }
  ],

  "fast_path_cache": {
    "time_query": {
      "tool": "get_time",
      "confidence": 0.99,
      "success_rate": 99.84,
      "attempts": 1247
    },
    "crypto_lookup": {
      "tool": "crypto_price",
      "confidence": 0.99,
      "success_rate": 99.25,
      "attempts": 532
    },
    "simple_bash": {
      "tool": "execute_bash",
      "confidence": 0.98,
      "success_rate": 96.20,
      "attempts": 421
    }
  },

  "learning_stats": {
    "total_queries_analyzed": 10000,
    "improvements_applied": 23,
    "success_rate_improvement": "+12%",
    "thinking_efficiency": "14.2%",
    "last_learning_run": "2025-11-18T06:00:00Z"
  }
}
```

---

## Monitoring & Debugging

### Thinking Logs (JSON Lines)

```jsonl
{"timestamp": "2025-11-18T19:30:00", "query": "When is my next reminder?", "first_tool": "search_memory", "first_success": false, "thinking_triggered": "error_recovery", "thinking_reasoning": "User asking about CURRENT state, not past memory", "corrected_tool": "list_reminders", "final_success": true, "thinking_duration_ms": 1200, "total_duration_ms": 2100}

{"timestamp": "2025-11-18T19:31:00", "query": "What time is it?", "first_tool": "get_time", "first_success": true, "thinking_triggered": false, "fast_path": true, "total_duration_ms": 120}

{"timestamp": "2025-11-18T19:32:00", "query": "What's the status?", "first_tool": "list_alerts", "first_confidence": 0.42, "thinking_triggered": "low_confidence", "thinking_reasoning": "Ambiguous query - could mean alerts, services, or system status", "corrected_tool": "list_alerts", "corrected_confidence": 0.88, "final_success": true, "thinking_duration_ms": 980, "total_duration_ms": 1850}
```

### Debug Commands

```bash
# View thinking logs (today)
tail -f logs/thinking/thinking-$(date +%Y-%m-%d).jsonl

# Count thinking usage
grep '"thinking_triggered"' logs/thinking/*.jsonl | wc -l

# Success rates
sqlite3 data/thinking_outcomes.db "
  SELECT
    thinking_used,
    COUNT(*) as total,
    SUM(final_success) as successes,
    ROUND(100.0 * SUM(final_success) / COUNT(*), 2) as rate
  FROM thinking_outcomes
  GROUP BY thinking_used
"

# Recent corrections
sqlite3 data/thinking_outcomes.db "
  SELECT
    query_text,
    first_tool,
    corrected_tool,
    thinking_reasoning
  FROM thinking_outcomes
  WHERE correction_made = 1
  ORDER BY timestamp DESC
  LIMIT 10
"
```

---

## Future Enhancements

### 1. **User Feedback Loop**
- After each response, optional: "Was this helpful? (yes/no)"
- Store feedback in `thinking_outcomes.user_feedback`
- Adjust routing based on user satisfaction

### 2. **Context-Aware Thinking**
- Consider conversation history
- User's recent activities
- Time of day / day of week patterns

### 3. **Adaptive Confidence Thresholds**
- Per-category thresholds
- Per-user preferences (some users prefer speed > accuracy)
- Auto-tune based on success rates

### 4. **Explainable Routing**
- `--explain` flag: "I chose list_reminders because..."
- Help users understand decisions
- Build trust in the system

### 5. **Distributed Learning**
- Multiple Jarvis instances learn collectively
- Share routing intelligence (privacy-preserving)
- Faster convergence to optimal routing

---

## Summary

**Key Principles:**
1. ✅ **Think when needed, not always** (10-20% of queries)
2. ✅ **Learn from outcomes** (successful thinking vs. wasted thinking)
3. ✅ **Self-correct on failures** (error recovery)
4. ✅ **Cache reliable patterns** (fast path for common queries)
5. ✅ **Measure everything** (success rates, latency, improvements)

**Expected Impact:**
- **Success rate**: 85% → 95% (+10%)
- **Recovery**: 70% of failures recovered via thinking
- **Latency**: 90% of queries <1s (fast path), 10% <2s (thinking)
- **Learning**: Continuous improvement (+5% success/month)

**Timeline:**
- **Phase 1** (Weeks 1-2): Error recovery
- **Phase 2** (Weeks 3-4): Learning agent
- **Phase 3** (Weeks 5-6): Confidence-based
- **Phase 4** (Weeks 7+): MCP thinking

**This is the path to a truly intelligent assistant.** 🧠
