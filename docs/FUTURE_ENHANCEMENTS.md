# Jarvis Roadmap & Future Enhancements

This document tracks planned improvements for Jarvis.

Guiding principles:
- Voice-first and headless-server friendly (no GUI assumptions)
- Provider-agnostic by default (cloud + local), with optional provider accelerators
- Stash-first for artifacts (avoid huge tool args; keep flows inspectable)
- Keep the tool surface clean (avoid redundant tools and tool-choice loops)

---

## ✅ Recently Completed (High-Level)

- **Stash system**: structured, tool-accessible artifact store for multi-step workflows (`stash`)
- **PDF creation**: `pdf_create` tool that composes PDFs from stash artifacts
- **Printer upgrades**: compact mode + better formatting + image printing
- **Tool blocklist**: `BLOCKED_TOOLS` support in tool sync + startup display filtering
- **Native provider web search**: optional built-in search for xAI + Anthropic to reduce tool calls/loops
- **TTS provider selection**: OpenAI, ElevenLabs, xAI, or Qwen3-TTS (`TTS_PROVIDER`)

---

## 🔨 In Progress / Near Term

### 1) Exact-Call Approval and Preflight Policies (Optional)
**Priority:** Deferred / narrow high-risk use only

Currently tools with `auto_approve: false` execute with a console warning. The permission check does not pause or wait, so it adds effectively no runtime latency.

**Why keep the metadata:** It documents side effects and provides one central policy hook shared by Web UI, CLI, and wake-word paths. A future implementation could use that hook for interactive confirmation or for non-user-facing validation and auditing.

**Design constraint:** Never ask the user to approve a vague intent and then let the model generate new arguments. Prepare the complete call first, show the material target/arguments, bind approval to a normalized call hash, and execute that exact call once with a short expiration.

```
You: "Delete all my files"
Jarvis: "Prepared execute_bash call targeting /specific/path with rm .... Approve this exact call?"
You: "Yes, I approve"
Jarvis: "Executing the approved call without regenerating arguments."
```

**Possible surface adapters:**
- Web UI: Yes/No controls showing tool, target, and material arguments
- CLI: terminal confirmation prompt
- Wake word: spoken summary and voice approval

All adapters should call a centralized orchestrator policy rather than implement separate approval semantics.

**Good candidates:** phone calls, outbound email/webhooks, SSH mutations, destructive Docker/system commands, and bulk deletion.

**Usually better alternatives:**
- Argument and target validation
- Allowlists and scoped credentials
- Dry-run/preview behavior
- Expected match counts and file/version hashes
- One-shot mutation tokens
- Structured audit logs

These deterministic safeguards often prevent incorrect actions more effectively than confirmation. `manage_intel replace`, for example, rejects ambiguous matches and stale file hashes without asking the user to reason about an underspecified prompt.

**Potential implementation areas:**
- `orchestrator/executor.py` — centralized preflight and exact-call approval lifecycle
- Web/CLI/wake adapters — presentation and response capture only
- Tool schemas — action-level risk metadata if coarse tool-level permissions become insufficient

### 2) Tool Set Hygiene (Reduce Confusion / Loops) - INSIGHTS HELP THIS IN GUIDING THE LLM TO USE THE CORRECT TOOLS
**Priority:** High

**Goal:** Keep the model from getting stuck by presenting too many overlapping ways to do the same thing.

Concrete improvements:
- Add a diagnostics summary: discovered MCP tools vs. synced/enabled tools vs. blocked tools
- Add a “preferred tool ordering” policy when multiple tools cover the same capability (search/fetch/browser)
- Make `BLOCKED_TOOLS` operational docs explicit (“blocked ≠ disabled at discovery time”)

### 3) Short-Lived Continuation Across Wake Activations - HAVE THIS ALREADY IN AUTO CONTEXT NUM AND MINUTES - IS DIFFERENT IN SESSION ID AND LOADING CONVERSATION FROM MEMORY DB
**Priority:** Medium

**Goal:** Remember context across wake word activations for ~5–10 minutes (without polluting long-term memory).

**Example:**
```
You: "Hey Jarvis, search for restaurants in Portland"
Jarvis: "I found several great restaurants..."

[30 seconds later]

You: "Hey Jarvis, what about the Italian ones?"
Jarvis: "From the Portland restaurants, here are the Italian options..."
```

**Implementation:**
- Session ID tied to time window
- Load recent conversation from memory DB
- Include in LLM context
- Expire after idle timeout

---

## ⭐ State-of-the-Art Assistant Upgrades (Worth Doing Early)

These are the “we wish we’d designed for this up front” features that make a real difference once you have lots of tools, multiple providers, and long-running workflows.

### A) Provider Capability Matrix + Auto-Detection
**Why:** Prevent “unknown unknowns” (e.g., built-in web search) and reduce unnecessary tools.

Ideas:
- Maintain a runtime “capabilities” object (search, vision, structured output, tool calling limits, context size, etc.)
- Auto-detect (or explicitly declare) per-provider features and expose them to routing + prompts
- One-page doc/command to print current capability matrix (cloud/local)

### B) Hybrid Retrieval: FTS5 + Semantic + Reranking
**Why:** Memory/tool retrieval quality is everything; hybrid beats either alone.

Ideas:
- Always run **FTS5 keyword** + **semantic search** and merge results
- Add a lightweight reranker step (LLM or local model) to order the merged candidates
- Add “query rewrite” for recall (expand synonyms, normalize entities, strip filler)

### C) Tool Routing Evals + Regression Suite
**Why:** Prevent silent regressions as tool count grows or providers change.

Ideas:
- Curated set of routing test prompts (“should call tool X”, “should not call search”, “should answer directly”)
- Track: tool calls count, latency, cost, success rate, loop rate, fallbacks
- CI-friendly runner that can test cloud + local modes (even a small subset)

### D) Observability: Tracing, Costs, and “Why Did You Do That?”
**Why:** Debugging assistants without traces is pain.

Ideas:
- Per-turn trace ID; log routing decision, chosen tools, retries, and final outcome
- Cost/latency budgets per request (“max tools”, “max time”, “max cost”)
- A debug command that prints a short “decision summary” (for humans)

### E) Background Jobs + Notifications (Headless)
**Why:** Some workflows shouldn’t block interactive voice turns.

Ideas:
- A small job queue: run long tasks asynchronously (downloads, OCR, big summaries)
- “Notify me when done” via existing channels (email/webhook/print)
- Persist job artifacts in stash; keep a job status tool (`jobs.list`, `jobs.status`)

---

## 🚀 Future / Nice to Have

### 4) Stale Relationships / Contact Decay Detection
**Priority:** Medium

**Why:** Proactive relationship management - detect when contacts haven't been reached out to in a while.

**Concept:** (From Digital Brain context engineering patterns)
- Tiered thresholds based on relationship importance:
  - `inner`: 14 days (close contacts)
  - `active`: 30 days (regular contacts)
  - `network`: 60 days (broader network)
  - `dormant`: 180 days (potential reactivation)

**Features:**
- Returns contacts in 3 categories: `urgent` (way overdue), `due` (past threshold), `coming_up` (75% of threshold)
- Integrates with existing contacts system (`config/contacts.json`)
- Could trigger proactive suggestions: "You haven't contacted Andrew in 45 days"
- Optional: Auto-generate email drafts or reminders

**Implementation:**
- New tool: `check_stale_relationships`
- Add `last_contact` field to contacts.json
- Track interactions via `send_email`, `phone_call` tools
- Optional scheduled job for weekly relationship health report

---

### 5) Remote VPS Ops (Tailscale + SSH + tmux)
**Priority:** High

**Why:** A headless VPS becomes a "remote executor" for long-running jobs, deployments, and isolated workloads.

Design notes:
- Prefer **Tailscale** networking (no public SSH ports required)
- Use `tmux` for persistence (stateless tool calls still map to a stable session)
- Support: run, upload/download stash artifacts, log tailing, process inspection

Potential tool: `remote_shell`
- `connect` (ensure host reachable, choose session)
- `exec` (run command in tmux session)
- `upload_from_stash` / `download_to_stash` (safe artifact bridge)
- `read_file` / `write_file` (guardrails + strict size limits)

### 6) Profiles / Tool Packs (Not Multi-User)
**Priority:** Medium

Instead of multi-user identity, support **named profiles** that change:
- tool availability (`BLOCKED_TOOLS` overlays)
- response style defaults
- safe-mode policies (disable dangerous tools)
- preferred search mode (native search vs MCP)

### 7) Smart Home Integration (Optional)
**Priority:** Low
**Requires:** Home Assistant or similar

```
You: "Turn on the living room lights"
You: "Set temperature to 72 degrees"
You: "Is the garage door open?"
```

**Tools needed:**
- `home_assistant_control`
- `hass_state_check`
- Device discovery

### 8) Memory UX (Headless-Friendly)
**Priority:** Medium

Ideas:
- Memory browser/editor (simple local web UI)
- Export/import tooling (backup + restore)
- Clear "what was remembered and why" traceability

### 9) Reliability: "Tool Doctor"
**Priority:** Medium

A single command that checks:
- config sanity (missing env vars)
- tool sync status (cloud/local)
- database integrity
- TTS health (provider + API key)
- MCP server health + discovered tools

---

## 📊 Implementation Priority

**High Priority (Next Sprint):**
- Verbal Confirmation Loop (dangerous ops)
- Provider capability matrix + auto-detection (avoid redundant tools)
- Hybrid retrieval + reranking (FTS5 + semantic)
- Routing evals + regression suite (prevent breakage as tools/providers change)
- Remote VPS Ops (Tailscale + SSH + tmux) if you want remote execution
- Tool set hygiene + diagnostics (reduce loops)

**Medium Priority (Next Month):**
- Short-lived continuation across wake activations
- Profiles / tool packs (not multi-user)
- Background jobs + notifications (stash-first artifacts)
- Observability improvements (trace + budgets + “why” summaries)

**Low Priority (Future):**
- Smart home integration (optional)
- Advanced visualizations

---

## 🧭 Strategic Direction (2026-05-21)

Jarvis is past the "add more features" phase. The next gains come from **tighter feedback loops**, **cross-surface continuity**, and **memory quality** - not pivoting to SOUL.md/MEMORY.md-style harnesses. Code-driven orchestration stays; borrow the *idea* of always-loaded persona/preferences via a structured user model, not unstructured markdown files.

Guiding bet: keep Jarvis' canonical state local (sessions, tool traces, completion guard, feedback). Use provider continuation (xAI, OpenAI Responses) only as an in-flight optimization — see [XAI_NATIVE_CONTINUATION_PLAN.md](archive/XAI_NATIVE_CONTINUATION_PLAN.md) and [CONVERSATION_STATE_ARCHITECTURE.md](CONVERSATION_STATE_ARCHITECTURE.md).

**Important framing:** the following phases are hypotheses from code exploration, not a command to plow ahead with implementation. Treat them as a research-first roadmap: verify the actual gap, check for regressions or existing partial coverage, then make the smallest code change that proves the improvement.

**Note:** user-facing preferences (e.g. "call me sir") already live in `knowledge_base` with auto-memory always-include - not in jarvis-intel files. See `AUTO_MEMORY_*` in `config/cloud.env` and [AUTO_MEMORY_INJECTION_FEATURE.md](AUTO_MEMORY_INJECTION_FEATURE.md).

### Phase Relationship

The structured user model is the center of gravity:

- **Phase 2 defines the target:** a compact, durable profile of how Jarvis should act toward the user over time.
- **Phase 1 supplies correction evidence:** cross-turn dissatisfaction and style corrections become signals that can update the profile or downgrade prior experiences.
- **Phase 3 protects memory quality:** write-time classification decides which facts/preferences are allowed to affect recall, routing, or the user model.

This is similar in spirit to Hermes/OpenClaw-style `SOUL.md` or `MEMORY.md` profile compaction, but not in storage or orchestration. Jarvis should keep the profile structured, local, queryable, and code-governed.

### What Already Partially Covers the Learning Loop

Several post-turn hooks already update the intelligence DB before reflection runs. These are **same-turn** corrections, not cross-turn:

| Hook | Function | What it does |
|------|----------|--------------|
| **Completion Guard (auto + manual)** | `update_experience_from_completion_guard()` | Writes guard status onto the linked experience; `repaired` / `unresolved` / `ticket_created` adjust `outcome_success`, `user_satisfied`, `had_to_retry`; folds corrected answer/tools into `raw_data.context` for reflection |
| **Feedback (LLM-as-QA)** | `update_experience_from_feedback()` | All ratings store metadata in `raw_data.feedback.latest`; ratings ≤ 2 retroactively mark `outcome_success=false` and bump reflection priority |
| **Same-turn signal inference** | `_infer_user_signals()` in `intelligence_hooks.py` | Pattern-matches the **current** query ("try again", "what I meant", "not that") at record time — does **not** look back at the previous turn |

See [FEEDBACK_SYSTEM.md](FEEDBACK_SYSTEM.md) and [INTELLIGENCE_LAYER.md](INTELLIGENCE_LAYER.md) for the full bridge docs.

**Cross-turn learning:** `USER_CORRECTION_LEARNING_MODE=shadow|apply`. **Shadow** (safe default for new installs): records candidates only — turn 1 unchanged. **Apply**: downgrades linked prior experience + optional lesson append. Production config uses **apply** after shadow review; set back to `shadow` if false positives appear.

### 1) Retroactive Satisfaction Detection (Cross-Turn Learning Loop)
**Priority:** High  
**Status:** Implemented — shadow + apply live; production on `apply` (May 2026); tune guardrails as needed

Cheapest path to a real self-improvement loop without "dreaming" or sandboxes:

```
Turn 1: Jarvis answers -> experience recorded (success=true)
         -> conversation log stores experience_id in metadata (wake-word/CLI)
Turn 2: User says "no I meant Portland OR not Portland ME"
         -> detect correction pattern on NEW query
         -> shadow: persist candidate on turn 2 + intel log (no turn 1 mutation)
         -> apply: UPDATE turn 1 experience: outcome_success=false, had_to_clarify=true
         -> queue reflection with high priority
```

**Why this matters:** today, `ok: True` + no guard failure + no feedback run = success. Many real failures only show up when the user rephrases on the next message. Completion Guard and Feedback help but are limited to the turn they run on.

**Implemented (2026-05-21):**
- `extract_user_correction_signals()` — conservative correction/retry/style patterns
- `update_experience_from_user_correction()` — apply-mode bridge (mirrors feedback/guard)
- `record_user_correction_shadow_candidate()` — shadow persistence + `get_intel_logger()` event
- `USER_CORRECTION_LEARNING_MODE=shadow|apply` — examples default `shadow`; flip to `apply` after review
- Apply + `USER_CORRECTION_APPEND_LESSONS=true` → `jarvis-learned-lessons.md` (dedup by experience id)
- Web UI: `experience_id` on assistant history → `_previous_experience_id_from_history()`
- Wake word / CLI: `experience_id` in conversation metadata → `get_previous_experience_id_from_recent_conversations()` within `AUTO_CONTEXT_MINUTES`

**Still open (nice-to-have):**
- Task-change guardrails ("I meant to ask something else" vs real correction)
- `experience_id` on some exit paths (duplicate-prevented, max-turns)
- Optional `user_model` trait nudge from style corrections (deferred)

**Guardrails:**
- Only downgrade when the correction clearly refers to Jarvis' previous answer, not when the user changes tasks naturally
- Store the correction text/evidence in `raw_data` so reflection can inspect it later
- Keep mutation local to the linked previous experience; do not rewrite broad history
- Shadow mode should be used to measure false positives before enabling apply mode; phrases like "I meant to ask something else" can be a natural topic change rather than dissatisfaction with the previous answer

**Current linkage:**

| Surface | How turn N finds turn N-1 `experience_id` |
|---------|---------------------------------------------|
| **Web UI** | Assistant message `experience_id` in client history → `_previous_experience_id_from_history()` |
| **Wake word / CLI** | Prior conversation row `metadata.experience_id` → `_resolve_previous_experience_id_for_auto_context()` |
| **Same process** | `_last_experience_id` fallback when orchestrator instance persists |

**Shadow review queries:**

```sql
-- Intelligence DB: shadow candidates (current turn)
SELECT id, query,
       json_extract(raw_data, '$.user_signals.previous_experience_id_candidate') AS prev_id,
       json_extract(raw_data, '$.user_correction_shadow.latest.signals') AS signals
FROM experiences
WHERE raw_data LIKE '%user_correction_shadow%'
ORDER BY id DESC LIMIT 20;
```

Intel logs: search for `user_correction_shadow_candidate` events.

**Files:** `lib/intelligence_hooks.py`, `orchestrator/orchestrator_v2.py`, `jarvis-web/server/sockets/chat.py`, `lib/memory_db.py`

### 2) Profile Card + user_model cache (Phase 2A)
**Priority:** High  
**Status:** Complete (core) — injection, cache, reconcile script, install template

**Source of truth:** `jarvis-intel/user_profile.md` → `## Profile Card` (~4–8 bullets, personal context). `## Profile Reference` below is on-demand only (search/intel).

**Cache:** `user_model.profile_card_cache` stores compiled card text + source hash — **not** scalar traits. See [USER_PROFILE_SYSTEM.md](USER_PROFILE_SYSTEM.md).

**Implemented:**
- `lib/user_profile.py` — extract, cache, router + synthesis append
- `USER_PROFILE_CARD_ENABLED` — router + `ResponseFormatter.apply_qa_prompt_overrides()`
- `jarvis-intel/user_profile.md.example` + README first-install notes
- `bin/reconcile-profile` — human review report (stdout only; no auto-write)
- Apply-mode corrections → **`jarvis-learned-lessons.md`**, not `user_profile.md`

**Deferred:** Web UI “approve profile edit” flow — not needed; edit `user_profile.md` directly or use `manage_intel` when you ask. `reconcile-profile` is the review aid.

**Optional later:** Filter `search_memory` / `semantic_recall` by `memory_type` (Phase 3B) — only if manual search noise becomes a problem.

**Updates:** Profile Card edited by you. Jarvis does **not** auto-edit Profile Card.

**Not a replacement for:** `JARVIS_RESPONSE_STYLE`, model prompt overrides, auto-memory always-include, or Profile Reference / intel files.

### 3) Memory Quality Gates
**Priority:** High  
**Status:** Complete (auto-inject scope) — write labels + filter + backfill; artifacts stay in DB by design

All rows still land in `knowledge_base` on write. **Auto-memory injection** filters by label; explicit `search_memory` / `semantic_recall` unchanged so stash/canvas rows remain findable when you ask.

| Type | Storage | Auto-inject | Notes |
|------|---------|-------------|-------|
| `preference` | `knowledge_base` | Yes | Durable prefs; Profile Card is separate |
| `fact` | `knowledge_base` | Yes | Stable facts with provenance |
| `artifact` | `knowledge_base` | **No** | Stash/canvas/generated — searchable on demand |
| `transient` | `knowledge_base` | **No** | e.g. `intel_hash_*` bookkeeping rows |

**Implemented:**
- `classify_memory_entry()` on every `MemoryDB.remember()` write
- `AUTO_MEMORY_TYPE_FILTER_ENABLED` — excludes artifact/transient from auto-inject (legacy rows classified on the fly)
- Wider FTS/semantic candidate pool when filter on (so facts aren't crowded out by artifacts pre-filter)
- `./bin/backfill-memory-types` — stamp `memory_type` metadata on existing rows (metadata only; no deletes)

**Deferred (not planned unless needed):**
- Reroute artifact writes away from `knowledge_base`
- Phase 3B: filter tool-based recall by type
- Session/task store for `transient` (Phase 4)

### 4) Unified Session / Task Layer
**Priority:** High (architectural)  
**Status:** Not implemented — see [WORKFLOW_ORCHESTRATION.md](WORKFLOW_ORCHESTRATION.md) and [CONVERSATION_STATE_ARCHITECTURE.md](CONVERSATION_STATE_ARCHITECTURE.md) for current context handling.

First-class `session` and `task` objects shared across voice, CLI, and Web UI. Auto-context handles wake-word continuity; Web UI has its own client-side history — no shared resumable work model yet. Unlocks cross-surface handoff, proactive "open tasks", and cleaner attachment of OpenCode session IDs, stash refs, and guard tickets.

### 5) OpenCode Supervised Subprocess
**Priority:** Medium–High  
**Status:** Phase 2 memory integration planned; interactive supervision loop not built

Jarvis should stream OpenCode session logs, track progress, and interrupt/redirect like a user in the TUI — not fire-and-forget. Needs `opencode_interrupt`, `opencode_send_message`, and task-layer linkage. See [archive/opencode/OPENCODE_PHASE2_STATUS.md](archive/opencode/OPENCODE_PHASE2_STATUS.md) (historical milestone).

**TODO: early session bridge for live status.** The OpenCode tool writes
`logs/opencode/opencode-YYYY-MM-DD.jsonl` immediately after `create_session()`
returns, before the long blocking task message completes:

```json
{"event":"session_start","session_id":"ses_...","task":"..."}
```

Explore a small side channel where `skills/opencode.py` or `OpenCodeLogger.log_session_start()`
records the active OpenCode `session_id` keyed by `JARVIS_SESSION_ID` /
`JARVIS_WEB_CONVERSATION_ID`. `StatusUpdater` could then discover that id while
the subprocess is still running and poll `/session/{session_id}` with Basic auth.
Current OpenCode API details are metadata-heavy, so first verify whether a newer
endpoint or event stream exposes useful step/tool progress before building a full
supervision UI.

### 6) Personal Corpus Ingestion
**Priority:** Medium (visible product win)  
**Status:** Building blocks exist — not unified

Bookmarks + URL ingest + intel files → one searchable personal corpus with dedup, tags, and provenance. Reuses `bookmark_search`, `url_ingest`, `deep_research` workflows.

### 7) Daily Recap
**Priority:** Medium  
**Status:** Idea only

On-demand or scheduled: short voice summary + full canvas detail (services, alerts, weather, crypto/stocks, stale reminders). Good workflow candidate — mostly glue.

### 8) Routing Evals + Regression Suite
**Priority:** Medium  
**Status:** Listed above (section C) — not built

~50 curated prompts with expected tool/no-tool behavior; CI-friendly runner for cloud + local. Prevents silent regressions as tool count and providers change.

### Defer / Keep Minimal

| Idea | Verdict |
|------|---------|
| "Dreaming" / offline simulation | High complexity — wait until cross-turn learning works |
| Full emotion/urgency classification | User model scalars get ~80% there |
| Orchestrator kernel refactor | Extract modules **during** session/task work, not as a standalone sprint |
| Smart home | Low unless used daily |

### Suggested Next Steps (May 2026)

```
Done: Profile Card injection, memory type auto-inject filter, backfill, correction apply mode
Now:  Run apply-mode corrections in production; watch intel logs + learned-lessons for false positives
Next: Phase 4 session/task layer OR routing evals — pick by daily pain
Optional: Phase 3B tool recall filter only if search_memory noise returns
```

### Updated Priority Stack (May 2026)

1. ~~Structured user model / Profile Card~~ — **shipped**
2. ~~Memory quality gates (auto-inject)~~ — **shipped**
3. **Cross-turn correction loop** — **shipped (apply)** — monitor false positives
4. **Session/task layer** — cross-surface continuity (Phase 4)
5. **OpenCode supervision OR personal corpus** — pick by daily usage
6. **Routing evals** — insurance as tool surface grows

---

## 🤝 Contributing

Want to implement something? Here's how:

1. Pick a feature from this list
2. Create a feature branch
3. Implement with tests
4. Update documentation
5. Test locally
6. Commit with clear messages

---

## 📝 Notes

- Focus on voice-first experience
- Keep it local-first (privacy)
- Provider-agnostic when possible
- Well-documented and tested
- Backward compatible

---

---

## 🔗 Related Documentation

- **[WORKFLOW_ORCHESTRATION.md](WORKFLOW_ORCHESTRATION.md)** - Multi-tool workflow system (recipes, pipelines, tool chains)
- **[ADVANCED_AI_TECHNIQUES.md](ADVANCED_AI_TECHNIQUES.md)** - Self-learning, prompt evolution, dynamic tool creation
- **[INTELLIGENCE_LAYER.md](INTELLIGENCE_LAYER.md)** - Learning from interactions

---

**Last Updated:** May 21, 2026  
**Version:** 2.7 (Phases 1–3 core shipped: correction apply, Profile Card, memory type auto-inject + backfill)
