# Advanced AI Techniques for Jarvis

> **Purpose**: This document outlines advanced self-learning, autonomous, and multi-agent techniques planned for Jarvis. Each technique includes implementation details, safety mechanisms, and integration points.

---

## 📋 Table of Contents

1. [Overview & Philosophy](#overview--philosophy)
2. [Phase 3: Self-Evolving Prompts](#phase-3-self-evolving-prompts)
3. [Phase 4: Dynamic Tool Creation](#phase-4-dynamic-tool-creation)
4. [Phase 5: Parallel Subagents](#phase-5-parallel-subagents)
5. [Phase 6: Self-Play Optimization](#phase-6-self-play-optimization)
6. [Phase 7: Versioned Prompts & Rollback](#phase-7-versioned-prompts--rollback)
7. [Implementation Priority](#implementation-priority)
8. [Safety & Guardrails](#safety--guardrails)

---

## TL;DR - Super Simple Explanation

**What is Prompt Evolution?**
Jarvis grades itself after every task. If a tool or the system prompt keeps getting bad grades, Jarvis automatically improves it.

**How it Works:**
1. **Feedback** → After each query, feedback LLM rates performance (1-5)
2. **Track** → Ratings are stored per-tool and for system prompt
3. **Detect** → If something has 2+ low ratings, it becomes an evolution candidate
4. **Improve** → LLM generates a better description/prompt
5. **Deploy** → Verified improvement gets deployed (tools auto, system prompt manual)

**Manual Commands:**
```bash
# See what needs improvement
./bin/evolve-prompts check cloud

# Generate improvements for candidates
./bin/evolve-prompts auto cloud

# Review system prompt suggestions
cat logs/evolution/system_prompt_suggestions.md
```

**Multi-Tool Fairness:** When 3 tools are used but only 1 failed, only that tool gets a bad rating. The other tools keep their good ratings.

---

## Overview & Philosophy

### Core Principles

1. **High Standards, Not Arbitrary Changes**: Changes to prompts/tools require evidence from multiple feedback sessions, not single instances.

2. **Audit Everything**: Every change must be traceable to a feedback session ID, with before/after snapshots.

3. **Verify Before Deploy**: All auto-generated content (prompts, tools) must pass validation before becoming active.

4. **Separate Auto-Generated Content**: Auto-created tools live in `skills/auto-tools/` to distinguish from human-crafted tools.

5. **Best Model for Critical Tasks**: Use `FEEDBACK_PROVIDER`/`FEEDBACK_MODEL` (strongest available) for verification and evolution tasks.

### Current Foundation (Already Built)

| Component | Status | Used By |
|-----------|--------|---------|
| Feedback System | ✅ Built | Collects LLM self-critique per interaction |
| Intelligence Layer | ✅ Built | Records experiences, generates insights |
| Meta-Cognition | ✅ Built | Detects learning blind spots |
| Tool RAG | ✅ Built | Dynamic tool retrieval |
| OpenCode Subagents | ✅ Available | `~/.config/opencode/agent/*.md` |

---

## Phase 3: Self-Evolving Prompts

### Concept

Use accumulated feedback data to automatically improve system prompts and tool descriptions. Changes are version-controlled, A/B tested, and require verification.

### Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PROMPT EVOLUTION PIPELINE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐                                                           │
│  │   Feedback   │  Accumulate ratings & suggestions                         │
│  │     Logs     │  (logs/feedback/feedback-*.jsonl)                         │
│  └──────┬───────┘                                                           │
│         │                                                                   │
│         ▼  Trigger: 5+ low ratings (<6) on same component                   │
│  ┌──────────────┐                                                           │
│  │   Analyze    │  Group feedback by component (system_prompt, tool:xyz)    │
│  │   Patterns   │  Extract common complaints/suggestions                    │
│  └──────┬───────┘                                                           │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────┐                                                           │
│  │   Generate   │  Use FEEDBACK_MODEL to propose improvements               │
│  │   Variants   │  Creates 2-3 candidate versions                           │
│  └──────┬───────┘                                                           │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────┐                                                           │
│  │   Verify     │  1. Syntax validation (JSON parseable, Python runs)       │
│  │   Candidates │  2. Semantic check (required fields present)              │
│  │              │  3. Test with synthetic queries                           │
│  └──────┬───────┘                                                           │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────┐                                                           │
│  │   A/B Test   │  Random 50/50 split for N interactions                    │
│  │   (Optional) │  Compare avg ratings                                      │
│  └──────┬───────┘                                                           │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────┐                                                           │
│  │   Promote    │  Winner becomes active                                    │
│  │   & Archive  │  Old version archived with full audit trail               │
│  └─────────────┘                                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Database Schema

```sql
-- New table: prompt_versions
CREATE TABLE prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- What this prompt is for
    component TEXT NOT NULL,           -- 'system_prompt', 'tool:search_memory', 'tool:execute_bash'
    component_type TEXT NOT NULL,      -- 'system', 'tool_description', 'tool_schema'
    
    -- Version tracking
    version INTEGER NOT NULL,
    content TEXT NOT NULL,             -- The actual prompt/description text
    
    -- Lineage
    parent_version_id INTEGER,         -- Which version this evolved from
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT,                   -- 'human', 'auto_evolution', 'rollback'
    
    -- Performance metrics
    times_used INTEGER DEFAULT 0,
    total_rating_sum REAL DEFAULT 0,
    avg_rating REAL GENERATED ALWAYS AS (
        CASE WHEN times_used > 0 THEN total_rating_sum / times_used ELSE NULL END
    ) STORED,
    
    -- Status
    is_active BOOLEAN DEFAULT FALSE,
    is_archived BOOLEAN DEFAULT FALSE,
    
    -- Audit trail
    trigger_feedback_ids TEXT,         -- JSON array of feedback IDs that triggered this
    change_summary TEXT,               -- LLM-generated summary of what changed
    
    FOREIGN KEY (parent_version_id) REFERENCES prompt_versions(id)
);

-- Index for fast lookups
CREATE INDEX idx_prompt_active ON prompt_versions(component, is_active);
CREATE INDEX idx_prompt_performance ON prompt_versions(component, avg_rating);
```

### Configuration (Environment Variables)

All evolution settings can be configured in `config/cloud.env` or `config/local.env`:

```bash
# --- Thresholds ---
EVOLUTION_MIN_LOW_RATINGS=2      # Min low ratings to trigger (testing: 2, prod: 5)
EVOLUTION_LOW_THRESHOLD=7        # Ratings below this are "low" (testing: 7, prod: 6)
EVOLUTION_WINDOW_DAYS=3          # Days to look back (testing: 3, prod: 7)

# --- Rate Limits ---
EVOLUTION_MAX_PER_DAY=5          # Max evolutions per day (testing: 5, prod: 3)

# --- Automation ---
EVOLUTION_AUTO_ENABLED=false     # Auto-evolve after feedback threshold
EVOLUTION_AUTO_CHECK_AFTER=10    # Feedback count to trigger auto-check

# --- Degradation Detection ---
EVOLUTION_DEGRADATION_ALERT_PCT=15    # Alert when perf drops by %
EVOLUTION_DEGRADATION_ROLLBACK_PCT=25 # Auto-rollback when perf drops by %

# --- A/B Testing ---
EVOLUTION_AB_TEST_SIZE=10        # Sample size for A/B tests (testing: 10, prod: 20)
```

### Trigger Conditions

Evolution is triggered when:
- A component has `EVOLUTION_MIN_LOW_RATINGS` or more ratings below `EVOLUTION_LOW_THRESHOLD`
- Within the last `EVOLUTION_WINDOW_DAYS` days
- Rate limit (`EVOLUTION_MAX_PER_DAY`) not exceeded

### Multi-Tool Attribution (Per-Tool Ratings)

**Problem**: Most queries use multiple tools. If overall rating is low, which tool is at fault?

**Solution**: The feedback LLM rates each tool separately:

```json
{
  "rating": 2,  // Overall: low because time was skipped
  "tool_ratings": {
    "remember": {"rating": 5, "note": "Correctly stored data"},
    "search_memory": {"rating": 5, "note": "Found relevant memories"},
    // get_time wasn't called, so no rating recorded
  }
}
```

**Attribution Logic**:

| Scenario | System Prompt Rating | Tool Ratings |
|----------|---------------------|--------------|
| All tools worked, overall good | Overall rating | Per-tool ratings |
| Tools worked, LLM made bad decision | Overall rating (low) | Per-tool ratings (high) |
| Specific tool failed | Overall rating | That tool gets low rating |

**Key Insight**: When the LLM fails to use a tool (like skipping `get_time` when user asks for time), the **system prompt** takes the rating hit, not the tools that were actually used. This correctly identifies that the LLM's routing decision was the problem, not the individual tool implementations.

**Example Database State After Multi-Tool Tests**:

```
Component                | Uses | Avg Rating | Notes
-------------------------|------|------------|----------------------
system_prompt           |   9  |    3.56    | Takes hit from LLM decision errors
tool:remember           |   2  |    5.00    | Perfect uses
tool:search_memory      |   1  |    5.00    | Per-tool rating preserved
tool:weather            |   1  |    5.00    | Individual rating correct
```

### Audit Trail Example

```json
{
  "version_id": 42,
  "component": "tool:search_memory",
  "component_type": "tool_description",
  "version": 3,
  "parent_version_id": 41,
  "created_by": "auto_evolution",
  "trigger_feedback_ids": ["fb_2025-12-01_001", "fb_2025-12-01_003", "fb_2025-12-01_007"],
  "change_summary": "Added explicit guidance for verification-style questions. Previous version lacked instruction to report whether matches were found.",
  "content_diff": {
    "added": "FOR VERIFICATION QUESTIONS (e.g., 'Do I have X saved?'), explicitly report whether matching entries were found.",
    "removed": null
  },
  "before_avg_rating": 5.2,
  "after_avg_rating": 7.8,
  "promoted_at": "2025-12-08T14:30:00Z"
}
```

### Implementation Files

```
bin/
├── evolve-prompts           # Main evolution CLI
├── setup-prompt-versions.py # Database schema setup
├── sync-evolution-db.py     # Sync evolution data between cloud/local

lib/
├── prompt_evolution.py      # Core evolution logic + LLM generation
└── prompt_versioning.py     # DB operations + version tracking

data/
├── jarvis_memory.db         # Contains prompt_versions, prompt_evolution_log, prompt_backups
└── jarvis_memory_local.db   # Same tables for local mode

logs/evolution/
└── evolution-YYYY-MM-DD.jsonl  # JSONL logs for Grafana/Loki
```

### Grafana Dashboard

A dedicated dashboard for monitoring feedback and evolution:

**Dashboard**: `Jarvis Feedback & Evolution`
**URL**: http://192.168.70.228:3000/d/jarvis-feedback-evolution

**Panels:**
1. **Feedback Overview** - Total feedback entries (24h)
2. **Average Rating** - Avg rating with color thresholds
3. **Low Ratings** - Count of ratings < 4
4. **Evolution Events** - Count of evolution events
5. **Rating Trend** - Rating over time graph
6. **Rating Distribution** - Pie chart of ratings 1-5
7. **Evolution by Component** - Which components evolved
8. **Recent Feedback Logs** - Live log stream
9. **Evolution Event Log** - Evolution activity stream

**LogQL Queries:**
```logql
# All feedback
{job="jarvis", log_type="feedback"} | json

# Low ratings
{job="jarvis", log_type="feedback"} | json | rating < 4

# Evolution events
{job="jarvis", log_type="evolution"} | json

# Rating trend
avg_over_time({job="jarvis", log_type="feedback"} | json | unwrap rating [1h])
```

### Cloud ↔ Local Sync

Evolution improvements can be synced between cloud and local databases:

```bash
# Sync cloud improvements to local (recommended)
# Use stronger cloud models to evolve, then sync to local
./bin/sync-evolution-db.py local --update-files
./bin/sync_tools.py local

# Sync local to cloud (if needed)
./bin/sync-evolution-db.py cloud --update-files
./bin/sync_tools.py cloud
```

**Recommended Workflow:**
1. Run evolution with cloud mode (stronger LLMs for generation)
2. Sync improvements to local: `./bin/sync-evolution-db.py local --update-files`
3. Sync tool embeddings: `./bin/sync_tools.py local`

### Logging & Monitoring

Evolution events are logged in JSONL format for Grafana/Loki integration:

```bash
# View today's evolution logs
cat logs/evolution/evolution-$(date +%Y-%m-%d).jsonl | jq '.'

# Via dashboard
jarvis-dashboard → 🧬 Evolution → Evolution Logs
```

**Logged Events:**
- `evolution_check_started` - Check initiated
- `evolution_deployed` - New version deployed
- `evolution_verification_failed` - Candidate failed validation
- `evolution_blocked` - Rate limit hit
- `degradation_detected` - Performance drop detected
- `auto_rollback` - Automatic rollback triggered

### CLI Usage

```bash
# Check what needs evolution (based on feedback)
./bin/evolve-prompts check

# Output:
# Components with low ratings (past 7 days):
#   tool:search_memory - 5 ratings avg 5.4 (threshold: 6.0)
#   system_prompt - 3 ratings avg 6.8 (below threshold, needs 5+)

# Generate candidates for a component
./bin/evolve-prompts generate tool:search_memory

# Output:
# Generated 2 candidate versions for tool:search_memory
# Candidate A: Added verification question guidance
# Candidate B: Restructured with examples
# Run validation...
# ✅ Both candidates passed validation
# Starting A/B test (need 20 interactions)

# View prompt history
./bin/prompt-history tool:search_memory

# Output:
# Version 1 (human, 2025-11-01) - Original
# Version 2 (auto_evolution, 2025-11-15) - Added FTS5 guidance
#   Trigger: 7 low ratings, avg improved 5.1 → 7.2
# Version 3 (auto_evolution, 2025-12-01) - Added verification guidance [ACTIVE]
#   Trigger: 5 low ratings, avg improved 5.4 → 7.8

# Rollback if needed
./bin/evolve-prompts rollback tool:search_memory --to-version 2
```

---

## Phase 4: Dynamic Tool Creation

### Concept

When feedback repeatedly suggests a missing capability, trigger a specialized Tool Builder agent to create a new tool. Auto-generated tools are stored separately and tracked.

### Key Safeguards

1. **High Bar for Creation**: Requires 3+ feedback sessions suggesting the same missing capability
2. **Specialized Builder**: Dedicated OpenCode subagent with tool-building expertise
3. **Separate Storage**: `skills/auto-tools/` directory
4. **Registry Tracking**: `data/auto_tools_registry.json` tracks all auto-created tools
5. **Verification Pipeline**: Must pass syntax, schema, and functional tests

### Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      DYNAMIC TOOL CREATION PIPELINE                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐                                                           │
│  │   Feedback   │  "Jarvis lacks a tool for X"                              │
│  │   Analysis   │  "Would be better with dedicated Y tool"                  │
│  └──────┬───────┘                                                           │
│         │                                                                   │
│         ▼  Trigger: 3+ feedback suggesting same capability gap              │
│  ┌──────────────┐                                                           │
│  │   Validate   │  1. Not duplicate of existing tool                        │
│  │   Need       │  2. Can't be done with tool combination                   │
│  │              │  3. General enough to be reusable                         │
│  └──────┬───────┘                                                           │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────┐                                                           │
│  │   OpenCode   │  Specialized subagent: tool-builder                       │
│  │   Subagent   │  Uses TOOL_TEMPLATE + existing tools as reference         │
│  │              │  Creates: xyz.py + xyz.tool.json                          │
│  └──────┬───────┘                                                           │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────┐                                                           │
│  │   Verify     │  1. Python syntax valid                                   │
│  │   Tool       │  2. JSON schema valid                                     │
│  │              │  3. Required fields present (ok, speech, data)            │
│  │              │  4. Test execution with sample input                      │
│  │              │  5. No dangerous operations (unless flagged)              │
│  └──────┬───────┘                                                           │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────┐                                                           │
│  │   Deploy     │  1. Save to skills/auto-tools/                            │
│  │   & Register │  2. Update auto_tools_registry.json                       │
│  │              │  3. Run sync_tools.py                                     │
│  │              │  4. Notify user of new tool                               │
│  └──────┬───────┘                                                           │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────┐                                                           │
│  │   Monitor    │  Track usage and feedback on new tool                     │
│  │   Performance│  Low performance → disable or improve                     │
│  └─────────────┘                                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
skills/
├── remember.py              # Human-created tools
├── remember.tool.json
├── ...
└── auto-tools/              # Auto-generated tools (separate)
    ├── README.md            # Explains auto-tool system
    ├── network_latency.py   # Auto-generated
    ├── network_latency.tool.json
    └── registry.json        # Tracks all auto-tools
```

### Auto-Tools Registry

```json
{
  "version": 1,
  "tools": [
    {
      "name": "network_latency",
      "created_at": "2025-12-05T10:30:00Z",
      "trigger_feedback_ids": ["fb_001", "fb_003", "fb_007"],
      "capability_gap": "Check network latency to specific hosts",
      "status": "active",
      "times_used": 15,
      "avg_rating": 7.2,
      "builder_session_id": "opencode_session_abc123",
      "verification_passed": true,
      "verification_log": "logs/auto-tools/network_latency_verify.log"
    }
  ],
  "pending_capabilities": [
    {
      "capability": "PDF text extraction",
      "feedback_count": 2,
      "first_requested": "2025-12-03T08:00:00Z",
      "status": "needs_more_feedback"
    }
  ]
}
```

### OpenCode Workspace Isolation

**Important Constraint**: OpenCode is isolated to `~/jarvis-workspace` and CANNOT write directly to `~/jarvis-voice/skills/`.

**Solution - Two-Stage Build**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    TOOL BUILDING WITH OPENCODE ISOLATION                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Stage 1: OpenCode builds in workspace                                      │
│  ─────────────────────────────────────                                      │
│    OpenCode → ~/jarvis-workspace/tools/new_tool.py                          │
│            → ~/jarvis-workspace/tools/new_tool.tool.json                    │
│                                                                             │
│  Stage 2: Install script moves to Jarvis                                    │
│  ─────────────────────────────────────────                                  │
│    ./bin/install-tool ~/jarvis-workspace/tools/new_tool                     │
│      1. Validates tool files                                                │
│      2. Copies to skills/auto-tools/                                        │
│      3. Runs sync_tools.py                                                  │
│      4. Updates registry                                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### OpenCode Tool Builder Subagent

Location: `~/.config/opencode/agent/tool-builder.md`

You can also define agents using markdown files. Place them in:

    Global: ~/.config/opencode/agent/
    Per-project: .opencode/agent/

~/.config/opencode/agent/review.md

```markdown
---
description: Reviews code for quality and best practices
mode: subagent
model: anthropic/claude-sonnet-4-5-20250929
temperature: 0.1
tools:
  write: false
  edit: false
  bash: false
---

You are in code review mode. Focus on:

- Code quality and best practices
- Potential bugs and edge cases
- Performance implications
- Security considerations

Provide constructive feedback without making direct changes.
```

The markdown file name becomes the agent name. For example, review.md creates a review agent.


```markdown
# Tool Builder Agent

You are a specialized agent for creating Jarvis voice assistant tools.

## Your Task
Create Python tools that follow Jarvis conventions exactly.

## Template to Follow
Every tool must have TWO files:

### 1. Python Script (tool_name.py)
```python
#!/usr/bin/env python3
"""
Tool Name: [Description]
Input: { "param": "value" }
Output: { "ok": bool, "speech": str, "data": dict }
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))
from config_loader import load_config, get_config_value

def main():
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        load_config()
        
        # Validate required params
        required_param = args.get('required_param')
        if not required_param:
            raise ValueError("required_param is required")
        
        # Tool logic here
        result = do_work(required_param)
        
        print(json.dumps({
            "ok": True,
            "speech": f"Completed: {result['summary']}",
            "data": result
        }))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Error: {e}"
        }))
        sys.exit(1)

def do_work(param):
    # Actual logic (separate for testing)
    return {"summary": "done"}

if __name__ == "__main__":
    main()
```

### 2. JSON Schema (tool_name.tool.json)
```json
{
  "enabled": true,
  "name": "tool_name",
  "description": "Clear description for LLM. Explain WHEN to use and WHAT it does.",
  "script": "auto-tools/tool_name.py",
  "parameters": {
    "type": "object",
    "properties": {
      "required_param": {
        "type": "string",
        "description": "What this does"
      }
    },
    "required": ["required_param"]
  },
  "permissions": {
    "dangerous": false,
    "network": true,
    "filesystem": false,
    "auto_approve": true
  }
}
```

## Critical Rules
1. ALWAYS return JSON with ok, speech, data
2. ALWAYS handle errors with try/except
3. ALWAYS validate required parameters
4. Script path must be "auto-tools/tool_name.py"
5. Description must explain WHEN to use (not just what it does)
6. Test your tool before declaring complete
```

### Verification Checklist

Before a tool goes live:

```python
VERIFICATION_CHECKS = [
    # Syntax
    ("python_syntax", "Python file parses without errors"),
    ("json_syntax", "JSON file is valid JSON"),
    
    # Schema compliance
    ("has_name", "JSON has 'name' field"),
    ("has_description", "JSON has 'description' field (min 50 chars)"),
    ("has_parameters", "JSON has 'parameters' field"),
    ("script_exists", "Script file exists at specified path"),
    
    # Output format
    ("returns_json", "Script returns valid JSON"),
    ("has_ok_field", "Output has 'ok' boolean field"),
    ("has_speech_field", "Output has 'speech' string field"),
    ("has_data_field", "Output has 'data' object field"),
    
    # Error handling
    ("handles_missing_params", "Gracefully handles missing required params"),
    ("handles_invalid_input", "Gracefully handles invalid input types"),
    
    # Safety
    ("no_dangerous_imports", "No subprocess.call with shell=True, no eval()"),
    ("permissions_accurate", "Permissions flags match actual behavior"),
]
```

### CLI Usage

```bash
# Check pending tool requests
./bin/auto-tool-builder check

# Output:
# Pending capability gaps:
#   "network latency check" - 4 feedback mentions (threshold: 3) ✅ READY
#   "PDF text extraction" - 2 feedback mentions (needs 1 more)

# Build a tool (invokes OpenCode subagent)
./bin/auto-tool-builder create "network latency check"

# Output:
# Invoking OpenCode tool-builder subagent...
# Session: opencode_session_abc123
# Creating: skills/auto-tools/network_latency.py
# Creating: skills/auto-tools/network_latency.tool.json
# Running verification...
#   ✅ python_syntax
#   ✅ json_syntax
#   ✅ has_name
#   ✅ has_description
#   ... (all checks)
# Verification PASSED
# Syncing tools...
# ✅ Tool 'network_latency' is now available!

# List auto-created tools
./bin/auto-tool-builder list

# Disable a problematic auto-tool
./bin/auto-tool-builder disable network_latency
```

---

## Phase 5: Parallel Subagents

### Concept

For complex multi-part queries, decompose into subtasks and execute in parallel using specialized subagents.

### When to Parallelize

```python
PARALLELIZATION_PATTERNS = [
    # Pattern: "Research X, Y, and Z"
    {
        "trigger": r"research|compare|analyze .+ (and|,) .+",
        "strategy": "parallel_research",
        "max_workers": 3
    },
    
    # Pattern: "Do A and also do B"
    {
        "trigger": r".+ and (also )?(do|check|find|get) .+",
        "strategy": "parallel_independent",
        "max_workers": 2
    },
    
    # Pattern: "What are the top N ..."
    {
        "trigger": r"(top|best|compare) \d+ .+",
        "strategy": "parallel_gather",
        "max_workers": "N"  # Dynamic based on number
    }
]
```

### Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PARALLEL SUBAGENT ORCHESTRATION                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  User: "Research TensorFlow, PyTorch, and JAX - compare and save to canvas"│
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                        TASK DECOMPOSER                                │   │
│  │  Analyzes query, identifies parallel-safe subtasks                   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ Subtask 1: Research TensorFlow    (independent)                      │   │
│  │ Subtask 2: Research PyTorch       (independent)                      │   │
│  │ Subtask 3: Research JAX           (independent)                      │   │
│  │ Subtask 4: Compare & save         (depends on 1,2,3)                 │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         ▼                                                                   │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │                    PARALLEL EXECUTION                            │        │
│  │                                                                  │        │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │        │
│  │  │  Worker 1   │  │  Worker 2   │  │  Worker 3   │              │        │
│  │  │ TensorFlow  │  │  PyTorch    │  │    JAX      │              │        │
│  │  │   search    │  │   search    │  │   search    │              │        │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │        │
│  │         │                │                │                      │        │
│  │         └────────────────┼────────────────┘                      │        │
│  │                          ▼                                       │        │
│  │                   ┌─────────────┐                                │        │
│  │                   │  AGGREGATOR │                                │        │
│  │                   │  Combine    │                                │        │
│  │                   │  results    │                                │        │
│  │                   └──────┬──────┘                                │        │
│  │                          │                                       │        │
│  └──────────────────────────┼───────────────────────────────────────┘        │
│                             ▼                                                │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    SEQUENTIAL PHASE                                   │   │
│  │  Subtask 4: Compare results + Save to canvas                         │   │
│  │  (Runs after parallel phase completes)                               │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                             │                                                │
│                             ▼                                                │
│                      Final Response                                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Implementation Architecture

```python
# lib/subagent_pool.py

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Optional
import threading

@dataclass
class SubTask:
    id: str
    query: str
    allowed_tools: List[str]
    depends_on: List[str] = None  # Task IDs this depends on
    max_turns: int = 2
    timeout: int = 60

@dataclass  
class SubTaskResult:
    task_id: str
    success: bool
    data: dict
    speech: str
    tools_used: List[str]
    duration_ms: int

class SubagentPool:
    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers
        self.results = {}
        self.lock = threading.Lock()
    
    def execute_parallel(self, tasks: List[SubTask]) -> List[SubTaskResult]:
        """Execute independent tasks in parallel, then dependent tasks."""
        
        # Separate independent and dependent tasks
        independent = [t for t in tasks if not t.depends_on]
        dependent = [t for t in tasks if t.depends_on]
        
        # Phase 1: Parallel execution of independent tasks
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._run_subtask, task): task
                for task in independent
            }
            
            for future in as_completed(futures):
                task = futures[future]
                result = future.result()
                with self.lock:
                    self.results[task.id] = result
        
        # Phase 2: Sequential execution of dependent tasks
        for task in dependent:
            # Wait for dependencies (already complete from phase 1)
            dep_results = [self.results[dep_id] for dep_id in task.depends_on]
            
            # Inject dependency results into task context
            task.context = {"previous_results": dep_results}
            
            result = self._run_subtask(task)
            self.results[task.id] = result
        
        return list(self.results.values())
    
    def _run_subtask(self, task: SubTask) -> SubTaskResult:
        """Run a single subtask with limited tools and turns."""
        from orchestrator_v2 import Orchestrator
        
        # Create mini-orchestrator with restricted tools
        orch = Orchestrator(
            mode=self.mode,
            allowed_tools=task.allowed_tools,
            max_turns=task.max_turns
        )
        
        result = orch.process(task.query)
        
        return SubTaskResult(
            task_id=task.id,
            success=result.get("ok", False),
            data=result.get("data", {}),
            speech=result.get("speech", ""),
            tools_used=result.get("tools_used", []),
            duration_ms=result.get("duration_ms", 0)
        )
```

### Task Decomposition Prompt

```python
DECOMPOSITION_PROMPT = """
Analyze this user query and decompose it into subtasks for parallel execution.

Query: {query}

Rules:
1. Identify subtasks that can run INDEPENDENTLY (no data dependencies)
2. Identify subtasks that DEPEND on others (need their output)
3. Each subtask should be achievable in 1-2 tool calls
4. Assign appropriate tools to each subtask

Output JSON:
{
  "is_parallelizable": true/false,
  "reason": "why or why not",
  "subtasks": [
    {
      "id": "task_1",
      "query": "specific query for this subtask",
      "tools": ["tool1", "tool2"],
      "depends_on": []  // empty = independent
    },
    {
      "id": "task_2", 
      "query": "...",
      "tools": ["..."],
      "depends_on": ["task_1"]  // runs after task_1
    }
  ]
}
"""
```

### Performance Comparison

| Query Type | Sequential | Parallel | Speedup |
|------------|-----------|----------|---------|
| Research 3 topics | ~45s | ~15s | 3x |
| Compare 5 items | ~75s | ~20s | 3.75x |
| Multi-search + summarize | ~60s | ~25s | 2.4x |

---

## Phase 6: Self-Play Optimization

### Concept

Jarvis simulates queries overnight, rates its own responses, and discovers better routing strategies without human interaction.

### Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SELF-PLAY OPTIMIZATION                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    QUERY GENERATION                                   │   │
│  │                                                                       │   │
│  │  Source 1: Past conversations (sample successful ones)               │   │
│  │  Source 2: Mutation of past queries (paraphrase, expand)             │   │
│  │  Source 3: Edge cases from feedback (low-rated interactions)         │   │
│  │                                                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    SANDBOXED EXECUTION                                │   │
│  │                                                                       │   │
│  │  - No real external calls (mocked responses)                         │   │
│  │  - No memory writes (dry run mode)                                   │   │
│  │  - Full routing logic exercised                                      │   │
│  │  - Tool selection recorded                                           │   │
│  │                                                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    SELF-EVALUATION                                    │   │
│  │                                                                       │   │
│  │  Evaluator LLM (FEEDBACK_MODEL) scores:                              │   │
│  │  - Tool selection appropriateness (1-10)                             │   │
│  │  - Response quality (1-10)                                           │   │
│  │  - Efficiency (turns used vs optimal)                                │   │
│  │                                                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    STRATEGY EXPLORATION                               │   │
│  │                                                                       │   │
│  │  For low-scoring interactions:                                       │   │
│  │  1. Generate alternative tool combinations                           │   │
│  │  2. Re-run with alternatives                                         │   │
│  │  3. Compare scores                                                   │   │
│  │  4. If alternative wins → record as new insight                      │   │
│  │                                                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    INSIGHT GENERATION                                 │   │
│  │                                                                       │   │
│  │  New insight: "For queries like X, prefer tool Y over Z"             │   │
│  │  Stored in intelligence layer with self-play origin                  │   │
│  │                                                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Query Mutation Examples

```python
MUTATION_STRATEGIES = {
    "paraphrase": {
        # Original: "What time is it?"
        # Mutations: "Tell me the current time", "What's the time now?", "Time?"
        "prompt": "Rephrase this query 3 different ways: {query}"
    },
    
    "expand": {
        # Original: "Weather"
        # Mutations: "What's the weather today?", "Weather forecast for my location"
        "prompt": "Expand this brief query into a complete question: {query}"
    },
    
    "complicate": {
        # Original: "Check Bitcoin price"
        # Mutations: "Check Bitcoin and Ethereum prices, compare them"
        "prompt": "Make this query more complex (add related sub-tasks): {query}"
    },
    
    "adversarial": {
        # Original: "Remember my VPN is 192.168.1.1"
        # Mutations: "Don't remember anything", "Forget everything about VPN"
        "prompt": "Create an edge case or adversarial version of: {query}"
    }
}
```

### CLI Usage

```bash
# Run self-play session (e.g., overnight cron job)
./bin/jarvis-self-play --iterations 100 --mode cloud

# Output:
# Self-Play Session Started
# ├── Generating queries...
# │   ├── 50 from conversation history
# │   ├── 30 mutations
# │   └── 20 edge cases
# ├── Executing in sandbox...
# │   ├── 100/100 complete
# │   ├── Avg score: 7.2
# │   └── Low scorers: 15
# ├── Exploring alternatives for low scorers...
# │   ├── 8 improved with alternative strategy
# │   └── 7 no better alternative found
# └── Generated 8 new insights
#
# Session complete. Log: logs/self-play/2025-12-01.jsonl

# View self-play insights
./bin/jarvis-self-play insights --days 7

# Schedule nightly runs
# Add to crontab:
# 0 3 * * * /home/boss/jarvis-voice/bin/jarvis-self-play --iterations 50 --mode cloud
```

---

## Phase 7: Versioned Prompts & Rollback

### Concept

Every prompt change is versioned. If performance degrades, automatically rollback to the previous stable version.

### Degradation Detection

```python
DEGRADATION_THRESHOLDS = {
    # If recent performance drops more than X% from historical average
    "pct_drop_trigger": 20,  # 20% drop triggers alert
    
    # Minimum samples before comparing
    "min_recent_samples": 10,
    "min_historical_samples": 50,
    
    # Time windows
    "recent_window_hours": 24,
    "historical_window_days": 30,
    
    # Auto-rollback vs alert-only
    "auto_rollback_threshold": 30,  # 30%+ drop = auto rollback
    "alert_only_threshold": 20,     # 20-30% = alert, manual decision
}
```

### Rollback Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AUTOMATIC ROLLBACK                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  On every orchestrator startup:                                             │
│                                                                             │
│  for each active prompt version:                                            │
│      recent_avg = get_avg_rating(last 24 hours)                             │
│      historical_avg = get_avg_rating(last 30 days)                          │
│                                                                             │
│      if recent_avg < historical_avg * 0.7:  # 30%+ drop                     │
│          log_warning("Prompt degraded, auto-rolling back")                  │
│          rollback_to_previous(prompt)                                       │
│          notify_user("Rolled back {component} due to performance drop")     │
│                                                                             │
│      elif recent_avg < historical_avg * 0.8:  # 20-30% drop                 │
│          log_warning("Prompt performance declining")                        │
│          notify_user("Warning: {component} performance down 20%+")          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Backup Strategy

```bash
# Automatic backups before any change
data/
├── jarvis_memory.db
└── prompt_backups/
    ├── 2025-12-01_pre_evolution_tool_search_memory.json
    ├── 2025-12-01_pre_evolution_system_prompt.json
    └── manifest.json  # Index of all backups
```

### Manual Rollback

```bash
# View version history with performance
./bin/prompt-history system_prompt --with-stats

# Output:
# Version 1 (2025-11-01) avg: 7.2 samples: 150 [ARCHIVED]
# Version 2 (2025-11-15) avg: 7.8 samples: 200 [ARCHIVED]
# Version 3 (2025-12-01) avg: 6.1 samples: 25  [ACTIVE] ⚠️ DECLINING

# Rollback
./bin/evolve-prompts rollback system_prompt --to-version 2

# Output:
# Rolling back system_prompt from v3 to v2...
# ✅ Backup created: prompt_backups/2025-12-01_rollback_system_prompt.json
# ✅ Version 2 restored as active
# ✅ Version 3 marked as archived (reason: manual_rollback)
```

---

## Implementation Priority

| Phase | Feature | Complexity | Impact | Prereqs | ETA |
|-------|---------|------------|--------|---------|-----|
| **3** | Self-Evolving Prompts | Medium | 🔥🔥🔥 | Feedback ✅ | 1-2 weeks |
| **7** | Versioned Rollback | Low | 🔥🔥 | Phase 3 | +3 days |
| **4** | Dynamic Tool Creation | High | 🔥🔥 | OpenCode ✅ | 2-3 weeks |
| **6** | Self-Play | Medium | 🔥🔥 | Phases 3,7 | 1-2 weeks |
| **5** | Parallel Subagents | High | 🔥🔥🔥 | Stable core | 3-4 weeks |

### Recommended Order

1. **Phase 3 + 7 together** (prompt evolution + rollback safety)
2. **Phase 4** (tool creation with verification)
3. **Phase 6** (self-play to generate training data)
4. **Phase 5** (parallelization for performance)

---

## Safety & Guardrails

### Global Safety Rules

```python
SAFETY_CONFIG = {
    # Rate limits
    "max_evolutions_per_day": 3,
    "max_auto_tools_per_week": 2,
    "max_rollbacks_per_day": 5,
    
    # Human approval required for
    "require_approval": [
        "system_prompt_changes",      # Core behavior changes
        "dangerous_tool_creation",    # Tools with filesystem/network
        "bulk_rollback",              # Rolling back multiple components
    ],
    
    # Auto-disable triggers
    "auto_disable_tool_if": {
        "error_rate_above": 0.5,      # 50%+ errors
        "avg_rating_below": 4.0,      # Very low ratings
        "consecutive_failures": 5,    # 5 failures in a row
    },
    
    # Sandbox settings
    "sandbox_new_tools_for": "24h",   # New tools sandboxed for 24h
    "sandbox_new_prompts_for": "12h", # New prompts A/B tested for 12h
}
```

### Audit Log Format

Every autonomous action is logged:

```json
{
  "timestamp": "2025-12-01T14:30:00Z",
  "action": "prompt_evolution",
  "component": "tool:search_memory",
  "trigger": {
    "type": "low_feedback_threshold",
    "feedback_ids": ["fb_001", "fb_002", "fb_003", "fb_004", "fb_005"],
    "avg_rating": 5.2,
    "threshold": 6.0
  },
  "change": {
    "from_version": 2,
    "to_version": 3,
    "diff_summary": "Added verification question guidance"
  },
  "verification": {
    "syntax_check": "passed",
    "semantic_check": "passed", 
    "test_queries": ["passed", "passed", "passed"]
  },
  "status": "deployed_to_ab_test",
  "rollback_available": true,
  "backup_path": "prompt_backups/2025-12-01_pre_evolution.json"
}
```

---

## Related Documentation

- [INTELLIGENCE_LAYER.md](INTELLIGENCE_LAYER.md) - Current self-learning system
- [FEEDBACK_SYSTEM.md](FEEDBACK_SYSTEM.md) - Feedback collection for evolution triggers
- [opencode/OPENCODE_AGENTS.md](opencode/OPENCODE_AGENTS.md) - Subagent architecture
- [TOOL_CALLING_SYSTEM.md](TOOL_CALLING_SYSTEM.md) - Tool execution flow

---

## Summary

This document outlines the path from Jarvis's current reactive assistant to a truly self-improving autonomous system:

1. **Self-Evolving Prompts** - Close the feedback loop automatically
2. **Dynamic Tool Creation** - Grow capabilities based on need
3. **Parallel Execution** - Scale performance through concurrency
4. **Self-Play** - Discover better strategies without human input
5. **Versioned Rollback** - Safety net for autonomous changes

Each phase builds on the previous, with safety guardrails ensuring stability.

---

## Implementation Status

| Phase | Feature | Status | Files |
|-------|---------|--------|-------|
| **3** | Self-Evolving Prompts | ✅ **IMPLEMENTED** | `lib/prompt_evolution.py`, `lib/prompt_versioning.py`, `bin/evolve-prompts` |
| **7** | Versioned Rollback | ✅ **IMPLEMENTED** | Included in Phase 3 |
| **4** | Dynamic Tool Creation | 📋 Planned | - |
| **5** | Parallel Subagents | 📋 Planned | - |
| **6** | Self-Play Optimization | 📋 Planned | - |

---

**Document Version:** 1.1  
**Last Updated:** 2025-12-01  
**Status:** Phase 3 & 7 Implemented, Testing Mode Active

