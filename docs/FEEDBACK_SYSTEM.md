# Jarvis Feedback System - LLM-as-QA

> **Purpose**: Allow Jarvis to critique its own experience after completing tasks, identifying issues with system prompts, tool descriptions, and suggesting improvements.

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [How It Works](#how-it-works)
3. [Usage Methods](#usage-methods)
4. [Commands Reference](#commands-reference)
5. [What the LLM Sees](#what-the-llm-sees)
6. [Output Format](#output-format)
7. [Log Files](#log-files)
8. [Use Cases](#use-cases)
9. [Configuration](#configuration)

---

## Overview

The Feedback System is a **self-improvement mechanism** where the LLM acts as a QA analyst reviewing its own performance. After completing a task, it's asked to:

1. **Rate** the experience (1-5)
2. **Identify issues** with system prompt, tool descriptions, or missing info
3. **Suggest improvements** for next time

This creates a feedback loop for continuous improvement without manual debugging.

### Why This Matters

- **The LLM has full context** - It sees everything you give it (system prompt, tools, instructions)
- **Catches issues humans miss** - Like the truncated insight we found ("co" cutoff)
- **Self-documenting** - Issues are logged with timestamps for later review
- **Actionable feedback** - Specific suggestions, not vague complaints
- **Updates Intelligence DB** - All ratings attach compact feedback metadata to the linked experience; low ratings (1-2) retroactively mark experiences as failures

---

## How It Works

### Flow Diagram

```
┌─────────────────┐
│  User Query     │
└────────┬────────┘
         ▼
┌─────────────────┐
│  Orchestrator   │  ← Normal task processing
│  (process)      │
└────────┬────────┘
         ▼
┌─────────────────┐
│  Task Result    │  ← speech, ok, tools_used, etc.
└────────┬────────┘
         ▼
┌─────────────────────────────────────────┐
│  FeedbackCollector.collect()            │
│                                         │
│  1. Build feedback prompt with:         │
│     - Original query                    │
│     - Task result (success/failure)     │
│     - Tools used                        │
│     - Summary of what was available     │
│                                         │
│  2. Ask LLM: "Rate and critique this"   │
│                                         │
│  3. Parse JSON response                 │
│                                         │
│  4. Log to feedback-YYYY-MM-DD.jsonl    │
│     (only if rating < 5 or always_log)  │
└─────────────────────────────────────────┘
```

### Key Points

1. **Separate LLM Call**: Feedback collection is a NEW LLM call after the task completes
2. **FULL System Prompt**: The feedback LLM sees the actual system prompt text
3. **Tool Descriptions**: Includes descriptions for used tools AND likely relevant tools
4. **Separate Provider**: Can use a DIFFERENT LLM for feedback (avoid self-grading bias)
5. **Logs stored separately**: In `logs/feedback/`, not mixed with other logs

### Completion Guard (Web UI, 2026)

When Completion Guard is enabled in Jarvis Web, **explicit async feedback waits until the turn is settled** (user accepted the answer, auto-evaluation passed, `tighten_only` settled, repair finished, a ticket was created, or the manual prompt expired/was superseded). The feedback LLM then grades the **final** response and tool picture—not a mid-repair snapshot.

- **Prompt**: `lib/feedback.py` injects a `=== COMPLETION GUARD ===` block (`completion_guard_context`). Instructions tell the grader to treat it as recovery context, not as an automatic penalty.
- **Settled states**: `tighten_only` is treated like a basically accepted answer with minor wording cleanup, not a failed repair. `expired` and `superseded` are neutral manual prompt settlements, not user dissatisfaction.
- **Random feedback**: `FEEDBACK_RANDOM_ENABLED` / `FEEDBACK_RANDOM_CHANCE` can sample normal orchestrator runs. Jarvis Web temporarily disables orchestrator-side random feedback while Completion Guard is enabled so random pre-collection does not race guard settlement.
- **Logs**: Each feedback JSONL record includes top-level `completion_guard` (or `{"status": "none"}`).
- **Intelligence bridge**: Feedback also stores `raw_data.feedback.latest` on the linked experience, preserving the rating, summary, issues, tool ratings, analysis, and guard status for future reflection.
- **Reference**: [Completion Guard](./COMPLETION_GUARD.md).

### Autonomous Workflow Grading

When normal orchestration selects the `workflow` meta-tool, feedback receives a
compact workflow execution block in addition to `Tools Used: workflow`. The
grader separates:

- workflow discovery and selection by the routing LLM
- deterministic component order owned by the workflow JSON
- component or recipe failures
- the final settled answer and artifacts

`workflow(search)` and `workflow(describe)` may legitimately precede one
`workflow(run)` and are not graded as repeated execution. The
`tool_ratings.workflow` score applies to discovery/input/selection of the
specific recipe; it is not automatically a rating for every internal component
tool. Search-only, missing-input, unavailable, cancelled, and failed-preflight
interactions are not treated as successful workflow executions.

Feedback remains optional/manual by default. Its rating can enrich the linked
Intelligence experience, but the higher-impact protection is in reflection:
workflow insights carry a specific `preferred_workflow_id` and cannot silently
become a generic preference for the wrapper tool.

---

## Usage Methods

### Method 1: WebUI Manual Feedback (NEW - 2026-01-23)

Trigger feedback directly from the Web UI:

**Option A: Toggle Button**
1. Click the 📊 button (next to ✨ Enhance)
2. Button turns purple when enabled
3. All subsequent messages will trigger feedback analysis

**Option B: Inline Flag**
1. Add `--feedback` anywhere in your message
2. Example: "What's the current price of bitcoin? --feedback"

**What Happens:**
```
User sends message
    ↓
Normal processing (tools, response)
    ↓
Response shown to user
    ↓
Async feedback collection starts (purple card appears)
    ↓
Card updates with rating, summary, issues
    ↓
Toast notification (6 seconds)
```

**Feedback Card Shows:**
- Rating (1-5 stars with color coding)
- Summary (one-line description)
- What went well (positive feedback)
- Issues (with category tags)
- Tool Performance (per-tool ratings)

**Click to expand/collapse** - Cards start expanded, click header to toggle.

**Logged** - Each completed feedback run appends one line to `logs/feedback/` (all ratings). Toggle vs `--feedback` only control *whether* feedback runs, not whether a successful run is written.

### Method 2: Random Feedback Sampling

Random feedback can run during normal orchestrator usage when enabled:

```bash
FEEDBACK_RANDOM_ENABLED=true
FEEDBACK_RANDOM_CHANCE=0.05
```

In Jarvis Web, random feedback can be pre-collected and emitted as the normal feedback card when Completion Guard is not active for that turn. When Completion Guard is enabled, Web temporarily disables the orchestrator random path and only explicit Web feedback (`📊` toggle or `--feedback`) is coordinated behind guard settlement.

### Method 3: `--feedback` Flag (CLI)

Add `--feedback` to any orchestrator command:

```bash
# Basic usage
./orchestrator/orchestrator_v2.py cloud "What time is it?" --feedback

# With other flags
./orchestrator/orchestrator_v2.py cloud "Search memory" --feedback --json
./orchestrator/orchestrator_v2.py cloud "Complex task" --feedback --debug-thinking
```

**When to use**: 
- Debugging a specific query
- Spot-checking after changes
- One-off testing

### Method 4: `bin/jarvis-feedback` (Dedicated Tool)

Standalone tool with multiple commands:

```bash
./bin/jarvis-feedback run "Query here"      # Single query with feedback
./bin/jarvis-feedback batch file.txt        # Batch testing
./bin/jarvis-feedback summary               # Summarize recent feedback
./bin/jarvis-feedback recent                # Show recent feedback entries
./bin/jarvis-feedback issues                # Show only issues (rating < 5)
```

**When to use**:
- Batch testing multiple queries
- Reviewing historical feedback
- Analyzing patterns in issues

---

## Commands Reference

### `--feedback` Flag

| Flag | Description |
|------|-------------|
| `--feedback` | Collect LLM feedback after task completion |

Example:
```bash
./orchestrator/orchestrator_v2.py cloud "What's the weather?" --feedback
```

### `bin/jarvis-feedback` Commands

#### `run` - Single Query

```bash
./bin/jarvis-feedback run "Your query here" [--mode cloud|local]
```

Runs a single query through the orchestrator and collects feedback.

#### `batch` - Batch Testing

```bash
./bin/jarvis-feedback batch queries.txt [--mode cloud|local]
```

Runs multiple queries from a file (one per line, `#` for comments).

Example file (`tests/feedback-queries.txt`):
```
# Memory tests
Search my memory for flask
What do you remember about my server?

# Tool tests
What time is it?
What's the Bitcoin price?
```

#### `summary` - Feedback Summary

```bash
./bin/jarvis-feedback summary [--days 7] [--mode cloud|local]
```

Shows aggregated statistics from feedback logs:
- Total feedback entries
- Average rating
- Issues grouped by category
- Low-rated tasks

**`--days` explained**: Looks back N days in the `logs/feedback/` directory. It reads `feedback-YYYY-MM-DD.jsonl` files from the past N days and aggregates them.

#### `recent` - Recent Feedback

```bash
./bin/jarvis-feedback recent [--days 7] [--mode cloud|local]
```

Shows individual feedback entries from recent days.

#### `issues` - Issues Only

```bash
./bin/jarvis-feedback issues [--days 7] [--mode cloud|local]
```

Shows only feedback with rating < 5 (tasks that had problems).

---

## What the LLM Sees

During feedback collection, the LLM receives **FULL CONTEXT** to enable specific, actionable feedback:

### Provided Information

| Info | Source | Purpose |
|------|--------|---------|
| Original query | User input | What was asked |
| Success/failure | Task result | Did it work |
| Response text | Task result | What was returned |
| Tools used | Task result | What tools ran |
| **FULL System Prompt** | Router | Critique rules, constraints, instructions |
| **Tool Descriptions** | Registry | For tools used + likely relevant tools |
| **Intelligence Insights** | Context | Learned strategies, known failures |
| **Config Context** | Config | Auto-context, response style, mode |
| **Completion Guard** | Web UI / collector | Settled-outcome status, repair notes, evaluator hints |

### Why Full Context Matters

The LLM needs to SEE the actual text to provide specific feedback like:
- "The system prompt says X but this conflicts with Y"
- "Tool description for `get_time` says 'returns current time' but doesn't mention timezone"
- "Intelligence insight #24 was misleading because..."

### Tool Description Detection

The system automatically includes descriptions for:
1. Tools that were actually used
2. Tools that SHOULD have been used (based on query keywords)

For example, a query with "time" will include the `get_time` description even if it wasn't used, so the LLM can say "This tool should have been used because..."

### The Feedback Prompt

```
You just completed a task as a voice assistant. Now provide HONEST FEEDBACK...

=== YOUR TASK WAS ===
User Query: What time is it?

=== RESULT ===
Success: Yes
Response: It's 2:15 PM on Sunday
Tools Used: get_time

=== WHAT YOU WERE GIVEN ===
System Prompt Summary:
- Memory-first rules requiring semantic_recall before external tools
- 25-word voice output limit
- Tool descriptions for 50 tools
- Intelligence insights (learned patterns, known failures)
- Auto-context with recent conversation history

Tools Available: 50
Intelligence Insights: Enabled
Auto-Context: Enabled (window=3, minutes=10)
Response Style: auto

=== PROVIDE FEEDBACK ===
Rate your experience (1-5)...
```

---

## Output Format

### JSON Structure

```json
{
    "rating": 4,
    "summary": "Task completed but tool description could be clearer",
    "tool_ratings": {
        "get_time": {"rating": 5, "note": "Returned correct time"},
        "remember": {"rating": 5, "note": "Stored data correctly"}
    },
    "issues": [
        {
            "category": "tool_description",
            "description": "get_time description doesn't mention timezone handling",
            "suggestion": "Add 'Returns time in user's local timezone' to description"
        }
    ],
    "positive": "Memory-first rule correctly skipped for time query",
    "timestamp": "2025-11-30T09:45:00.000000",
    "session_id": "20251130_094500",
    "query": "What time is it?",
    "result_ok": true,
    "raw_llm_response": "It's 2:15 PM on Sunday, December 1st, 2025.",
    "final_speech": "It's 2:15 PM on Sunday",
    "tools_used": ["get_time"],
    "mode": "cloud",
    "feedback_provider": "anthropic",
    "feedback_model": "claude-sonnet-4-5-20250929",
    "completion_guard": {
      "status": "accepted",
      "mode": "manual",
      "note": ""
    }
}
```

### Per-Tool Ratings (Multi-Tool Attribution)

When multiple tools are used, each tool is rated **individually**:

```json
"tool_ratings": {
    "remember": {"rating": 5, "note": "Correctly stored data"},
    "search_memory": {"rating": 5, "note": "Found relevant memories"},
    "crypto_price": {"rating": 5, "note": "Accurate price data"}
}
```

**Why this matters:**
- Overall `rating` may be low (e.g., 2) due to LLM decision failures
- But individual tools that worked well get high `tool_ratings` (e.g., 5)
- Evolution system uses per-tool ratings to correctly attribute issues
- Tools that work well aren't penalized for system prompt issues

**Example:**
```
Query: "get bitcoin price and tell me the time"
Tools used: crypto_price (only)
Overall rating: 2 (LLM failed to call get_time)

tool_ratings:
  - crypto_price: 5 (worked perfectly)
  
Result: crypto_price keeps its good rating, system_prompt takes the hit
```

### Issue Categories

| Category | Description |
|----------|-------------|
| `system_prompt` | Issues with instructions, rules, constraints |
| `tool_description` | Tool descriptions don't match behavior |
| `intelligence_insights` | Issues with learned strategies or known failures |
| `config` | Configuration issues (auto-context, response style) |
| `missing_info` | Information that would have helped |
| `other` | Anything else |

### Issue Structure

Each issue now includes:
```json
{
    "category": "tool_description",
    "description": "What's wrong",
    "current_text": "The actual text that's problematic (quoted)",
    "suggestion": "How to fix it with specific improved text"
}
```

This allows you to see exactly WHAT text needs changing and HOW to change it.

### Rating Scale

| Rating | Meaning |
|--------|---------|
| 5 | Perfect - no issues |
| 4 | Minor improvements possible |
| 3 | Some issues but workable |
| 2 | Significant issues |
| 1 | Major problems |

---

## Log Files

### Location

```
logs/feedback/
├── feedback-2025-11-30.jsonl
├── feedback-2025-11-29.jsonl
└── ...
```

### Format

One JSON object per line (JSONL):
```jsonl
{"rating": 5, "summary": "No issues", "timestamp": "...", ...}
{"rating": 3, "summary": "Tool description misleading", "issues": [...], ...}
```

### When Logs Are Written

- **Current behavior**: Each successful feedback collection appends **one JSON line** to the day’s file (`feedback-YYYY-MM-DD.jsonl`), regardless of rating or trigger source (manual, inline flag, batch, or random sample). Failed collections still write an error-shaped entry.
- **`JARVIS_FEEDBACK_ALWAYS_LOG`**: Legacy hook set temporarily in the Web UI feedback path; `FeedbackCollector` always appends a line and does not gate on this variable.

---

## Use Cases

### 1. After Making Changes

```bash
# Test that your changes didn't break anything
./bin/jarvis-feedback batch tests/feedback-queries.txt
```

### 2. Debugging Specific Issues

```bash
# Something seems off with memory search
./orchestrator/orchestrator_v2.py cloud "Search my memory for flask" --feedback
```

### 3. Weekly Review

```bash
# What issues came up this week?
./bin/jarvis-feedback issues --days 7
./bin/jarvis-feedback summary --days 7
```

### 4. Tool Description QA

Run queries that use each tool and check if descriptions are accurate:
```bash
./bin/jarvis-feedback run "What's the Bitcoin price?"
# → Feedback might say: "Description says 'current price' but also returns 24h change"
```

### 5. System Prompt Validation

Ask meta-questions:
```bash
./bin/jarvis-feedback run "What tools do you have available?"
# → Feedback might say: "20-word limit too restrictive for this question"
```

---

## Configuration

### Dedicated Feedback Provider (Recommended)

**Problem**: Using the same LLM to grade itself creates bias - it won't catch its own mistakes.

**Solution**: Use a DIFFERENT LLM for feedback analysis.

```bash
# In config/cloud.env or config/local.env

# Use Claude to grade xAI's work
FEEDBACK_PROVIDER=anthropic
FEEDBACK_MODEL=claude-sonnet-4-5-20250929

# Or use OpenAI to grade anyone's work
FEEDBACK_PROVIDER=openai
FEEDBACK_MODEL=gpt-5.4-nano

# Or use a larger Ollama model to grade a smaller one
FEEDBACK_PROVIDER=ollama
FEEDBACK_MODEL=qwen3:32b
```

### Recommended Setups

| Task Provider | Feedback Provider | Why |
|---------------|-------------------|-----|
| xAI (cheap, fast) | Anthropic Claude | Claude's analysis is thorough |
| Ollama (local) | Anthropic or OpenAI | Cloud model catches local model mistakes |
| Anthropic | OpenAI | Different training, different blind spots |
| OpenAI | Anthropic | Same logic |

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FEEDBACK_PROVIDER` | LLM provider for feedback | Same as task |
| `FEEDBACK_MODEL` | Model for feedback | Provider's default |

### Supported Providers

- `anthropic` - Claude models (claude-sonnet-4-5-20250929, etc.)
- `openai` - GPT models (e.g. `gpt-5.6-luna` as code default when `FEEDBACK_PROVIDER=openai` and model unset—see `lib/feedback.py`; shipped cloud often pins `FEEDBACK_MODEL`)
- `xai` - Grok models (grok-4.5, etc.)
- `ollama` - Local models (gemma4, qwen3.5:latest, etc.)

### From Dashboard

The Jarvis Dashboard (Testing tab) includes:
- **Feedback Summary** - `./bin/jarvis-feedback summary --days 7`
- **Feedback Issues** - `./bin/jarvis-feedback issues --days 7`
- **Feedback Test** - `./bin/jarvis-feedback run "What time is it?"`

---

## Grafana & Loki Integration

### Log Shipping

Feedback logs are shipped to Loki via Promtail:

```yaml
# monitoring/promtail-config.yml
- job_name: jarvis_feedback
  static_configs:
    - targets: [localhost]
      labels:
        job: jarvis
        log_type: feedback
        __path__: /var/log/jarvis/feedback/feedback-*.jsonl
```

### Labels Available

| Label | Values | Use |
|-------|--------|-----|
| `log_type` | `feedback` | Filter feedback logs |
| `rating` | `1-5` | Filter by rating |
| `mode` | `cloud`, `local` | Filter by mode |
| `result_ok` | `true`, `false` | Filter by task success |
| `feedback_provider` | `anthropic`, `openai`, etc. | Filter by grading LLM |

### LogQL Queries

**All feedback logs:**
```logql
{job="jarvis", log_type="feedback"} | json
```

**Low ratings only (< 4):**
```logql
{job="jarvis", log_type="feedback"} | json | rating < 4
```

**Feedback by tool (from tool_ratings):**
```logql
{job="jarvis", log_type="feedback"} 
| json 
| line_format "{{.tool_ratings}}"
```

**Issues grouped by category:**
```logql
sum by (category) (
  count_over_time(
    {job="jarvis", log_type="feedback"} 
    | json 
    | unwrap issues [24h]
  )
)
```

**Average rating over time:**
```logql
avg_over_time(
  {job="jarvis", log_type="feedback"} 
  | json 
  | unwrap rating [1h]
)
```

### Dashboard Panels (Suggested)

1. **Rating Distribution** (Pie/Bar Chart)
   - Count of ratings 1-5

2. **Rating Trend** (Time Series)
   - Average rating over time

3. **Issues by Category** (Bar Chart)
   - system_prompt, tool_description, other

4. **Low-Rated Queries** (Table)
   - Queries with rating < 4

5. **Per-Tool Performance** (Table)
   - Average tool_ratings per tool

6. **Evolution Candidates** (Stat)
   - Components with 2+ low ratings

---

## Example Session

```bash
$ ./orchestrator/orchestrator_v2.py cloud "What's the current price of Bitcoin?" --feedback

🎯 Processing: 'What's the current price of Bitcoin?'
📡 Mode: cloud
🤖 Model: grok-4.3
============================================================

... normal task output ...

============================================================
🔍 COLLECTING FEEDBACK (LLM-as-QA Mode)
============================================================

📊 Feedback Rating: 5/5
📝 Summary: Task completed efficiently - crypto_price tool worked as expected

✅ What Worked: Intelligence insights correctly suggested crypto_price as preferred tool

📁 Feedback logged to: logs/feedback/feedback-2025-11-30.jsonl
```

---

## Feedback → Intelligence Bridge (Enhanced 2026-04-18)

Feedback ratings now **automatically enrich and correct** the Intelligence Layer's experience records.

### The Problem (Before)

```
User: "Play podcast on Spotify"
LLM: "No device available" (WITHOUT calling any tools)
Orchestrator: ok = True (LLM responded!)
Intelligence DB: outcome_success = True ← WRONG!
```

The system thought it succeeded because the LLM responded without error.

### The Solution (Now)

```
User: "Play podcast on Spotify"
LLM: "No device available" (WITHOUT calling tools)
Orchestrator: ok = True (default)
Feedback: Rating 2/5 ("Action requested but no tools called")
                ↓
Intelligence DB: outcome_success = False ← CORRECTED!
                 user_satisfied = False
                 had_to_retry = True
                 reflection_priority = 0.8 (high)
                 raw_data.feedback.latest = {rating, summary, issues...}
```

### How It Works

1. **Experience recorded** with default `outcome_success = True`
2. **Feedback collected** with rating 1-5
3. **All ratings**: `update_experience_from_feedback()` stores compact feedback metadata under `raw_data.feedback.latest`
4. **If rating ≤ 2**: it corrects:
   - `outcome_success = False`
   - `user_satisfied = False`
   - `had_to_retry = True`
   - Bumps reflection queue priority to 0.8
5. **If rating ≥ 4**: it may mark `user_satisfied = True` unless Completion Guard already recorded a hard failure (`unresolved`, `ticket_created`, `error`)

### Rating → Correction Logic

| Rating | Action | Rationale |
|--------|--------|-----------|
| 5 | Store feedback; mark satisfied when safe | Perfect execution |
| 4 | Store feedback; mark satisfied when safe | Minor issues, still success |
| 3 | Store feedback; leave outcome as-is | Ambiguous |
| 2 | **Store + correct** | Significant issues = failure |
| 1 | **Store + correct** | Major problems = failure |

### Stored Experience Metadata

The feedback JSONL remains the full audit log. The intelligence DB stores a compact copy on the linked experience so reflection can see why the turn was graded poorly:

```json
{
  "feedback": {
    "latest": {
      "rating": 2,
      "summary": "Relevant tool, but the answer missed requested hours and inferred an address.",
      "issues": [
        {
          "category": "other",
          "description": "The response did not satisfy the requested fields."
        }
      ],
      "tool_ratings": {
        "serpapi_yelp_search": {"rating": 3}
      },
      "completion_guard_status": "auto_accepted",
      "updated_at": "2026-04-18T04:30:34"
    },
    "history": []
  }
}
```

If multiple feedback runs touch the same experience, the prior `latest` entry rolls into a short `history` list.

### Completion Guard Interaction

Completion Guard and feedback update the **same experience row** but different metadata blocks:

- Completion Guard writes `raw_data.completion_guard`
- Feedback writes `raw_data.feedback`

Low feedback can downgrade an `auto_accepted` / `tighten_only` settled answer if the QA reviewer finds a real miss. High feedback does not erase repaired/failed guard history, so reflection can still learn that the first pass needed recovery.

### Why Default to Success?

**False negatives are worse than false positives** for learning:
- Legitimate "no tools" scenarios: LLM used internal knowledge, auto-context, system prompt time
- Rigid rules would incorrectly penalize valid responses
- The feedback LLM (with full context) is the best judge

### Console Output

When correction happens:
```
🔄 Intelligence corrected: experience 338 marked as FAILURE (rating 1)
```

### Verify in Database

```sql
SELECT id, outcome_success, user_satisfied, query 
FROM experiences 
WHERE id = 338;
```

---

## Future Enhancements

1. **Aggregate analysis** - Pattern detection across many feedback entries
2. **Auto-fix suggestions** - Generate patches for tool descriptions
3. ~~**Integration with intelligence layer**~~ ✅ DONE - Feedback now corrects experiences and stores feedback context for reflection
4. ~~**Completion Guard alignment**~~ ✅ DONE - Web feedback passes guard context; experiences also updated from guard outcomes (see [INTELLIGENCE_LAYER.md](./INTELLIGENCE_LAYER.md))
5. **Slack/Discord alerts** - Notify on low ratings

---

## Related Documentation

- [Completion Guard](./COMPLETION_GUARD.md) - Post-answer completion loop, repair, tickets
- [Intelligence Layer](./INTELLIGENCE_LAYER.md) - Learning from success/failure patterns
- [Tool Calling System](./TOOL_CALLING_SYSTEM.md) - How tools work
- [Memory System](./MEMORY_SYSTEM.md) - Memory-first rules
