# Auto-Memory Injection Feature

**Status**: Implemented (Phases 1–3)  
**Goal**: Memory from the vector DB is automatically loaded into the LLM context when relevant—no tool calls required. New chats inherit learned knowledge (e.g., "call me sir") without explicit search.

---

## Problem Statement

1. **LLM must call tools to access memory** – `search_memory` and `semantic_recall` require explicit tool use. The LLM often skips them unless the user says "remember" or the query clearly demands recall.

2. **Remember tool underused** – Unless told to remember or something seems obviously important, the LLM rarely calls `remember`. Preferences, instructions, and facts slip through.

3. **New chat = amnesia** – Start a new chat, say "call me sir" → it works. New chat later → LLM doesn't know to call you sir unless it searches memory.

4. **Topic-aware context missing** – When discussing machine learning, relevant ML knowledge in the vector DB is not injected. The LLM would need to call `semantic_recall` first.

---

## Design Principles

- **Transparent injection** – Relevant memories appear in context before the LLM responds, similar to conversation history.
- **Sensible cutoffs** – Use similarity thresholds and limits to avoid noise and token bloat.
- **Complement tools** – Auto-injection does not replace tools; it reduces the need for them in common cases.
- **Configurable** – Enable/disable, tune limits and thresholds via config.

---

## Component 1: Auto-Memory Injection (Pre-LLM)

### Concept

Before each LLM call, run semantic search on the current transcript (and optionally recent conversation summary). Inject matching memories into the prompt, similar to how OpenCode uses `get_memory_context()`.

### Flow

```
User: "Let's talk about machine learning"
    ↓
Orchestrator.process()
    ↓
1. Build base transcript: _format_conversation_context() [web] OR _build_conversation_context() [auto-context] OR raw transcript
2. Prepend _get_relevant_memories(transcript)  →  "=== RELEVANT STORED KNOWLEDGE ===" block
3. Prepend _get_learning_insights()  →  learned strategies / tool preferences
    ↓
Final order (top of prompt downward): LEARNING  →  MEMORY  →  conversation / query
    ↓
router.route(enhanced_transcript)
```

Memory runs on the **raw user transcript** for search; the **injected blocks** are ordered so strategies sit above stored knowledge above thread context.

### Implementation (`orchestrator/orchestrator_v2.py` → `_get_relevant_memories`)

**Merge:** Candidates come from (1) addressing preferences (pinned), (2) optional intel FTS matches on tooling-heavy queries, (3) semantic search with recency weighting and intel boosts. Each row gets a numeric **score** used for ordering.

**Sort:** `merged.sort(key=lambda x: (score, importance), reverse=True)`, then `top = merged[:AUTO_MEMORY_LIMIT]`. Primary key is **score** (higher = listed first). **Importance** breaks ties. **Recency** is not a separate column; it multiplies semantic similarity before comparison. There is no “newest first” sort by itself.

**Prompt lines:** Each bullet includes a short **match hint**: `rank=…` matches the sort key; semantic rows also show `embed=…` (raw cosine before recency). A header line states the **semantic bar** (`AUTO_MEMORY_SIMILARITY_THRESHOLD`): adjusted rank must be ≥ threshold to qualify. Pinned and intel-keyword rows use fixed tags (`pinned_pref`, `intel_kw`, `intel_curated`, `intel_semantic`).

**Config** (cloud.env / local.env):

```bash
# Auto-Memory Injection (pre-LLM semantic search)
# Shipped: cloud LIMIT=3, local LIMIT=2; THRESHOLD=0.40
AUTO_MEMORY_INJECTION_ENABLED=true
AUTO_MEMORY_LIMIT=3
AUTO_MEMORY_SIMILARITY_THRESHOLD=0.40
```

### Tuning

| Threshold | Effect |
|-----------|--------|
| 0.30 | More memories, some loosely related |
| 0.38–0.42 | Balanced (shipped 0.40; code fallback nearby) |
| 0.45 | Fewer, tighter matches |
| 0.50+ | Only very close matches |

**Token impact**: ~5–10 memories × ~50 tokens ≈ 250–500 tokens per request. Similar to auto-context.

---

## Component 2: Better Automatic Memory Creation

### 2a. Stronger Remember Prompting

The `remember` tool description already says "proactively decide what's important." We can:

- Add explicit examples in the system prompt: "When user says 'from now on X', 'call me Y', 'I prefer Z' → call remember."
- Add a "memory-first" rule for preference/instruction phrases.

### 2b. Post-Conversation Extraction (Optional)

After each exchange, optionally run a lightweight extraction pass:

1. **Trigger**: Conversation ends (user got a response).
2. **Input**: Last user message + assistant response (or last N turns).
3. **Process**: Call a small/fast model or `text_summarizer` to extract:
   - Preferences (e.g., "call me sir")
   - Facts (e.g., "wife's birthday is March 15")
   - Instructions (e.g., "always use port 5000 for Flask")
4. **Action**: For each extracted item, call `remember` (or a batch remember API) in the background.

**Caveats**:

- Adds latency or requires async/background job.
- Risk of over-remembering noise.
- Needs careful prompting to avoid hallucinated facts.

**Simpler variant**: Only run extraction when the user explicitly says "remember this" or when the LLM already called `remember` (to reinforce/expand).

### 2c. Conversation → Memory Pipeline

Use `text_summarizer` (summarize, keywords) to condense conversation and extract key details:

- **When**: End of a chat session, or every N messages.
- **Flow**: Summarize last N messages → extract entities/preferences → batch insert into memory.
- **Storage**: Store as `category: "conversation_summary"` or similar, with metadata linking to conversation ID.

---

## Component 3: Preference/Instruction Priority

Some memories should be injected more aggressively:

- **High priority**: `preference`, `instruction`, `personal` (e.g., "call me sir")
- **Standard**: `fact`, `technical`, `project`
- **Lower priority**: `system`, ephemeral

**Idea**: Use a two-tier threshold:

- High-priority categories: inject if similarity ≥ 0.32
- Others: inject if similarity ≥ 0.40

Or: always include top N high-importance memories (e.g., importance ≥ 8) up to a small limit (e.g., 3), regardless of similarity, when the query is at least somewhat open-ended.

---

## Implementation Order

| Phase | Component | Effort | Impact |
|-------|-----------|--------|--------|
| 1 | Auto-memory injection (`_get_relevant_memories`) | Low | High – "call me sir" works in new chats |
| 2 | Config + tuning (limit, threshold) | Low | - |
| 3 | Stronger remember prompting in system prompt | Low | Medium – more proactive remembering |
| 4 | Category/importance-aware injection | Medium | Medium – better relevance |
| 5 | Post-conversation extraction | High | High – but complex, needs care |

**Recommendation**: Start with Phase 1–3. Phase 4 and 5 can follow once the base behavior is validated.

---

## Example: "Call Me Sir"

**Before (current)**:

1. User: "From now on, call me sir."
2. LLM: Calls `remember` (if it decides to).
3. New chat. User: "What's the weather?"
4. LLM: No memory in context → might not use "sir."

**After (with auto-injection)**:

1. User: "From now on, call me sir."
2. LLM: Calls `remember` (with stronger prompting, more likely).
3. New chat. User: "What's the weather?"
4. **Pre-LLM**: `_get_relevant_memories("What's the weather?")` → semantic search may still return "user prefers to be called sir" if the query is broad enough, or we could always inject top N preferences.
5. **Enhancement**: Always inject a small "user preferences" block (e.g., top 3–5 by importance) in addition to query-based semantic search. That way "call me sir" is always in context for any new chat.

**Refinement**: Combine query-based semantic search with a small "always include" set:

- Query-based: `semantic_search(transcript)` – topic relevance.
- Always-include: `get_addressing_preferences(limit=2)` – addressing/response-style only.

---

## Config Summary

Add to `config/cloud.env` and `config/local.env` (or copy from *.example):

```bash
# Auto-Memory Injection (CLI, WebUI, wake word)
# Shipped: cloud LIMIT=3, local LIMIT=2
AUTO_MEMORY_INJECTION_ENABLED=true
AUTO_MEMORY_LIMIT=3
AUTO_MEMORY_SIMILARITY_THRESHOLD=0.40
AUTO_MEMORY_TYPE_FILTER_ENABLED=true
AUTO_MEMORY_RECENCY_ENABLED=true
AUTO_MEMORY_ALWAYS_INCLUDE_LIMIT=2
```

| Var | Default | Description |
|-----|---------|--------------|
| `AUTO_MEMORY_INJECTION_ENABLED` | true | Master switch – set false to disable |
| `AUTO_MEMORY_LIMIT` | 3 cloud / 2 local (shipped) | Max memories injected per request |
| `AUTO_MEMORY_SIMILARITY_THRESHOLD` | 0.40 (shipped) | Min similarity (0.35–0.42 recommended) |
| `AUTO_MEMORY_TYPE_FILTER_ENABLED` | true | Filter injected memories by query type |
| `AUTO_MEMORY_RECENCY_ENABLED` | true | Recent memories rank slightly higher |
| `AUTO_MEMORY_ALWAYS_INCLUDE_LIMIT` | 2 | Max addressing/response-style items always included |

---

## Implementation (Phases 1–3)

- **orchestrator/orchestrator_v2.py**: `_get_relevant_memories()` – semantic search, recency weighting, always-include preferences
- **lib/memory_db.py**: `get_addressing_preferences()` – addressing/response-style only
- **orchestrator/router_v2.py**: Stronger remember prompting for "call me sir" / "from now on" patterns
- **config/*.env.example**: All `AUTO_MEMORY_*` vars documented

Recency: 7 days = 1.0, 30 days = 0.97, 60 days = 0.94, 120 days = 0.90, older than 120 days = 0.85. Importance used for tie-break and conflict resolution.

**Labeling**: Always-included preferences show "user preference (always included)" (not "100% relevance") so it's clear they're not semantically matched to the query. Semantic results show actual relevance %.

**Always-include = addressing/response-style only**: Keys matching `address`, `how_to`, `response_tone`, `response_style`, `preferred_language` are the only ones always injected. Topic-specific prefs (dog, Spotify, etc.) appear only when semantically relevant to the query.

## Related Docs

- `AUTO_CONTEXT_SYSTEM.md` – Short-term conversation context
- `MEMORY_SYSTEM.md` – Memory tools and schema
- `opencode/OPENCODE_MEMORY_STRATEGY.md` – OpenCode's `get_memory_context`
- `MEMORY_SYSTEM.md` – Memory tools, schema, and when to use each search tool
