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

### 1) Verbal Confirmation Loop (Dangerous Ops)
**Priority:** High

Currently tools with `auto_approve: false` execute with a console warning.

**Goal:** Voice-based approval for dangerous operations.

```
You: "Delete all my files"
Jarvis: "This will execute a bash command. Do you approve?"
You: "Yes, I approve"
Jarvis: "Okay, executing... Done."
```

**Implementation:**
- Detect confirmation requirement
- Speak warning
- Record user response
- Check for approval phrases
- Execute or cancel

**Files to modify:**
- `orchestrator/executor.py` - Add confirmation flow
- `bin/confirm.sh` - Record and transcribe approval

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

Jarvis is past the "add more features" phase. The next gains come from **tighter feedback loops**, **cross-surface continuity**, and **memory quality** — not pivoting to SOUL.md/MEMORY.md-style harnesses. Code-driven orchestration stays; borrow the *idea* of always-loaded persona/preferences (~500 tokens) via a structured user model, not unstructured markdown files.

Guiding bet: keep Jarvis' canonical state local (sessions, tool traces, completion guard, feedback). Use provider continuation (xAI, OpenAI Responses) only as an in-flight optimization — see [XAI_NATIVE_CONTINUATION_PLAN.md](XAI_NATIVE_CONTINUATION_PLAN.md) and [CONVERSATION_STATE_ARCHITECTURE.md](CONVERSATION_STATE_ARCHITECTURE.md).

### What Already Partially Covers the Learning Loop

Several post-turn hooks already update the intelligence DB before reflection runs. These are **same-turn** corrections, not cross-turn:

| Hook | Function | What it does |
|------|----------|--------------|
| **Completion Guard (auto + manual)** | `update_experience_from_completion_guard()` | Writes guard status onto the linked experience; `repaired` / `unresolved` / `ticket_created` adjust `outcome_success`, `user_satisfied`, `had_to_retry`; folds corrected answer/tools into `raw_data.context` for reflection |
| **Feedback (LLM-as-QA)** | `update_experience_from_feedback()` | All ratings store metadata in `raw_data.feedback.latest`; ratings ≤ 2 retroactively mark `outcome_success=false` and bump reflection priority |
| **Same-turn signal inference** | `_infer_user_signals()` in `intelligence_hooks.py` | Pattern-matches the **current** query ("try again", "what I meant", "not that") at record time — does **not** look back at the previous turn |

See [FEEDBACK_SYSTEM.md](FEEDBACK_SYSTEM.md) and [INTELLIGENCE_LAYER.md](INTELLIGENCE_LAYER.md) for the full bridge docs.

**Remaining gap:** a user correction on turn 2 does not retroactively downgrade turn 1's experience. Turn 1 is still recorded as `outcome_success=true` (HTTP 200 / LLM responded) unless Completion Guard or Feedback catches it on that same turn.

### 1) Retroactive Satisfaction Detection (Cross-Turn Learning Loop)
**Priority:** High  
**Status:** Not implemented — highest-ROI intelligence improvement

Cheapest path to a real self-improvement loop without "dreaming" or sandboxes:

```
Turn 1: Jarvis answers → experience recorded (success=true)
Turn 2: User says "no I meant Portland OR not Portland ME"
         → detect correction pattern on NEW query
         → UPDATE turn 1 experience: outcome_success=false, had_to_clarify=true
         → queue reflection with high priority
```

**Why this matters:** today, `ok: True` + no guard failure + no feedback run = success. Many real failures only show up when the user rephrases on the next message. Completion Guard and Feedback help but are limited to the turn they run on.

**Implementation sketch:**
- Post-turn hook (orchestrator entry or web chat pre-route): compare new query against previous experience in the same session/auto-context window
- Reuse/extend correction patterns from `_infer_user_signals()` (`what i meant`, `no i want`, `not that`, `too long`, `you forgot`, etc.)
- Call new `update_experience_from_user_correction(previous_experience_id, signals)` — same shape as feedback/guard bridges
- Optionally nudge `user_model` traits (verbosity, etc.) when style corrections are detected
- Wire `experience_id` through session/auto-context so turn N+1 can find turn N's row

**Files likely involved:** `lib/intelligence_hooks.py`, `orchestrator/orchestrator_v2.py`, `jarvis-web/server/sockets/chat.py`

### 2) Structured User Model (Phase 2A)
**Priority:** High  
**Status:** Documented in [Psychological-Profile-Ideas.md](Psychological-Profile-Ideas.md) — not implemented

Replace scattered "always call me sir" intel files with a `user_model` table in memory DB (`verbosity`, `technical_depth`, `formality`, `prefers_code_first` as 0.0–1.0 scalars). Inject ~5 lines into the system prompt every turn — no semantic search needed. Update from correction patterns + explicit preferences. Respects existing `JARVIS_RESPONSE_STYLE=auto`; nudges within mode rather than overriding it.

### 3) Memory Quality Gates
**Priority:** High  
**Status:** Partial — score thresholds raised for auto-memory injection; no write-time type taxonomy

Before auto-memory writes to knowledge base, classify entries: `preference | fact | artifact | transient`. Route `artifact`/`transient` to stash/intel only; `preference` → user_model + small intel file; `fact` → knowledge base with source tag. Stops canvas pages and misc junk from polluting routing recall.

### 4) Unified Session / Task Layer
**Priority:** High (architectural)  
**Status:** Not implemented — see [personal/app-next-steps-roadmap.md](personal/app-next-steps-roadmap.md)

First-class `session` and `task` objects shared across voice, CLI, and Web UI. Auto-context handles wake-word continuity; Web UI has its own client-side history — no shared resumable work model yet. Unlocks cross-surface handoff, proactive "open tasks", and cleaner attachment of OpenCode session IDs, stash refs, and guard tickets.

### 5) OpenCode Supervised Subprocess
**Priority:** Medium–High  
**Status:** Phase 2 memory integration planned; interactive supervision loop not built

Jarvis should stream OpenCode session logs, track progress, and interrupt/redirect like a user in the TUI — not fire-and-forget. Needs `opencode_interrupt`, `opencode_send_message`, and task-layer linkage. See [opencode/OPENCODE_PHASE2_STATUS.md](opencode/OPENCODE_PHASE2_STATUS.md).

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

### Suggested Next Four Weeks

```
Week 1: Retroactive satisfaction (cross-turn) + memory type gates
Week 2: User model table + prompt injection
Week 3: Session/task schema + Web UI wiring
Week 4: Daily recap workflow OR OpenCode streaming (pick daily-use winner)
```

### Updated Priority Stack (May 2026)

1. **Retroactive satisfaction detection** — closes the biggest intelligence gap; complements existing guard/feedback hooks
2. **User model + memory quality gates** — SOUL.md benefits without harness drift
3. **Session/task layer** — cross-surface continuity and foundation for everything else
4. **OpenCode supervision OR personal corpus** — pick by daily usage
5. **Routing evals** — insurance as tool surface grows

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
**Version:** 2.2 (Added strategic direction section — learning loop, session layer, user model)
