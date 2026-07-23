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

#### Soft Empty-Result Tool Failures Should Continue In-Loop
**Priority:** Medium reliability / token control
**Status:** Possible patch; separate from the request-wide `MAX_TOOL_TURNS` accounting fix

Some live-data tools can return a technically failed result for a normal
research miss, such as `serpapi_yelp_search` reporting that Yelp returned no
results for a narrow query. Today these failures can enter the recursive
tool-failure retry path. That preserves trace context, but after the single
retry budget is spent, a later soft miss can end an otherwise useful
multi-tool research run.

**Goal:** Treat recognized empty-result misses as in-loop context rather than
terminal error recovery. The model should see the failed result, spend one
normal tool turn, and continue choosing a broader query, alternate local-search
tool, fetch/search source, or final answer from gathered evidence.

**Possible design:**
- Add a small failure taxonomy at the orchestrator/tool-result boundary:
  `empty_results`, `invalid_args`, `auth_error`, `rate_limit`,
  `transient_service_error`, and `terminal_tool_error`.
- For `empty_results`, append the failed tool result to `conversation_context`
  with `freshness: failed_tool_call`, emit the red tool card, and continue the
  existing `for turn_num in range(...)` loop instead of recursively calling
  `process()`.
- Preserve the same request-wide `MAX_TOOL_TURNS` budget. Empty-result misses
  should consume a turn, not reset or extend the budget.
- Keep true failures on the existing guarded retry/terminal path: auth errors,
  missing required args, schema errors, rate limits, and side-effecting
  single-call tools should not be silently treated as harmless misses.
- Include explicit prompt context such as: "That query returned no results;
  broaden the query, use a different search source, or answer from results
  already gathered."

**Regression coverage to add:**
- Yelp empty result followed by Maps/search fallback stays within
  `MAX_TOOL_TURNS`.
- A second empty-result miss does not abort the whole run before remaining
  turns are exhausted.
- Auth/rate-limit/schema errors still use the existing retry or terminal
  failure path.
- Failed tool cards remain ordered by `_tool_trace` and do not count as
  successful grounding in Completion Guard / follow-up evidence.

#### Ghost-Tool Description and Schema Compression
**Priority:** Medium–High token efficiency / measure after router-prompt A/B testing

Ghost tools are included on every applicable routing request, so their tool
descriptions and JSON schemas have a larger recurring token cost than tools
loaded only when Tool RAG retrieves them. A Caveman-light cleanup could keep
the same tool behavior with shorter, more direct wording.

**Experiment boundary:** Do not combine this with router-prompt comparisons.
Hold the selected router prompt, provider/model, ghost list, Tool RAG settings,
and test requests fixed so routing changes can be attributed to tool metadata.

**Measurement-first approach:**
- Use Tool RAG trace fields (`tool_schema_chars`, estimated tokens, and largest
  schema contributors) to record the current cost per request and per tool.
- Start with the effective always-loaded ghost list because it offers the
  highest repeat savings; optimize retrieved-only tools later.
- Shorten descriptions first. Preserve exact tool names, “use when,” “do not
  use,” side effects, live-data/freshness rules, and all argument semantics.
- Treat parameter names, types, required fields, enums, defaults, and validation
  constraints as contracts; do not remove them merely to reduce tokens.
- Compare tool-selection accuracy, invalid/missing arguments, duplicate loops,
  multi-tool completion, total input tokens, and latency before expanding the
  rollout.

**Main risk:** Always-loaded tools influence nearly every request. An ambiguous
short description could save tokens while causing unnecessary memory calls,
wrong-tool selection, malformed arguments, or failures on complex workflows.
Keep the existing descriptions as the control and roll back individual tools
that lose adherence. Provider/model-specific compact variants are a possible
later step only if one shared description cannot perform reliably everywhere.

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

### 4) Anthropic SDK Consolidation (Stray Raw HTTP) then we also have to do it for XAI, OpenAI and Olama Cloud because they all have functions for HTTP requests for analyze vision
**Priority:** Low / housekeeping

Main chat/tool path in `lib/llm_provider.py` already uses the Anthropic SDK (thinking, caching, native web search). A few stragglers still POST to `api.anthropic.com` directly:
- `skills/analyze_image.py`
- `skills/stash.py`
- `jarvis-web/server/sockets/chat.py` (one path) vision?

**Goal:** One SDK path for auth headers, error handling, and future SDK features (e.g. `service_tier` for latency-sensitive voice/status calls).

**Not urgent:** Current raw HTTP paths work; this is maintainability, not a user-facing feature.
NOTE: The same can be said about xAI and Openai as they also send POST requests to their respective API endpoints and dont use the SDK.

### 5) Lift FastAPI `<0.137` Cap (Post prometheus-instrumentator 8.x)
**Priority:** Low / infra

`pyproject.toml` and `requirements.txt` cap FastAPI below 0.137 because prometheus-fastapi-instrumentator had issues with FastAPI `_IncludedRouter` ([#370](https://github.com/trallnag/prometheus-fastapi-instrumentator/issues/370)). After the dependency refresh, the stack runs fastapi 0.136.3 + prometheus-fastapi-instrumentator 8.0.2 with metrics and routing working in smoke tests.

**Goal:** Verify `/metrics` and instrumentator behavior with all included routers, then remove the `<0.137` cap if stable.

**Files:** `pyproject.toml`, `requirements.txt`, `docs/docker/README.md`

### 6) Replace Werkzeug for Jarvis Web Socket.IO Serving
**Priority:** Low / runtime hardening

Jarvis Web currently uses Flask-SocketIO in `threading` mode with `simple-websocket`, served through Werkzeug via `socketio.run(..., allow_unsafe_werkzeug=True)`. This applies to both native and Docker launches.

Closing or replacing a healthy WebSocket connection can produce a false HTTP 500 and traceback:

```text
AssertionError: write() before start_response
```

The client connection itself works, the server receives the normal Socket.IO disconnect, and subsequent health/API requests remain successful. Cross-UI navigation or opening Jarvis Web in another tab merely makes the teardown easier to notice. A minimal Flask-SocketIO reproduction shows that this is not caused by Jarvis routing, authentication, Canvas, or Docker networking.

**Verified direction:** A single Gunicorn `gthread` worker with multiple threads and `simple-websocket` handled repeated WebSocket connect/disconnect cycles without the false 500. Returning to Eventlet is not desirable because its monkey-patching previously interfered with gRPC, subprocess, Python locks, and clean greenlet shutdown.

**Advantages of Gunicorn:**
- Removes the known Werkzeug development-server limitation and warning
- Clean WebSocket teardown and less misleading error logging
- Better production lifecycle, signal handling, timeouts, and worker supervision
- More appropriate long-term server for the Docker deployment

**Migration risks / checks:**
- Start with exactly one worker; multiple Socket.IO workers require sticky sessions and a shared message queue
- Preserve request-local cloud/local mode loading before the app accepts traffic
- Preserve Web UI auth, shared-secret loading, upload paths, background tasks, and Socket.IO event registration
- Verify long-running LLM/tool requests against Gunicorn worker/thread timeouts
- Keep stdout/stderr logging, Docker health checks, graceful shutdown, and native tmux behavior intact
- Add `gunicorn` consistently to `pyproject.toml`, `requirements.txt`, `jarvis-web/requirements.txt`, and the uv lock

**Not urgent:** The traceback was noisy but non-breaking, and is now suppressed by the interim mitigation below. If it ever reappears (for example after a python-engineio upgrade), it can still be ignored when it occurs immediately after a normal `[WS] Client disconnected` event and health checks continue returning 200.

**Interim mitigation (2026-07-03):** the traceback is now suppressed by `jarvis-web/server/werkzeug_ws_compat.py` (applied in `server/app.py`, covered by `tests/test_werkzeug_websocket_teardown.py`). The shim patches a private Engine.IO module and is temporary; remove it when this Gunicorn item lands or when python-engineio fixes the `werkzeug` teardown upstream. Details in `docs/personal/Gunicorn_Upgrade.md`. This item stays open for the lifecycle/supervision benefits, not the traceback.

**Likely files:** `jarvis-web/server/app.py`, `bin/jarvis-web`, `docker/entrypoint.sh`, `Dockerfile`, dependency manifests, Web runtime tests, and Docker/native deployment docs.

### 7) Ollama Cloud Account Quota and Usage Status
**Priority:** Blocked upstream / integrate when Ollama exposes a supported API

Jarvis can currently identify the Ollama Cloud connection path and authentication state:
- `connection_mode=api_key` for direct `https://ollama.com` requests using `OLLAMA_API_KEY`
- signed-daemon status through Ollama's account probe
- per-request input/output token counts returned by model calls

It cannot retrieve account-level session or weekly usage, remaining quota, reset times, or plan limits. Ollama's `/api/me` response does not expose those values, model responses provide only per-request token counts, and there is no documented public quota endpoint or response header. Therefore, Web Settings → System must treat quota as unavailable rather than infer it from chat totals, scrape the Ollama dashboard, or display a guessed percentage.

**Interim UI semantics:**
- API-key path: `API key configured · usage unavailable · Manage`
- signed-daemon path: `Signed in · usage unavailable · Manage`
- Keep connection/authentication status separate from account quota status
- Continue linking **Manage** to Ollama's account/usage page

**Implementation trigger:** Add live quota reporting only after Ollama documents a stable source such as `/api/me` fields, a dedicated account-usage endpoint, or official quota response headers.

**Desired implementation once available:**
- Normalize limit, used, remaining, period, and reset timestamp into the existing Ollama Cloud status payload
- Support both direct API-key and signed-daemon transports without changing model routing
- Cache/poll conservatively and degrade to `usage unavailable` on unsupported versions or request failures
- Show session/weekly usage and reset times in System without mixing them with conversation token accounting
- Add contract tests for complete, partial, unavailable, unauthorized, and rate-limited responses

**Upstream tracking (checked 2026-07-03):**
- [ollama/ollama#12532 — Cloud usage stats](https://github.com/ollama/ollama/issues/12532) — open primary request for exposing usage through `/api/me`
- [ollama/ollama#15663 — Expose account quota/usage details via the Cloud API](https://github.com/ollama/ollama/issues/15663) — closed as a duplicate of #12532; documents the missing headers/body/endpoint options
- [ollama/ollama#16448 — API endpoint to check Cloud Usage/Quota limits](https://github.com/ollama/ollama/issues/16448) — closed as a duplicate of #12532

### 8) Latency-Aware Status Updates Across Web, CLI, and Wake Word - this is done
**Priority:** Medium–High usability / latency
**Status:** Implemented (2026-07-04); tune timing from live use

Operational behavior and configuration are documented in
[`STATUS_UPDATES.md`](STATUS_UPDATES.md).

Status updates originated in the wake-word interface to fill otherwise silent
tool waits. They remain useful in Web and CLI too, and the static phrase path
remains available on all three surfaces. Previously, the optional Status LLM
request ran synchronously before `tool:start` and the tool itself, so a slow or
missed provider call extended the critical path even though speech playback was
asynchronous. The implementation below removes that wait.

**Goal:** Preserve short, well-timed feedback without making tool turns slower,
feeding a small status model a large prompt, or allowing late status audio to
interrupt the final answer.

**Implemented timing design:**
- Tool execution starts without waiting for the Status LLM provider.
- A dynamic phrase is generated concurrently under `STATUS_LLM_DEADLINE_MS`
  (default 1000 ms).
- If the deadline is missed, use the static phrase fallback;
  do not hold the tool for the provider timeout.
- Only one Status LLM request runs at a time; superseded provider calls may
  finish in the background, but their result is discarded and no new overlap
  is started.
- A `STATUS_UPDATE_DEBOUNCE_MS` delay (default 250 ms) lets fast tools finish
  without beginning status speech.
- Late phrases are suppressed when the tool/turn has already completed.
- Final-response audio has strict priority: cancel pending status generation,
  pending Web `/api/tts` requests, and status playback before final TTS starts.
- Execution order is separate from presentation order. A Web tool card may
  appear before its optional phrase because neither display blocks execution.

**Small context contract:** Do not send the whole transcript, raw tool output,
or accumulated conversation to the status model. Use a bounded, sanitized
snapshot (target roughly 300–500 characters):
- phase (`starting`, `running`, `retrying`, `wrapping_up`)
- human-readable tool action/tool description
- allowlisted, redacted argument summary when it materially explains the task
- turn number and elapsed time
- one short sanitized previous-tool outcome for multi-tool turns, when useful

The status model should infer a natural phrase from that small snapshot. It
does not need internal thinking, full results, or the final-answer context.

**Caching:** Native `say-status.sh` and `say-status-local.sh` cache audio
by exact text plus provider/voice settings, so repeated static or dynamic
phrases avoid another TTS call. Web `/api/tts` now has a persistent status-only
cache keyed by mode, provider, text, and voice/model settings. Final-response
TTS remains independent and uncached by this path.

**Retain:**
- `STATUS_UPDATES_ENABLED` as the master opt-in
- `STATUS_LLM_ENABLED` as optional dynamic phrasing
- `status_phrases.json` / unhinged phrases as the fast fallback
- personality controls and rate limiting
- Web ephemeral text, optional Web TTS, CLI TTS, and wake-word TTS

**Included correctness cleanup:** `_last_context` is cleared on every new turn,
errors provide a bounded redacted context, and `near_complete` maps to the
Status LLM completion event rather than generic progress.

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

### 9) Reliability: Manual "Tool Doctor" Skill or Script
**Priority:** Medium

A single command that checks:
- config sanity (missing env vars)
- credential-aware tool/provider availability (see the detailed plan below)
- tool sync status (cloud/local)
- database integrity
- TTS health (provider + API key)
- MCP server health + discovered tools
- optional live dependency health without slowing normal startup

### 10) Per-Provider Media Model Pickers (Web AI Config)
**Priority:** Medium

**Problem:** Web Settings → AI config exposes image/video **provider** and **resolution**, but not the underlying model for that provider. For Gemini video this is especially limiting: switching between Veo (`veo-3.1-fast-generate-preview`, up to 4K) and Omni Flash (`gemini-omni-flash-preview`, 720p, Interactions API) still requires pinning `GEMINI_VIDEO_MODEL` in `cloud.env` / `local.env`. The same gap exists for other providers — e.g. OpenAI `sora-2` vs `sora-2-pro`, xAI Grok Imagine variants — where catalog metadata already knows the options but the UI does not expose them.

**Goal:** Let users pick any curated image or video model for the **currently selected provider** on the fly in Web AI config, without editing env files or restarting services.

**Desired UX:**
- When user selects a video provider (e.g. Gemini), show a **model** dropdown populated from `MEDIA_MODEL_CATALOG` for that provider
- When user selects an image provider, same pattern (e.g. `gpt-image-2`, `gemini-3.1-flash-image`, `grok-imagine-image`)
- Changing model refreshes dependent options (resolutions, duration limits, capabilities) from catalog metadata — same behavior as today’s provider-level resolution refresh, but driven by the chosen model pin
- Persist per-mode overrides in web config (alongside existing `image_provider` / `video_provider`), with env vars as fallback defaults

**Implementation notes:**
- Source of truth for options: `lib/model_catalog.py` (`get_media_model_catalog`, `get_media_provider_options`)
- Settings surface: `jarvis-web/server/services/settings_manager.py` + client settings UI
- Runtime resolution: map web override → effective model (mirror `GEMINI_VIDEO_MODEL`, `OPENAI_VIDEO_MODEL`, etc.) in tool dispatch and media modal
- Env keys remain optional pins for headless/voice paths; web override wins when set

**Acceptance criteria:**
- Switch Gemini video Veo ↔ Omni from Settings without touching env
- Resolution/duration UI clamps correctly per selected model (Omni 720p only; Veo 4K when supported)
- Image and video model pickers work independently per mode (cloud/local)

### 11) Configurable Cross-UI Public Ports
**Priority:** Low / coordinated infrastructure change

Jarvis browser navigation currently assumes the established UI ports: Web `5001`, Memory `5002`, Intelligence `5003`, Docs `5004`, and Canvas `8890`. This includes header icons between UIs and Canvas media handoffs to Jarvis Web. The fixed ports are acceptable today; Docker users normally customize only the FastAPI host port when resolving a conflict.

If configurable UI ports become necessary, implement them as one shared public-URL/port registry rather than changing a single link independently. The same configuration must drive:

- Docker published ports and native launchers
- Header links in every Jarvis UI
- Canvas image/video handoffs to Jarvis Web
- Documentation, health checks, and operator scripts
- Same-hostname navigation so the shared authentication cookie continues working across UI ports

Do not make only the Canvas-to-Web port configurable; partial configuration would leave the other cross-UI links inconsistent.

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
- Per-provider media model pickers in Web AI config (Gemini Veo/Omni, Sora variants, etc.)
- Credential-aware tool/provider availability + manual Tool Doctor diagnostics

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
| **Latest-response human reaction** | `update_experience_from_user_reaction()` | One 👍/👎 while reflection is pending stores direct satisfaction evidence and promotes reflection without retrying, clarifying, or changing operational success |
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

**Why this matters:** `ok: True` can still hide a poor result. Latest-response human reactions now capture an immediate explicit satisfaction signal without rerunning the task; many other failures only show up when the user rephrases on the next message. Cross-turn correction detection covers that later signal.

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

Jarvis should eventually stream OpenCode session logs, track progress, and interrupt/redirect like a user in the TUI. Today the OpenCode tool blocks until a result or timeout, and `check_opencode_sessions` can combine the OpenCode API with Jarvis-side JSONL logs afterward when a result is missing or more detail is requested. Needs `opencode_interrupt`, `opencode_send_message`, and task-layer linkage. See [archive/opencode/OPENCODE_PHASE2_STATUS.md](archive/opencode/OPENCODE_PHASE2_STATUS.md) (historical milestone).

**TODO: early session bridge for live status.** The OpenCode tool writes
`logs/opencode/opencode-YYYY-MM-DD.jsonl` immediately after `create_session()`
returns, before the long blocking task message completes:

```json
{"event":"session_start","session_id":"ses_...","task":"..."}
```

The newer `check_opencode_sessions` path can read those logs by OpenCode session
ID after execution, but the outer `StatusUpdater` still does not receive that ID
while `skills/opencode.py` is blocked. Revisit a small side channel where
`skills/opencode.py` or `OpenCodeLogger.log_session_start()` records the active
OpenCode `session_id` keyed by `JARVIS_SESSION_ID` /
`JARVIS_WEB_CONVERSATION_ID`. `StatusUpdater` could then discover it while the
subprocess is still running and read the bounded Jarvis log summary or poll an
OpenCode endpoint with Basic auth. Do not add a routine post-success check:
successful OpenCode output is already authoritative, and the router correctly
keeps `check_opencode_sessions` fallback-only. First verify that the available
logs or a newer endpoint/event stream provide meaningful incremental progress
rather than metadata-only noise.

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

### 9) Credential-Aware Tool and Provider Availability
**Priority:** Medium
**Status:** Implemented (2026-07)

Tools and Web UI providers are gated on **credential presence** in the active mode
(`config/cloud.env` or `config/local.env`). Missing or blank hard requirements
prevent registration with the LLM; the UI annotates unconfigured providers and
blocks newly selecting them. Secret **values** are never read into logs, API
responses, or the UI — only requirement names and configured/missing status.

See also: `skills/README.md` (manifest authoring), `docs/TOOL_BUILDER.md`
(approval lifecycle), `docs/JARVIS_WEB_UI.md` (provider dropdown behavior).

#### What shipped

**Tools (runtime)**
- Shared evaluator: `lib/tool_availability.py` (`all_of_env`, `any_of_env`,
  `config_files`, `webhook_registry`, `provider_requirements`, `setup_hint`;
  malformed blocks fail closed per tool)
- Strict tools carry `availability` blocks in `skills/*.tool.json` (and
  auto-tools); Tool Builder always emits them for new tools
- `ToolRegistry` filters unavailable tools **after** profile resolution; diagnostics
  in `registry.unavailable_tools` (names only, never values)
- `./bin/sync-tools.py <mode>` prints excluded tools and disables stale DB rows;
  `./bin/manage-tools.py --mode <mode> list` shows 🔒 unavailable status
- `generate_image` / `generate_video` preflight the **selected** provider and
  list configured alternatives — no silent provider switching
- Web tool discovery keeps unavailable manifest tools in the map as
  `enabled=false / available=false` so stale Tool RAG rows cannot resurrect them

**Web UI (providers)**
- Settings payload includes `provider_availability` per domain (LLM, image, video,
  TTS, completion guard)
- Dropdowns annotate and disable unconfigured providers; Ollama Cloud merges the
  live `/api/ollama/cloud-status` sign-in check
- Saving a **newly selected** unavailable provider returns HTTP 400 with
  `{field, provider, reason}` before any mutation (including mode); unrelated
  settings still save
- API Keys panel names the **active mode's** env file, not always `cloud.env`

**Tool Builder**
- Spec `required_env_vars` → manifest `availability` block (even when keys already
  exist on the build machine)
- `pending_api_key` builds: static-only verification (`ast.parse`, `py_compile`,
  `find_spec` — no code execution); files kept in `skills/pending/`
- Approval: availability gate in the report's build mode, then full verification,
  then move; mode-correct `./bin/sync-tools.py <mode>` hint

**Tests:** `tests/test_tool_availability.py`, `tests/test_tool_builder.py`,
`tests/test_web_provider_availability.py`

#### How availability is computed

Manifests stay `"enabled": true` in git. Availability is calculated at runtime:

```text
effective tool = enabled by manifest/profile
                 AND not administratively blocked
                 AND required configuration is present
```

Three states (do not conflate):

| State | Meaning | Source |
|---|---|---|
| **Enabled** | User/profile permits the tool | Manifest + `JARVIS_TOOL_PROFILE` |
| **Available** | Required static configuration exists in the active mode | Env requirements (see below) |
| **Healthy** | Optional live dependency check succeeds | Not built — see deferred |

A profile override cannot bypass a missing hard requirement. Adding the key and
restarting or re-running `./bin/sync-tools.py <mode>` restores the tool without
editing tracked manifest files.

**Manifest `availability` block** (optional; omit = always available):

```json
{
  "availability": {
    "all_of_env": ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"],
    "any_of_env": ["BRAVE_API_KEY", "BRAVE_SEARCH_API_KEY"],
    "provider_setting": "IMAGE_TOOL_PROVIDER",
    "provider_default": "gemini",
    "provider_requirements": {
      "gemini": {"all_of_env": ["GEMINI_API_KEY"]},
      "openai": {"all_of_env": ["OPENAI_API_KEY"]},
      "xai": {"all_of_env": ["XAI_API_KEY"]}
    },
    "setup_hint": "Set the key in the active mode env file."
  }
}
```

- `all_of_env` / `any_of_env`: presence and non-blank only (no placeholder heuristics)
- `config_files`: non-empty file at the listed path (contents not read)
- `webhook_registry`: named entries in `config/webhook_registry.json` must exist,
  not be disabled, and have a resolvable URL
- `provider_requirements`: tool available when **at least one** provider's keys are
  configured; media preflight errors on the **selected** provider without switching
- Inventory rule: only unambiguous hard requirements affect registration; optional
  keys (weather, CoinGecko), action-dependent tools (phone_call), direct-URL
  webhooks (`send_webhook`), and stash vision providers stay ungated

**Static-config gated tools (2026-07 follow-up):**
- `ssh_remote` — `config/ssh.json` (host aliases; key paths inside are dynamic)
- `send_email` — enabled `send_email` webhook entry with resolved URL
- `crawl_url`, `screenshot_url` — `CRAWL4AI_URL` (auth env vars optional)
- `create_social_clip` — `MONEYPRINTER_API_URL`
- `spotify` — env credentials + `data/.spotify_cache` (prior release)

**Intentionally not globally gated:** `send_webhook` (direct URL works without
registry), `phone_call` (contacts/status without Vapi; only placing calls needs
Vapi), GitHub/CoinGecko/weather/Supa-Crawl optional keys, stash vision providers.

Registry construction is static and fast — no network health checks at startup.

#### Deferred follow-ups (optional; not required for merge)

These were scoped out of the first release. The core feature above is complete.

| Follow-up | Would add | What exists today |
|---|---|---|
| **TTS / Completion-Guard live health** | Probe backends actually work (Kokoro server up, Qwen3-TTS reachable, ElevenLabs account valid) | Static API-key checks for providers that need keys; local engines (`kokoro`, `qwen3-tts`) marked available without a server probe; Ollama Cloud uses live sign-in status |
| **Placeholder-value detection** | Reject values like `your-api-key-here` / `changeme` | Present and non-blank counts as configured (avoids false positives on valid unusual keys) |
| **MCP duplicate detection hardening** | Tool Builder checks the live MCP registry, not manifest filenames | Separate from runtime availability; manifest scan only |

Suggested order if revisited: live TTS health → conservative placeholder
patterns → MCP duplicate hardening. Static `config_files` / `webhook_registry`
requirements shipped for file-backed tools (Spotify OAuth, `ssh_remote`,
`send_email`) plus env gates for Crawl4AI and MoneyPrinterTurbo.

#### Key files

- `lib/tool_availability.py` — shared evaluator
- `lib/tool_schema.py` — registry filter + `unavailable_tools`
- `bin/sync-tools.py`, `bin/manage-tools.py`
- `jarvis-web/server/services/tool_discovery.py`, `settings_manager.py`
- `jarvis-web/server/routes/api.py`, `jarvis-web/client/js/app.js`, `chat.js`
- `lib/tool_builder.py`, `bin/build-tool`
- Selected `skills/*.tool.json` manifests with `availability` blocks

---

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

**Last Updated:** July 1, 2026  
**Version:** 2.8 (Added media model picker roadmap item for Web AI config)
