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
- **TTS provider selection**: OpenAI or ElevenLabs (`TTS_PROVIDER`)

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

### 2) Tool Set Hygiene (Reduce Confusion / Loops)
**Priority:** High

**Goal:** Keep the model from getting stuck by presenting too many overlapping ways to do the same thing.

Concrete improvements:
- Add a diagnostics summary: discovered MCP tools vs. synced/enabled tools vs. blocked tools
- Add a “preferred tool ordering” policy when multiple tools cover the same capability (search/fetch/browser)
- Make `BLOCKED_TOOLS` operational docs explicit (“blocked ≠ disabled at discovery time”)

### 3) Short-Lived Continuation Across Wake Activations
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

### 4) Remote VPS Ops (Tailscale + SSH + tmux)
**Priority:** High

**Why:** A headless VPS becomes a “remote executor” for long-running jobs, deployments, and isolated workloads.

Design notes:
- Prefer **Tailscale** networking (no public SSH ports required)
- Use `tmux` for persistence (stateless tool calls still map to a stable session)
- Support: run, upload/download stash artifacts, log tailing, process inspection

Potential tool: `remote_shell`
- `connect` (ensure host reachable, choose session)
- `exec` (run command in tmux session)
- `upload_from_stash` / `download_to_stash` (safe artifact bridge)
- `read_file` / `write_file` (guardrails + strict size limits)

### 5) Profiles / Tool Packs (Not Multi-User)
**Priority:** Medium

Instead of multi-user identity, support **named profiles** that change:
- tool availability (`BLOCKED_TOOLS` overlays)
- response style defaults
- safe-mode policies (disable dangerous tools)
- preferred search mode (native search vs MCP)

### 6) Smart Home Integration (Optional)
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

### 7) Memory UX (Headless-Friendly)
**Priority:** Medium

Ideas:
- Memory browser/editor (simple local web UI)
- Export/import tooling (backup + restore)
- Clear “what was remembered and why” traceability

### 8) Reliability: “Tool Doctor”
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

**Last Updated:** 2025-12-12
**Version:** 2.0 (Stash + Native Search + Tool Blocklist + TTS Providers)
