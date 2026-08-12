# Jarvis Intelligence Layer

**Status**: Active / Phase 1.5 Complete + 2026 operational bridges
**Created**: 2025-11-27
**Updated**: 2026-08-11 (request-scoped insight applicability and Chat-only reflection)
**Location**: `lib/intelligence.py`, `lib/intelligence_hooks.py`, `jarvis-intelligence/` (dashboard)

## Overview

The Intelligence Layer is Jarvis's self-learning system. It observes interactions, reflects on what worked and what didn't, and applies learned insights to improve future routing decisions.

![Intelligence Layer Info Graph](images/intelligence-info-graph.jpeg)

**Key Principles**:
- Everything is continuous (vectors), not discrete rules
- Learning generalizes through semantic similarity
- **Phase 1**: Positive AND negative constraints (what to do AND what NOT to do)
- Negative constraints with structured triggers apply only when the current user request contains one of those trigger signals
- **Phase 1**: Fact vs Procedural classification (only skills stored, not facts)
- **Phase 1**: Generalizability filtering (low-value insights filtered out)

---

## Quick Start

### Default and Emergency Opt-Out

Intelligence is a core feature and is enabled by default. No cloud/local env
declaration is required. To disable it temporarily for testing or recovery:

```bash
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
- `last_outcome` - Most recent result (`success` / `failure` / `unused`) ✅ Updated automatically

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

### 8. Autonomous Workflow Attribution in Reflection (2026-07-23)

Autonomous workflow orchestration records a compact `workflow_execution` block
alongside the ordinary outer tool trace. It identifies:

- autonomous meta-tool versus explicit slash invocation
- discovery actions (`search`, `describe`) versus `run`
- selected workflow ID, name, purpose, triggers, and query inputs
- whether the run started, completed, failed, or was cancelled
- component tools and bounded step outcomes
- `component_order_owner=deterministic_workflow_recipe`

Reflection therefore grades the router's decision to select a particular
workflow separately from execution of the fixed recipe. Discovery calls are not
treated as retries, and component order is never copied into
`preferred_tool_sequence`.

A positive workflow insight is accepted only for a successful, completed,
non-cancelled run. It must explicitly prefer the `workflow` meta-tool and stores
the exact recipe in `preferred_workflow_id`. The old `final_tool` fallback is
disabled for workflow experiences, preventing a reflection that returns no
preference from silently becoming a generic `workflow` preference.

Workflow reflection is explicitly grounded in the recipe's underlying purpose
and outputs. Test wording and orchestration phrases such as “run the previously
successful procedure” must not become the trigger concept. For retrieval, a
positive workflow insight's `applies_to_pattern` and embedding are anchored to
the selected recipe metadata, so a `quick_note` lesson matches requests to save
a note to memory and Canvas rather than only prompts that mention workflows.
When a new reflection merges into the same exact `preferred_workflow_id`, these
semantic fields replace the legacy workflow wording; ordinary non-workflow
insight merges retain their existing blend-without-replace behavior.

Before injection, Jarvis verifies that the `workflow` meta-tool, the named
workflow, and every required component tool remain in the effective registry
for the current mode/profile/request surface. Explicit `required: false`
components may be unavailable and will be skipped and reported as degraded at
execution. The prompt presents the recipe as a candidate that must still be
confirmed through workflow discovery. If that specific workflow does not run
successfully, the insight is not counted as helpful merely because some other
workflow ran.

Reflections already queued before this field existed reconstruct the same
summary from their stored workflow result and tool trace when possible.

### 9. Presentation Artifact Learning (2026-04-18)

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

### 10. Provider-Native Tool Metadata in Reflection (2026-04-04)

When providers use native server-side tools such as xAI `x_search` / `web_search` or native code execution, the intelligence layer now treats that as **evidence metadata**, not as Jarvis routing behavior.

- Reflection can see provider-native tool usage so it does **not** misread an empty `tools_used` list as a zero-tool hallucination.
- Completion Guard also treats those native tools as real evidence during audits.
- These native provider tools are **not** converted into `preferred_tool` / `avoided_tool` insights, so Jarvis does not start preferring provider-specific internals over normal Jarvis tools.

### 11. Reflection Usage Tracking (2026-04-18)

Reflection LLM calls now preserve their own observability metadata on generated insights:

- `reflection_provider`
- `reflection_model`
- `reflection_input_tokens`
- `reflection_output_tokens`
- `reflection_total_tokens`
- `reflection_cost_usd`

The Intelligence UI shows a compact badge on insight cards, for example `35,303 tok $0.0071`, and the insight detail modal shows the input/output token split. Existing insights keep zero/blank values until they are created or updated by a new reflection run.

**Cumulative vs. latest semantics**: insights can be updated by many reflection runs over time, so the token and cost columns are *additive* — every new reflection that updates an insight adds its own tokens and cost onto the running totals. The `reflection_provider` and `reflection_model` columns, by contrast, are overwritten on each update and reflect only the most recent reflection run. The UI labels this explicitly as "Lifetime Reflection Cost / Tokens" and "Last Reflection Provider" so the card badge (`🧾 5,391 tok $0.0012`) is understood as a lifetime rollup, not the cost of the most recent run.

### 11. Insight Provenance and Soft Tool Sequences (2026-04-21)

Insights now keep an auditable link back to the experience that created them:

- `source_experience_id`
- `source_web_conversation_id`
- `source_query`
- `source_tool_sequence`
- `source_reflection_json`

Every create/update also writes an `insight_evidence` row. This gives the Intelligence UI an evidence trail so broad or stale lessons can be traced back to the originating interaction instead of hunting by timestamp.

Multi-tool lessons can store:

- `preferred_tool_sequence`
- `supporting_tools`
- `sequence_required`
- `trigger_signals`
- `primary_intent`

Important: `preferred_tool_sequence` is **advisory evidence**, not a hard workflow contract. Reflection should set `sequence_required=true` only when the exact order is essential for correctness. Non-required sequences are stored for audit/UI visibility but are not injected into the live routing prompt. Normal routing and Tool RAG remain free to choose a different combination when the user's current intent is different.

Similar insight text no longer merges automatically when the preferred/avoided tool association conflicts. The new reflection is stored as a separate insight so an old tool preference does not survive under a freshly reinforced but semantically different lesson.

### 12. Secret Redaction for Intelligence Records (2026-04-21)

Before interaction data is stored in the Intelligence DB or sent into reflection, Jarvis redacts credential-like material:

- API keys
- passwords
- bearer tokens
- cookies
- private keys
- JWTs
- credentialed URLs
- secret-looking key/value pairs such as `api_key=...` or `Authorization: Bearer ...`

Normal personal/contact data such as email addresses is not redacted by this layer because it can be legitimate task context. The Intelligence dashboard also redacts on read so older records are less likely to display credential material, but historical DB rows created before this redaction pass may still need a one-time scrub if they are known to contain secrets.

### 13. Intelligence Dashboard Pagination (2026-04-21)

The Intelligence Dashboard no longer loads large card lists eagerly on first paint.

- Experiences and Insights are fetched in 50-row pages.
- Infinite scroll loads the next page automatically when the user nears the bottom of the list.
- Sidebar counts, tool facets, Completion Guard facets, and confidence buckets come from lightweight summary endpoints instead of fetching hundreds or thousands of records.
- Sort and filter operations are applied server-side before pagination, so "Sort by tool count" or "Sort by confidence" means the full dataset, not only the cards currently in view.

This keeps the default Experiences tab responsive as the intelligence DB grows while preserving detail-modal behavior: raw experience data is still fetched only when opening a single record.

### 14. Request-Scoped Negative Insight Applicability (2026-08-11)

Semantic similarity discovers possible insights; it does not, by itself, prove
that a narrow prohibition applies to the current request. Before Intelligence
retrieval, Jarvis now derives the clean current user request and excludes
Jarvis-added tool-hint, learned-strategy, memory, and prior-result wrappers from
the embedding query. Those blocks remain available to the appropriate routing
layers and to the LLM; they are simply not mistaken for user-authored intent by
Intelligence retrieval.

Negative insights that contain `trigger_signals` receive an additional
applicability check after semantic retrieval and before prompt injection or tool
bias calculation:

1. Normalize the current request and stored triggers for case, apostrophes,
   punctuation, and word boundaries.
2. Require at least one complete stored trigger word or phrase to appear in the
   clean current request.
3. Skip the negative insight entirely when none match. It contributes neither
   an `AVOID` prompt instruction nor a negative tool bias.

For example, this valid lesson:

```text
Never re-call Brave for prior-citation questions when the user says not to search again.
trigger_signals = ["sources did that Brave call cite", "Don't search again", "that Brave call"]
```

still applies to `What sources did that Brave call cite? Don't search again`,
but it does not penalize `use brave to get the latest AI news`. Merely naming
the same tool is not enough to activate the narrow prohibition.

This safeguard is intentionally asymmetric:

- Positive insights retain semantic generalization.
- Negative insights with trigger metadata require an explicit trigger match
  because `INTELLIGENCE_NEGATIVE_WEIGHT` makes their consequences stronger.
- Legacy negative insights with no `trigger_signals` retain their established
  semantic-only behavior for backward compatibility.
- An explicit Web UI tool hint remains current-turn user intent and still
  outranks a learned negative preference for Tool RAG schema inclusion.

The matched phrases are retained as `matched_trigger_signals` in the applied
insight payload for provenance and debugging. This applicability guard is a
correctness rule, not another tuning parameter; it does not alter confidence,
learning rate, negative weight, or decay behavior.

### 15. Web Chat-Only Learning Semantics (2026-08-11)

Jarvis Web's sticky `#chat_only` mode preserves normal experience recording and
reflection while removing tool-routing pressure from that turn:

- Routing provenance stores `tool_policy=none` and `tool_rag_skipped=true`.
- Relevant auto-memory and recent conversation context remain available to the
  answer, but learned routing-insight injection is skipped before routing.
- Reflection receives the response style, word limits, user/guard evidence,
  auto-memory context, and explicit Chat-only provenance.
- Its dedicated rubric evaluates relevance, accuracy, completeness, clarity,
  tone, appropriate qualification, and correct use of already supplied context.
- Using zero tools is intentional—not missing telemetry, a routing failure, or
  evidence that Jarvis should have searched.
- Reflection must not create `preferred_tool`, `avoided_tool`,
  `preferred_workflow_id`, `preferred_tool_sequence`, or `supporting_tools`
  associations for the Chat-only experience. Storage also suppresses these
  associations as a final guard.
- If no independently reusable non-tool procedural lesson remains, reflection
  returns `is_procedural=false` and stores no routing insight.
- Completion Guard can still contribute accepted/repaired/unresolved evidence,
  but any repair inherits Chat only and remains QA-only.
- Passive thumbs reactions remain valid direct satisfaction evidence. LLM
  Feedback Analysis and random feedback sampling are skipped for the turn.

This keeps conversational quality learning without teaching the normal router
that deliberately unavailable tools were either missing or suboptimal. See
[Jarvis Web UI: `#chat_only`](./JARVIS_WEB_UI.md#chat_only-sticky-no-tools-chat).

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
   - `last_outcome` updated to `success` or `failure`

### 4. Maintenance Jobs

Three automated maintenance jobs keep the intelligence layer healthy:

#### Decay Job
```bash
# Config
INTELLIGENCE_DECAY_RATE=0.95           # 5% decay per week unused
INTELLIGENCE_DECAY_INTERVAL_DAYS=30    # Current cloud recommendation; code default: 7 if unset
```

**What it does**:
- Checks each insight's newest activity timestamp: `last_applied`, `updated_at`, latest `insight_evidence.created_at`, or `created_at`
- If unused >7 days: `confidence *= DECAY_RATE`
- If has failures: extra decay `confidence *= 0.9^consecutive_failures`
- If successful (>80% helpful): slight boost
- If confidence drops below 0.15: **auto-pruned**

**⚠️ IMPORTANT**: The decay job tracks when it was last run and **skips if run within the minimum interval** (current cloud recommendation: 30 days; code default if unset: 7). This prevents accidental double-decay from compounding confidence reductions. Use `--force` to bypass if needed.

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
│     ├─▶ [PYTHON] Extract clean current user request                              │
│     │      Excludes Jarvis-added hint/memory/intelligence wrappers               │
│     │                                                                           │
│     ├─▶ [EMBEDDING API] get_embedding(clean_request) ← OpenAI/Ollama call        │
│     │      Returns: 1536/768-dim vector                                         │
│     │                                                                           │
│     ├─▶ [PYTHON] Cosine similarity search in insights DB                        │
│     │      Finds: matching insights by pattern_embedding                        │
│     │                                                                           │
│     ├─▶ [PYTHON] Gate structured negative insights by trigger_signals            │
│     │      No trigger match → no prompt instruction and no negative bias         │
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

**Why separate?** Data mode owns the database and expected embedding space:
- Cloud default: OpenAI embeddings (1536 dimensions)
- Local default: Ollama/nomic embeddings (768 dimensions)

This is independent of chat-provider selection. Cloud mode can use Ollama Cloud
for chat while retaining the cloud Intelligence DB and OpenAI embeddings.

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
| Cloud (OpenAI/Anthropic/xAI/Ollama Cloud) | ✅ Yes | Uses cloud DB/embedding config |
| Local (normally local Ollama) | ✅ Yes | Uses local DB/embedding config |
| Switching modes | ✅ Yes | Separate databases |

### Tools & MCP Servers ✅

| Scenario | Effect | Notes |
|----------|--------|-------|
| Disable a tool | ✅ Works | Insights that require the missing tool are filtered before prompt injection |
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
BLOCKED_TOOLS="mcp_playwright_browser_navigate,mcp_playwright_browser_snapshot"
```

**Precedence** (highest to lowest):
1. `BLOCKED_TOOLS` in `.env` → Always skipped during sync
2. `enabled=false` in `.tool.json` → Skipped (local skills)
3. MCP discovered / `enabled=true` → Synced normally

After editing `BLOCKED_TOOLS`, run `./bin/sync-tools.py cloud` (or `local`).

#### Insight Filtering for Unavailable Tools

When insights are formatted for the LLM prompt, the orchestrator builds the **allowed tool set** as:

1. `ToolRegistry.list_tools()` from the active mode after manifest enablement,
   profile overrides, and config/credential availability
2. Minus **Web UI/request** blocked tools (`excluded_tools` from the request)

The registry is the capability authority. `tool_definitions` remains the
semantic ranking index; a stale enabled database row cannot make an insight
surface a tool absent from the live registry. This includes the mandatory
discovery helpers `tool_search` and `workflow`: when either helper is disabled
or request-blocked, insights cannot reintroduce it.

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
- **Trigger signals**: Exact words/phrases that activate a structured negative constraint
- **Preferred approach**: "Use fetch tools directly"
- **Confidence**: 0.0-1.0

### How Insights Apply
When a new query comes in:
1. Extract the clean current user request from any Jarvis-added wrappers
2. Generate the clean-request embedding
3. Find candidate insights with cosine similarity
4. Require a stored trigger match for negative insights that have `trigger_signals`
5. Weight applicable insights by confidence and relevance
6. Inject applicable insights and biases into routing context

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
├── cloud.env   # Optional Intelligence tuning and emergency opt-out
├── local.env   # Optional Intelligence tuning and emergency opt-out

logs/intelligence/
├── intelligence-YYYY-MM-DD.jsonl  # Daily intelligence logs

tests/
├── test_intelligence_maintenance.py
├── test_intelligence_provenance.py
├── test_intelligence_redaction.py
└── test_intelligence_server_side_tools.py
```

---

## Configuration

### Environment Variables

```bash
# Optional emergency opt-out (Intelligence defaults to enabled)
# JARVIS_INTELLIGENCE=false

# Learning parameters (advanced, optional)
INTELLIGENCE_LEARNING_RATE=0.1          # How fast to update confidence on new evidence
INTELLIGENCE_DECAY_RATE=0.95            # Decay multiplier per week unused (0.95 = 5% decay)
INTELLIGENCE_DECAY_INTERVAL_DAYS=30     # Current cloud recommendation; code default if unset: 7
INTELLIGENCE_ANOMALY_THRESHOLD=2.5      # Z-score threshold for outlier detection
INTELLIGENCE_MIN_CONFIDENCE=0.40        # Minimum confidence to become a retrieval candidate
INTELLIGENCE_NEGATIVE_WEIGHT=1.5        # Recommended; code default if unset: 1.0
```

### Parameter Tuning Guide

| Parameter | Low Value | High Value | Recommendation |
|-----------|-----------|------------|----------------|
| `LEARNING_RATE` | 0.05 (slow learning) | 0.3 (fast adaptation) | Start at 0.1 |
| `DECAY_RATE` | 0.8 (aggressive pruning) | 0.99 (persistent) | 0.95 is balanced |
| `ANOMALY_THRESHOLD` | 1.5 (flag more) | 3.5 (flag less) | 2.5 catches outliers |
| `MIN_CONFIDENCE` | 0.1 (use weak insights) | 0.5 (only strong) | 0.40 is the current recommendation |
| `NEGATIVE_WEIGHT` | 1.0 (equal to positive) | 2.0 (strong penalty) | 1.5 makes negatives win |

**NEGATIVE_WEIGHT explained**: When multiple insights conflict (e.g., 2 positive + 1 negative for same tool), this multiplier ensures negative constraints are respected. At 1.5, a single negative insight can outweigh multiple weak positives.

These values tune belief strength, candidate confidence, and maintenance timing;
they do not determine whether a narrow negative lesson applies to a particular
request. That decision is handled by the request-scoped `trigger_signals` gate.
If a valid negative insight is activating too broadly, inspect and correct its
triggers before raising `MIN_CONFIDENCE`, lowering `NEGATIVE_WEIGHT`, changing
decay, or deleting the insight.

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

### Reflection queue (operational detail)

Reflection is **queued, not automatic**. By default, every interaction writes an
experience and enqueues `reflection_queue` (`processed=0`). Nothing calls the
reflection LLM until you trigger it.

```
Every interaction:
  User query → route → tools → response
  → experiences row inserted
  → reflection_queue row (processed=0)

When triggered (manual, cron, or maintenance):
  trigger_reflection(batch_size=N)
  → fetch N pending rows
  → for each: separate LLM reflection call → insights table → processed=1
```

**Why on-demand:** each reflection is a paid LLM call (~2–5s each). Batching controls cost and load.

**Trigger options:**

```bash
# Python
python3 -c "from lib.intelligence_hooks import trigger_reflection; print(trigger_reflection(5))"

# Main API (port 8880)
curl -X POST "http://localhost:8880/api/intelligence/reflect?batch_size=5"

# Intelligence dashboard API (port 5003)
curl -X POST "http://localhost:5003/api/maintenance/reflect?batch_size=5"

# CLI maintenance
./bin/run-intelligence-maintenance.py --reflect
```

**Future automation options** (not implemented): after every N interactions, end-of-session batch, hourly cron, or background daemon. Phase 2 **reflection gate** would skip trivial queries before spending an LLM call — see [Future Enhancements](#future-enhancements).

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

# Preview decay changes without writing updates
./bin/run-intelligence-maintenance.py --decay --dry-run

# Specify mode
./bin/run-intelligence-maintenance.py --mode local --watch

# Force decay run (bypasses minimum interval check - use with caution!)
./bin/run-intelligence-maintenance.py --decay --force
```

**⚠️ Decay Job Interval Protection**: The decay job tracks when it was last run and will **skip** if run within `INTELLIGENCE_DECAY_INTERVAL_DAYS` (current cloud recommendation: 30 days; code default if unset: 7). This prevents accidental double-decay which compounds confidence reductions incorrectly. Use `--force` only if you understand the implications.

**API Endpoints**:
```bash
# Run all maintenance jobs
curl -X POST http://localhost:8880/api/intelligence/maintenance/all

# Individual jobs
curl -X POST http://localhost:8880/api/intelligence/maintenance/decay
curl -X POST http://localhost:8880/api/intelligence/maintenance/anomaly
curl -X POST http://localhost:8880/api/intelligence/maintenance/meta-cognition

# Preview decay without writing updates
curl -X POST 'http://localhost:8880/api/intelligence/maintenance/decay?dry_run=true'

# View meta-knowledge findings
curl http://localhost:8880/api/intelligence/meta-knowledge
```

### What Each Job Does

#### 1. Decay Job (`--decay`)
**Purpose**: Keep insight pool fresh by decaying unused/failed insights

**⚠️ Interval Protection**: The decay job tracks when it was last run in the `meta_knowledge` table. If run within `INTELLIGENCE_DECAY_INTERVAL_DAYS` (current cloud recommendation: 30 days; code default if unset: 7), it will **skip** with status `"skipped"`. Use `--force` to bypass.

**Why?** Running decay multiple times compounds the reduction incorrectly:
- First run: 1.0 → 0.95 (correct: 5% decay)
- Second run same day: 0.95 → 0.9025 (wrong: double decay!)

**Algorithm**:
```
1. Check if decay ran within minimum interval
   If yes: SKIP (unless --force)

2. For each insight:
   a. Calculate newest activity timestamp:
      max(last_applied, updated_at, latest evidence, created_at)

   b. If newest activity > 7 days ago:
      confidence *= DECAY_RATE  (default 0.95 = 5% decay)

   c. If consecutive_failures > 0:
      confidence *= 0.9 ^ consecutive_failures

   d. If helpful_ratio > 80%:
      confidence *= 1.02  (2% boost)

   e. If confidence < 0.15:
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
# Merge cloud → local (regenerates 768-dim embeddings)
./bin/sync-intelligence-db.py local

# Merge local → cloud (regenerates 1536-dim embeddings)
./bin/sync-intelligence-db.py cloud

# Replace target with a source mirror, discarding target-only rows
./bin/sync-intelligence-db.py --replace local

# Reset a database (with backup)
./bin/sync-intelligence-db.py --reset cloud

# Dry run (see what would happen)
./bin/sync-intelligence-db.py --dry-run local

# Reset (delete) a database
./bin/sync-intelligence-db.py --reset local
```

Default sync is additive: it copies missing source experiences, insights, insight evidence, and pending reflections while preserving target-only learning from the other mode. Use `--replace` only when you intentionally want those synchronized tables in the target Intelligence database to mirror the source.

Insight and evidence sync preserves `preferred_workflow_id`; the target-mode
runtime still revalidates that recipe against its own effective registry before
injecting the recommendation.

`meta_knowledge` is deliberately not synchronized. The cloud and local Intelligence databases each keep their own maintenance history and meta-cognition findings because these rows describe the state of that specific database, such as its last decay run, blind spots, and learning-quality findings. Keeping them separate prevents maintenance performed on one database from incorrectly changing the maintenance schedule or reported health of the other. Each database can derive fresh findings after portable learning data is synchronized.

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
# Check effective runtime status
./bin/check-intelligence-health.py cloud --json

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

### Unrelated Negative Insight or Tool Avoidance

Inspect the insight's applicability metadata before changing global tuning:

```bash
sqlite3 -readonly data/jarvis_intelligence.db "
SELECT id, description, applies_to_pattern, trigger_signals, primary_intent,
       avoided_tools, confidence
FROM insights
WHERE id = <INSIGHT_ID>;
"
```

- If `trigger_signals` contains the request's actual prohibition or boundary,
  keep the insight; unrelated requests will not activate it merely because they
  mention the same tool.
- If the triggers themselves are too broad, back up the active mode's database
  and update the JSON `trigger_signals` field directly. The current dashboard
  edit form does not expose this field. This metadata-only correction does not
  require re-embedding.
- If `trigger_signals` is empty, the row is a legacy insight and still uses
  semantic-only applicability. Add precise triggers when narrowing it, or
  remove the insight only when its underlying lesson is actually invalid.

Do not use confidence/decay tuning to compensate for one bad applicability
boundary; those settings affect every insight.

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
| `preferred_tool_sequence` | ❌ No | ✅ Yes | Advisory sequence shown for audit/context; not a hard route |
| `supporting_tools` | ❌ No | ✅ Yes | Secondary tools that helped in source evidence |
| `sequence_required` | ❌ No | ✅ Yes | Only true when the exact order is required |
| `primary_intent` | ❌ No | ✅ Yes | Compact intent label for audit/gating |
| `source_*` fields | ❌ No | ⚠️ Usually no | Provenance/audit trail from the originating experience |
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
- `preferred_tools`, `avoided_tools`, `confidence`, `reasoning`, `trigger_concept`, `trigger_signals`, `primary_intent`

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
| `/api/intelligence/maintenance/decay?dry_run=true` | POST | Preview decay job without writes |
| `/api/intelligence/maintenance/decay` | POST | Run decay job (`force=true` optional) |
| `/api/intelligence/maintenance/anomaly` | POST | Run anomaly detection |
| `/api/intelligence/maintenance/meta-cognition` | POST | Run meta-cognition |
| `/api/intelligence/maintenance/all` | POST | Run all maintenance jobs (`dry_run=true` previews decay and skips anomaly/meta writes) |
| `/api/intelligence/metrics` | GET | JSON metrics snapshot (`status`, `metrics`) |
| `/api/intelligence/reflections` | GET | Pending reflection queue |
| `/api/intelligence/reflections/{reflection_id}` | DELETE | Cancel a single pending reflection |
| `/api/intelligence/reflections` | DELETE | Clear the reflection queue |

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

### Grafana / Prometheus metrics

Intelligence metrics JSON is exposed at **`GET /api/intelligence/metrics`** (port 8880). For Prometheus text scraping, use **`GET /metrics`** instead. Example series from `/api/intelligence/metrics`:

```promql
jarvis_intelligence_experiences_total
jarvis_intelligence_insights_total{constraint_type="positive"}
jarvis_intelligence_pending_reflections
jarvis_intelligence_avg_confidence
jarvis_intelligence_helpful_ratio{mode="cloud"}
```

**Note:** There is **no** checked-in `monitoring/grafana/dashboards/jarvis-intelligence.json` today. Use the **Intelligence Dashboard** at port **5003** for interactive monitoring, or build a Grafana dashboard from the Prometheus metrics above.

### Intelligence Dashboard (primary UI)

See [jarvis-intelligence/README.md](../jarvis-intelligence/README.md). Key panels equivalent to the old Grafana plan:

**Stats row:** enabled flag, experience/insight counts, pending reflections, avg confidence, helpful ratio

**Constraint distribution:** positive vs negative insight counts (Insights tab filters)

**Growth over time:** experience and insight totals (Stats tab)

**Pending queue alert:** Reflection tab — investigate when pending > 10 (also surfaced in `/api/intelligence/health`)

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
docker compose restart promtail
```

Verify promtail sees the logs:
```bash
docker compose logs promtail | grep intelligence
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
  "model": "grok-4.3",
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

### 2. User preferences — partial support (2026)

**Implemented today:**

- **Profile Card** — `user_model` table + `lib/user_profile.py` injects stable prefs at routing time. See [USER_PROFILE_SYSTEM.md](USER_PROFILE_SYSTEM.md).
- **Intelligence insights** — learned `preferred_tool` / `avoided_tools` from reflection.
- **Manual overrides** — `jarvis-intel` files and ghost-tool config.
- **Correction learning** — `USER_CORRECTION_LEARNING_MODE=apply` downgrades bad prior experiences.

**Not yet implemented:**

- Dedicated config file for static tool bias (e.g. `ALWAYS_USE=crypto_price` without learning)
- UI panel for editing Profile Card fields (dashboard is read/edit for experiences/insights, not full profile CRUD)

### 3. Behavioral learning — partial

Intelligence **does** learn tool routing and negative constraints. It **does not yet** learn:

- Automatic memory-save triggers
- Response verbosity defaults
- Communication style (formal/casual) as first-class insights

Profile Card and feedback bridge cover some of this manually; Phase 3 below tracks automated behavioral learning.

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

**Why it happens**: The decay formula `confidence *= DECAY_RATE^(days/7)` is based on time since newest activity, not success rate. New reflection merges and evidence rows refresh activity, so a newly reinforced older insight should not decay just because its original `created_at` is old. The maintenance boost (1.02×) cannot outpace the decay (0.9025×) for insights that are both rarely used and not recently reinforced.

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

## Cross-turn correction learning (2026)

Detects when the user **corrects** Jarvis across turns (e.g. "no, use the other tool", "that's wrong") and links the correction to the prior experience.

```bash
USER_CORRECTION_LEARNING_MODE=shadow   # record candidates only (safe default)
USER_CORRECTION_LEARNING_MODE=apply    # downgrade linked experience + optional lesson append
```

| Mode | Behavior |
|------|----------|
| `shadow` | Logs correction candidates to intelligence logs; routing unchanged |
| `apply` | Marks linked prior experience outcome failed; may append deduped lessons to `jarvis-learned-lessons.md` |

**Code path:** `orchestrator_v2.py` post-response hook → `lib/intelligence_hooks.py` correction handlers.

**Related:** [USER_PROFILE_SYSTEM.md](USER_PROFILE_SYSTEM.md), [FUTURE_ENHANCEMENTS.md](FUTURE_ENHANCEMENTS.md) (Strategic Direction — cross-turn correction learning).

---

## Profile Card boundary (2026)

Stable user preferences are injected **before** intelligence insights via `lib/user_profile.py`:

- Source: memory DB `user_model` table (cloud/local DBs)
- Injected as a compact **Profile Card** in router context
- Complements intelligence insights (learned routing) with explicit prefs (tone, tool prefs, boundaries)

Does **not** replace `jarvis-intel` files — those remain the manual override layer. See [USER_PROFILE_SYSTEM.md](USER_PROFILE_SYSTEM.md) for schema and edit workflow.

---

## Intelligence Dashboard (port 5003)

Dedicated UI at **`http://localhost:5003`** (`jarvis-intelligence/`). Start
cloud/default with `./bin/jarvis-intelligence` or `./bin/start --ui-only`; use
`./bin/jarvis-intelligence local` or `./bin/start --ui-only --local` to load
`config/local.env`.

| Tab | Capabilities |
|-----|----------------|
| **Experiences** | Sort by date/turns/tools/CG status; filter success/fail, tool count, specific tool; server-side pagination; detail modal with raw JSON |
| **Insights** | Positive/negative constraints; 5-tier confidence filters; preferred/avoided tool badges; re-embed after edits |
| **Reflection** | Pending queue, trigger reflection, meta-knowledge (blind spots, over-generalization) |
| **Stats** | Totals, tool performance table, maintenance actions |
| **Feedback** | Browse `logs/feedback/` with rating filters |

Full API table: [jarvis-intelligence/README.md](../jarvis-intelligence/README.md).

**Mode switch:** Cloud → `data/jarvis_intelligence.db` (1536-dim embeddings). Local → `data/jarvis_intelligence_local.db` (768-dim). Dimensions are **not** interchangeable.

---

## Database schema (core tables)

Defined in `lib/intelligence.py` `_init_db()`:

| Table | Purpose |
|-------|---------|
| `experiences` | Raw interactions: query, embeddings, `tools_used`, `tool_sequence`, `turns_taken`, `final_tool`, outcome booleans, `raw_data` JSON |
| `insights` | Learned rules: `constraint_type` (positive/negative), `preferred_tool` / `avoided_tools`, confidence, decay fields, `times_applied` / `times_helpful` / `times_failed`, `last_outcome` |
| `insight_evidence` | Provenance links insight ↔ experience with evidence snippets |
| `meta_knowledge` | Meta-cognition output (blind spots, quality issues); also stores `last_decay_run` for interval protection |
| `reflection_queue` | Pending experiences awaiting reflection (`processed`, priority) |

Sync between machines: `./bin/sync-intelligence-db.py`. Health: `./bin/check-intelligence-health.py`.

---

## Main API endpoints (port 8880)

Monitoring and maintenance via `api/routes/intelligence.py` (no auth on local LAN — lock down in production):

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/intelligence/stats` | Counts, pending reflections, avg confidence |
| GET | `/api/intelligence/health` | Enabled flag, issues list |
| GET | `/api/intelligence/metrics` | JSON metrics snapshot |
| GET | `/api/intelligence/insights` | Recent insights (limit 20) |
| GET | `/api/intelligence/experiences` | Recent experiences |
| GET | `/api/intelligence/reflections` | Reflection queue |
| DELETE | `/api/intelligence/reflections/{id}` | Remove queue entry |
| DELETE | `/api/intelligence/reflections` | Clear queue (careful) |
| POST | `/api/intelligence/reflect?batch_size=N` | Process reflections |
| GET | `/api/intelligence/evaluate` | Dry-run evaluation helpers |
| POST | `/api/intelligence/maintenance/decay` | Run decay job |
| POST | `/api/intelligence/maintenance/anomaly` | Anomaly detection |
| POST | `/api/intelligence/maintenance/meta-cognition` | Meta-cognition pass |
| POST | `/api/intelligence/maintenance/all` | All maintenance jobs |
| GET | `/api/intelligence/meta-knowledge` | Meta-knowledge rows |
| GET | `/api/intelligence/logs/recent` | Recent intelligence log events |

---

## Completion Guard bridge (operational notes)

When Completion Guard (CG) is enabled, experiences store CG metadata in `raw_data`:

| CG status | Intelligence treatment |
|-----------|------------------------|
| `accepted` / `auto_accepted` | Normal success path |
| `repaired` | Outcome may still succeed; reflection sees repair context |
| `ticketed` / `expired` / `superseded` | Often treated as soft failures for learning |
| `tighten_only` | Guard adjusted phrasing without full reject — not a hard failure |
| `operational_correction` | User-facing correction — pairs with correction learning mode |

Dashboard filters expose CG facets on the Experiences tab. See [COMPLETION_GUARD.md](COMPLETION_GUARD.md) for guard configuration.

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
- [ ] **Reflection gate / auto-processing mode** - Before running full reflection, classify whether an experience is worth learning from. Use cheap rules first, then optional low-cost LLM gating for ambiguous cases. Skip obvious non-learning experiences (`hello`, `thanks`, dev test messages, cancelled runs, duplicate low-value failures) while writing an auditable `reflection_skipped` event with `experience_id`, reason, confidence, and query preview.
- [ ] **Implicit failure detection** - Detect when user rewords query within 60s
- [ ] **Tool trashing detection** - When Tool A fails → Tool B succeeds, create negative constraint
- [ ] ~~**The Reaper service** - Periodic pruning of low-confidence insights~~ ✅ (now in decay job)
- [ ] **Conflict resolution** - When new insight contradicts old one
- [ ] **Content attribution** - Track which tool's output actually answered the query
- [ ] **User bias injection** - Allow user to specify tool preferences in config

**Reflection gate config sketch**:

```bash
INTELLIGENCE_REFLECTION_GATE_ENABLED=true
INTELLIGENCE_REFLECTION_GATE_MODE=rules_then_llm
INTELLIGENCE_REFLECTION_GATE_LOG_SKIPS=true
INTELLIGENCE_REFLECTION_GATE_MIN_QUERY_CHARS=12
INTELLIGENCE_REFLECTION_AUTO_PROCESS=true
```

Example skip reasons:

- `trivial_greeting`
- `test_message`
- `no_actionable_pattern`
- `duplicate_low_value`
- `tool_dev_failure`
- `user_cancelled`
- `insufficient_signal`
- `private_or_sensitive`

### Phase 3 (User Profile Learning) 🧠 — partially shipped
- [x] **Profile Card** — `user_model` + injection at routing ([USER_PROFILE_SYSTEM.md](USER_PROFILE_SYSTEM.md))
- [x] **Correction learning** — cross-turn `USER_CORRECTION_LEARNING_MODE`
- [ ] **Config-file tool bias** — static preferences without reflection
- [ ] **Behavioral learning** — verbosity, auto-memory, "the usual" patterns
- [ ] **Communication style learning** — tone, humor, terminology
- [ ] **Auto-parameter tuning** — `INTELLIGENCE_LEARNING_RATE`, decay tuning from measured performance

### Phase 4 (Advanced)
- [ ] **Chain caching / Macro-skills** - Learn entire workflows, not just tool preferences
- [x] **Metrics exposition** - `/api/intelligence/metrics` (Prometheus); interactive UI at port 5003
- [ ] **Grafana dashboard JSON** - Not checked in; build from metrics or use port 5003 UI
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
   pytest -q tests/test_intelligence_mode_cache.py \
     tests/test_intelligence_server_side_tools.py
   # Runs deterministic Intelligence mode and learning-signal regressions.
   # There is no automatic --tune command in the current implementation.
   ```

### Why This Matters

The goal isn't just "call the right tool" - it's:
> **An assistant that knows YOU and adapts to YOUR way of working**

This is the difference between a tool and a true assistant.

---

## Related Documentation

- [archive/KNOWLEDGE_GRAPH_MEMORY_EXPLORATION.md](archive/KNOWLEDGE_GRAPH_MEMORY_EXPLORATION.md) - Vision doc (historical)
- [MEMORY_SYSTEM.md](MEMORY_SYSTEM.md) - Main memory system
- [MEMORY_SYSTEM_TUNING.md](MEMORY_SYSTEM_TUNING.md) - Memory optimization
- [FEEDBACK_SYSTEM.md](FEEDBACK_SYSTEM.md) - Feedback system
- [COMPLETION_GUARD.md](COMPLETION_GUARD.md) - Post-answer completion loop and repair
- [ADVANCED_AI_TECHNIQUES.md](ADVANCED_AI_TECHNIQUES.md) - Advanced AI techniques
