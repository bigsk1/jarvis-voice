# Advanced AI Techniques for Jarvis

> **Purpose**: This document outlines advanced self-learning, autonomous, and multi-agent techniques planned for Jarvis. Each technique includes implementation details, safety mechanisms, and integration points.

---

## 📋 Table of Contents

1. [Overview & Philosophy](#overview--philosophy)
2. [Design Note: Runtime-Aware Context Gating](#design-note-runtime-aware-context-gating)
3. [Design Note: Runtime-Aware Capability Narration](#design-note-runtime-aware-capability-narration-qa)
4. [Autonomous Workflow Orchestration](#autonomous-workflow-orchestration)
5. [Design Note: Presentation Artifact Learning](#design-note-presentation-artifact-learning)
6. [Phase 4: Dynamic Tool Creation](#phase-4-dynamic-tool-creation)
7. [Phase 5: Parallel Subagents](#phase-5-parallel-subagents)
8. [Phase 6: Self-Play Optimization](#phase-6-self-play-optimization)
9. [Implementation Priority](#implementation-priority)
10. [Safety & Guardrails](#safety--guardrails)
11. [Implementation Status](#implementation-status)
12. [Phase 8: Swarm Mode](#phase-8-swarm-mode-research-parallelism)
13. [Phase 9: Autonomous Maintenance Agent](#phase-9-autonomous-maintenance-agent)
14. [Phase 10: Proactive Briefing Agent](#phase-10-proactive-briefing-agent)

---

## Retired Experiment

The legacy prompt-evolution and prompt-versioning experiment was retired in August 2026. Feedback grading and the Intelligence layer remain supported; prompt and tool-description changes now go through normal source review instead of an automatic mutation pipeline. Historical evolution tables and logs may remain in existing installations but are not active runtime inputs.

---

## Overview & Philosophy

### Core Principles

1. **High Standards, Not Arbitrary Changes**: Changes to prompts and tools should be based on concrete evidence and reviewed source changes.

2. **Audit Everything**: Every change must be traceable to a feedback session ID, with before/after snapshots.

3. **Verify Before Deploy**: Auto-generated tools must pass validation before becoming active.

4. **Separate Auto-Generated Content**: Auto-created tools live in `skills/auto-tools/` to distinguish from human-crafted tools.

5. **Best Model for Critical Tasks**: Use `FEEDBACK_PROVIDER`/`FEEDBACK_MODEL` for independent grading and the dedicated Tool Builder provider settings for code generation.

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
- per-mode sync state after `./bin/sync-tools.py <mode>`
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
| `active_response_preference` | Scope/expiry-resolved addressing, style, language, or tone slot | Always allow unless explicitly forgotten |
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
- Do not filter resolved active response preferences through tool matching.
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

- Always allow resolved active response preferences.
- Suppress memories with `requires_enabled_tools` that are unavailable.
- Demote exact-name/source matches for disabled tools.
- Allow disabled-tool memories when the user explicitly asks about that tool.
- Annotate allowed disabled-tool memories as historical/debug context.

This closes the “disabled capability leaks into auto-memory context” gap without stripping useful project history.

---

## Design Note: Runtime-Aware Capability Narration (Q&A)

### Problem

When a user asks meta questions (“what can you do?”, “tell me about yourself”), the model often answers with **Q&A intent** and never inspects the live tool list. The reply can mention capabilities—phone calls, OpenCode, Spotify, media generators—that are **disabled** in the active `JARVIS_TOOL_PROFILE` or by an individual `"enabled": false` in `*.tool.json`.

Example: `local_minimal_assistant` sets `"phone_call": false`, but a self-description may still say Jarvis can place calls with Jarvis/James/Jay/Samantha personas because that text appears in curated intel (`intel/jarvis-tool-knowledge.md`) or in the model’s synthesis of the static router prompt.

### What profiles already control

| Layer | Profile-aware today? |
|-------|----------------------|
| Tool registry shown to the router | Yes — disabled tools are excluded |
| Tool execution | Yes — disabled tools cannot run |
| Learned insight injection | Yes — `format_insights_for_prompt(..., available_tools=...)` drops strategies for unavailable tools |

### What profiles do **not** control today

- **Static router system prompt** (`orchestrator/router_v2.py`, `_system_prompt_base`) — large fixed instruction block with capability examples (OpenCode, Spotify, memory workflows, etc.) that is not trimmed per profile.
- **Intel / auto-memory injection** — curated intel and related memories can still surface disabled-tool details on tooling-adjacent or semantically similar queries (see [Runtime-Aware Context Gating](#design-note-runtime-aware-context-gating) above).
- **Pure Q&A self-description** — the model answers from system prompt + injected context + parametric knowledge, not from enumerating `available_tool_names` on the current turn.

Important distinction:

```text
tool list        = what Jarvis can execute on this turn
system prompt + intel + memory = what the model thinks Jarvis can do in general
```

For “what can you do?”, the gap usually shows up as **marketing overshoot**, not unsafe execution: if the user asks to *perform* a disabled action, routing should fail or decline even though the earlier self-summary was too broad.

### Possible future enhancement

Inject a short **runtime capabilities block** derived from the same effective
enabled tool set the router already computes (`ToolRegistry.list_tools()` minus
Web/request exclusions):

1. **Source of truth** — the active-mode live registry after manifest/profile/config availability, minus request exclusions. `tool_definitions` remains the semantic ranking index, not the capability authority.
2. **Placement** — append to per-turn router context (e.g. near existing runtime date/style notes), not a separate system prompt fork per profile.
3. **Content** — compact summary for Q&A/meta queries: grouped categories or one-line descriptions from `*.tool.json`, not a raw dump of every tool name.
4. **Behavior** — for meta questions, prefer this block over static prompt examples when describing *current* abilities; keep the static prompt for workflows and safety rules.

**Profile-only prompt slices** help coarse modes (`local_minimal_assistant` vs full cloud) but do not cover toggling a single tool under the `default` profile. **Per effective enabled tool set** is the better long-term source of truth because it matches both profile overlays and per-tool `enabled` flags.

### Open questions

- Should capability narration be injected on every turn (small token cost) or only when the router detects a meta/capability query?
- Should disabled tools be listed explicitly (“not available in this profile: phone_call, opencode, …”) or omitted silently?
- Should `intel/jarvis-tool-knowledge.md` be split into “always-on architecture” vs “operational capabilities” sections to reduce overshoot before runtime gating lands?

---

## Autonomous Workflow Orchestration

> **Status:** Foreground discovery and execution are implemented. Durable background runs and deferred conversation delivery remain future work.

### Goal

Normal voice or Web chat orchestration can recognize when an existing deterministic workflow is a better fit than selecting and sequencing its component tools one turn at a time. Long workflows may eventually run in the background and deliver their result back to the originating conversation or voice session.

This should preserve the current workflow advantage: the JSON definition owns tool order and step behavior, while the LLM only decides whether an eligible workflow matches the user's intent and supplies its inputs.

### Current Safety Prerequisite

Workflow availability is strict for required components and runtime-aware:

- Every tool used by a required workflow step must exist in the effective tool registry.
- An explicit `required: false` step may be unavailable or surface-blocked; it is skipped without a call and reported as degraded.
- Conditional steps remain required unless explicitly optional, and a tool used by any required step remains required.
- Active tool-profile overrides, per-tool `enabled` state, missing configuration, and mode-specific availability are inherited from `ToolRegistry`.
- Web-blocked or request-excluded tools make the workflow unavailable for that surface.
- Unavailable workflows are omitted from normal workflow lists and slash-command suggestions.
- Explicit slash execution, direct API execution, scheduled-task creation, scheduled execution, and `PipelineExecutor` all recheck availability before running.
- `ToolExecutor` enforces request exclusions at execution time so a workflow cannot bypass a Web or request-level block.

The tool-discovery precedence is:

```text
manifest enabled value
        ↓
active profile override wins
        ↓
mode/config/credential availability
        ↓
effective ToolRegistry
        ↓
Web or request exclusions
        ↓
Tool RAG discovery candidates
```

`ToolRegistry.list_tools()` returns the already-filtered effective registry,
not every manifest or every enabled database row. Intelligence filtering uses
that live list minus request exclusions so stale Tool RAG metadata cannot
resurface a disabled discovery helper or component tool.

`data/.tool_sync_status_cloud.json` and its local equivalent are sync health markers. They report status and usable tool count but do not enumerate runtime capabilities. Workflow admission must use the current effective registry or surface-specific tool view, not the sync-status file alone.

The invariant is deliberately simple:

```text
any workflow tool unavailable
        ↓
entire workflow unavailable
```

A workflow never force-enables a tool, changes the active profile, silently substitutes another tool, or starts with a known missing dependency.

### Implemented Foreground Shape

Jarvis does not register every workflow as a separate Tool RAG schema. That would duplicate component-tool descriptions and increase routing context.

One compact `workflow` meta-tool is a mandatory discovery candidate, like `tool_search`, when it exists in the effective registry:

```text
workflow(
  action = search | describe | run,
  workflow_id,
  query
)
```

The foreground flow is:

```text
User request
    ↓
Tool RAG surfaces the workflow meta-tool
    ↓
workflow(search) returns a few currently runnable matches
    ↓
LLM selects one and supplies required input
    ↓
workflow(run) repeats availability and safety checks
    ↓
PipelineExecutor runs the fixed recipe and the current turn waits
    ↓
LLM receives the final result and answers without repeating component tools
```

Search reads both `data/workflows/*.json` and `data/workflows/personal/*.json`, preserving personal same-ID overrides. Results contain only compact metadata: workflow ID, name, description, triggers, query-derived inputs, step count, and component-tool names. `describe` adds compact step labels but never includes component schemas.

Only workflows runnable in the active mode, profile, and request surface are returned. A profile can disable the `workflow` tool itself; because mandatory ghost injection only uses the effective registry, a disabled meta-tool is neither routed nor surfaced by Intelligence. A workflow cannot call the `workflow` meta-tool recursively.

That switch applies to autonomous orchestration only. Explicit slash commands,
workflow APIs, and scheduled workflow tasks invoke the loader/pipeline directly
and remain available when their workflow JSON and every required component tool
pass their own execution-surface checks. Likewise, a Web block on `workflow` stops
autonomous Web calls but does not currently hide direct slash workflows.

`run` is synchronous. The Web chat worker waits, but Socket.IO remains responsive and receives the existing workflow status callbacks (`Starting workflow` and step progress). The CLI/voice request likewise remains active until a final workflow result or failure is available.

The outer `workflow` call executes in-process, before `ToolExecutor` enters its subprocess path, so the generic 60-second cloud / 75-second local subprocess timeout does not cap the whole recipe. There is also no separate Web worker or `PipelineExecutor` wall-clock timeout. Each component tool still runs through `ToolExecutor` and retains its own normal timeout, including any tool-specific longer timeout. Provider and HTTP calls inside a component retain their own configured timeouts.

Foreground cancellation propagates through the shared `ToolExecutor`. A cancelled component stops the pipeline before later steps, returns partial step data, and prevents later side effects from continuing.

Web conversation persistence recognizes both explicit slash workflows and autonomous `workflow(run)` results. It emits component step results to the live UI, stores a tool-name-keyed projection for history, and feeds each component through the existing compact follow-up adapters. Repeated component tools remain a candidate list rather than overwriting earlier runs. This preserves actionable handles such as Canvas page IDs and Stash refs; text summaries remain bounded. A later request can therefore call `canvas read`/`update`, inspect a Stash artifact, or run another individual tool without replaying the complete workflow payload.

The immediate next orchestration turn receives a separate step-aware preview capped at 8,000 characters. It keeps every step in current workflows, including late artifact IDs/refs, while omitting the duplicated `variables` graph and bounding large component payloads. The full canonical result remains available to the Web persistence/follow-up path; preview truncation does not alter what the workflow executed or what is stored.

Workflow execution is guarded at two different levels:

- Discovery is not treated as execution: `workflow(search)` and `workflow(describe)` may precede one `workflow(run)`.
- Once a workflow run has started, the duplicate guard rejects another run in the same user request, even with another workflow ID or different arguments. Failed preflight or missing-input validation does not consume the run.
- `workflow` is in the default Completion Guard exclusion set, and recognized workflow results also bypass its manual prompt and automatic evaluation paths. Completion Guard therefore cannot launch a repair turn that repeats a completed recipe.

Workflow usage is folded into the parent response:

- LLM calls made by `PipelineExecutor` for parameter filling, validation, titles, and completion speech.
- LLM usage reported by component tools, including `text_summarizer` and Stash auto-summary.
- Token, cache, cost/billing, peak-context, model-call, and provider-native-tool fields when the selected provider reports them.
- `component_llm_usage` preserves the component tool plus provider/model identity when a workflow uses a dedicated summary model instead of the router model.

This is important for evaluating the intended context savings honestly: deterministic sequencing avoids repeated router schemas and prior-context replay, but a recipe may still deliberately perform its own summarization calls.

Workflow turns also carry explicit learning attribution. Intelligence reflection
sees discovery actions, the selected workflow ID, bounded recipe purpose,
triggers/query inputs, run state, component tools, and bounded step outcomes in
a separate `workflow_execution` block. It evaluates whether the LLM selected
the right recipe without treating recipe-owned component order or internal
summarizer calls as router decisions.

Positive workflow learning requires a successful completed run and stores both
`preferred_tools={"workflow": ...}` and the exact
`preferred_workflow_id`. Workflow experiences do not use the generic
`final_tool` preference fallback. Before an insight is injected again, the named
workflow and all of its component tools must still be available in the effective
mode/profile/request registry; otherwise both the advice and its workflow bias
are omitted. Manual feedback uses the same attribution block and rates the
`workflow` wrapper for discovery/selection rather than every component.

Reflection must learn the underlying task (“save a quick note to memory and
Canvas”), not orchestration/test scaffolding (“find a workflow” or “use the
previously successful procedure”). Positive workflow relevance patterns are
therefore anchored to the selected recipe metadata. The v2-v4 experimental
router prompts also tell the routing model to search with that underlying task,
confirm an exact runnable recipe, run it at most once, and leave component order
to the recipe. A later reflection for the same exact workflow ID may replace
legacy overfit workflow wording and its pattern embedding. v1 remains unchanged
as the immutable prompt control.

### Foreground and Background Semantics

Foreground execution is the current contract when the answer depends on the workflow result. It matches explicit slash execution: the orchestration turn waits for `PipelineExecutor`, receives status updates, and returns one final answer.

Background execution requires a durable run object:

```text
queued → running → succeeded | failed | blocked | cancelled
```

The run should persist:

- Run and workflow IDs.
- Originating mode, surface, conversation/session, and tool profile.
- Query/input and timestamps.
- Current step and progress.
- Tools used, usage, speech, result data, artifacts, and error.
- Result-delivery status.

Completion delivery would be surface-specific:

- Web: persist an assistant follow-up in the originating conversation and emit it to the conversation Socket.IO room.
- Active voice/CLI: announce a concise completion.
- Disconnected/headless session: retain a pending completion notification.
- Additional reasoning: start a new bounded orchestration turn using the trusted workflow result; do not attempt to resume an expired provider request.

### Why `schedule_task run_now` Is Not the Execution Bridge

Scheduled tasks own **when** work runs. Today, `run_now` queues an existing task by moving its next-run time; it does not immediately create a conversation-addressable workflow run or return the final result to the initiating LLM.

A future shared workflow-run service should own execution and results:

- Direct orchestration creates an ad-hoc run.
- A scheduled task creates a run when it becomes due.
- Both use the same worker and `PipelineExecutor`.

This keeps scheduling, execution, and conversational delivery separate while sharing the same safety checks.

### Required Guardrails

- Workflow search returns only workflows runnable in the current mode/profile/surface.
- `start` revalidates even if `search` just succeeded; profiles and credentials can change between turns.
- Background workers preserve the originating surface exclusions and cannot select a broader profile.
- Revalidate before execution and fail closed if a dependency becomes unavailable.
- Prevent duplicate component-tool execution after a workflow is selected.
- Keep the one-run-per-request guard distinct from tool discovery so search/describe can still lead to one execution.
- Exclude workflow turns from Completion Guard repair/evaluation so it cannot replay a recipe with side effects.
- Side-effecting workflows remain subject to existing tool permission and approval behavior.
- Apply idempotency and per-workflow concurrency limits before enabling parallel launches.
- Report partial results explicitly if a policy change blocks a later step; completed external side effects may not be reversible.

### Remaining Implementation Order

1. Evaluate foreground workflow selection accuracy, latency, token savings, and false-positive rates.
2. Add explicit workflow input, side-effect, expected-output, duration, idempotency, and background-safety metadata.
3. Introduce durable workflow run records and a shared worker.
4. Add authenticated Web conversation follow-up and reconnect delivery.
5. Add voice/CLI pending-completion delivery and cancellation.
6. Allow background selection only for explicitly background-safe workflows.
7. Refactor scheduled workflows to create runs through the same service.

Do not add `background`, `status`, `result`, or `cancel` actions to the meta-tool until the durable run and delivery boundaries exist. A process-local thread or “fire and forget” response would lose results on restart, reconnect, or CLI exit and could execute under stale profile/exclusion state.

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

## Phase 4: Dynamic Tool Creation ✅ IMPLEMENTED

> **Status**: Fully implemented. See [TOOL_BUILDER.md](TOOL_BUILDER.md) for complete documentation.

### Concept

When an operator selects a missing capability, the in-house Tool Builder creates a candidate tool. Feedback and Intelligence can supply the evidence for that decision. The builder uses existing LLM providers (no external dependencies) with safety checks and full traceability.

### Key Safeguards

1. **Reviewed Gap Selection**: The operator confirms that a dedicated tool is warranted
2. **In-House LLM Builder**: Uses existing providers (xAI, Anthropic, OpenAI, Ollama) - no OpenCode dependency
3. **Separate Storage**: `skills/auto-tools/` directory (auto-discovered by sync-tools.py)
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
Calls Jarvis Orchestrator
        ↓
Jarvis uses its tools (Brave search, fetch, memory)
        ↓
Returns research to Tool Builder
        ↓
Better, more accurate tool created!
```

**Auto-Triggers**: Research is automatic when gap description contains API-related keywords (weather, stock, api, oauth, etc.)
8. **Local Mode Compatible**: Works with Ollama for fully offline operation

### Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      DYNAMIC TOOL CREATION PIPELINE                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Operator selects a reviewed capability gap                                 │
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
│  │  Deploy              │ skills/auto-tools/ + sync-tools.py               │
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
./bin/sync-tools.py cloud
```

### Building from Feedback Gaps

Feedback and Intelligence can reveal repeated capability gaps. Tool creation remains operator-driven: review the evidence, describe the selected gap to `build-tool`, inspect its report, and sync the approved tool.

### Configuration

```bash
# config/cloud.env

# Optional dedicated provider (falls back to FEEDBACK_PROVIDER → LLM_PROVIDER)
TOOL_BUILDER_PROVIDER=anthropic
TOOL_BUILDER_MODEL=claude-sonnet-4-5-20250929

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

Jarvis generates read-only queries, executes them through the real orchestrator,
collects evaluator feedback, and records tool-gap evidence without requiring a
human to author every test case.

This is a live learning harness, not a mocked sandbox. It can incur provider and
search API costs, and it intentionally writes selected-mode conversation,
Intelligence experience, and feedback records. External actions,
artifact creation, persistent user-data mutations, and cross-mode Memory sync
are blocked during self-play.

### Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SELF-PLAY OPTIMIZATION                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    QUERY GENERATION                                   │   │
│  │                                                                       │   │
│  │  Source: category prompts + reviewed read-only examples              │   │
│  │  Categories include information, live data, research, productivity,  │   │
│  │  media lookup, and system status                                     │   │
│  │                                                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    GUARDED LIVE EXECUTION                             │   │
│  │                                                                       │   │
│  │  - Real provider/tool routing for meaningful results                 │   │
│  │  - Fail-closed allowlist; new tools start excluded                   │   │
│  │  - No action/artifact tools or cross-mode Memory sync                │   │
│  │  - Selected-mode learning and feedback records are retained          │   │
│  │                                                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    SELF-EVALUATION                                    │   │
│  │                                                                       │   │
│  │  Evaluator LLM (FEEDBACK_PROVIDER / FEEDBACK_MODEL) scores:          │   │
│  │  - Overall response quality (1-5)                                    │   │
│  │  - Per-tool quality (1-5)                                            │   │
│  │  - Issues, strengths, and improvement suggestions                    │   │
│  │                                                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    GAP ANALYSIS                                       │   │
│  │                                                                       │   │
│  │  - Aggregate ratings and failures                                    │   │
│  │  - Detect categories repeatedly falling back to Brave search         │   │
│  │  - Save JSONL results and a complete session summary                 │   │
│  │                                                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    LEARNING EVIDENCE                                  │   │
│  │                                                                       │   │
│  │  - Normal selected-mode Intelligence experiences are recorded        │   │
│  │  - Feedback updates selected-mode Intelligence outcomes              │   │
│  │  - Session summaries support later human analysis                    │   │
│  │                                                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Safety Model

- Reviewed read-only tools are allowlisted in `lib/self_play.py`.
- New registry tools and tools marked `permissions.dangerous` are excluded by
  default. Registry initialization failure aborts the session instead of
  running fail-open.
- `SELF_PLAY_EXCLUDED_TOOLS` can add site-specific blocks.
- `SELF_PLAY_ALLOWED_TOOLS` can opt in an additional reviewed read-only tool;
  it cannot override the built-in denylist or a dangerous permission.
- Generated queries are also filtered for action-oriented language, but that
  heuristic is defense-in-depth rather than the primary safety boundary.
- Each orchestrator child receives `export_config_environment(mode)`, keeping
  local and cloud configuration isolated.

### CLI Usage

```bash
# Start with a small reviewed session
~/jarvis-venv/bin/python ./bin/jarvis-self-play --queries 5 --mode local --categories information

# Run a larger cloud session
~/jarvis-venv/bin/python ./bin/jarvis-self-play --queries 100 --mode cloud

# Skip evaluator feedback (query execution still records normal learning data)
~/jarvis-venv/bin/python ./bin/jarvis-self-play --queries 10 --mode local --no-feedback

# Output:
# Self-Play Session Started
# ├── Generating queries...
# │   └── Read-only category prompts
# ├── Executing with guarded live tools...
# │   ├── 100/100 complete
# │   ├── Avg score: 4.2
# │   └── Low scorers: 15
# └── Tool gaps found: 2
#
# Session complete. Log: logs/self-play/session-YYYYMMDD_HHMMSS.json

# List and inspect sessions
~/jarvis-venv/bin/python ./bin/jarvis-self-play list --mode cloud
~/jarvis-venv/bin/python ./bin/jarvis-self-play results --session latest --mode cloud

# Schedule nightly runs
# Add to crontab:
# 0 3 * * * /home/USER/jarvis-venv/bin/python /home/USER/jarvis-voice/bin/jarvis-self-play --queries 50 --mode cloud
```

---

## Implementation Priority

| Phase | Feature | Complexity | Impact | Prereqs | ETA |
|-------|---------|------------|--------|---------|-----|
| **4** | Dynamic Tool Creation | High | 🔥🔥 | OpenCode ✅ | 2-3 weeks |
| **6** | Self-Play | Medium | 🔥🔥 | Feedback ✅ | 1-2 weeks |
| **5** | Parallel Subagents | High | 🔥🔥🔥 | Stable core | 3-4 weeks |

### Recommended Order

1. **Phase 4** (tool creation with verification)
2. **Phase 6** (guarded self-play and feedback collection)
3. **Phase 5** (parallelization for performance)

---

## Safety & Guardrails

### Global Safety Rules

```python
SAFETY_CONFIG = {
    # Rate limits
    "max_auto_tools_per_week": 2,

    # Human approval required for
    "require_approval": [
        "dangerous_tool_creation",    # Tools with filesystem/network
    ],

    # Auto-disable triggers
    "auto_disable_tool_if": {
        "error_rate_above": 0.5,      # 50%+ errors
        "avg_rating_below": 4.0,      # Very low ratings
        "consecutive_failures": 5,    # 5 failures in a row
    },

    # Sandbox settings
    "sandbox_new_tools_for": "24h",   # New tools sandboxed for 24h
}
```

## Related Documentation

- [INTELLIGENCE_LAYER.md](INTELLIGENCE_LAYER.md) - Current self-learning system
- [FEEDBACK_SYSTEM.md](FEEDBACK_SYSTEM.md) - Feedback collection and Intelligence coordination
- [opencode/OPENCODE_AGENTS.md](opencode/OPENCODE_AGENTS.md) - Subagent architecture
- [TOOL_CALLING_SYSTEM.md](TOOL_CALLING_SYSTEM.md) - Tool execution flow

---

## Summary

This document outlines the path from Jarvis's current reactive assistant to a truly self-improving autonomous system:

1. **Dynamic Tool Creation** - Grow reviewed capabilities from concrete needs
2. **Parallel Execution** - Scale performance through concurrency
3. **Self-Play** - Discover better strategies through guarded evaluation

Each phase builds on the previous, with safety guardrails ensuring stability.

---

## Implementation Status

| Phase | Feature | Status | Files |
|-------|---------|--------|-------|
| **4** | Dynamic Tool Creation | ✅ **IMPLEMENTED** | `lib/tool_builder.py`, `bin/build-tool`, Ouroboros research 🐍 |
| **5** | Parallel Subagents | 📋 Planned | See Phase 8 below |
| **6** | Self-Play Optimization | ✅ Implemented, guarded live execution | `lib/self_play.py`, `bin/jarvis-self-play` |
| **8** | Swarm Mode | 📋 Brainstorming | `docs/swarm/BRAINSTORM.md` |
| **9** | Autonomous Maintenance | 📋 Brainstorming | See below |
| **10** | Proactive Briefing Agent | 📋 Brainstorming | See below |

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
| Feedback analysis | Feedback and Intelligence UI review | Auto-analyzes patterns, proposes fixes |
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
        "auto_action": "flag_for_human_review",
        "approval_required": True
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
./bin/run-intelligence-maintenance.py --mode cloud --dry-run

# Output:
# 🔍 Observing system state...
# ├── Memory: 523 total, 89 stale (>90d), 145 low importance
# ├── Errors (24h): brave_search: 3, fetch: 1
# ├── Feedback: 12 entries, avg 3.8, lowest: search_memory (2.5)
# └── Tokens (24h): 45,231 (normal range)
#
# 🧠 Analysis:
# ├── Memory cleanup recommended: 89 stale entries
# ├── No tool health issues
# └── search_memory flagged for human review
#
# 📋 Proposed Actions (dry run):
# 1. [AUTO] Archive 89 stale memories
# 2. [REVIEW] Inspect repeated search_memory feedback
#
# Run with --execute to perform actions

# Cron (every 6 hours)
0 */6 * * * cd ~/jarvis-voice && ./bin/run-intelligence-maintenance.py --mode cloud >> logs/maintenance.log 2>&1
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
**Status:** Phases 4 and 6 implemented; Phase 5 planned; Phases 8-10 brainstorming. Legacy Phases 3 and 7 are retired.
