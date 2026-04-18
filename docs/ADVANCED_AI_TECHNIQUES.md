# Advanced AI Techniques for Jarvis

> **Purpose**: This document outlines advanced self-learning, autonomous, and multi-agent techniques planned for Jarvis. Each technique includes implementation details, safety mechanisms, and integration points.

---

## 📋 Table of Contents

1. [Overview & Philosophy](#overview--philosophy)
2. [Design Note: Runtime-Aware Context Gating](#design-note-runtime-aware-context-gating)
3. [Design Note: Presentation Artifact Learning](#design-note-presentation-artifact-learning)
4. [Phase 3: Self-Evolving Prompts](#phase-3-self-evolving-prompts)
5. [Phase 4: Dynamic Tool Creation](#phase-4-dynamic-tool-creation)
6. [Phase 5: Parallel Subagents](#phase-5-parallel-subagents)
7. [Phase 6: Self-Play Optimization](#phase-6-self-play-optimization)
8. [Phase 7: Versioned Prompts & Rollback](#phase-7-versioned-prompts--rollback)
9. [Implementation Priority](#implementation-priority)
10. [Safety & Guardrails](#safety--guardrails)
11. [Implementation Status](#implementation-status)
12. [🚨 Reality Check: Why Nothing Evolves](#-reality-check-why-nothing-evolves-feb-2026)
13. [Phase 8: Swarm Mode](#phase-8-swarm-mode-research-parallelism)
14. [Phase 9: Autonomous Maintenance Agent](#phase-9-autonomous-maintenance-agent)
15. [Phase 10: Proactive Briefing Agent](#phase-10-proactive-briefing-agent)

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

## Design Note: Runtime-Aware Context Gating

### Problem

Jarvis now has multiple ways to remove a tool from the current runtime:

- `enabled: false` in a `skills/*.tool.json` file
- active tool profiles such as `skills/profiles/offline.json`
- per-mode sync state after `./bin/sync_tools.py <mode>`
- Web UI or request-level excluded tools

Learned insight injection already receives the current `available_tools` list, so positive strategies that recommend unavailable tools can be filtered. Auto-memory injection is different: it retrieves factual memories and intel notes before the LLM sees the request. Some of those memories may mention unavailable tools even when they are not tool recommendations.

Example:

- `samantha` tool is disabled.
- A user says they are working on Jarvis.
- Auto-memory finds `intel/samantha.md` or old Samantha integration notes because the text is semantically related and intel sources get a boost.
- The memory is true, but it can still make the assistant act like Samantha is currently operational.

The important distinction:

```text
memory truth != runtime capability
```

### Why Not Toggle Memories On/Off?

Do not globally mark memories as disabled just because a tool is disabled.

Reasons:

- The memory may still be historically useful.
- A disabled tool can be the subject of conversation, debugging, or migration work.
- Tool profiles are runtime overlays; memories are durable facts.
- A future profile may re-enable the tool, and bulk mutating memory state would create cleanup problems.
- Intel files can contain mixed content: some lines are operational instructions, others are architecture notes, history, or warnings.

Better model:

```text
keep memories factual
gate whether they become prompt context for this turn
```

### Candidate Classification

Auto-memory should eventually classify each candidate memory into one of these buckets before injection:

| Bucket | Meaning | Default Behavior |
|--------|---------|------------------|
| `pinned_preference` | Addressing, tone, language, stable user preference | Always allow unless explicitly forgotten |
| `general_fact` | Personal/project/history fact not requiring a tool | Allow when relevant |
| `about_disabled_tool` | Mentions a disabled tool but is historical or explanatory | Demote or annotate; allow for explicit tool-history/debug queries |
| `requires_disabled_tool` | Would cause the model to use, recommend, or assume a disabled tool works | Suppress unless user explicitly asks about that disabled tool |
| `disabled_tool_warning` | Explains why not to use a disabled/broken tool | Allow, and possibly boost |

This avoids a blunt text filter. A memory that says “Samantha integration existed” is not the same as “Use Samantha for this task.”

### Runtime Inputs

The auto-memory layer should receive:

- `available_tool_names`: already computed in `orchestrator_v2.process()`
- known tool names from `tool_definitions`
- active profile overrides from `tool_profiles`
- request-level excluded tools
- optional blocked tools from Web UI settings

Then it can compute:

```text
unavailable_tools = known_tools - available_tool_names
```

That set should inform ranking and injection, not mutate memory rows.

### Metadata-First Design

Long-term, memories and intel-derived rows should support lightweight metadata:

```json
{
  "related_tools": ["samantha"],
  "requires_enabled_tools": ["samantha"],
  "context_role": "history|instruction|warning|capability|preference",
  "runtime_scope": "always|when_tool_available|when_explicitly_asked"
}
```

Suggested meanings:

- `related_tools`: the memory talks about these tools, but may still be useful if they are disabled.
- `requires_enabled_tools`: suppress if any listed tool is unavailable unless the user explicitly asks about that tool.
- `context_role=warning`: safe to show even if the tool is disabled.
- `context_role=capability`: risky to show when the tool is disabled because it implies current ability.
- `runtime_scope=when_explicitly_asked`: show only when the user directly mentions the topic/tool.

### Conservative Text Fallback

Not all old memories have metadata. A fallback can still help, but should be conservative:

- Match exact known tool names only, not broad English words.
- Use source paths as hints, e.g. `intel/samantha.md`.
- Treat `source=intel/<tool>.md` as `about_disabled_tool`, not automatically `requires_disabled_tool`.
- Do not filter pinned preferences through tool matching.
- Prefer demotion/annotation over deletion.

Example rule:

```text
if candidate mentions disabled tool:
  if metadata.requires_enabled_tools intersects disabled tools:
    suppress unless explicit user mention
  elif source/path strongly tied to disabled tool:
    demote unless explicit user mention
  elif candidate is a warning/limitation:
    allow
```

### Explicit User Intent Exception

If the user explicitly asks about a disabled tool, related memories should be allowed because they are the topic:

- “Why is Samantha disabled?”
- “What did Samantha used to do?”
- “Help me migrate Samantha notes.”
- “What broke with the Samantha heartbeat?”

In that case, the prompt should annotate the memory block:

```text
Note: Some retrieved memories mention tools that are currently unavailable. Treat them as history or debugging context, not active capabilities.
```

For unrelated queries, those same memories should be suppressed or demoted so the model does not casually offer the disabled capability.

### Intel Boost Interaction

Intel rows currently get extra retrieval strength because curated project knowledge is often valuable. This is good, but a disabled tool should add a counterweight:

```text
final_score = semantic_score + intel_boost - disabled_tool_demotion
```

Suggested starting behavior:

- `requires_disabled_tool`: suppress
- `about_disabled_tool`: subtract 0.20 from rank
- `disabled_tool_warning`: no demotion, maybe small boost
- explicit user mention of tool: no demotion, add unavailable-tool annotation

This keeps `intel/samantha.md` from appearing in ordinary Jarvis-app chat while still allowing it in Samantha-specific troubleshooting.

### Prompt Annotation Option

A softer alternative is to keep the memory but label it:

```text
- Samantha integration note ... (related_tool=samantha, tool_status=disabled, use_as=historical_context)
```

This is safer than silent injection, but it still spends context tokens and relies on the model obeying the label. It is best for explicit disabled-tool discussions, not general chat.

### Proposed Config

```bash
# Profile-aware auto-memory filtering
AUTO_MEMORY_FILTER_DISABLED_TOOLS=true

# If true, suppress memories that appear to require disabled tools.
# If false, annotate/demote instead.
AUTO_MEMORY_DISABLED_TOOL_STRICT=true

# Optional: allow historical memories about disabled tools only when user names the tool.
AUTO_MEMORY_DISABLED_TOOL_REQUIRE_EXPLICIT=true
```

Start with one real flag (`AUTO_MEMORY_FILTER_DISABLED_TOOLS=true`) and keep the others as design options until behavior is proven.

### Implementation Sketch

1. Pass `available_tool_names` into `_get_relevant_memories(transcript, available_tools=None)`.
2. Build `unavailable_tools` from `tool_definitions`.
3. Add helper: `_classify_memory_runtime_fit(memory, unavailable_tools, transcript)`.
4. Apply classification after candidate retrieval but before final sort/top-N selection.
5. Record debug metadata when filtering happens:

```json
{
  "event": "auto_memory_filtered",
  "memory_key": "What Samantha Can Do note",
  "related_tool": "samantha",
  "classification": "about_disabled_tool",
  "action": "demoted",
  "active_profile": "offline"
}
```

### Open Questions

- Should `intel/<tool>.md` automatically imply `related_tools=[tool]`, or should ingestion write that metadata?
- Should old `user_conversation` memories be backfilled with `related_tools` when they mention exact tool names?
- Should disabled-tool memories be visible in the Intelligence UI with a small “runtime gated” hint?
- Should guard behavior differ for local/offline profiles versus a tool disabled directly in `.tool.json`?

### Recommendation

Implement a metadata-first, runtime-only filter. Do not edit memory enabled state when profiles change.

Initial practical behavior:

- Always allow pinned preferences.
- Suppress memories with `requires_enabled_tools` that are unavailable.
- Demote exact-name/source matches for disabled tools.
- Allow disabled-tool memories when the user explicitly asks about that tool.
- Annotate allowed disabled-tool memories as historical/debug context.

This closes the “disabled capability leaks into auto-memory context” gap without stripping useful project history.

---

## Design Note: Presentation Artifact Learning

### Problem

Jarvis often runs in `auto` or `casual` response style, where spoken/display output is intentionally short. That is correct for voice and quick UI interactions, but it can conflict with user requests that need a structured multi-item result.

Example:

```text
User: find golf driving ranges near me and provide locations and hours
```

A short spoken answer can summarize the top result, but the useful deliverable may be a complete table: name, address, hours, source URL, rating, notes, and missing fields. If the LLM only speaks a compressed answer, feedback may mark the turn as incomplete even when the first search tool was reasonable.

### Desired Learning Shape

Reflection should separate two kinds of correction:

| Correction Type | Example Lesson |
|-----------------|----------------|
| Evidence/tool correction | Do not state addresses or hours unless the tool result returned them or a follow-up source verified them. |
| Presentation/artifact correction | In short response styles, use a brief spoken summary plus an available artifact tool for the full structured details. |

The second lesson should only be learned when an artifact tool was actually available to the original LLM. Otherwise reflection will overgeneralize from tools it could not call.

### Artifact Tool Rule

When all of these are true:

- `response_style` is `auto` or `casual`
- the user asks for multiple items or multiple fields per item
- the result needs more detail than a voice-friendly answer can comfortably carry
- an artifact tool such as `canvas` or `stash` is in `available_tools`

then reflection may learn:

```text
Use the spoken response for a concise summary, and save the full structured result to canvas/stash.
```

It should not learn “always use canvas” for every local search. The better trigger is:

```text
short response style + multi-item/multi-field deliverable + artifact tool available
```

### Practical Notes

- Keep `canvas` and `stash` in `GHOST_TOOLS` when they are core runtime capabilities.
- Record `response_style`, `qa_word_limit`, and `multi_turn_word_limit` in experience context so reflection can distinguish short-answer constraints from poor answer quality.
- Reflection should still prefer verification first when fields are missing. Artifacts are for presentation/storage, not a substitute for evidence.
- If an artifact is created, feedback should not penalize short speech for omitting every detail; the user can review the saved page/file.

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

# --- Random Feedback (Passive Learning) ---
FEEDBACK_RANDOM_ENABLED=false    # Enable random feedback during normal queries
FEEDBACK_RANDOM_CHANCE=0.1       # Chance per query (0.1 = 10%)

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

### When Does Evolution Run?

**Current Behavior (Pull-Based)**

Evolution only runs during active Jarvis queries, not on a schedule:

```
User Query → Feedback Collection → (if threshold met) → Auto-Evolution
```

Key points:
- **Feedback only collected during queries** (with `--feedback` flag or `FEEDBACK_RANDOM_ENABLED`)
- **Auto-evolution runs once per day** (marker file prevents re-runs)
- **If Jarvis is idle for a week**, no evolution happens until next query

**Scheduled Evolution (Optional)**

For periodic evolution even when Jarvis is idle, add a cron job:

```bash
# Run evolution check daily at 2 AM
0 2 * * * cd ~/jarvis-voice && source ~/jarvis-venv/bin/activate && ./bin/evolve-prompts --mode cloud auto --deploy --activate >> /tmp/jarvis-evolution.log 2>&1

# Or weekly (every Sunday at 3 AM)
0 3 * * 0 cd ~/jarvis-voice && source ~/jarvis-venv/bin/activate && ./bin/evolve-prompts --mode cloud auto --deploy --activate
```

**Tip**: Scheduled evolution uses the same feedback window (`EVOLUTION_WINDOW_DAYS`), so it will process accumulated feedback from days you didn't use Jarvis.

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
**URL**: http://localhost:3000/d/jarvis-feedback-evolution

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
# Check what needs evolution (based on feedback)  evolve prompt created but no prompt history A/B feature yet as of 12/5/25
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

## Phase 4: Dynamic Tool Creation ✅ IMPLEMENTED

> **Status**: Fully implemented. See [TOOL_BUILDER.md](TOOL_BUILDER.md) for complete documentation.

### Concept

When feedback repeatedly suggests a missing capability, the in-house Tool Builder creates a new tool. Uses existing LLM providers (no external dependencies) with safety checks and full traceability.

### Key Safeguards

1. **Consistent Gap Detection**: Requires 2+ feedback mentions of the same capability gap
2. **In-House LLM Builder**: Uses existing providers (xAI, Anthropic, OpenAI, Ollama) - no OpenCode dependency
3. **Separate Storage**: `skills/auto-tools/` directory (auto-discovered by sync_tools.py)
4. **Report Cards**: Full traceability with `tool_name.report.json` linking to feedback IDs
5. **Verification Pipeline**: Syntax check + import check + runtime test with sample input
6. **Dependency Gating**: New packages → `skills/pending/` for human approval
7. **Duplicate Detection**: Checks ALL existing tools (local + MCP + auto-tools) - not just MCP
8. **API Key Awareness**: Flags tools needing new credentials with suggested env var name

### Ouroboros Research Pattern 🐍

The Tool Builder can call Jarvis itself to research APIs and documentation before building:

```
Tool Builder needs API info
        ↓
Calls Jarvis Orchestrator (JARVIS_TOOL_BUILDER_CONTEXT=true)
        ↓
Jarvis uses its tools (Brave search, fetch, memory)
        ↓
Returns research to Tool Builder
        ↓
Better, more accurate tool created!
```

**Loop Prevention**: Environment variable `JARVIS_TOOL_BUILDER_CONTEXT=true` prevents recursive building.

**Auto-Triggers**: Research is automatic when gap description contains API-related keywords (weather, stock, api, oauth, etc.)
8. **Local Mode Compatible**: Works with Ollama for fully offline operation

### Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      DYNAMIC TOOL CREATION PIPELINE                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Feedback identifies gap                                                    │
│  "No tool for X" / "Had to use workaround"                                 │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────┐                                                  │
│  │  Tool Builder LLM    │  Uses TOOL_BUILDER_PROVIDER/MODEL                │
│  │  Generates:          │  Falls back to FEEDBACK_PROVIDER                 │
│  │  - tool_name.py      │  Falls back to LLM_PROVIDER                      │
│  │  - tool_name.json    │                                                  │
│  └──────────┬───────────┘                                                  │
│             │                                                               │
│             ▼                                                               │
│  ┌──────────────────────┐                                                  │
│  │  Dependency Check    │ New packages → skills/pending/ (human review)    │
│  └──────────┬───────────┘                                                  │
│             │                                                               │
│             ▼                                                               │
│  ┌──────────────────────┐                                                  │
│  │  Verification        │ Syntax + imports + runtime test                  │
│  │  (3 retries on fail) │                                                  │
│  └──────────┬───────────┘                                                  │
│             │                                                               │
│             ▼                                                               │
│  ┌──────────────────────┐                                                  │
│  │  Deploy              │ skills/auto-tools/ + sync_tools.py               │
│  │  + Report Card       │ tool_name.report.json (traceability)             │
│  └──────────────────────┘                                                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
skills/
├── *.py                      # Human-created tools
├── *.tool.json              
├── auto-tools/               # Auto-generated tools
│   ├── text_case_converter.py
│   ├── text_case_converter.tool.json
│   └── text_case_converter.report.json  # Traceability
└── pending/                  # Tools needing human approval
    └── (tools requiring new packages)

logs/tool-builder/
└── tool-builder-YYYY-MM-DD.jsonl  # Creation logs for Grafana
```

### CLI Commands

```bash
# Build a tool manually
./bin/build-tool --mode cloud build "Convert between units"

# List pending tools (need package approval)
./bin/build-tool list-pending

# Approve pending tool
./bin/build-tool approve my_tool --install

# View tool report card
./bin/build-tool info my_tool

# List auto-generated tools
./bin/build-tool list-auto

# Sync after creation
./bin/sync_tools.py cloud
```

### Integration with Evolution

Tool creation is automatically triggered during `./bin/evolve-prompts --mode cloud auto --deploy`:

1. Evolution Step 5 detects capability gaps from feedback
2. If gap mentioned 2+ times → auto-build tool
3. Tool verified and deployed to `skills/auto-tools/`
4. Sync runs automatically

### Configuration

```bash
# config/cloud.env

# Optional dedicated provider (falls back to FEEDBACK_PROVIDER → LLM_PROVIDER)
TOOL_BUILDER_PROVIDER=anthropic
TOOL_BUILDER_MODEL=claude-sonnet-4-5-20250929

# Minimum gap mentions to trigger auto-build
EVOLUTION_MIN_GAP_COUNT=2
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
# │   ├── 50 from conversation history  ( not good if recending emails and alerts and remindered need to modify this )
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
# 0 3 * * * ~/jarvis-voice/bin/jarvis-self-play --iterations 50 --mode cloud
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
| **3** | Self-Evolving Prompts | ✅ Built, ⚠️ Not Triggering | `lib/prompt_evolution.py`, `lib/prompt_versioning.py`, `bin/evolve-prompts` |
| **7** | Versioned Rollback | ✅ Built, Untested | Included in Phase 3 |
| **4** | Dynamic Tool Creation | ✅ **IMPLEMENTED** | `lib/tool_builder.py`, `bin/build-tool`, Ouroboros research 🐍 |
| **5** | Parallel Subagents | 📋 Planned | See Phase 8 below |
| **6** | Self-Play Optimization | 📋 Planned | - |
| **8** | Swarm Mode | 📋 Brainstorming | `docs/swarm/BRAINSTORM.md` |
| **9** | Autonomous Maintenance | 📋 Brainstorming | See below |
| **10** | Proactive Briefing Agent | 📋 Brainstorming | See below |

---

## 🚨 Reality Check: Why Nothing Evolves (Feb 2026)

**The Problem:** Evolution infrastructure exists but hasn't triggered in 2+ months.

### Root Causes

| Issue | Why It Matters |
|-------|----------------|
| **Feedback rarely collected** | `--feedback` flag required, `FEEDBACK_RANDOM_ENABLED=false` by default |
| **Thresholds too conservative** | Need 5+ low ratings (prod), 2+ (test) - but feedback is rare |
| **No scheduled checks** | Evolution only runs during active queries |
| **Cron not configured** | No nightly `evolve-prompts` job running |
| **Self-play not built** | Would generate synthetic feedback, but doesn't exist yet |

### Quick Fix Checklist

```bash
# 1. Enable random feedback collection (15% of queries)
# In config/cloud.env:
FEEDBACK_RANDOM_ENABLED=true
FEEDBACK_RANDOM_CHANCE=0.15

# 2. Lower thresholds for testing
EVOLUTION_MIN_LOW_RATINGS=2
EVOLUTION_LOW_THRESHOLD=7
EVOLUTION_WINDOW_DAYS=14

# 3. Add cron job for scheduled evolution
crontab -e
# Add:
0 3 * * * cd ~/jarvis-voice && source ~/jarvis-venv/bin/activate && ./bin/evolve-prompts --mode cloud auto --deploy --activate >> /tmp/jarvis-evolution.log 2>&1

# 4. Check current feedback state
sqlite3 data/jarvis_memory.db "SELECT COUNT(*) FROM feedback WHERE rating < 6"
./bin/evolve-prompts check cloud
```

### The Deeper Problem: Reactive vs Autonomous

All current systems are **reactive** (require user initiation):

```
Current Architecture:
┌─────────────────────────────────────────────────┐
│  User Query → Jarvis Processes → User Response  │
│                    │                            │
│              (optional feedback)                │
│                    │                            │
│        (optional evolution if thresholds met)   │
└─────────────────────────────────────────────────┘

What's Missing:
┌─────────────────────────────────────────────────┐
│           Autonomous Background Loop            │
│                                                 │
│  ┌─────────┐   ┌─────────┐   ┌─────────────┐   │
│  │ Observe │ → │ Decide  │ → │ Act/Report  │   │
│  └─────────┘   └─────────┘   └─────────────┘   │
│       ↑                             │          │
│       └─────────────────────────────┘          │
│                                                 │
│  Runs: Cron / Event-triggered / Always-on      │
└─────────────────────────────────────────────────┘
```

---

## Phase 8: Swarm Mode (Research Parallelism)

> **Status:** Brainstorming  
> **Full Design:** [docs/swarm/BRAINSTORM.md](swarm/BRAINSTORM.md)

### Concept

For research-heavy queries, spawn multiple specialized subagents in parallel, then synthesize results.

```
Query: "Compare React, Vue, and Svelte for a new project"

        ┌───────────────────────────────────┐
        │         Swarm Orchestrator        │
        └───────────────────────────────────┘
                        │
         ┌──────────────┼──────────────┐
         ▼              ▼              ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐
    │ Agent 1 │   │ Agent 2 │   │ Agent 3 │
    │ React   │   │   Vue   │   │ Svelte  │
    │ research│   │ research│   │ research│
    └────┬────┘   └────┬────┘   └────┬────┘
         │              │              │
         └──────────────┼──────────────┘
                        ▼
               ┌──────────────┐
               │  Swarm Boss  │
               │  (Synthesis) │
               └──────────────┘
                        │
                        ▼
               Canvas Report + Speech Summary
```

### When Swarm Makes Sense

| Good for Swarm | Better as Workflow/Sequential |
|----------------|-------------------------------|
| Multi-topic research | Single API calls (weather, time) |
| Compare N items | Simple CRUD operations |
| Fact verification (consensus) | Memory operations |
| Security analysis (red team) | Deterministic multi-step tasks |
| Creative brainstorming | Cost-sensitive queries |

### Key Design Elements

1. **Subagent Profiles** (`config.json` + `SKILL.md`)
   - Static config: model, tools, limits, timeout
   - Dynamic guidance: generated from query or pre-written

2. **Quantity Parameter**: `qty: 2` spawns 2 identical agents for diversity

3. **Model Diversity**: Different agents can use different LLMs
   - Grok for speed, Gemini for multimodal, Claude for reasoning

4. **Swarm Boss**: Smarter model synthesizes all results

5. **MCP Considerations**: Single server handles concurrent requests

### Cost/Benefit Reality Check

| Metric | Sequential | Swarm (3 agents) |
|--------|-----------|------------------|
| Latency | ~45s | ~18s (parallel) |
| Tokens | ~10k | ~35k (3x research + synthesis) |
| Cost | $0.10 | $0.40 |
| Quality | Single perspective | Multiple perspectives |

**Verdict:** Swarm is for quality-critical research, not everyday queries.

---

## Phase 9: Autonomous Maintenance Agent

### Concept

An always-on (or cron-scheduled) agent that monitors system health and takes action without user prompting.

### What Autonomous Jarvis Should Do

| Task | Current State | Autonomous State |
|------|--------------|------------------|
| Memory cleanup | Manual or never | "500 memories, cleaned 200 stale" |
| Tool health | User notices failures | "brave_search failed 10x, switching to fallback" |
| Feedback analysis | `evolve-prompts check` | Auto-analyzes patterns, proposes fixes |
| Proactive briefing | Hardcoded workflow | LLM decides what's worth mentioning |
| Cost monitoring | Manual check | "Token usage 3x normal, investigating" |
| Error patterns | Read logs manually | "Detected recurring timeout in X, added retry" |

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    AUTONOMOUS MAINTENANCE LOOP                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Trigger: Cron (every 6h) OR Event (error spike) OR Manual      │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                     OBSERVE PHASE                        │    │
│  │                                                          │    │
│  │  - Memory DB stats (count, age distribution, duplicates) │    │
│  │  - Error logs (last 24h, patterns, frequencies)          │    │
│  │  - Feedback ratings (trends, low performers)             │    │
│  │  - Tool usage (success rates, latencies)                 │    │
│  │  - Token costs (daily, by tool, anomalies)               │    │
│  │                                                          │    │
│  └──────────────────────────┬──────────────────────────────┘    │
│                             │                                    │
│                             ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                     DECIDE PHASE                         │    │
│  │                                                          │    │
│  │  LLM analyzes observations:                              │    │
│  │  - What needs attention?                                 │    │
│  │  - Priority ranking                                      │    │
│  │  - Safe to auto-fix vs needs human approval?             │    │
│  │                                                          │    │
│  └──────────────────────────┬──────────────────────────────┘    │
│                             │                                    │
│                             ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                      ACT PHASE                           │    │
│  │                                                          │    │
│  │  Auto-actions (safe):                                    │    │
│  │  - Archive old memories (>90 days, low relevance)        │    │
│  │  - Retry failed tool sync                                │    │
│  │  - Clear stale cache entries                             │    │
│  │                                                          │    │
│  │  Require approval:                                       │    │
│  │  - Delete memories                                       │    │
│  │  - Disable tools                                         │    │
│  │  - Modify prompts                                        │    │
│  │                                                          │    │
│  └──────────────────────────┬──────────────────────────────┘    │
│                             │                                    │
│                             ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    REPORT PHASE                          │    │
│  │                                                          │    │
│  │  - Log all observations and actions                      │    │
│  │  - Generate summary for user (if significant)            │    │
│  │  - Queue notifications for morning briefing              │    │
│  │                                                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Maintenance Checks (Concrete)

```python
MAINTENANCE_CHECKS = [
    {
        "name": "memory_health",
        "query": """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN created_at < date('now', '-90 days') THEN 1 ELSE 0 END) as stale,
                SUM(CASE WHEN importance < 3 THEN 1 ELSE 0 END) as low_importance
            FROM memory_entries
        """,
        "action_threshold": {"stale": 100, "low_importance": 200},
        "auto_action": "archive_stale_memories",
        "approval_required": False
    },
    {
        "name": "tool_health",
        "source": "logs/api/errors-*.jsonl",
        "pattern": "Count errors per tool in last 24h",
        "action_threshold": {"error_count": 10, "error_rate": 0.3},
        "auto_action": "alert_and_suggest_fallback",
        "approval_required": True  # Don't auto-disable tools
    },
    {
        "name": "feedback_patterns",
        "query": "SELECT component, AVG(rating) FROM feedback GROUP BY component",
        "action_threshold": {"avg_rating": 5.0},
        "auto_action": "trigger_evolution_check",
        "approval_required": False
    },
    {
        "name": "cost_anomaly",
        "source": "logs/api/access-*.jsonl",
        "pattern": "Compare today's tokens vs 7-day average",
        "action_threshold": {"pct_increase": 200},  # 2x normal
        "auto_action": "alert_user",
        "approval_required": True
    }
]
```

### CLI / Cron

```bash
# Manual run (dry mode)
./bin/jarvis-maintenance --mode cloud --dry-run

# Output:
# 🔍 Observing system state...
# ├── Memory: 523 total, 89 stale (>90d), 145 low importance
# ├── Errors (24h): brave_search: 3, fetch: 1
# ├── Feedback: 12 entries, avg 6.8, lowest: tool:search_memory (5.2)
# └── Tokens (24h): 45,231 (normal range)
#
# 🧠 Analysis:
# ├── Memory cleanup recommended: 89 stale entries
# ├── No tool health issues
# └── search_memory flagged for evolution check
#
# 📋 Proposed Actions (dry run):
# 1. [AUTO] Archive 89 stale memories
# 2. [AUTO] Trigger evolution check for search_memory
#
# Run with --execute to perform actions

# Cron (every 6 hours)
0 */6 * * * cd ~/jarvis-voice && ./bin/jarvis-maintenance --mode cloud --execute >> logs/maintenance.log 2>&1
```

---

## Phase 10: Proactive Briefing Agent

### Concept

Instead of hardcoded "good morning" workflows, an LLM-driven agent that **decides** what's worth telling you.

### Current State (Workflow)

```json
{
  "steps": [
    {"tool": "get_weather"},
    {"tool": "list_calendar_events"},
    {"tool": "check_stock_prices"}
  ]
}
```

**Problem:** Same output every day, even if nothing changed or nothing is relevant.

### Proactive State (Agent)

```python
BRIEFING_PROMPT = """
You are preparing a morning briefing.

Available sources: Weather, Calendar, Email, Stocks, News, Jarvis logs

Your job:
1. Check each source ONLY if likely relevant
2. Skip sources with no significant info
3. Prioritize: urgent > time-sensitive > informational
4. Keep total briefing under 60 seconds spoken

Output what the user NEEDS to know, not everything you CAN fetch.
"""
```

### Example Output Comparison

| Workflow (Current) | Agent (Proactive) |
|--------------------|-------------------|
| "Weather: 65°F. Calendar: No events. Stocks: AAPL +0.1%" | "Rain this afternoon, grab an umbrella. Your 3pm with Sarah moved. Bitcoin hit $50k." |

---

## Open Questions

### Architecture
- **Persistent daemon vs cron?** Daemon enables real-time reactions but adds complexity
- **Notification channel?** Discord, email, voice, or just logs?
- **Token budget for autonomous actions?** Cap daily spend?

### For Swarm
- Start with 2-agent research prototype?
- How to handle MCP rate limits across parallel agents?

### For Maintenance
- How aggressive should auto-cleanup be?
- Archive vs delete for old memories?

### For Proactive Briefings
- Learn user preferences? (skip stocks if never asked)
- Interrupt threshold? (only notify if importance > X)

---

## References

- [LLM Council](https://github.com/karpathy/llm-council) - Multi-LLM consensus (Karpathy)
- [OpenAI Swarm](https://github.com/openai/swarm) - Lightweight multi-agent
- [CrewAI](https://github.com/joaomdmoura/crewAI) - Role-based agents
- [AutoGen](https://github.com/microsoft/autogen) - Microsoft multi-agent
- [Swarm Brainstorm](swarm/BRAINSTORM.md) - Jarvis-specific design

---

**Document Version:** 2.0  
**Last Updated:** 2026-02-02  
**Status:** Phases 3, 4, 7 built but underutilized. Phases 8-10 brainstorming.
