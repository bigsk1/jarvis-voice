# Jarvis Voice Assistant Documentation

![jarvis-info-graph](images/jarvis-info-graph.jpeg)

## 📚 Core Documentation

### Getting Started
- **[JARVIS_WORKFLOW.md](JARVIS_WORKFLOW.md)** - 🆕 **Complete workflow guide with visual flowcharts** (START HERE!)
- **[QUICKSTART.md](QUICKSTART.md)** - Quick setup guide
- **[INSTALL_GUIDE.md](INSTALL_GUIDE.md)** - 🆕 **Complete installation guide** (clone to `~/jarvis-voice`, run `./install.sh`, then configure keys/audio) ⭐ CRITICAL
- **[docker/README.md](docker/README.md)** - 🐳 **Docker guide** — run Web UIs + API in containers (commands, `.env`, hybrid mode)
- **[../config/README.md](../config/README.md)** - Configuration guide
- **[NETWORK_PROXY.md](NETWORK_PROXY.md)** - **HTTP proxy chain** (`LOCAL_PROXY` / `LOCAL_PROXY2`, `http_client`, yt-dlp, stock tool)
- **[XAI_PROVIDER.md](XAI_PROVIDER.md)** - 🆕 **xAI Grok provider** (`grok-4.5` recommended default; also `grok-4.3`, `grok-build-0.1`, native search/TTS, in-flight continuation) ⭐ RECOMMENDED
- **[OPENAI_PROVIDER.md](OPENAI_PROVIDER.md)** - 🆕 **OpenAI provider** (Chat Completions default, optional Responses API routing, hosted tools, in-flight continuation)
- **[ollama/README.md](ollama/README.md)** - **Ollama local + Ollama Cloud guide** (`OLLAMA_MODEL` vs `OLLAMA_CLOUD_MODEL`, vision uses cloud model in cloud mode / `OLLAMA_VISION_MODEL` in local mode, signed-in daemon, Docker addressing, troubleshooting)

### Main Features
- **[JARVIS_WEB_UI.md](JARVIS_WEB_UI.md)** - 🌐 **Web Interface** (mode-scoped settings, Completion Guard, multi-image vision, server logs) ⭐ ENHANCED
- **[../jarvis-memory/README.md](../jarvis-memory/README.md)** - 🧠 **Memory Browser UI** (view/search/edit memories, intel files, conversations)
- **[api/API_OVERVIEW.md](api/API_OVERVIEW.md)** - 🔌 **Comprehensive FastAPI** (Memory, Query, Stash, Canvas, Conversations, Intelligence, Intel, Voice) ⭐ ENHANCED
- **[api/VOICES.md](api/VOICES.md)** - 🔊 **Voice API** (TTS playback with multi-agent voice identity support)
- **[MEMORY_SYSTEM.md](MEMORY_SYSTEM.md)** - Memory database with semantic search + auto-injection
- **[tools/phone/PHONE_CALLS.md](tools/phone/PHONE_CALLS.md)** - 📞 **AI Phone Calls** (outbound calls via Vapi.ai, personas, transcripts)
- **[tools/spotify/SPOTIFY.md](tools/spotify/SPOTIFY.md)** - 🎵 **Spotify Control** (play, pause, skip, queue, search, multi-device)
- **[STASH_SYSTEM.md](STASH_SYSTEM.md)** - 📦 **Artifact storage** (multi-step workflows, URL downloads, **Memory+Stash architecture**, **stash.remember with PDF/LLM summarization** ⭐ ENHANCED)
- **[INTELLIGENCE_LAYER.md](INTELLIGENCE_LAYER.md)** - 🧠 **Self-learning system** (tool traces, feedback metadata, Completion Guard outcomes, positive/negative constraints) ⭐ ENHANCED
- **[CANVAS_SYSTEM.md](CANVAS_SYSTEM.md)** - 🎨 **Visual knowledge viewer** (rich content display, research results)
- **[api/IMAGES.md](api/IMAGES.md)** - 🖼️ **Cloudflare CDN Upload** (permanent image hosting, multi-agent sharing, metadata tracking)
- **[FEEDBACK_SYSTEM.md](FEEDBACK_SYSTEM.md)** - 📝 **LLM self-critique** (feedback grading, improvement suggestions, intelligence outcome updates)
- **[COMPLETION_GUARD.md](COMPLETION_GUARD.md)** - 🛡️ **Completion Guard** (same-runtime repair loop, completion check, escalation tickets) 🆕
- **[tools/scheduled-tasks/scheduled-tasks.md](tools/scheduled-tasks/scheduled-tasks.md)** - ⏱️ **Scheduled Tasks** (implemented foundation for recurring queries, workflows, parser, API, and runner) 🆕
- **[DUAL_DATABASE_SYSTEM.md](DUAL_DATABASE_SYSTEM.md)** - Cloud/local DB architecture
- **[SEMANTIC_THRESHOLD_TUNING.md](SEMANTIC_THRESHOLD_TUNING.md)** - Tune search sensitivity
- **[WEBHOOK_SYSTEM.md](WEBHOOK_SYSTEM.md)** - Modular webhook system (email, n8n, external APIs with auth)
- **[opencode/OPENCODE.md](opencode/OPENCODE.md)** - Autonomous coding agent
- **[TOOL_CALLING_SYSTEM.md](TOOL_CALLING_SYSTEM.md)** - Tool orchestration system + `tool_search` and autonomous `workflow` discovery flows ⭐ ENHANCED
- **[WORKFLOW_ORCHESTRATION.md](WORKFLOW_ORCHESTRATION.md)** - 🔄 **Multi-tool workflow system** (slash/API/scheduled plus autonomous foreground execution, strict availability, follow-up context) ⭐ IMPLEMENTED
- **[TOOL_MANAGEMENT.md](TOOL_MANAGEMENT.md)** - Manifest/profile/mode/Web precedence; enabled vs credential **available** status (`--mode`)
- **[../skills/README.md](../skills/README.md)** - **Tool profile overlays** (`JARVIS_TOOL_PROFILE`, `skills/profiles/<name>.json`, `bin/manage-tools.py profile …`); git tracks `default.json` and `skills/profiles/examples/*.json` (copy to `profiles/<name>.json` for use). After changing profile: restart services, then `./bin/sync-tools.py local` or `cloud`
- **[tools/status-tool/README.md](tools/status-tool/README.md)** - 📊 **Status Recap Tool v1.4** (weather, crypto, stocks/futures, alerts, reminders, system health, canvas + stash)
- **[tools/serp-api-tool/README.md](tools/serp-api-tool/README.md)** - 🛒 **SerpApi Search Tool** (Amazon + engine-based SerpApi queries)

### Document Processing
- **PDF Read Tool** (`skills/pdf_read.py`) - 📄 **PDF reading and manipulation**
  - Extract text from PDFs (with page ranges)
  - Extract embedded images to stash
  - Merge multiple PDFs, split PDFs
  - Convert pages to PNG/JPEG images
  - Search text within PDFs with context
  - Integrated with `stash.remember` for automatic PDF text extraction

### Remote & Infrastructure
- **[tools/ssh/README.md](tools/ssh/README.md)** - 🔐 **SSH Remote Tool** (execute commands on remote hosts, apt management, multi-command)
- **[tools/docker-tool/README.md](tools/docker-tool/README.md)** - 🐳 **Docker Control** (containers, compose, images, networks, volumes, exec, prune)
- **[DEEP_MEMORY_SEARCH.md](DEEP_MEMORY_SEARCH.md)** - 🔍 **Deep Memory Search** (unified search across all data sources)
- **[qmd/README.md](qmd/README.md)** - 📚 **Internal Knowledge Search** (Q&A about Jarvis capabilities via QMD semantic search)

### Monitoring & Observability ⭐ ENHANCED
- **[../monitoring/README.md](../monitoring/README.md)** - Grafana + Prometheus + Loki stack
- **[../jarvis-intelligence/README.md](../jarvis-intelligence/README.md)** - 📊 **Intelligence Dashboard** ⭐ ENHANCED
  - Experience sorting (date, turns, tool count) & filtering (success/fail, tool count, specific tool)
  - Insight sorting (applied, helpful, preferred/avoided tools, confidence, updated)
  - 5-tier confidence filtering (Elite 96%+, High 85-95%, Good 75-84%, Medium 50-74%, Low 0-49%)
  - Differentiated confidence bars (green for DO, red for DON'T)
  - Tool performance showing ALL tools with prefer/avoid counts
  - **NEW: Feedback tab** - View all feedback logs with rating/time filters, expandable details
- **Conversation Audit v2** - Deep drill-down into LLM decisions and tool calls
- **API Intelligence Endpoints** - `/api/intelligence/*` for stats, health, maintenance jobs
- **Maintenance Jobs** - Decay, anomaly detection, meta-cognition via API or CLI

### Web Crawling & Scraping
- **[crawl4ai/README.md](crawl4ai/README.md)** - 🕷️ **Crawl4AI Integration**
  - `crawl_url` - Extract markdown from any webpage (stealth mode, JS wait)
  - `screenshot_url` - Full-page capture + vision AI analysis
  - Bypasses anti-bot measures via screenshot + vision
  - Deep crawling, LLM extraction, PDF generation (future)
- **[tools/supa_crawl_knowledge/README.md](tools/supa_crawl_knowledge/README.md)** - 📚 **Supa-Crawl-Knowledge Tool**
  - Read-only access to your Supa-Crawl-Chat corpus
  - Search, site/page inspection, page chunks, auth examples, and multi-tool follow-up prompts

### System Architecture
- **Tool system** - Located in `skills/` directory with JSON schemas
- **Orchestrator** - `orchestrator/orchestrator_v2.py` - Main routing logic
- **MCP Integration** - External tools via Model Context Protocol

## 🚀 Quick Start

```bash
# Cloud mode (xAI/Anthropic/OpenAI or Ollama Cloud)
./jarvis

# Local mode (Ollama)
./jarvis-local

# Command Dashboard TUI (all commands in one place!)
./bin/jarvis-dashboard   # Or: jarvis-d (if alias set)

# Run deterministic core smoke tests
~/jarvis-venv/bin/python -m pytest -q \
  tests/test_docs_integrity.py tests/test_mode_plumbing_scripts.py

# Maintained integration wrappers (no external calls by default)
./tests/integration/test-thinking-mode.sh
./tests/integration/test-opencode-integration.sh
```

## 🛠️ Key Features

**Memory System:**
- Semantic search with embeddings
- Auto-remembers important info
- Self-manages (edit/delete old data)

**OpenCode Integration:**
- Autonomous coding agent
- Workspace-isolated (`~/jarvis-workspace`)
- Systemd service for reliability

**Tool Ecosystem:**
- Local tools (time, crypto, memory, bash, etc.)
- MCP servers (web search, fetch, etc.)
- OpenCode (complex tasks)

## 📖 Full Documentation Index

### Memory System
| Document | Purpose |
|----------|---------|
| **MEMORY_SYSTEM.md** | Memory database architecture and tools |
| **AUTO_MEMORY_INJECTION_FEATURE.md** | Auto-inject relevant memories into context (no tool calls) |
| **DEEP_MEMORY_SEARCH.md** | 🔍 **Deep search across ALL data sources** (memory, conversations, intel, canvas, stash)  |
| **USER_PROFILE_SYSTEM.md** | User profile management (intel + dynamic memories)  |
| **SEARCH_FALLBACK_SYSTEM.md** | Multi-tier search fallbacks (AND→OR→LIKE) |
| **FTS5_SEARCH_SYSTEM.md** | FTS5 full-text search with BM25 ranking |
| **DUAL_DATABASE_SYSTEM.md** | Cloud/local database with auto-sync |
| **EMBEDDING_HEALTH_CHECKS.md** | Embedding dimension validation |
| **SEMANTIC_THRESHOLD_TUNING.md** | How to tune similarity threshold |
| **MEMORY_SYSTEM_TUNING.md** | Advanced memory optimization |
| **SYNC_ARCHITECTURE.md** | Memory, tool, and intelligence sync behavior |

### Tool System
| Document | Purpose |
|----------|---------|
| **WORKFLOW_ORCHESTRATION.md** | 🔄 **Workflow system** - Deterministic pipelines plus autonomous foreground discovery/execution ⭐ IMPLEMENTED |
| **[../data/workflows/AGENTS.md](../data/workflows/AGENTS.md)** | 📖 **Workflow building guide** - Tool outputs, extract rules, testing |
| **TOOL_RAG_STRATEGY.md** | Tool RAG system - Dynamic retrieval, ghost tools, `tool_search`/`workflow` discovery, and compact query tuning |
| **[archive/TOOL_RAG_IMPLEMENTATION_SUMMARY.md](archive/TOOL_RAG_IMPLEMENTATION_SUMMARY.md)** | Historical Tool RAG implementation record |
| **[archive/TOOL_RAG_TROUBLESHOOTING.md](archive/TOOL_RAG_TROUBLESHOOTING.md)** | Tool RAG debugging guide (historical)  |
| **[archive/TEST_SCRIPT_TOOL_RAG_FIX.md](archive/TEST_SCRIPT_TOOL_RAG_FIX.md)** | Test script integration fixes (historical)  |
| **TOOL_CALLING_SYSTEM.md** | Tool orchestration and routing |
| **TOOL_MANAGEMENT.md** | Manifest/profile/mode/Web precedence; enabled vs credential **available** (`--mode`) |
| **[../skills/README.md](../skills/README.md)** (section *Tool profiles*) | Optional overlay JSON per profile; `JARVIS_TOOL_PROFILE`; `bin/manage-tools.py profile`; re-sync tools DB after changes |
| **[tools/serp-api-tool/README.md](tools/serp-api-tool/README.md)** | SerpApi search tool guide (setup, params, examples, troubleshooting) |
| **MULTI_TURN_ORCHESTRATION.md** | Multi-turn tool chaining |
| **ERROR_RECOVERY.md** | Error handling and retries |

### OpenCode (Autonomous Coding)
| Document | Purpose |
|----------|---------|
| **opencode/OPENCODE.md** | Main OpenCode guide |
| **opencode/OPENCODE_API_REFERENCE.md** | Full API reference |
| **opencode/OPENCODE_AGENTS.md** | Agent system architecture |
| **opencode/OPENCODE_MEMORY_STRATEGY.md** | Memory integration |
| **opencode/OPENCODE_PERMISSIONS.md** | Permission system |
| **opencode/OPENCODE_PLUGINS.md** | Plugin system |
| **[archive/opencode/](archive/opencode/)** | Historical OpenCode phase milestones (Phase 1 / Phase 2) |

### Testing & Analysis
| Document | Purpose |
|----------|---------|
| **COMPREHENSIVE_TESTING.md** | Burn test suite for all features  |
| **TESTING.md** | Comprehensive testing guide |
| **BASELINE_TOKEN_USAGE.md** | Token usage tracking |
| **../tests/README.md** | Test suite overview |

### System Understanding
| Document | Purpose |
|----------|---------|
| **JARVIS_WORKFLOW.md** | Complete workflow with visual flowcharts |
| **AUTO_CONTEXT_SYSTEM.md** | Short-term conversation memory  |
| **CONVERSATION_STATE_ARCHITECTURE.md** | State management between cycles  |
| **[api/INTEL.md](api/INTEL.md)** | 🆕 **Intel API** - CRUD operations for jarvis-intel files |
| **api/READY_TO_USE.md** | Proactive API (Phase 1 COMPLETE) - Webhook system for alerts |
| **[service/PROACTIVE_ASSISTANT_SYSTEM.md](service/PROACTIVE_ASSISTANT_SYSTEM.md)** | Proactive assistant architecture |

### Configuration & Setup
| Document | Purpose |
|----------|---------|
| **QUICKSTART.md** | Quick setup guide |
| **../config/README.md** | Configuration reference |
| **[mcp/README.md](./mcp/README.md)** | MCP integration (servers, transports, security) ⭐ |

### Advanced Features
| Document | Purpose |
|----------|---------|
| **PROMPT_CACHING.md** | Anthropic prompt caching |
| **MODEL_PROMPT_OVERRIDES.md** | Provider/model-specific prompt overlays for surgical behavior tuning |
| **EXTENDED_THINKING.md** | Opt-in LLM reasoning (`--debug-thinking`, logs, supported models) |
| **CASUAL_VS_DETAILED_MODE.md** | Response styles |
| **AUTO_MODE_EXPLAINED.md** | Auto/casual/detailed response flow, TTS interplay, direct-speech bypass, and future formatter ideas |
| **METADATA_SYSTEM.md** | Cost tracking and metadata |
| **[archive/VOICE_MODE_FIXES.md](archive/VOICE_MODE_FIXES.md)** | Voice mode improvements (historical) |

### Integrations & Webhooks
| Document | Purpose |
|----------|---------|
| **WEBHOOK_SYSTEM.md** | **Modular webhook system** - Email, n8n, external APIs with auth examples  |
| **n8n/docs/GOOGLE_CALENDAR_SYNC.md** | Bidirectional Google Calendar sync (reminders ↔ events) |
| **n8n/docs/WEBHOOK_AND_EMAIL_SYSTEM.md** | Email tool and webhook registry details |
| **[n8n/n8n-mcp.md](n8n/n8n-mcp.md)** | n8n MCP integration and workflow management |
| **api/REMINDER_SYSTEM.md** | Reminder API and voice commands |

### Intelligence & Learning
| Document | Purpose |
|----------|---------|
| **INTELLIGENCE_LAYER.md** | Self-learning system (Phase 1.5 - COMPLETE) ⭐ ENHANCED |
| **COMPLETION_GUARD.md** | Completion validation + same-runtime repair + ticket escalation |
| **ADVANCED_AI_TECHNIQUES.md** | 🚀 **AGI Roadmap** - Self-evolving prompts, tool builder, parallel subagents ⭐ ENHANCED |
| **TOOL_BUILDER.md** | 🔧 **Dynamic Tool Creation** - Autonomous tool building with safety checks  |
| **JARVIS_PLAYGROUND.md** | 🎮 **Playground Design** - Self-play, Docker, VM workspace, Carvis twin  |
| **Psychological-Profile-Ideas.md** | **Phase 2 Roadmap** - User modeling, style reflection, behavioral intelligence ⭐ FUTURE |
| **SYNC_ARCHITECTURE.md** | Memory, tool, and intelligence sync systems |

### Developer Tools
| Document | Purpose |
|----------|---------|
| **Command Dashboard** | TUI for all Jarvis commands - `./bin/jarvis-dashboard`  |
| **Memory Browser** | Web UI for memories/intel/conversations - `./bin/jarvis-memory` (localhost:5002)  |
| **Canvas Viewer** | Visual knowledge display - `./bin/jarvis-canvas` (localhost:8890)  |
| **Feedback System** | LLM self-critique - `./bin/jarvis-feedback` or `--feedback` flag  |
| **Prompt Evolution** | Self-improving prompts - `./bin/evolve-prompts check --mode cloud`  |
| **Tool Builder** | Dynamic tool creation - `./bin/build-tool --mode cloud build "..."`  |
| **[Prompt Validator](SYSTEM_PROMPT_VALIDATOR.md)** | Debug unexpected behavior - `./bin/validate-system-prompt --issue "..."`  |

**Intelligence Features (Phase 1.5):**
- Insight tracking (times_applied, times_helpful, times_failed)
- Decay job (prunes stale insights)
- Anomaly detection (flags unusual experiences)
- Meta-cognition (learning health analysis)
- CLI: `./bin/run-intelligence-maintenance.py`
- API: `/api/intelligence/maintenance/*`

### Reference & Archives
| Document | Purpose |
|----------|---------|
| **[archive/DATABASE_DEEP_DIVE.md](archive/DATABASE_DEEP_DIVE.md)** | Database evolution (historical) |
| **JARVIS_INTEL_SYSTEM.md** | Intel file ingestion |
| **FUTURE_ENHANCEMENTS.md** | Planned features |
| **[STATUS_UPDATES.md](STATUS_UPDATES.md)** | Current latency-aware status behavior, configuration, caching, and delivery |
| **[DOCS_STATUS.md](DOCS_STATUS.md)** | Documentation health and maintenance checklist |
| **archive/** | Historical docs, changelogs, and phase milestones |
| **[archive/thinking/](archive/thinking/)** | Thinking-mode branch notes (see `EXTENDED_THINKING.md`) |
| **[archive/XAI_NATIVE_CONTINUATION_PLAN.md](archive/XAI_NATIVE_CONTINUATION_PLAN.md)** | Implemented historical design; live guide: `XAI_PROVIDER.md` |
| **[archive/OPENAI_RESPONSES_ADAPTER_PLAN.md](archive/OPENAI_RESPONSES_ADAPTER_PLAN.md)** | Implemented historical design; live guide: `OPENAI_PROVIDER.md` |
| **[archive/STATUS_UPDATES_DESIGN.md](archive/STATUS_UPDATES_DESIGN.md)** | Historical 2025 design sketches; live guide: `STATUS_UPDATES.md` |
| **[archive/SEQUENTIAL_THINKING_ARCHITECTURE.md](archive/SEQUENTIAL_THINKING_ARCHITECTURE.md)** | Unimplemented sequential-thinking research design |
| **[archive/OAuth/README.md](archive/OAuth/README.md)** | Unimplemented provider OAuth research; not a setup guide |
| **[archive/docker/DOCKER_PLANNING.md](archive/docker/DOCKER_PLANNING.md)** | Original Docker design record; use `docker/README.md` for operations |
| **[archive/api/FIXES_LOG.md](archive/api/FIXES_LOG.md)** | Historical API fix log |
| **[archive/service/FIXES.md](archive/service/FIXES.md)** | Historical service fix log |

## 🔧 Configuration

**Main config files:**
- `config/cloud.env` - Cloud data/config mode; supports xAI, Anthropic, OpenAI, or Ollama Cloud through a signed daemon/direct API key
- `config/local.env` - Local data/config mode; normally uses a locally hosted Ollama model
- `~/.config/opencode/opencode.json` - OpenCode config

**Key environment variables:**
- `LLM_PROVIDER` - openai | anthropic | xai | ollama
- `JARVIS_RESPONSE_STYLE` - casual | detailed
- `OPENCODE_ENABLED` - true | false

## 📊 System Overview

```
YOU (voice)
    ↓
JARVIS (wake word detection)
    ↓
ORCHESTRATOR (routing)
    ├─→ Local Tools (time, memory, crypto, etc.)
    ├─→ MCP Servers (web search, fetch)
    └─→ OpenCode (complex coding tasks)
        ↓
    Response (natural language)
    ↓
YOU (hear result)
```

## 🧪 Testing

```bash
# Deterministic core smoke group
~/jarvis-venv/bin/python -m pytest -q \
  tests/test_docs_integrity.py tests/test_mode_plumbing_scripts.py

# Provider thinking integration (mocked by default)
./tests/integration/test-thinking-mode.sh

# OpenCode client/tool integration (mocked by default)
./tests/integration/test-opencode-integration.sh

# Read-only live OpenCode health check
./tests/integration/test-opencode-integration.sh --health cloud

# Check logs
./bin/tool-logs
./bin/opencode-logs
```

## 🐛 Troubleshooting

**Check health:**
```bash
# Jarvis tools
./orchestrator/orchestrator_v2.py cloud "what time is it?"

# OpenCode
sudo systemctl status opencode-jarvis.service
curl http://localhost:4096/health

# Logs
tail -f logs/tools/tool-calls-*.jsonl
./bin/opencode-logs --verbose
```

## 🤝 Contributing

1. Read relevant docs (MEMORY_SYSTEM.md, OPENCODE.md, etc.)
2. Follow code style in `AGENTS.md` (root)
3. Add tests for new features
4. Update documentation

## 📝 Change Log

**2026-07-27 (unreleased):**
- ✅ **Per-tool and MCP proxy policy**
  - Added runtime `proxy_policy` metadata with migration-safe `inherit`,
    direct-only `off`, proxy-first `prefer`, and fail-closed `require`.
  - Preserved the existing `LOCAL_PROXY` → `LOCAL_PROXY2` → optional direct
    behavior for native HTTP helpers and proxy-aware subprocess tools.
  - MCP Docker servers still receive only explicit environment values;
    `prefer` / `require` add only conventional proxy names derived from the
    first reachable configured proxy, with a fast listener check before calls.
  - Upgraded the tracked DuckDuckGo MCP image to upstream v0.6.0 and enabled
    `proxy_policy: "prefer"`.

**2026-07-25 (unreleased):**
- ✅ **Credential-free DuckDuckGo MCP search/fetch**
  - Added the Docker MCP Catalog `mcp/duckduckgo` server with US English,
    Strict SafeSearch, an unprivileged/read-only/capability-dropped container,
    and no API key.
  - Normalized the server's text-encoded failures to Jarvis `ok: false`.
  - Added compact persisted Web follow-up and Completion Guard evidence for
    DuckDuckGo search candidates and bounded DuckDuckGo/Fetch page excerpts.
  - Documented the image-provenance, SSRF, search-poisoning, typosquat, and
    prompt-injection trust boundaries under [`docs/mcp/`](mcp/README.md).

**2026-07-23 (unreleased):**
- ✅ **Autonomous deterministic workflows**
  - Added the compact `workflow(search|describe|run)` Tool RAG helper for shared and personal recipes, with strict active-mode/profile/surface admission.
  - Foreground execution waits for the complete pipeline result, preserves component usage, supports cancellation, and exposes bounded step-aware context for final synthesis and later Web follow-ups.
  - Added one-started-workflow-run-per-request protection and excluded workflow turns from Completion Guard repair/evaluation.
  - Intelligence reflection and optional feedback now distinguish workflow discovery/selection from deterministic component execution; positive workflow insights store and revalidate a specific `preferred_workflow_id`.
- ✅ **Unified tool availability documentation**
  - Documented manifest → profile → availability → effective registry → Web/request exclusion → Tool RAG precedence.
  - Clarified that `tool_search` and `workflow` are mandatory candidates only when enabled, and that disabling the workflow meta-tool does not disable direct slash/API/scheduled workflows.

**2026-07-11 (v2.55.1):**
- ✅ **Web conversation cleanup**
  - `./bin/cleanup-all` now calls `./bin/cleanup-web-conversations --days 90`.
  - Pinned Web UI conversations are preserved; only old unpinned conversations are eligible for deletion.
  - Dry-run output lists exact candidates before live deletion.
- ✅ **Canvas Image Gallery favorites and CDN sorting**
  - Gallery images can be marked as favorites, filtered to favorites only, and protected from generated-image cleanup.
  - Gallery sorting can group images by cached Cloudflare CDN URL status without contacting Cloudflare.
  - Uncached CDN uploads now ask for confirmation; cached URLs still copy directly from `cdn_catalog.json`.

**2026-07-08 (v2.55.1):**
- ✅ **Grok 4.5 xAI support**
  - Added `grok-4.5` with `grok-4.5-latest` / `grok-build-latest` aliases, 500K context, text+vision metadata, reasoning support, pricing, rate limits, and regional availability in the shared model catalog.
  - xAI cloud defaults now target Grok 4.5; API-key chat, OAuth-backed Grok CLI chat, usage metadata, prompt-cache affinity, and model prompt overrides all follow the catalog entry instead of hardcoded model IDs.
  - Web System status distinguishes OAuth subscription routing from xAI API-key billing and shows high-level Grok CLI `/usage` quota/reset details when OAuth is active.
- ✅ **Versioned router system prompts**
  - Added selectable router prompt versions `v1` through `v4`, with hash validation for pinned prompt contents and per-mode selection via env or Web Settings.
  - `v1` remains the immutable full-context baseline; `v2` cuts the base router prompt by `62.0%`, `v3` by `72.8%`, and `v4` by `71.9%` versus v1 while using fuller wording than v3.
  - Local env examples default to `v4`; cloud examples remain on `v1` for conservative rollout. See [`../orchestrator/router_prompts/README.md`](../orchestrator/router_prompts/README.md).
- ✅ **Tool RAG final schema caps**
  - Tool RAG limits now apply after semantic retrieval, ghost tools, `tool_search`, and explicit positive signals are merged, so final schemas respect `CLOUD_TOOL_RAG_LIMIT` / `LOCAL_TOOL_RAG_LIMIT`.
  - Ghost tools are prioritized rather than appended outside the budget; cap drops are visible in Tool RAG logs via `dropped_by_cap` and in trace JSON via `final_schema_limit`.
  - Web Settings can tune the per-mode cap, and Send-to-Canvas sends a one-turn cap of `3` to keep export turns focused (`canvas`, `tool_search`, plus one ranked fallback).

**2026-07-04 (v2.55.1):**
- ✅ **Latency-aware status updates across Web, CLI, and Wake Word**
  - Status LLM generation moved off the tool critical path; a 250 ms debounce suppresses speech for fast tools and a 1-second deadline selects the static fallback without delaying execution.
  - Status prompts now use a bounded, sanitized snapshot instead of raw tool output or conversation context, with one Status LLM request allowed at a time.
  - Turn completion cancels native status generation/playback; Web final responses, errors, cancellation, and mode changes abort pending status TTS so progress audio cannot interrupt the answer.
  - Web status phrases now use a persistent status-only TTS cache, while final-response TTS remains independent. Effective timing/model/cache values are visible in Settings → System.
  - ElevenLabs can use `eleven_flash_v2_5` for fast, lower-cost status speech through `ELEVENLABS_STATUS_TTS_MODEL` while preserving `ELEVENLABS_TTS_MODEL` and the same custom voice ID for final answers.
  - Actual Status LLM calls now use `prompt_type=status_update` in `llm-calls` logs; a separate `status-updates` lifecycle log tracks emitted/discarded/fallback outcomes and Web TTS cache/provider activity without changing conversation usage totals.
  - See: [`STATUS_UPDATES.md`](STATUS_UPDATES.md)

**2026-07-03 (v2.55.1):**
- ✅ **xAI Grok CLI OAuth subscription provider**
  - Added `XAI_AUTH_MODE=auto|api_key|oauth`; OAuth uses xAI's documented CLI chat proxy, discovered `grok models` chat IDs, and owner-only `~/.grok/auth.json` credentials without logging or returning tokens.
  - Primary chat, Jarvis function calls, verified `grok-4.5` uploaded-image vision, status summaries, and completion-guard evaluators can use OAuth; xAI server-side search, image/video generation, and TTS remain explicitly API-key-only.
  - Web settings discover supported OAuth chat models from `grok models`, reject coding-agent Composer as a drop-in chat model, keep OAuth/API-key model capabilities separate, and show sanitized auth/quota status in the System tab.
  - OAuth usage retains exact provider token counts while marking dollar cost and account quota unavailable under subscription billing; expired sessions delegate refresh to the official Grok CLI.

**2026-07-02:**
- ✅ **Credential-aware tool and provider availability**
  - Tools with hard requirements declare an optional `availability` block in `skills/*.tool.json` (`all_of_env`, `config_files`, `webhook_registry`, `provider_requirements`); `lib/tool_availability.py` gates registration at runtime — metadata is not sent to the LLM.
  - `./bin/manage-tools.py --mode <mode> list` shows 🔒 unavailable tools; `./bin/sync-tools.py <mode>` prints excluded tools and disables stale Tool RAG rows.
  - Web UI `provider_availability` annotates unconfigured LLM/image/video/TTS/completion-guard providers; saves validate before mutation.
  - Static-config gates: `ssh_remote` (`config/ssh.json`), `send_email` (webhook registry), `crawl_url`/`screenshot_url` (`CRAWL4AI_URL`), `create_social_clip` (`MONEYPRINTER_API_URL`), plus prior API-key tools.
  - See: [`FUTURE_ENHANCEMENTS.md`](FUTURE_ENHANCEMENTS.md) section 9, [`../skills/README.md`](../skills/README.md) → Availability, [`TOOL_MANAGEMENT.md`](TOOL_MANAGEMENT.md), [`SYNC_ARCHITECTURE.md`](SYNC_ARCHITECTURE.md)

**2026-07-01:**
- ✅ **Managed Bash/Zsh Jarvis commands**
  - Replaced the stale copied `.bashrc` alias block with one tracked Bash/Zsh command file and an idempotent managed RC source block; current launcher names and external `~/jarvis-venv`/uv routing now have one source of truth.
  - Added text-only cloud/local CLI helpers plus cloud/local stack, Web, API, stop-all, and all-session-status commands. Shell selection supports auto-detection, `--shell bash|zsh`, and `--rc-file` for custom setups.
- ✅ **Integration test safety cleanup**
  - Reviewed every legacy script under `tests/integration/`; removed 13 obsolete, redundant, or state-mutating harnesses that rewrote env files, rotated active databases, depended on retired model/tool names, or made ungated paid calls.
  - Removed the retired Memory Tools, Intelligence, and Compare Models commands from the dashboard; retained provider-thinking and OpenCode integration entry points with deterministic defaults and explicit `--health`/`--live` boundaries.
  - Refreshed active testing documentation to point at focused fresh-process pytest coverage and read-only diagnostics; cross-app `server`/`services` namespace collisions remain test-collection isolation debt rather than a runtime blocker.
- ✅ **Catalog-backed Anthropic thinking**
  - Removed the stale model-name allowlist from `lib/thinking.py`; Anthropic thinking type, aliases, and valid effort levels now come from the audited shared model catalog, including Claude Fable 5.
  - `--debug-thinking` remains opt-in and process-local, Web UI provider reasoning remains off by default, and OpenAI/xAI/Ollama keep their provider-native reasoning controls rather than sharing misleading legacy model-name rules.
- ✅ **OpenAI model-catalog availability audit**
  - Added `./bin/audit-openai-models.py --mode cloud`, machine-readable `--json`, and human `--show-all` output backed by the official OpenAI Models API.
  - The audit checks every curated ID/alias against the active account and detects newer general-purpose GPT families while filtering specialized image, audio, realtime, embedding, moderation, Sora, search, Codex, and legacy inventory from actionable chat-catalog drift.
  - OpenAI's endpoint exposes identity, creation time, ownership, and account availability only; context limits, capabilities, modalities, and pricing remain explicitly curated instead of being inferred from incomplete API data.
  - The first live audit found all 15 existing Jarvis options available and surfaced `gpt-5.5` plus its dated snapshot for manual metadata/pricing review; it was not automatically added or made default.
- ✅ **Model-aware Anthropic cache cost tracking**
  - Anthropic cache creation and cache reads are now billed from the selected model's catalog pricing instead of a hardcoded Sonnet fallback; Fable, Opus, Sonnet, and Haiku therefore report their own rates.
  - First requests show cache-write cost with no claimed savings, while follow-ups separately show cache-read cost and actual savings. SDK-reported 5-minute and 1-hour cache-write token classes use Anthropic's respective 1.25x and 2x input multipliers.
  - The Web token hover now includes cache-write/read tokens and their dollar costs, and the displayed total includes normal input, cache activity, and output instead of materially understating provider charges.
- ✅ **xAI model-catalog drift audit**
  - Added `./bin/audit-xai-models.py --mode cloud` plus `--json` output to compare Jarvis with xAI's live `/v1/models` and `/v1/language-models` responses.
  - Canonical IDs, aliases, context windows, text/image modalities, standard token prices, and the higher pricing tier at 200K tokens are now validated directly from xAI's API.
  - Corrected both Grok 4.20 variants to their canonical `0309` IDs, 1M context, and current pricing while preserving the previous model names as supported aliases; existing env pins remain valid and display as configured aliases instead of duplicate custom models.
  - Cost estimation now applies xAI's long-context tier when a prompt reaches its API-reported threshold. The Grok 4.20 multi-agent model remains explicitly excluded until Jarvis has a reviewed integration path.
- ✅ **Anthropic model-catalog drift audit**
  - Added `claude-fable-5` and Claude Haiku 4.5 as opt-in models while keeping Claude Sonnet 5 as the default; canonical API IDs, input/output limits, capabilities, and current pricing now live in the shared catalog.
  - `./bin/audit-anthropic-models.py --mode cloud` compares Jarvis against the live Anthropic Models API; `--json` provides complete machine-readable output for maintenance by an LLM or CI job.
  - The audit treats token/capability mismatches and unreviewed API models as drift, preserves account-specific availability as a warning, and tracks pricing verification separately because the Models API does not return prices.
  - Raised the Anthropic SDK minimum to `0.115.0`, corrected Sonnet 4.5 to its live 1M input/64K output limits, and recorded Sonnet 5's introductory pricing expiry so it cannot silently remain stale after August 31, 2026.
- ✅ **Gemini Omni Flash video support**
  - Added `gemini-omni-flash-preview` as an opt-in catalog model using the Interactions API for 3-10 second 720p text-to-video and image-to-video with native audio.
  - Veo 3.1 Fast remains the default; catalog metadata now selects the correct Gemini API backend and keeps Web attachment resolution choices aligned with the pinned model.
  - Generator failures now stop after the single authorized attempt and preserve the provider's error, preventing duplicate-recovery synthesis or silent provider switching from claiming blocked media is still being generated.
  - Gemini SDK bytes now flow directly into the final save path instead of creating gallery-visible `gemini_temp` intermediates; failed or interrupted processing therefore leaves no placeholder video behind.
  - Web image-to-video now passes the user's instruction verbatim; because this path intentionally skips preliminary vision analysis, the routing LLM can no longer invent unsupported subjects or scene details while expanding the prompt.
  - LLM Enhance is now multimodal when an image is attached, grounding rewrites in visible evidence; shared vision dispatch also routes cloud-mode Ollama through `OLLAMA_CLOUD_MODEL` instead of incorrectly falling through to xAI.
  - `analyze_image`, Web upload analysis, and multimodal Enhance now share one provider implementation. If the selected Enhance model rejects image input, the UI warns that it used a conservative text-only rewrite instead of returning a generic server error.
- ✅ **Shared image/video model catalog**
  - Image and video defaults, capabilities, retired-model replacements, and provider-specific pricing metadata now live beside chat models in `lib/model_catalog.py`.
  - Provider model env variables are optional pins: unset values follow curated catalog defaults, while explicit new/custom IDs remain usable before the catalog is updated.
  - CLI, wake-word tools, generated-media API health routes, and Web UI provider metadata now resolve through the same catalog.
- ✅ **Gemini image SDK migration**
  - Replaced the hand-built Gemini image REST request with `google.genai.Client`, typed `GenerateContentConfig`/`ImageConfig`, SDK error handling, image editing, grounding, expanded aspect ratios, and 1K/2K/4K output support.
  - Raised the shared `google-genai` minimum to `2.10.0` and replaced retired Gemini image defaults with `gemini-3.1-flash-image`.
- ✅ **Catalog-driven attachment video resolutions**
  - Image-to-video resolution choices now follow the effective provider model loaded from the active cloud/local env.
  - Gemini's default Veo model exposes 720p, 1080p, and 4K; optional pins such as Sora Pro or Grok Imagine Video 1.5 expose their own supported resolutions.
- ✅ **Dependency-upgrade compatibility and environment fixes**
  - Gemini video duration is now sent as an integer so Veo respects supported 4/6/8-second selection instead of always defaulting to 8 seconds.
  - Migrated deprecated Pydantic `class Config` schema examples to `ConfigDict`, updated the UV lock/install flow to use `~/jarvis-venv`, and corrected dashboard memory-sync commands for explicit `--from/--to` mode arguments.
  - Docker retains its requirements-based install while also receiving the package-layout metadata needed for reproducible project builds.
- ✅ **Self-play safety and mode-isolation hardening**
  - Self-play now uses a fail-closed reviewed read-only tool allowlist; persistent mutations, artifact generation, external actions, dangerous tools, and newly discovered unreviewed tools are excluded.
  - Orchestrator children receive the selected mode through the shared environment exporter, and self-play skips automatic cloud↔local Memory synchronization while retaining its intended selected-mode learning and feedback records.
  - Updated the implemented CLI and safety documentation to replace the obsolete mocked-sandbox and `--iterations` examples.
- ✅ **Web video posters and clean Socket.IO shutdown**
  - Generated videos in Web chat now use cached ffmpeg first-frame posters, matching the reliable thumbnails already shown by the Canvas video gallery in native and Docker installs.
  - Replaced deprecated eventlet monkey-patching with Flask-SocketIO threading plus `simple-websocket`, eliminating gRPC/subprocess greenlet-finalization tracebacks during Ctrl-C or tmux shutdown while preserving native WebSocket transport.

**2026-06-27 (v2.55.1):**
- ✅ **Cloud/local startup mode plumbing**
  - Added one canonical `JARVIS_MODE` resolver with cloud as the backward-compatible default and strict validation for explicit local startup.
  - `./bin/start --local` starts the full local-env stack; the TUI exposes **Start All Services (Local)** and **Start UI Only (Local)** without changing existing cloud actions.
  - Web, Canvas, Memory, Intelligence, and Docs honor explicit or inherited startup mode and report `startup_mode` from health/status endpoints.
  - Memory and Intelligence initialize pristine selected-mode databases; browser data-mode choices remain independent through URL/localStorage selectors.
  - API/services validate the selected env before migration or sync and initialize/migrate only the selected Memory database.
- ✅ **Docker mode and live-config parity**
  - Compose `JARVIS_MODE` reaches every UI; entrypoint validation happens before init and DB checks follow only selected sync modes.
  - Compose mounts `config/` read-only, allowing local-only installs without a `cloud.env` stub and exposing read-only runtime registries without rebuilding.
  - Mutable price-alert thresholds live in shared `data/price-alerts.yaml`; fresh installs seed it from tracked `data/price-alerts.yaml.example`, and the one-tool Compose override is no longer needed.
  - See: [`docs/INSTALL_GUIDE.md`](INSTALL_GUIDE.md), [`docs/docker/README.md`](docker/README.md)

**2026-06-24:**
- ✅ **`create_social_clip` tool** — MoneyPrinterTurbo B-roll social videos (stock footage + narration + subtitles + BGM)
  - Added `skills/create_social_clip.py` + `create_social_clip.tool.json`; distinct from `generate_video` (xAI/Sora/Veo AI animation)
  - POST `/api/v1/videos` → poll task → download `final-*.mp4` → stash; 20-minute executor timeout, 429 retry, relative URL safety net
  - Env: `MONEYPRINTER_API_URL`, `MONEYPRINTER_VOICE`, `MONEYPRINTER_MAX_WAIT_SEC` in `config/cloud.env`
  - Web UI: modular inline `<video>` player for any tool result with stash video / `video/*` mime (not hardcoded per tool)
  - Cursor skill: `.cursor/skills/social-clip-video/SKILL.md`
- ✅ **Multi-image vision (Web UI)** — upload and analyze several images in one turn
  - Web UI supports multi-image analyze (up to 6 cloud / 2 local); image-to-image and image-to-video stay single-reference
  - Lightweight socket upload metadata with server-side hydration from disk; limits enforced on upload and send paths
  - Centralized multimodal request building in `lib/vision_multimodal.py`; `analyze_image` accepts an `images` list
  - Follow-up grounding: batch stash labels/tags, `uploaded_images` metadata, ordinal stash-ref hints in context
  - Skip native server-side tools when web-upload vision is pre-attached (avoids redundant xAI `view_image` loops on analyze flows)
  - Image Action Modal provider defaults respect AI config overrides after settings save
  - See: [`docs/JARVIS_WEB_UI.md`](JARVIS_WEB_UI.md), [`docs/api/QUERY.md`](api/QUERY.md), [`docs/api/IMAGES.md`](api/IMAGES.md)

**2026-06-25:**
- ✅ **OpenCode service/auth/workspace hardening**
  - OpenCode systemd rendering now uses the target user's home instead of root expansion, starts the server in `~/jarvis-workspace`, creates `projects/`, `temp/`, and `deployments/`, and points temp env vars at `~/jarvis-workspace/temp`.
  - Jarvis OpenCode API calls, read-only session checks, and status polling helpers now support `OPENCODE_SERVER_USERNAME` / `OPENCODE_SERVER_PASSWORD` Basic auth.
  - Added a git-safe `config/opencode.config.json.template`, xAI/Grok Build examples, provider-key setup notes, and install/update syncing for workspace-protection plugins.
  - `opencode` is single-call capped per user request to prevent duplicate build/summary passes; `check_opencode_sessions` is documented as fallback-only.
  - `check_opencode_sessions` now enriches OpenCode's weak `/session` metadata with Jarvis JSONL log summaries: original task, response preview, duration, token usage, model, and completion status.
  - See: [`opencode/OPENCODE.md`](opencode/OPENCODE.md), [`opencode/OPENCODE_PLUGINS.md`](opencode/OPENCODE_PLUGINS.md), [`FUTURE_ENHANCEMENTS.md`](FUTURE_ENHANCEMENTS.md)

**2026-06-22:**
- ✅ **Experimental Docker Web stack (v2.55.1)**
  - Added root `Dockerfile` and `docker-compose.yml` for the Web UI, API, Canvas, Memory, Intelligence, Docs, and background services using the existing host `data/`, config, logs, and audio bind mounts.
  - Added Docker service DNS/internal API routing with optional Bearer auth, a foreground daemon supervisor, Compose restart policies, crash-safe init locking, and native-watchdog separation.
  - Added the tracked `skills/profiles/docker.json` baseline plus configurable `JARVIS_DOCKER_TOOL_PROFILE`; hybrid installs can use `default` Tool RAG while blocking container-incompatible tools only in Web UI Settings.
  - Added in-container shell/CLI examples, Docker-specific environment guidance, LAN UI access notes, and separate planning/design documentation.
  - Pinned FastAPI below `0.137` pending prometheus instrumentator compatibility and corrected the unavailable `fpdf2` dependency pin.
  - See: [`docs/docker/README.md`](docker/README.md), [`docs/archive/docker/DOCKER_PLANNING.md`](archive/docker/DOCKER_PLANNING.md)

**2026-05-21:**
- ✅ **Cross-turn correction learning (v2.55.1)**
  - `USER_CORRECTION_LEARNING_MODE=shadow|apply` — shadow records correction candidates without changing routing; apply downgrades the linked prior experience and can append deduped lessons to `jarvis-learned-lessons.md`.
  - Web UI and wake-word paths pass `experience_id` so turn-2 corrections can reach the prior turn's experience record.
  - Topic-pivot guard skips new questions that look like corrections without an explicit correction cue.
  - See: [`docs/FUTURE_ENHANCEMENTS.md`](FUTURE_ENHANCEMENTS.md), [`docs/USER_PROFILE_SYSTEM.md`](USER_PROFILE_SYSTEM.md)
- ✅ **Profile Card + `user_model` cache**
  - `jarvis-intel/user_profile.md` → `## Profile Card` injects a compact operator lens at router and synthesis boundaries without affecting Tool RAG embeddings.
  - Compiled card text is cached in `user_model.profile_card_cache` (hash + timestamp); `bin/reconcile-profile` prints drift vs memories/lessons for human review.
  - Git-tracked `jarvis-intel/user_profile.md.example` for first install; copy and edit before ingest.
  - See: [`docs/USER_PROFILE_SYSTEM.md`](USER_PROFILE_SYSTEM.md), [`docs/INSTALL_GUIDE.md`](INSTALL_GUIDE.md)
- ✅ **Memory type auto-inject filtering**
  - Every `remember()` stamps `memory_type` metadata (`preference`, `fact`, `artifact`, `transient`) with confidence and reason.
  - `AUTO_MEMORY_TYPE_FILTER_ENABLED` excludes `artifact` and `transient` rows from auto-memory injection; legacy unlabeled rows are classified on the fly.
  - `./bin/backfill-memory-types` stamps metadata on existing rows; manual `search_memory` / `semantic_recall` still see all types.
  - See: [`docs/MEMORY_SYSTEM.md`](MEMORY_SYSTEM.md), [`docs/FUTURE_ENHANCEMENTS.md`](FUTURE_ENHANCEMENTS.md)
- ✅ **Memory sync health + `user_model` sync**
  - `./bin/check-memory-sync-health.py` reports intel hash drift, memory row drift, and structured `user_model` drift between cloud/local DBs.
  - `./bin/sync-memory-db.py` now syncs the `user_model` table alongside memories and conversations.
  - See: [`docs/SYNC_ARCHITECTURE.md`](SYNC_ARCHITECTURE.md), [`docs/DUAL_DATABASE_SYSTEM.md`](DUAL_DATABASE_SYSTEM.md)
- ✅ **xAI model catalog: `grok-build-0.1`**
  - Added Grok Build 0.1 (256K context; $1.00 / 1M input, $2.00 / 1M output) to `lib/model_catalog.py` for UI dropdowns, context labels, and cost estimation.
  - Catalog is the source of truth for `XAI_REASONING_EFFORT` — only grok-4.3-family models send it; Build 0.1 omits the parameter.
  - See: [`docs/XAI_PROVIDER.md`](XAI_PROVIDER.md)

**2026-05-10:**
- ✅ **OpenAI Responses API routing support (v2.55.1)**
  - OpenAI tool-capable router turns can now use `/v1/responses` when `OPENAI_API_MODE=responses` and `OPENAI_RESPONSES_TOOLS=true` are enabled.
  - Optional in-flight continuation supports `previous_response_id` + `function_call_output` for Jarvis client tool loops without making saved Web UI follow-ups depend on provider-side state.
  - Responses tools are converted through a dedicated adapter with non-strict function schemas, usage/cost parsing, cached-input/reasoning token reporting, diagnostics, and safe Chat Completions fallback boundaries.
  - Optional OpenAI-hosted tools (`web_search`, `file_search`, `code_interpreter`) have separate config gates and budgets so they do not piggyback on xAI native-search controls.
  - Provider-facing tool result previews now preserve exact source candidates and valid JSON when bounded, reducing repeated search/canvas hallucination risk.
  - Web upload vision supports multi-image analysis, keeps socket payloads lightweight, and OpenAI vision follows `OPENAI_MODEL` when `VISION_MODEL` is blank or provider-mismatched while forwarding supported `VISION_DETAIL`.
  - See: [`docs/OPENAI_PROVIDER.md`](OPENAI_PROVIDER.md), [`docs/archive/OPENAI_RESPONSES_ADAPTER_PLAN.md`](archive/OPENAI_RESPONSES_ADAPTER_PLAN.md), [`docs/CONVERSATION_STATE_ARCHITECTURE.md`](CONVERSATION_STATE_ARCHITECTURE.md)

**2026-05-03:**
- ✅ **xAI SDK client-tool routing + in-flight continuation**
  - xAI SDK path now handles Jarvis client-side tools even when xAI server-side tools are disabled for a turn.
  - `XAI_STORE_MESSAGES=true` + `XAI_NATIVE_CONTINUATION=true` can link in-flight Jarvis tool loops with `previous_response_id` and structural `tool_result(...)`.
  - Saved Web UI follow-ups still use Jarvis recent conversation context and follow-up extraction; persisted xAI response IDs across web turns are a future option.
  - OpenAI-compatible xAI chat completions remains the fallback when the SDK path is unavailable or fails outside stored-continuation turns.
  - See: [`docs/XAI_PROVIDER.md`](XAI_PROVIDER.md), [`docs/CONVERSATION_STATE_ARCHITECTURE.md`](CONVERSATION_STATE_ARCHITECTURE.md)

**2026-04-28:**
- ✅ **`crypto_chart` tool + price chart API** - Native CoinGecko historical series for price, market cap, and volume
  - Added `skills/crypto_chart.py` with chart-ready structured output and `skills/crypto_chart.tool.json`
  - Added `GET /api/prices/crypto/{symbol}/chart` and docs in `docs/api/PRICES.md`
- ✅ **Web UI + Canvas SVG crypto charts** - Local/offline-friendly chart rendering without a third-party chart library
  - Web UI now renders `crypto_chart` tool results directly as inline SVG charts
  - Canvas supports saved/inferred chart embeds and proxies chart loads locally for auth-safe rendering
- ✅ **Follow-up grounding prefers structured tool results** - Recent conversation context now treats saved `tool_results` as source-of-truth over prior assistant prose
  - Helps follow-up actions like Canvas saves build from structured JSON instead of markdown summaries

**2026-04-27:**
- ✅ **Jarvis Docs assistant (viewer `:5004`)**
  - Dedicated LLM assistant in [jarvis-docs](../jarvis-docs/) with read-only retrieval from `docs/`, citation links normalized to explorer paths (relative to `docs/`, fuzzy filename matching for stable “open doc” behavior).
  - **Retrieval:** uses QMD when `qmd` is on PATH; otherwise skips semantic search and uses **ripgrep** (`rg`) when available; graceful handling when neither is installed (metadata in UI, no hard failure). Documented under [docs/qmd/README.md](qmd/README.md) (*Jarvis Docs assistant*).
  - Chat UX: loading state (**Working…** + spinner) while the LLM round-trip runs; muted **Ask** control styling. Assistant is not duplicated in jarvis-web; API: `POST /api/docs/assistant/chat`.

**2026-04-23:**
- ✅ **xAI native TTS + expressive final-speech tags**
  - Added first-class xAI TTS provider support across CLI, Web UI TTS, Voice API, and status playback paths using `TTS_PROVIDER=xai` and `XAI_API_KEY`.
  - Added `XAI_TTS_STYLE_TAGS_ENABLED` so the final chat/speech path may use supported xAI delivery tags such as `[pause]`, `[laugh]`, `<soft>...</soft>`, `<whisper>...</whisper>`, and `<slow>...</slow>` when useful.
  - Web UI chat display strips TTS-only tags while stored `speech` keeps the tagged version for playback; generated Web UI TTS stores `audio_url` on the message.
  - Status updates can be voiced by xAI TTS, but the status LLM remains plain 5-8 word progress phrases unless a separate status-tag option is added later.
  - See: [`docs/XAI_PROVIDER.md`](XAI_PROVIDER.md)

**2026-04-21:**
- ✅ **Tool RAG compact retrieval + live trace tuning**
  - Tool retrieval now embeds a compact current-request signal instead of the whole routing prompt whenever possible, preventing learned strategies, auto-memory, and long recent-history blocks from diluting tool similarity.
  - `TOOL_SIMILARITY_THRESHOLD` applies to compact/current/trailing request signals; `TOOL_SIMILARITY_THRESHOLD_FULL` applies only to true `full_fallback` routes.
  - `logs/tool-rag/` traces now show `signal_source`, threshold, final tool list, `tool_schema_chars`, estimated schema tokens, and largest schema contributors for live tuning.
- ✅ **Follow-up extraction refactor + richer web/search context**
  - Follow-up data extraction moved out of `jarvis-web/server/sockets/chat.py` into pure service functions in `jarvis-web/server/services/followup_extractor.py`, while compatibility delegates keep older tests/docs references working.
  - Added compact follow-up evidence for `crawl_url` nested results and MCP Brave web/news/local search URLs so later turns see prior crawled URLs/search candidates instead of re-searching blindly.
  - Completion Guard and follow-up evidence paths now treat xAI/Anthropic native server-side tools as real grounding instead of “zero tools used.”
- ✅ **xAI native search/tool budget guardrails**
  - Added configurable caps for xAI server-side/native tool loops (`XAI_SERVER_SIDE_MAX_TOOL_TURNS`, optional per-request search budget) so provider-native search cannot multiply across every router turn.
  - Conversation metadata can record provider-native search usage (`server_side_tools`) for auditability, even when no client-side Jarvis skill was called.
- ✅ **Intelligence provenance, sync, and safe maintenance**
  - Insights now retain provenance back to source experience / web conversation IDs, source query, source tool sequence, preferred tool sequence, supporting tools, and reflection provider/token/cost metadata.
  - `bin/sync-intelligence-db.py` was updated for the new provenance/evidence schema so cloud ↔ local intelligence sync preserves the new audit trail.
  - `bin/run-intelligence-maintenance.py --dry-run` plus Jarvis Dashboard support lets decay/anomaly/meta-cognition jobs be previewed safely before write operations.
- ✅ **Intelligence Dashboard performance**
  - Experiences and Insights now page in 50-row chunks with automatic infinite scroll instead of eager 500/1000-row list loads.
  - Sidebar counts/facets use lightweight summary endpoints; sort/filter operations are applied server-side so sorting covers the full dataset before pagination.
- ✅ **Canvas LAN/public links**
  - Canvas now separates `CANVAS_INTERNAL_URL` (tool/API calls from the Jarvis host) from `CANVAS_PUBLIC_URL` (clickable links shown to users).
  - Direct `/page_...` links serve the Canvas UI and select the page after auth, fixing headless-server LAN links such as `http://192.168.70.228:8890/page_...`.
- ✅ **Auto-context and time handling cleanup**
  - Auto-context freshness checks now use the shared `lib/time_utils.py` path instead of local timestamp patchwork.
  - Auto-context instruction noise was reduced so CLI/TUI context remains useful without injecting unavailable-tool hints.

**2026-04-18:**
- ✅ **Intelligence feedback metadata bridge**
  - Feedback now stores compact QA context on the linked experience (`raw_data.feedback.latest`) instead of only flipping low-rated outcomes
  - Low ratings still downgrade the experience and raise reflection priority; high ratings can mark satisfaction without erasing Completion Guard repair/failure metadata
  - Reflection prompts now see feedback rating, summary, issues, analysis, and Completion Guard status together
- ✅ **Reflection tool trace + argument recovery**
  - Experiences now preserve sanitized per-tool attempt traces with arguments, failures, and recovery path
  - Reflection can learn reusable tool-argument lessons and insight scoring no longer rewards a preferred tool that failed before recovery
- ✅ **Reflection token/cost visibility**
  - Generated insights now store the reflection provider/model plus input/output/total tokens and estimated cost
  - Token and cost columns accumulate across every reflection update for the insight; provider/model reflect only the most recent run
  - Intelligence UI insight cards show a compact reflection usage badge labeled as lifetime usage, with full token split in the detail modal
- ✅ **Presentation artifact learning**
  - Experiences record response style and word limits so reflection can recognize short `auto`/`casual` answers
  - When `canvas`/`stash` are available, reflection may learn “brief spoken summary + full structured artifact” for multi-item, multi-field requests
  - Added `docs/ADVANCED_AI_TECHNIQUES.md` design note for presentation artifact learning
- ✅ **TTS URL-example cleanup**
  - TTS normalizer now removes parenthesized bare URL examples such as `(e.g., yelp.com/search?find_desc=...)` from spoken output
  - Added regression coverage in `tests/test_tts_normalizer.py`
- ✅ **Intelligence docs refresh**
  - Updated `docs/INTELLIGENCE_LAYER.md` and `docs/FEEDBACK_SYSTEM.md` for Completion Guard + feedback coordination, tool traces, and presentation-context reflection

**2026-04-17:**
- ✅ **Stash viewer (Web UI)** — Dedicated page at `/stash/view/<space_id>/<file_id>` renders Markdown and text stash artifacts (JSON pretty-print, etc.); non-text artifacts link to raw `GET /api/stash/...`. Documented in `docs/STASH_SYSTEM.md` (see *Stash viewer (Jarvis Web UI)*).
- ✅ **Tool profile overlays** — `JARVIS_TOOL_PROFILE` selects JSON overlays under `skills/profiles/` so dev / MCP-minimal / full tool sets share one codebase; see `skills/README.md` (*Tool profiles*) and `bin/manage-tools.py profile …`.
- ✅ **Learned insights + profiles** — Learned-insight injection respects Web UI block settings and the active tool profile so hidden tools do not surface as “insights” when they are not available.
- ✅ **`sync_tools` + profiles** — `bin/sync-tools.py` surfaces profile-related behavior more clearly when aligning the tools DB with a profile.
- ✅ **Provider error vs. long Markdown answers** — Connectivity or troubleshooting answers that mention phrases like “gateway timeout” in prose are less likely to be misclassified as provider failures; short explicit error lines are still detected (`lib/provider_errors.py`, tests in `tests/test_provider_error_fallbacks.py`).

**2026-04-16:**
- ✅ **Web thread context + gap timing** — Prior turns sent to the orchestrator omit the in-flight user message so the current request is not duplicated; optional per-message timestamps support resumed-thread hints. Context may include local time plus relative gap when the anchor is unambiguous (`orchestrator_v2._format_conversation_context`, `jarvis-web` conversation builder). ISO parsing for those timestamps uses `lib/time_utils.safe_iso_to_local_datetime`.
- ✅ **Tool RAG docs** — `docs/TOOL_RAG_STRATEGY.md` explains compact retrieval signals, `signal_source` trace labels (`trailing_request`, `original_user_request_tail`, `legacy_history_strip`, `full_fallback`), threshold selection (`TOOL_SIMILARITY_THRESHOLD` vs `TOOL_SIMILARITY_THRESHOLD_FULL`), and the live `logs/tool-rag/` trace. Router comments clarify that only `find_tools()` embeddings use the compact query; the routing LLM still sees the full transcript.
- ✅ **Auto-memory injection transparency** — Injected memories include compact **match hints** (sort **rank**, raw **embed** cosine for semantic rows; tags for pinned / intel keyword / intel semantic). Header line shows the configured semantic bar. **Merge/sort** (score, then importance) and prompt assembly order (learning → memory → base) are documented in `docs/AUTO_MEMORY_INJECTION_FEATURE.md`. `docs/CONVERSATION_STATE_ARCHITECTURE.md` notes web CONTEXT vs DB HISTORY. Example envs use `AUTO_MEMORY_SIMILARITY_THRESHOLD=0.45`.

**2026-04-12:**
- ✅ **Jarvis Web UI v2.12** - Dedicated `/logs` browser for local log triage
  - **Read-only `/logs` page**: Auth-protected log browser inside Jarvis Web UI
  - **Allowed file types only**: Lists folders containing `.jsonl`, `.log`, and `.md`, while skipping hidden files and `.pid`
  - **Stable folder navigation**: Folder column stays A-Z while files remain newest-first
  - **Folder search**: Search ranks matching files and filters viewer content to matching records/lines
  - **JSONL viewer**: Dotted keys are nestified and rendered as YAML-style cards with modal expansion
  - **Markdown/log viewing**: Markdown renders cleanly, logs lazy-load, and mobile uses folder → file → viewer drill-down
  - See: `docs/JARVIS_WEB_UI.md`

**2026-04-10:**
- ✅ **Duplicate-tool recovery + transcript follow-up hardening**
  - Exact duplicate tool calls no longer immediately end the request. Jarvis now blocks the repeated call, injects a duplicate-guard note into the next routing turn, and gives the model bounded recovery turns before falling back to duplicate-prevention synthesis.
  - Duplicate-prevention fallback text is now more useful for transcript/stash-style runs and no longer returns weak tool speech like `Read file.md` as the final user-facing answer.
  - `_build_turn_context()` now tells the model that large tool payload previews may be intentionally truncated, includes explicit `result_truncated`, `result_chars_shown`, and `result_chars_total` metadata for each prior tool result, and uses valid JSON `Result Preview` objects instead of raw sliced JSON fragments.
  - Tool-failure retries now preserve in-flight orchestrator state such as `tool_call_counts`, `tools_used`, accumulated data, and prior tool context, which keeps repeated tool cards and WebUI/tool-history behavior consistent across retries.
- ✅ **Stash follow-up context + model override fixes**
  - Web conversation follow-up extraction now preserves real `stash` tool results instead of treating them like upload-only metadata, which improves same-conversation follow-up questions against prior transcript/file reads.
  - Model prompt override resolution now strips bare runtime suffixes like `-latest` and `-cloud` in addition to `:latest`, so folders such as `config/models/xai/grok-4.3/` correctly apply to active runtime IDs like `grok-4.3`.

**2026-04-09:**
- ✅ **Ollama local-model routing hardening**
  - Ollama tool-routing requests apply `OLLAMA_CONTEXT_WINDOW` to local models such as `gemma4`; cloud-backed models omit `num_ctx`
  - Native Ollama tool calls now send explicit exact-schema tool-contract guidance plus stricter retry hints after invalid tool-name or arg-shape failures
  - Tool-routing requests now explicitly disable Ollama thinking unless thinking is intentionally enabled, which helps preserve context for large Tool RAG turns
- ✅ **Fresh-install sync repair path**
  - `sync-memory-db.py` now documents the current `--from/--to` usage at the top of the script and repairs fresh local targets by creating missing `conversations.metadata`, `alerts`, and `reminders` schema before syncing
  - Conversation sync now tolerates older source DBs that do not yet have a `metadata` column
  - `sync-evolution-db.py` now creates prompt-evolution tables on the target during sync and exits cleanly when the source DB has not been initialized with `prompt_versions` yet

**2026-04-07:**
- ✅ **Amazon product follow-up + Canvas improvements**
  - `serpapi_search` now supports stronger Amazon shopping flows with top-level sort and price fields, better Amazon sort mapping, and improved focused-product handling
  - Jarvis WebUI can now render a single Amazon product preview card with image, title, price, rating, review count, ASIN, and direct link for `amazon_product` lookups
  - Amazon search follow-up context now preserves a compact shortlist of prior product candidates so later turns like "tell me more about the Aura frame" or "save that one to canvas" have the right ASIN, URL, and thumbnail available
  - Canvas page creation/update now supports explicit embedded images and also auto-recovers inline `Image: https://...` product-image lines into a real embedded image block
- ✅ **Conversation recovery + feedback polish**
  - Random pre-collected feedback now emits the normal feedback card payload in WebUI instead of silently logging without showing the card
  - Usage metadata now survives max-turn-limit and duplicate-prevention exits so the WebUI token counter no longer shows `0 tokens` for those completed runs
- ✅ **Model catalog hardening**
  - Added curated support for newer xAI model IDs like `grok-4.20-non-reasoning-latest`
  - Tightened exact-id vs alias matching, quieter Ollama metadata handling, and safer fallback/default resolution across the shared model catalog

**2026-04-06:**
- ✅ **Embedding fallback visibility**
  - Runtime embedding fallback is now tracked separately from stored DB embedding health
  - `semantic_recall`, semantic deep-memory search, and semantic memory-update fallback now surface `fallback_embeddings` in tool results/logs
  - Non-tool semantic paths like auto memory injection and Tool RAG now emit explicit fallback warnings instead of degrading silently
- ✅ **OpenAI tool-schema compatibility**
  - OpenAI function-call schemas are now sanitized before dispatch so unsupported top-level schema features do not break tool routing
  - Added documentation for the strict cross-provider schema subset in `TOOL_CALLING_SYSTEM.md` and `skills/README.md`
- ✅ **Web UI model-default + context fixes**
  - Web UI provider defaults now respect env-configured model defaults instead of silently using the first provider model
  - Context-window hover now resolves model-specific limits correctly, including GPT-5.4 Nano at 400K
- ✅ **Prompt enhancer + shopping/tool guidance**
  - The `✨` prompt enhancer now emphasizes the user's primary intent, preserves exact entities like model numbers, reduces distracting context, and stays tool/provider agnostic
  - Strengthened `serpapi_search` descriptions for Amazon-style product lookup, comparison, and purchase intent
- ✅ **Model prompt overrides implemented**
  - Added runtime model/provider-specific prompt overrides with YAML config loading for routing, QA synthesis, and Completion Guard evaluation
  - Override resolution now supports exact model folders plus deterministic aliases for dated model names and runtime suffixes like `:latest` and `:cloud`
  - New design and usage details documented in `MODEL_PROMPT_OVERRIDES.md`
- ✅ **Shared cloud model catalog**
  - Curated cloud model metadata now lives in one shared catalog used by the Web UI dropdowns, default-model fallbacks, cost estimation, and context-window reporting
  - New env or override models that are not yet curated now still appear in the settings UI as custom entries instead of disappearing from the selector
  - This reduces model-maintenance drift between `settings_manager.py`, `cost_estimator.py`, and `measure-baseline-tokens`
  - `config/README.md` now documents `lib/model_catalog.py` as the source of truth for adding or removing curated cloud chat models

**2026-04-05:**
- ✅ **Scheduled task notification UX**
  - Scheduled-task run history and task details now show notification outcomes such as `Email sent to Boss`, `Alert created`, `Webhook sent`, and `cooldown suppressed`
  - Runtime notification cooldown state is now ignored by git so local delivery artifacts do not pollute the worktree

**2026-04-04:**
- ✅ **Scheduled task notifications**
  - Scheduled tasks can now send email on success/failure using contact names from `config/contacts.json`
  - Scheduled tasks can create failure alerts and send named webhooks on success/failure
  - Notification delivery is deduped per scheduled occurrence to avoid restart-loop email or alert spam
  - `everyday at 9am` now parses like `every day at 9am` in the shared schedule parser
- ✅ **Intelligence sync + embedding hardening**
  - `sync-intelligence-db.py` now preserves insight timestamps (`created_at`, `updated_at`, `last_applied`) so decay and pruning history survives cloud ↔ local sync
  - Reflection queue sync now copies **only pending** entries and reports them clearly as pending reflections
  - Ollama embeddings now use the newer embed API when available, support `OLLAMA_EMBEDDING_CONTEXT_WINDOW`, and retry with compacted text before falling back
- ✅ **Provider-native tool awareness for guard + reflection**
  - Completion Guard now treats xAI/Anthropic native server-side tools as real evidence instead of false "zero tools used" hallucination cases
  - Intelligence reflection now sees provider-native tool usage as metadata-only evidence
  - Native provider tools are intentionally excluded from preferred/avoided Jarvis tool learning
- ✅ **OpenCode integration hardening**
  - OpenCode now respects `OPENCODE_PROVIDER` and `OPENCODE_MODEL` instead of drifting to stale defaults
  - `agent_mode` is forwarded correctly for `build` vs `plan` sessions, and Jarvis accepts either `id` or `sessionId` from the OpenCode API
  - Jarvis no longer injects memory into OpenCode build tasks by default; optional memory injection now requires `OPENCODE_INCLUDE_MEMORY=true`
  - Router guidance now treats `check_opencode_sessions` as a fallback-only verification tool instead of a normal post-build step
  - Duplicate-prevention synthesis now prefers real OpenCode build output over thin session-status summaries
  - `opencode` tool summaries now extract stronger user-facing results from OpenCode response parts, including project path and run hints when available
- ✅ **OpenCode UX improvements**
  - Stop/cancel handling now interrupts long-running local tool execution cleanly, which fixes lingering OpenCode status updates after cancellation
  - Completion Guard now excludes `opencode` so cancelled or stalled builds do not silently relaunch a second OpenCode task
  - Jarvis Web UI tool-card details now show a clickable `Open session` link for OpenCode results, one click away from the full OpenCode UI flow
  - OpenCode docs now reflect the current runtime model: one blocking build call, generic Jarvis progress updates, fallback-only session checks, and direct session URL access
- ✅ **Alerts: first-class tool + Memory UI tab**
  - Added `create_alert` as a real Jarvis tool on top of the existing FastAPI alert manager path
  - Added a dedicated `Alerts` tab in Jarvis Memory UI for browsing and managing proactive alerts alongside reminders and scheduled tasks
  - Alert dedupe now supports generic `metadata.dedupe_key` suppression so workflows and tools can prevent same-condition duplicates cleanly
- ✅ **Weather watch workflow** - Added `/weather-watch` as a reusable default-location workflow
  - Uses `JARVIS_DEFAULT_LOCATION` for location-aware daily weather reporting
  - Builds a Canvas report with forecast highs, lows, wind, conditions, and alert outcomes
  - Can raise condition-specific alerts for cold, wind, heat, and severe weather using `create_alert`
  - Workflow executor gained deterministic condition evaluation and safer placeholder handling for indexed forecast values
- ✅ **Shared TTS normalizer** - Added `lib/tts_normalizer.py` as the single speech cleanup layer
  - `sanitize_for_speech()` now delegates to the shared normalizer for backward compatibility
  - API voice routes, alerts, reminders, follow-up alerts, self-healing notices, wake greetings, Web UI TTS, and shell question flows now use the same normalization rules
  - Added `bin/tts-normalize.py` so shell-based callers can reuse the same logic
  - New regression coverage in `tests/test_tts_normalizer.py`
- ✅ **Named TTS profiles** - Added context-aware speech profiles for awkward domains
  - `weather_watch` strips forecast ISO dates that sound robotic in speech
  - `camera_alert` smooths UniFi-style phrasing like `Person: Front Door` and `Camera Offline: Driveway`
  - `price_quote` makes market speech more natural, such as `$80.54` → `80 dollars and 54 cents`
  - `timestamped` converts ISO dates and datetimes into natural spoken timestamps
- ✅ **Voice API profile support** - `/api/voice/speak` now accepts an optional `profile` parameter
  - Profiles are validated against an explicit allowlist before use
  - External callers can opt into the same normalization behavior used internally by alerts and workflows
  - Adding a new profile now requires updating the shared allowlist in `lib/tts_normalizer.py`

**2026-04-03:**
- ✅ **Completion Guard: AI Config evaluator overrides**
  - Added per-mode Web UI overrides for `Completion Guard: Eval Provider` and `Completion Guard: Eval Model`
  - System tab now shows the effective Completion Guard eval provider/model alongside other current runtime values
- ✅ **Ollama cloud judge compatibility**
  - AI Config now separates `Ollama (Cloud)` and `Ollama (Local)` model lists by mode
  - Completion Guard Ollama cloud evals now use cloud-friendly JSON mode and a larger output budget so reasoning-heavy models still return final JSON
  - Added defensive fallback/logging for cloud models that return empty `message.content` with reasoning in `message.thinking`

**2026-04-02:**
- ✅ **Completion Guard: tighten-only settlement**
  - `tighten_only` names **post-repair** wording-only settlement; judge JSON `recommended_action: tighten_only` (no repair run) is stored as **`auto_accepted`** with `evaluator_recommended_action` for clarity
  - Auto mode avoids surfacing a visible repaired answer unless the repair introduced a real evidence delta or tool-path delta
  - No-tool rewrite repairs now default to `tighten_only` unless the repaired answer explicitly cites a direct source or verified action
- ✅ **Completion Guard: evaluator/provider split**
  - Auto evaluation now clearly follows its own provider/model path: `JARVIS_COMPLETION_GUARD_EVAL_PROVIDER` → `FEEDBACK_PROVIDER` → main provider
  - This allows a separate audit model from the main chat model, while still supporting fully local overrides when configured
- ✅ **Provider-error formatter fallback**
  - Added protection so provider-side formatter/condense errors do not leak raw gRPC or safety error strings into the final visible answer

**2026-03-31:**
- ✅ **Scheduled Tasks: foundation implemented**
  - Added `schedule_task` with `create`, `list`, `update`, `cancel`, `delete`, `run_now`, and `list_runs`
  - Added durable `scheduled_tasks` and `scheduled_task_runs` tables plus cloud/local sync support
  - Added FastAPI endpoints for CRUD, queue-now, and run history
  - Added `services/scheduled_task_runner.py` and wired it into `bin/jarvis-services`, `bin/start`, `bin/restart-services`, and `services/self_healing_daemon.py`
  - Added Jarvis Memory UI `Scheduled` tab with create/edit modal, run controls, status badges, filters, sorting, inline run history, due-soon highlighting, and local-time display
- ✅ **Shared schedule/time parsing cleanup**
  - Added `lib/time_utils.py` and `lib/schedule_parser.py` as the shared scheduling foundation
  - Reminder creation/listing/scheduler were updated to use cleaner timezone-aware parsing before Scheduled Tasks was built on top
  - Parser now supports absolute dates like `April 4th at 4pm`, `4/4 at 4pm`, and `04/04/2026 at 4pm` with human-friendly summaries
- ✅ **Reminders: full Memory UI management tab**
  - Added a dedicated Jarvis Memory `Reminders` tab with local-time display, status filters, sorting, detail modal, and CRUD-style management
  - Added acknowledge-one and acknowledge-all-triggered flows directly in the UI
  - Added permanent delete support for reminders in the manager and API paths, in addition to cancel
  - Replaced the raw recurrence-rule text box with a friendly recurrence picker for `Once`, `Daily`, `Weekly`, and `Monthly`
  - Added proper `DAILY` rescheduling support in `services/reminder_scheduler.py` so daily reminders now repeat correctly

**2026-03-30:**
- ✅ **Completion Guard: auto mode + learning bridge**
  - Added real `auto` mode that audits the raw final answer in the background and only auto-repairs when a deterministic repair score crosses a configurable threshold
  - Added `JARVIS_COMPLETION_GUARD_AUTO_THRESHOLD` plus Web UI override support for the threshold
  - Manual `Yes` is now persisted instead of being client-only, so accepted outcomes survive reload/export
  - Completion Guard outcomes now update the recorded intelligence experience (`accepted`, `auto_accepted`, `repaired`, `ticket_created`; `expired`/`superseded` as neutral metadata)
  - Reflection prompts now see Completion Guard notes/metadata so future insights can learn from repaired and ticketed runs
- ✅ **Completion Guard: manual repair loop** - Phase 2 manual repair flow now works in Jarvis Web
  - Inline `Completed correctly?` card runs one bounded repair pass on `No`
  - Repair uses the original query, raw LLM response, tool outputs, and user note
  - Tickets now include repair strategy and repair attempt details when unresolved
- ✅ **Completion Guard: smarter repair routing**
  - Added repair-strategy classifier (`intel_file_lookup`, `verification_repair`, `artifact_update`, `memory_lookup`, `generic_repair`)
  - Repair prompt now injects preferred/avoid tool-family hints instead of retrying blindly
  - Added synthesis fallback so existing tool data can be turned into a final answer without more tool calls
- ✅ **Completion Guard: exclusions + exports**
  - Workflows and fire-and-forget/sensitive tools are skipped
  - Excluded tools can now be extended from `.env` via `COMPLETION_GUARD_EXCLUDED_TOOLS`
  - Markdown conversation export now includes Completion Guard status, note, ticket path, and repair message ID when available
- ✅ **Completion Guard: Web UI polish**
  - Stop button now cleanly cancels in-flight repair orchestrators
  - Repair responses no longer create duplicate Completion Guard cards in chat
  - Completion Guard card now renders persisted `accepted`, `repaired`, `cancelled`, `ticket_created`, `expired`, and `superseded` states correctly
  - Manual guard cards now show a countdown and settle stale prompts neutrally when they expire or are superseded by continued chat
- ✅ **Intelligence Dashboard: Completion Guard visibility**
  - Experience and insight timestamps now show configured-local time while preserving UTC context
  - Experience details expose Completion Guard metadata and full stored raw experience JSON
  - Experiences can be sorted and filtered by Completion Guard status
  - Stats now include an optional lifetime Completion Guard summary with repaired count and status breakdown
- ✅ **Completion Guard: final learning model**
  - Internal repair prompts no longer create standalone learning experiences
  - Successful repairs fold corrected answer, corrected tools, and corrected tool results back into the original experience
  - Reflections now compare the original failed path against the repaired path to learn a better first-pass strategy
- ✅ **Completion Guard + Feedback coordination**
  - In Jarvis Web, explicit feedback is now deferred until Completion Guard reaches a settled state
  - Feedback grades the settled outcome instead of a temporary pre-repair answer
  - Web disables orchestrator-side random feedback sampling while Completion Guard is active so random pre-collection does not race settlement
  - Feedback prompts now receive Completion Guard metadata and update the linked experience record
  - Original message card updates to `Repaired` / `Unresolved` / `Ticket created`
  - Internal repair-response messages no longer render their own empty Completion Guard card

**2026-03-29:**
- ✅ **Web UI AI Config: response style overrides** - Added per-mode overrides for voice formatting behavior
  - `JARVIS_RESPONSE_STYLE`, `JARVIS_QA_WORD_LIMIT`, and `JARVIS_MULTI_TURN_WORD_LIMIT` can now be overridden from `jarvis-web` Settings → AI Config
  - Overrides are saved per mode in `jarvis-web/config/web_config.json`
  - Reset button now clearly resets to the active mode's env defaults
- ✅ **Runtime prompt alignment** - Router/system prompt now reflects live response formatting limits
  - When asked directly, the LLM sees the active response style plus current Q&A and multi-turn word caps instead of stale generic defaults
  - Final orchestrator formatting also reads these values through `get_config_value()` so Web UI overrides and actual speech formatting stay in sync

**2026-03-21:**
- ✅ **SerpApi query optimization** - Conversational prompts can be compacted to keyword-style queries before search
  - Tool output includes `query_was_optimized`; `query` (original) and `query_effective` (optimized) for transparency
  - `optimize_query` in `serpapi_search.tool.json` (default on) to disable when needed
- ✅ **Canvas & workflows** - Workflows pass `source_query` into canvas create (fixes `source_query: null`)
  - Trimmed payloads sent to the canvas LLM so long Amazon-style results do not truncate mid-list
- ✅ **Canvas URLs** - Rejects truncated URL patterns (`https://...`, tokens with `...`); tool guidance requires full resolvable links
- ✅ **Web UI: canvas links** - Canvas page links open in a new window/tab
- ✅ **Chat bubble markdown** - Lists, bullets, and URL styling in message bubbles
- ✅ **Speech sanitization** - `lib/security_utils.sanitize_for_speech()` strips markdown links, http(s)/www URLs, bare domains, `stash://` refs, IPs, and noisy paths/tokens
  - Applied before auto WebUI TTS, `/api/tts`, and orchestrator `--speak`
- ✅ **MCP client deadlock fix** - Non-reentrant lock in `lib/mcp_client.py` caused hangs (e.g. Brave Search); `_send_request` no longer deadlocks during `start()` / `_initialize()`
- ✅ **Orchestrator duplicate-tool handling** - Prefers the last real tool speech when deduplicating; `_extract_useful_data` pulls nested lists/fields for synthesis
  - Reuses last speech only if it looks human-readable; otherwise falls back to synthesis instead of JSON-like text
- ✅ **Pipeline & tool cards** - `pipeline_executor` always includes `error` and `speech` in step results; failed workflow steps with no data send `{ "error": "..." }` to tool cards and persist it in saved conversations
- ✅ **create_reminder** - Normalizes `a.m.` / `p.m.` (and spaced variants) before time parsing
- ✅ **Log streamer (Web UI)** - Reads `args` or `arguments`; success from `success` or `result.ok`; error from `error` or `result.error`; quick actions in details for canvas debugging; full args in expandable details
- ✅ **Dependencies & models** - yt-dlp update; Qwen model config refresh; Anthropic web search integration version bump

**2026-03-13:**
- ✅ **SerpApi Search Tool** - New generic `serpapi_search` tool (Amazon + engine-based search)
  - Supports `amazon` listings and `amazon_product` ASIN lookups
  - Uses `SERP_API_KEY` with proxy-aware HTTP requests
  - Normalized output for cleaner WebUI/CLI synthesis
- ✅ **SerpApi Tool Documentation** - Added short-link tool guide
  - New doc: `docs/tools/serp-api-tool/README.md`
  - Added tool reference in docs index and skills tool list

**2026-03-01:**
- ✅ **Bookmark Search Shortcut** - `*` prefix in Web UI (Firefox-style)
  - Type `*` in chat to search Firefox bookmarks; `*docker` searches for "docker"
  - Autocomplete shows "Search bookmarks" with 🔖 icon
  - New `bookmark_search` workflow with `*` trigger
- ✅ **Docs Reorganization** - `docs/tools/` folder for tool-specific docs
  - Moved phone, spotify, video, status-tool, ssh, docker-tool, generate-image-tool, convert-file-tool, etc.
  - Updated all references from `docs/X` to `docs/tools/X`

**2026-02-28:**
- ✅ **Clickable URLs in Tool Cards** - URLs in tool card details and message details now open in browser
  - `Utils.escapeHtmlAndLinkify()` converts URLs to `<a target="_blank">` links
  - Styled with accent color and hover state
- ✅ **bookmark_search Tool** - Search Firefox bookmark export (Netscape HTML)
  - Keyword/phrase search, filters by tags, folders, domains
  - Actions: search, list_tags, list_folders, stats

**2026-02-26:**
- ✅ **New Workflows** - `youtube_ingest` and `memory_scan`
  - `/youtube_ingest <url>` - Download video + transcript, summarize, create study brief
  - `/memory_scan` - Run memory dedupe analysis, save reports to stash + canvas
- ✅ **memory_deduper Tool** - Memory quality maintenance
  - Detects exact duplicates, probable duplicates, potential conflicts
  - `action=analyze` (safe): scan and propose; `action=apply` with approval
  - Supports dry_run, apply_mode (exact_only, exact_and_probable)
- ✅ **git_release_notes Tool** - Generate release notes from GitHub URLs
  - Analyzes releases, commit/PR/issue breakdown, risk flags
  - Optional stash and canvas output
- ✅ **Gemini Image Model** - `gemini-3.1-flash-image` for image generation
- ✅ **xAI Image Model** - Removed deprecated model

**2026-02-24:**
- ✅ **youtube_video Tool** - Download YouTube videos or audio via yt-dlp
  - Saves to stash for Web UI preview/download
  - Updated yt-dlp version, uv lock

**2026-02-23:**
- ✅ **qr_code_generator Tool** - Generate QR codes for URLs, text, WiFi, contacts
  - Saves PNG to stash for printing, canvas, email

**2026-02-22:**
- ✅ **API Rate Limiter** - Rate limiting on API query endpoint
- ✅ **Tool Builder Fixes** - Parsing issues fixed, max tokens support
- ✅ **API Rate Limiting Docs** - Updated documentation

**2026-02-21:**
- ✅ **Mobile UI Fixes** - Intelligence and Memory dashboards on small screens
- ✅ **Anthropic Sonnet 4.6** - Added model option
- ✅ **Image Upload Fixes** - EXIF orientation, vision follow-up context, Anthropic model selection

**2026-02-15:**
- ✅ **Auto-Memory Injection** - Relevant memories loaded into LLM context automatically
  - No tool calls needed for recall; "What do you know about Jessi?" works without search_memory
  - **Always-include**: Addressing/response-style only (call me sir, tone, language) – 1–2 items max
  - **Semantic search**: Topic-specific memories (dog, Spotify, etc.) only when relevant to query
  - Recency weighting: recent memories rank slightly higher; 60+ day old fade
  - Config: `AUTO_MEMORY_INJECTION_ENABLED`, `AUTO_MEMORY_LIMIT`, `AUTO_MEMORY_SIMILARITY_THRESHOLD`, `AUTO_MEMORY_ALWAYS_INCLUDE_LIMIT`
  - Works for CLI, WebUI, and wake word
  - See: `docs/AUTO_MEMORY_INJECTION_FEATURE.md`
- ✅ **Clear Chat & Import Knowledge** - Web UI sidebar footer
  - Clear Chat: clears messages, keeps conversation; API `POST /api/conversations/<id>/clear`
  - Import Knowledge: upload .txt/.md to jarvis-intel/, background ingestion; API `POST /api/intel/upload` (max 1MB)
- ✅ **"No Specific Preference" Filter** - Auto-memory skips these from always-include; router steers "forget" to forget tool
- ✅ **cleanup-all Updates** - Unreferenced Web uploads use 60-day retention;
  saved-conversation uploads and stash references are protected

**2026-02-11:**
- ✅ **Jarvis Intel System**
  - Added new documentation for the Jarvis Intel System
**2026-02-10:**
- ✅ **Video Follow-up Context** - LLM now gets previous video results for smarter follow-ups
  - `source_image` extracted from image-to-video results (enables regeneration from same image)
  - `tool_args` saved in error data for post-mortem debugging
  - Video URL expiration tracked: `(expired)` injected into context after 4 hours
- ✅ **Video Editing Guardrails** - Prevents common xAI editing mistakes
  - Tool description rewritten: xAI editing requires public URLs, cannot change duration/aspect/resolution
  - 4-hour hard cutoff on provider URLs (xAI ~8h observed, 4h safe limit)
  - `_resolve_video_source` now logs failures to stderr instead of silently returning None
- ✅ **Single-Call Tool Cap** - Expensive tools limited to 1 successful call per request
  - Prevents LLM loops when results don't match expectations (e.g., duration ignored by provider)
  - Affects: `generate_video`, `generate_image`, `generate_music`, `send_email`
  - Failures don't count — recursive retry gets fresh counts
- ✅ **Generated Videos API** - New metadata fields in list and detail endpoints
  - `stash_ref`, `source_url`, `source_url_created`, `edit_url_status` exposed
  - `edit_url_status`: `available`, `expired`, or `null` based on 4h cutoff
  - `video_url` parameter docs updated with xAI limitations
- ✅ **@TOOL_CONFIG Tagging System** - Codebase convention for tool-specific config locations
  - Search `@TOOL_CONFIG` to find every spot that needs updating when adding a new tool
  - 12 tags across orchestrator, chat, executor covering timeouts, extraction, caps, formatting
  - See: `docs/TOOL_CALLING_SYSTEM.md`
- ✅ **Debug Output Fix** - All `print()` in `generate_video.py` redirected to stderr
  - Prevents JSON output corruption when tool subprocess writes debug info to stdout

**2026-02-09:**
- ✅ **OpenAI Sora Video Generation** - Third video provider with native audio
  - 4/8/12s durations, 16:9 or 9:16 aspect ratios, 720p/1080p resolution
  - Image-to-video support (auto-resizes input to match Sora's dimension requirements)
  - Video remix support (extend/edit existing videos via video ID)
  - Native audio generation (dialogue, sound effects)
  - $0.10/s (sora-2) or $0.30-0.50/s (sora-2-pro for 1080p)
  - Videos also viewable at platform.openai.com/playground/videos
  - Web UI: Added OpenAI option to video provider dropdowns
  - See: [`docs/tools/video/README.md`](tools/video/README.md)
- ✅ **Video Gallery OpenAI Support** - Provider badges now include OpenAI
  - Fixed provider detection to recognize `openai` tags in stash metadata
  - Client-side fallback also checks tags (not just filenames)
  - Temp file cleanup for Sora downloads
- ✅ **Gemini Image-to-Video Fix** - Now properly resolves stash refs and local files
  - Previously only handled HTTP URLs, now uses `_resolve_image_source()` like other providers

**2026-02-06:**
- ✅ **Image-to-Image Editing** - Edit existing images with all 3 providers
  - Upload an image in Web UI → select "Image to Image" → describe changes
  - **xAI**: Uses `/v1/images/edits` endpoint with `image: { url: "data:..." }` (separate from generation)
  - **Gemini**: Includes image as `inline_data` in contents array alongside text prompt
  - **OpenAI**: Uses `/v1/images/edits` endpoint with multipart/form-data
  - New `reference_image` parameter on `generate_image` tool (stash ref, path, URL, or data URI)
  - `_resolve_image_to_base64()` helper converts any image source to base64 + mime type
  - LLM instructed to keep edit prompts short and direct for best results
  - See: [`docs/tools/generate-image-tool/README.md`](tools/generate-image-tool/README.md)
- ✅ **Image Action Modal** - Upload image → choose action (Analyze, Image-to-Image, Image-to-Video)
  - Provider-specific settings (aspect ratio, resolution, duration, model) per action
  - Parameters enforced via `tool_overrides` (bypasses LLM parameter choices)
  - Context-aware follow-up: type edit instructions after selecting action
- ✅ **Video Gallery Lazy Loading** - Videos load on scroll instead of all at once
  - `IntersectionObserver` with 200px rootMargin loads videos before they're visible
  - `data-src` + `preload="none"` prevents any network requests until needed
  - Hover-to-play still works (loads src on demand if observer hasn't fired)
- ✅ **Image Gallery Lightbox Fix** - Options bar no longer overlaps the image
  - Changed from `position: absolute` overlay to flexbox layout (matches video gallery)
  - Bottom margin prevents bar from touching desktop taskbar

**2026-02-05:**
- ✅ **Internal Knowledge Search** - Q&A about Jarvis capabilities without executing tools
  - `search_docs` tool - Semantic search over 153 indexed docs using QMD
  - Answers questions like "What video sizes can I generate?" without calling generate_video
  - Uses vsearch (meaning-based) with 35% min score threshold
  - Works in both cloud and local modes (uses local QMD models)
  - See: `skills/search_docs.py`
- ✅ **Docs Search API** - REST endpoint for programmatic doc queries
  - `POST /api/docs/search` - Semantic search with topic filtering
  - `GET /api/docs/status` - Index health (153 files, 1317 vectors)
  - `GET /api/docs/topics` - List available topic filters
  - Rate limited: 3 requests/minute per IP (CPU-intensive search)
  - See: `api/routes/docs.py`
- ✅ **@jarvis_docs Prompt** - WebUI prompt for Q&A mode
  - Guides LLM to use search_docs instead of generative tools
  - Use: `@jarvis_docs What video durations can I generate?`
  - See: `jarvis-web/data/prompts/jarvis_docs.md`
- ✅ **QMD Index Cleanup** - Excluded private directories from search
  - Removed: `docs/personal/`, `docs/samantha-skill/`, `docs/vps2/`
  - Updated maintenance docs with exclusion procedure
  - See: `docs/qmd/README.md`

**2026-02-04:**
- ✅ **Server-Side Tools Logging** - Track xAI/Anthropic native tool usage
  - New dedicated log folder: `logs/server-side-tools/`
  - Tracks `web_search`, `x_search`, `code_execution` usage with counts
  - Auto-logged from LLM calls and workflow executions
  - Dashboard commands: "Server-Side Tools" and "Server-Side Summary" in 📋 Logs
  - Included in `cleanup-logs` for 60-day retention
  - Programmatic access: `LLMLogger().get_server_side_tools_summary(days=7)`
- ✅ **Workflow Server-Side Tool Toast** - Visual feedback for native tools in workflows
  - Workflows now pass through `server_side_tools` data to UI
  - Toast shows "🔍 Server-side: X Search, Web Search" after workflow completes
  - Previously only worked for single/multi-tool calls, now works for workflows too
- ✅ **WebUI Auth Logging** - Track authentication failures
  - Auth events logged to `logs/auth/auth-YYYY-MM-DD.jsonl`
  - Logs: login success/failure, token validation errors
  - Helps debug auth issues across web UIs

**2026-02-02:**
- ✅ **xAI Image Generation** - Fast & cheap image generation
  - Added `xai` provider to `generate_image` tool (grok-imagine-image model)
  - Batch generation: `n` parameter (1-10 images) for variations
  - All batch images saved to same stash space with individual refs
  - Works with all existing tools (canvas, email, gallery, CDN upload)
  - Set `IMAGE_TOOL_PROVIDER=xai` or use `provider: "xai"` per-request
  - Note: Quality parameter not supported by xAI (no 1K/2K/4K)
  - See: [`docs/api/GENERATED_IMAGES.md`](api/GENERATED_IMAGES.md)
- ✅ **Real-time Progress Events** - See tool execution as it happens
  - WebUI shows "Using weather...", "Using brave_search..." during processing
  - Tool cards appear with status (pending → complete with duration)
  - Toggle in Settings → UI → Progress Events
  - Duplicate tool calls tracked separately (e.g., `search_0`, `search_1`)
- ✅ **Stop Button** - Graceful processing cancellation
  - Red stop button (⏹) appears during processing
  - Cancels between turns, returns partial results
  - "Stopped after 2 tool(s). Results so far: ..."
- ✅ **Mobile Layout Fixes** - Better button visibility on small screens
  - Send button no longer cut off on iPhone 13 Pro (428px)
  - Mobile shows: Upload (🖼️), Enhance (✨), Send (➤), Stop (⏹)
  - Mic hidden on mobile (native keyboard has voice input)
- ✅ **Voice Compression Fix** - Preserves named entities in multi-tool summaries
  - Before: "Animation adventure at Regal" (useless!)
  - After: "Shelter, Iron Lung, Avatar: Fire and Ash at Regal Evergreen"
  - Compression now sees BOTH LLM response (names) + raw data (numbers)
  - Configurable via `JARVIS_MULTI_TURN_WORD_LIMIT` (default baseline 75)

**2026-02-01:**
- ✅ **Video Gallery UI** - Browse generated videos in jarvis-canvas
  - Grid view with hover preview and provider badges (xAI/Gemini)
  - Lightbox viewer with video controls below video
  - Search, sort by date/name/size/duration
  - Download and delete functionality
  - Access via `/video-gallery` or "🎬 Videos" link in Canvas header
  - See: [`docs/CANVAS_SYSTEM.md`](CANVAS_SYSTEM.md)
- ✅ **Video Catalog System** - Persistent metadata for generated videos
  - `video_catalog.json` stores provider, aspect ratio, tags per video
  - Auto-syncs with stash metadata, survives stash TTL cleanup
  - Shared between `jarvis-api` (8880) and `jarvis-canvas` (8890)
  - API now returns `provider`, `aspect`, `tags` in video listings
  - See: [`docs/api/GENERATED_VIDEOS.md`](api/GENERATED_VIDEOS.md)
- ✅ **Canvas Modular Architecture** - Refactored jarvis-canvas for maintainability
  - Migrated from monolithic 3,770-line file to proper Flask app structure
  - Matches pattern of jarvis-web, jarvis-memory, jarvis-intelligence
  - Separate CSS/JS/templates for canvas, gallery, video-gallery
  - See: [`docs/CANVAS_SYSTEM.md`](CANVAS_SYSTEM.md)
- ✅ **Image Gallery UI Improvements** - Delete button moved to right side
- ✅ **Video Generation Tool** - AI video generation with dual provider support
  - **xAI Grok Imagine Video**: 1-15s duration, 7 aspect ratios, video editing
  - **Gemini Veo 3.1**: 4/6/8s duration, native audio, up to 4K resolution
  - `generate_video` tool for text-to-video and image-to-video
  - Configure via `VIDEO_TOOL_PROVIDER=xai` or `VIDEO_TOOL_PROVIDER=gemini`
  - Saves to `data/generated_videos/` + stash + memory
  - Video player in jarvis-web chat UI
  - See: [`docs/tools/video/README.md`](tools/video/README.md)
- ✅ **Generated Videos API** - Full management of generated videos
  - `GET /api/generated-videos` - List/search videos with pagination + provider/tags
  - `GET /api/generated-videos/{name}` - Download video file
  - `GET /api/generated-videos/{name}/info` - Video metadata with provider/tags
  - `DELETE /api/generated-videos/{name}` - Delete video + update catalog
  - `POST /api/generated-videos/generate` - Generate new video
  - See: [`docs/api/GENERATED_VIDEOS.md`](api/GENERATED_VIDEOS.md)
- ✅ **Tool Builder Research Fix** - Smarter query extraction
  - Extracts documentation URLs and key technical terms
  - Removes sensitive info (API keys, IPs, paths)
  - Better error logging for build failures
- ⬆️ **xai-sdk >= 1.17.0** - Required for video generation (1.17.0+)

**2026-01-30:**
- ✅ **Optional API Authentication** - Bearer token auth for Jarvis API
  - Toggle via `JARVIS_API_AUTH=true/false` in cloud.env/local.env
  - `JARVIS_API_KEY` environment variable for the secret key
  - Localhost (127.0.0.1, ::1) always whitelisted - no auth needed
  - Public paths (`/`, `/api/health`, `/metrics`, `/docs`) always accessible
  - API keys never logged (security by design)
  - Remote services updated: jarvis-monitor, unifi-protect-webhook
  - See: [`docs/SECURITY_HARDENING.md`](SECURITY_HARDENING.md)
- ✅ **Docker Monitoring Fixes** - Prometheus container-to-host connectivity
  - `host.docker.internal` with `extra_hosts` for portable configs
  - Fixed jarvis_api scrape target for Docker environments
- ✅ **UFW Firewall Documentation** - Added to INSTALL_GUIDE.md
  - Essential ports for Jarvis services (8880, 5001, 5002, 5003, 8890, etc.)
  - Example UFW rules for quick setup

**2026-01-28:**
- ✅ **Generated Images API** - Full management of local generated images
  - `GET /api/generated-images` - List/search images with pagination
  - `GET /api/generated-images/{name}` - Download image file
  - `GET /api/generated-images/{name}/base64` - Get as base64
  - `DELETE /api/generated-images/{name}` - Delete image
  - `POST /api/generated-images/generate` - Generate new image with `upload_to_cdn` option
  - `GET /api/generated-images/{name}/cdn-url` - Get/create CDN URL (uploads once, caches)
  - `GET /api/generated-images/cdn-catalog` - List all uploaded images with URLs
  - CDN catalog (`cdn_catalog.json`) tracks uploaded images for instant URL retrieval
  - See: [`docs/api/GENERATED_IMAGES.md`](api/GENERATED_IMAGES.md)
- ✅ **Image Gallery UI** - Browse generated images in jarvis-canvas
  - New "🖼️ Gallery" link in Canvas header → `/gallery`
  - Grid view with thumbnails, search, sort by date/name/size
  - Lightbox for full-size viewing with keyboard navigation
  - Download, Get CDN URL (🔗), and Delete buttons
  - Responsive design for mobile/tablet
- ✅ **Canvas Pin → Stash Pin Sync** - Image preservation
  - When pinning a canvas page, automatically pins referenced stash spaces
  - Prevents images from breaking when stash TTL expires
  - Stash `is_expired` property fix for correct pinned space handling

**2026-01-27:**
- ✅ **Service Resilience** - Daemon crash prevention ⭐ ENHANCED
  - Retry logic with exponential backoff for DB locks (reminder_scheduler, follow_up_daemon, self_healing_daemon)
  - Self-healing daemon now monitors systemd services and sibling daemons
  - PID + cmdline verification prevents false positives from PID reuse
  - Graceful degradation on transient failures
- ✅ **API Request Logging** - Track all API traffic
  - `logs/api/access-YYYY-MM-DD.jsonl` and `errors-YYYY-MM-DD.jsonl`
  - Configurable loopback filtering (internal vs external traffic)
  - `jq` commands for live tailing, filtering, performance analysis
  - See: [`docs/api/LOGGING.md`](api/LOGGING.md)
- ✅ **Log Management** - Automated cleanup
  - `bin/cleanup-logs` - Clean logs older than 60 days
  - `bin/cleanup-audio` - Clean audio files older than 30 days
  - `bin/cleanup-all` - Master script (logs, audio, images, stash)
  - Cron automation documented in [`docs/service/README.md`](service/README.md)
- ✅ **Workflow API Fixes** - Better LLM integration
  - Auto-strip trigger prefixes from queries
  - Required input validation with clear error messages
  - `triggers` and `requires_input` fields in workflow list response
- ✅ **Cloudflare Images API** - Upload images to Cloudflare CDN for permanent hosting
  - `POST /api/images` - Upload from file, URL, base64, or stash reference
  - `POST /api/images/base64` - Convenience endpoint for generated images
  - Organized paths: `{uploader}/{date}/{category}/{filename}_{hash}`
  - Metadata storage: prompt, tags, provider, upload time
  - Multi-agent support: Samantha can upload via API, get CDN URL for canvas
  - Privacy warning: URLs are public - don't upload sensitive content
  - Jarvis tool: `upload_cloudflare` for direct use in workflows
  - See: [`docs/api/IMAGES.md`](api/IMAGES.md)

**2026-01-26:**
- ✅ **Samantha Multi-Agent Integration** - Secondary AI assistant on VPS2
  - `samantha` tool for real-time chat via OpenAI-compatible API
  - Samantha can POST back to Jarvis API (intel, canvas, alerts, voice)
  - Priority levels: urgent, normal, background
  - Configurable timeout (30-300s) for quick vs complex tasks
  - Fire-and-forget webhook option for Discord/Telegram posting
  - See: [`skills/samantha.tool.json`](../skills/samantha.tool.json), [`docs/api/VOICES.md`](api/VOICES.md)
- ✅ **Voice API Multi-Agent Support** - Per-request TTS provider/voice override
  - `/api/voice/speak` now accepts `tts_provider` and `voice` parameters
  - Enables different agents to speak with distinct voices
  - Jarvis uses ElevenLabs, Samantha uses Qwen3-TTS "Samantha" voice
  - Backwards compatible - existing calls work unchanged
  - See: [`docs/api/VOICES.md`](api/VOICES.md)
- ✅ **Qwen3-TTS Integration** - Local network TTS with 28 cloned voices
  - OpenAI-compatible API running on local network (free, fast, high quality)
  - Custom cloned voices: Jarvis, Paddington, Professor, Victoria, Samantha, and 23 more
  - Works in both cloud and local modes as alternative to ElevenLabs/Kokoro
  - `TTS_PROVIDER=qwen3-tts` in cloud.env or local.env
  - See: [`docs/qwen3-tts/QWEN3_TTS_INTEGRATION_GUIDE.md`](qwen3-tts/QWEN3_TTS_INTEGRATION_GUIDE.md)
- ✅ **Orchestrator `--speak` Flag** - Speak final result through local speakers
  - `./orchestrator/orchestrator_v2.py cloud "What time is it?" --speak`
  - Uses `say.sh` (cloud) or `say-local.sh` (local) for TTS
  - Status updates were already playing; this adds final response speech
  - Useful for CLI testing without wake word

**2026-01-25:**
- ✅ **File Conversion Tool** - Local media conversion with ImageMagick, FFmpeg, and Potrace
  - Converts images (JPG, PNG, WebP, GIF, BMP, TIFF, ICO), video (MP4, WebM, MOV, AVI, MKV), audio (MP3, WAV, FLAC, OGG, AAC)
  - Raster to vector (PNG/JPG → SVG) using Potrace tracing
  - Extract audio from video (MP4 → MP3/WAV)
  - **Web UI 🔄 button** - Dedicated convert button bypasses vision analysis
  - **Conversion modal** - Format selector with preview, descriptions, and advanced options
  - **Advanced options** - Resize, quality, bitrate, FPS, threshold, speckle size per format type
  - **Inline results** - Converted media displays with ⬇️ Download button
  - All processing local (no API costs), output saved to stash
  - See: `docs/tools/convert-file-tool/README.md`, `skills/convert_file.py`
- ✅ **Intel API** - Programmatic access to jarvis-intel knowledge files
  - CRUD operations for intel files (create, read, update, delete)
  - `GET /api/intel/stats` - Folder statistics (total files, facts, size)
  - `GET /api/intel` - List all files with ingestion stats
  - `POST /api/intel` - Create intel file with optional auto-ingest
  - `PUT /api/intel/{filename}` - Update file, re-ingest to memory
  - `DELETE /api/intel/{filename}` - Delete file and associated memories
  - `POST /api/intel/ingest` - Manual ingestion (sync or async mode)
  - See: [`docs/api/INTEL.md`](api/INTEL.md)
- ✅ **URL Ingest Workflow** - `/url_ingest <url>` to crawl, summarize, and ingest URLs to memory
- ✅ **System Prompt Validator** - LLM-powered debugging tool for prompt engineering
  - `./bin/validate-system-prompt --tools` - Comprehensive prompt audit
  - `--issue` flag for targeted debugging: `--issue "Jarvis called canvas before search"`
  - Root cause analysis: traces exact rules that caused unexpected behavior
  - Supports Anthropic, xAI, OpenAI providers
  - Outputs recommended fixes with diff format
  - See: `docs/SYSTEM_PROMPT_VALIDATOR.md`
- ✅ **Meta-Response Fix** - Jarvis now synthesizes actual answers when duplicate tool calls detected
  - No more "I've completed the task using X tool(s)" responses
  - Orchestrator extracts and summarizes accumulated research data
- ✅ **System Prompt Improvements** - Refined rules based on validator feedback
  - Memory-first exceptions for live-state queries (reminders, alerts, time)
  - Redundancy rule clarified with multi-step workflow exceptions
  - Music playback guidance updated for Spotify and ElevenLabs tools
  - crawl_url explicitly allowed when native search is enabled
- ✅ **OpenAI API Fix** - max_completion_tokens for gpt-5.x models

**2026-01-24:**
- ✅ **Feedback Tab in Intelligence Dashboard** - View all feedback logs in a friendly UI
  - 📊 New "Feedback" tab at http://localhost:5003
  - Filter by rating (All, Issues 1-3, Good 4-5) and time range (7, 30, 90 days)
  - Stats bar shows average rating, total count, and issue rate percentage
  - Feedback cards display rating stars, query, summary, tool badges
  - Click cards to expand detailed modal with:
    - Positive comments and detailed issues with suggestions
    - Tool-specific ratings with individual scores
    - Response preview and metadata (session, message ID, duration)
  - Search feedback by query text
  - No more terminal/log file browsing required
  - API endpoints: `/api/feedback`, `/api/feedback/stats`, `/api/feedback/files`
  - See: `jarvis-intelligence/README.md`

**2026-01-23:**
- ✅ **Manual Feedback in WebUI** - Trigger LLM-as-QA feedback from the web interface
  - 📊 Toggle button enables feedback for all messages
  - `--feedback` inline flag for per-message trigger
  - Purple feedback card shows rating (1-5), summary, issues, tool ratings
  - Click to expand/collapse feedback details
  - 6-second toast notification with rating summary
  - Manual feedback ALWAYS logged (overrides rating < 5 filter)
  - WebSocket events: `feedback:start`, `feedback:complete`
  - See: `docs/JARVIS_WEB_UI.md`, `docs/FEEDBACK_SYSTEM.md`
- ✅ **Token/Cost Tracking in WebUI** - Real-time token usage and cost display
  - Floating counter shows cumulative tokens + estimated USD cost
  - Context-aware: uses the selected model's window from `lib/model_catalog.py` (for example Grok 4.3 1M, curated Grok 4.20 2M, and GPT-5.4 Nano 400K)
  - Warning states at 50%/80% context usage with provider tooltip
  - Persists across conversation switches (saved with messages)
- ✅ **Workflow Token Tracking** - Pipeline executor now tracks LLM usage
  - Tracks usage from llm_prompt, validation, and decision calls
  - Returns usage in workflow response for WebUI display
- ✅ **Workflow Token Efficiency Documentation** - Highlighted 99%+ savings
  - Workflows bypass 35K baseline (system prompt + tool definitions)
  - Critical for local models with limited context windows
  - See: `docs/WORKFLOW_ORCHESTRATION.md`, `docs/BASELINE_TOKEN_USAGE.md`

**2026-01-21:**
- ✅ **Workflow Orchestration System** - Deterministic multi-tool pipeline execution ⭐ MAJOR
  - **Explicit command triggers**: `/archive`, `/research`, `/note`, `/health`
  - **Pipeline executor**: Executes workflow steps deterministically (no LLM routing variability)
  - **Variable system**: Extract from query, step results, nested paths (`${article.url}`)
  - **LLM parameter filling**: `llm_prompt` resolves variables before LLM fills remaining params
  - **Content validation**: Heuristic validation with `min_length`, `reject_patterns`
  - **Required step failure**: Aborts workflow on critical step failures
  - **Built-in transforms**: Output transforms for crawl_url and search tools
  - **WebUI integration**:
    - Hover tooltips show workflow steps and descriptions
    - Hover tooltips show prompt key points
    - Tool cards display correctly for workflow results
    - Workflow logs appear in server logs panel
  - **Replaced /commands system** - Workflows are the new standard for multi-tool tasks
  - See: `docs/WORKFLOW_ORCHESTRATION.md`, `data/workflows/AGENTS.md`
- ✅ **Workflow Recipes** - Pre-built workflow definitions
  - `/archive <url>` - Archive web pages to stash with Canvas summary
  - `/research <topic>` - Multi-source research with Brave search and crawling
  - `/note <content>` - Quick note to memory with Canvas
  - `/health [host]` - Server health check via SSH (host from `config/ssh.json`)
  - See: `data/workflows/*.json`, `data/workflows/README.md`

**2026-01-18:**
- ✅ **Comprehensive FastAPI Expansion** - Full programmatic access to Jarvis ⭐ MAJOR
  - **Memory API** - CRUD operations, keyword/semantic search, stats, categories
  - **Query/Chat API** - Send queries programmatically (`POST /api/query/quick`)
  - **Conversations API** - Read-only access to conversation history
  - **Stash API** - Read-only access to artifacts (images, PDFs, music)
  - **Canvas API** - Read-only access to canvas pages
  - **Intelligence API** - Reflection queue management (list, cancel)
  - **Dark mode Swagger UI** at `/docs/dark`
  - See: `docs/api/API_OVERVIEW.md`, individual API docs in `docs/api/`
- ✅ **Canvas Tool Read Action** - Read pages back for verification/troubleshooting
  - `action="read"` with `page_id` or `search` parameter
  - Direct file access fallback when canvas server is down
  - Enables self-correction workflows (read → verify → update)
- ✅ **Intelligence Interval Protection** - Decay job won't compound if run multiple times
  - `INTELLIGENCE_DECAY_INTERVAL_DAYS` config (default 14 days)
  - `--force` flag to override protection
- ✅ **Multi-day Reminders** - "Set a reminder for the next 5 days at 2pm"
  - Creates multiple individual reminders from single tool call
  - Supports patterns: "next N days", "every day for N days"
- ✅ **Smart Reminder Cancellation** - Clear feedback when reminder already acknowledged
- ✅ **Dashboard API Commands** - 27 API commands (was 6) for testing all endpoints

**2026-01-15:**
- ✅ **Stock Price Tool** - Stock, futures, and commodity prices via yfinance
  - Supports tickers (TSLA, AAPL) and company names (Tesla, Apple)
  - Futures: GC=F (gold), SI=F (silver), CL=F (oil), NG=F (natural gas)
  - Forex pairs: EURUSD=X, USDJPY=X, etc.
  - Returns price, change, volume, market cap, P/E, 52-week range
  - See: `skills/stock_price.py`
- ✅ **Status Recap Tool v1.4** - Comprehensive daily status aggregator ⭐ ENHANCED
  - Weather, crypto (BTC, SOL), stocks/futures (TSLA, gold, silver)
  - Alerts, reminders, system health (CPU, RAM, disk, uptime)
  - Saves full report to Canvas + Stash for follow-up queries
  - Optional AI-generated dashboard image (Gemini)
  - Native grounding search for news when enabled
  - Direct speech mode prevents LLM price mangling
  - See: `docs/tools/status-tool/README.md`
- ✅ **Tool Builder v2.0** - Network/proxy auto-fix ⭐ ENHANCED
  - Auto-detects network errors during tool verification
  - Injects proxy configuration instructions on retry
  - Uses `get_proxy_config()` / `http_request` patterns aligned with `docs/NETWORK_PROXY.md`
  - See: `docs/TOOL_BUILDER.md`, `docs/NETWORK_PROXY.md`

**2026-01-07:**
- ✅ **SSH Remote Tool** - Execute commands on remote hosts via SSH
  - Secure credential management (keys in filesystem, passwords in .env)
  - Multi-command execution, apt management, sudo support
  - Stateless sessions - no orphaned connections
  - See: `docs/tools/ssh/README.md`
- ✅ **Docker Control Tool** - Comprehensive Docker management
  - Container lifecycle: list, start, stop, restart, logs, inspect, stats
  - Compose: up, down, restart, pull, build with force-recreate
  - Images, networks, volumes, exec, system prune
  - See: `docs/tools/docker-tool/README.md`
- ✅ **@ssh prompt** - Web UI prompt for guided remote operations
- ✅ **YouTube Transcript Tool** - Download video transcripts as .srt/.md files

**2025-12-31:**
- ✅ **Deep Memory Search** - Unified multi-source search (memory, conversations, intel, canvas, stash)
- ✅ **ElevenLabs Music Generation** - AI music creation with stash integration and web playback
  - See: [`docs/tools/generate-music-tool/README.md`](tools/generate-music-tool/README.md)
- ✅ **Audio Playback Controls** - Enhanced TTS controls with pause/resume/stop
- ✅ **Prompt System Enhancements** - Context-first injection, new prompts (email, daily, music)

**2025-12-21:**
- ✅ **Intelligence Dashboard** - Visual dashboard for self-learning system
  - **Experience sorting**: Date, Turns (complexity), Tool Count
  - **Experience filtering**: Success/Failed, Tool Count (none/single/multi), Specific Tool dropdown
  - **Insight sorting**: Times Applied, Times Helpful, Has Preferred/Avoided Tools, Confidence, Recently Updated
  - **5-tier confidence**: Elite (96-100%), High (85-95%), Good (75-84%), Medium (50-74%), Low (0-49%)
  - **Differentiated confidence bars**: Green shades for positive, red/orange for negative constraints
  - **Tool visibility on cards**: Shows preferred (👍) and avoided (👎) tools inline
  - **Full tool performance**: Shows ALL tools (no limit) with prefer/avoid counts and net score
  - **Improved text contrast** for better readability
  - **Mobile responsive** at ≤730px: hamburger menu, slide-out sidebar
  - Launch: `./bin/jarvis-intelligence` (localhost:5003)
  - See: `jarvis-intelligence/README.md`
- ✅ **Memory Browser UI** - Web interface for memory management
  - **View/search/edit/delete** memories from `knowledge_base`
  - **FTS5 search** for fast keyword lookups (no LLM required)
  - **Intel file manager**: create, edit, upload, delete, ingest `.md`/`.txt` files
  - **Conversation browser** with full detail popup
  - **Statistics dashboard** with category breakdown and embedding health
  - **Dual database support**: switch between cloud/local modes
  - **Memory health indicators**: size badges (S/M/L/XL), missing embedding warnings
  - **Re-embed button**: regenerate embeddings after manual text edits
  - **Mobile responsive** at ≤730px: hamburger menu, slide-out sidebar
  - Launch: `./bin/jarvis-memory` (localhost:5002)
  - See: `jarvis-memory/README.md`
- ✅ **Canvas Mobile Responsive** - Hamburger menu and slide-out sidebar at ≤730px
- ✅ **Cross-UI Navigation** - 🧠 Memory and 📊 Intelligence links in all dashboard headers

**2025-12-19:**
- ✅ **Jarvis Web UI v1.9** - Server Logs Panel & Developer Tools ⭐ ENHANCED
  - **Server Logs Panel**: Real-time LLM + Tool log streaming at bottom of UI
  - **LLM logs**: Model, tokens, cost, duration, tool called - color-coded
  - **Tool logs**: Name, duration, success/error, expandable result details
  - **Source toggles**: Enable/disable LLM, Tools, OpenCode, Feedback
  - **Resizable panel**: Drag to resize, state persisted in localStorage
  - **Slash commands**: `/canvas`, `/search`, `/recall`, `/detailed`
  - **@prompts**: `@research`, `@quick`, `@compare` - inject methodologies
  - **✨ Enhance with AI**: Transform rough input into optimal prompts
  - **Conversation search**: Quick filter + deep search across all messages
  - **Export/Import**: Download as JSON/Markdown, restore from JSON
  - See: `docs/JARVIS_WEB_UI.md`

**2025-12-18:**
- ✅ **Jarvis Web UI v1.6** - Image upload, vision, analyze_image tool
  - **Image upload**: Drag-drop/paste/click to attach one or more images
  - **Mode-aware vision**: Cloud=Grok/Claude, Local=llava
  - **Auto-stash uploads**: Images saved to stash + memory_db for cross-tool use
  - **analyze_image tool**: Analyze URLs, files, stash refs, and multi-image comparisons with SSRF protection
  - **Expand details button**: Show full LLM response before voice shortening
  - **generate_image fix**: Now saves source + metadata for semantic recall
  - See: `docs/JARVIS_WEB_UI.md`

**2025-12-17:**
- ✅ **Jarvis Web UI v1.2** - Mode-aware web interface ⭐ ENHANCED
  - **Mode-aware TTS**: Cloud=ElevenLabs, Local=Kokoro or Qwen3-TTS via provider-specific URL settings
  - **Per-mode settings**: `cloud`/`local` sections in web_config.json
  - **Dynamic Ollama models**: Fetches available models from Ollama server
  - **Clean mode switching**: Intelligence singleton resets on mode change
  - **STT_PROVIDER config**: Ready for push-to-talk (faster-whisper/openai)
  - System tab shows mode-specific .env values
  - See: `docs/JARVIS_WEB_UI.md`

**2025-12-16:**
- ✅ **Google Gemini Image Generation** - AI image generation with Gemini 3 Pro
  - "Generate an infographic about bitcoin history"
  - "Create a cute robot dog" → saves to stash + memory
  - Supports: aspect ratios, styles, negative prompts
  - **Google Search Grounding** - Real-time data in images (weather, prices, etc.)
  - Multi-tool workflows: generate → email, generate → print, generate → canvas
  - Auto-saves to stash with memory index for cross-session recall
  - See: `skills/generate_image.py`
- ✅ **Stash + Memory Architecture** - Unified artifact workflow ⭐ ENHANCED
  - **Stash** = Workshop (temporary files, 7-day TTL)
  - **Memory** = Index (permanent references to stash locations)
  - Tools now save artifacts to stash AND create memory entries
  - Cross-session recall: "Where is that bitcoin image?" → memory finds stash ref
  - Graceful degradation: `safe_resolve_file()` handles expired stash items
- ✅ **PDF Create Memory Persistence** - PDFs now indexed in memory
  - Created PDFs auto-save to memory with stash reference
  - "What PDFs have I created?" → finds via memory search
- ✅ **Printer Stash Resolution** - Print directly from stash refs
  - `file_path` now accepts `stash://space_xxx/file_id` references
  - "Print the image I generated" → resolves stash ref automatically
- ✅ **Send Email Attachments** - Attach images/files to emails
  - Supports stash refs and direct file paths
  - Multi-tool: "Generate an image and email it to Andrew"

**2025-12-15:**
- ✅ **AI Phone Calls via Vapi.ai** - Outbound AI phone calls on your behalf
  - Multiple personas (Jarvis, James/professional, Jay/casual, Samantha/female)
  - Custom Vapi dashboard assistants with variable injection (`{{owner}}`, `{{task}}`)
  - Voicemail detection (hangup, leave message, or disabled)
  - Sync mode (wait for result) or async mode (check later)
  - Auto-save transcripts to Canvas and memory
  - Contact management (save phone numbers by name)
  - See: `docs/tools/phone/PHONE_CALLS.md`
- ✅ **Spotify Integration** - Full music playback control
  - Play playlists, albums, artists, songs by voice
  - Searches your library first, then public Spotify
  - Multi-device support (Fire TV, Echo, phone, desktop)
  - Queue management, shuffle, repeat, volume
  - Share what's playing via email with album art
  - OAuth setup: `./bin/spotify-auth`
  - See: `docs/tools/spotify/SPOTIFY.md`

**2025-12-12:**
- ✅ **Native Web Search for Cloud Providers** - Built-in real-time search ⭐ MAJOR
  - **XAI_SEARCH=true**: Grok's live search (web + X posts) via `search_parameters`
  - **ANTHROPIC_SEARCH=true**: Claude's web search tool with beta header
  - Auto mode: Only searches when query needs real-time data
  - No tool calls needed - cleaner context, faster responses
  - Eliminates endless Brave Search loops
  - Works transparently with existing tool orchestration
- ✅ **Blocked Tools Startup Filter** - Hide blocked tools from startup display
  - Shows "(🚫 N blocked tool(s) hidden)" count
  - Cleaner startup output matching actual LLM capabilities
- ✅ **Config Naming Cleanup** - CHAT_MODEL → OPENAI_MODEL
  - Consistent pattern: {PROVIDER}_MODEL across all providers

**2025-12-11:**
- ✅ **Stash System** - Artifact storage for multi-step workflows
  - Temporary file/image/data storage across tool calls
  - URL downloads with SSRF protection (blocks private IPs)
  - Content-type validation, file size limits, quota management
  - Workflow pattern: `stash.save()` → `pdf_create()` → `printer.print()`
  - See: `docs/STASH_SYSTEM.md`
- ✅ **PDF Create Tool** - Generate PDF documents
  - Create PDFs from text, images, or stash files
  - Basic markdown header support (# ## ###)
  - Image centering and scaling
  - Saves back to stash for printing/emailing
  - See: `skills/pdf_create.py`
- ✅ **Printer Tool** - Print from stash, files, or text
  - CUPS integration for network printers
  - Color/grayscale, compact mode, quality settings
  - Print from file paths, stash refs, or Canvas pages
  - See: `skills/printer.py`
- ✅ **Speaker Volume Tool** - Control system audio
  - Get/set/adjust speaker volume via amixer
  - Uses OUT_DEV from cloud.env/local.env
  - See: `skills/speaker_volume.py`
- ✅ **Improved Tool Descriptions** - Better LLM routing
  - Added "Use this when / Do NOT use for" guidance to tools
  - Helps LLM distinguish document generation vs software development
  - opencode, pdf_create, stash descriptions updated

**2025-12-06:**
- ✅ **Network Tools** - Comprehensive network diagnostics
  - Ping with full statistics (min/avg/max latency, packet loss)
  - DNS lookup and resolution
  - Port connectivity checks with latency measurement
  - HTTP/HTTPS status checks with SSL verification
  - Traceroute (cross-platform: Linux/Windows/Mac)
  - Internet connectivity testing
  - See: `skills/auto-tools/network_tools.py`
- ✅ **System Monitor** - Real-time system resource monitoring
  - CPU usage (total + per-core percentages)
  - Memory stats (RAM + swap with GB conversions)
  - Disk usage for all mount points
  - Process list (top N by CPU or memory)
  - Network I/O statistics (bytes sent/received, errors, drops)
  - System uptime with boot time
  - See: `skills/auto-tools/system_monitor.py`
- ✅ **Text Summarizer** - Text processing and analysis
  - Extractive summarization (sentence ranking)
  - Keyword extraction with stopword filtering
  - Word/character/sentence/paragraph counting
  - Basic sentiment analysis (positive/negative/neutral)
  - See: `skills/auto-tools/text_summarizer.py`
- ✅ **System Dependencies Documentation** - Reproducibility improvements
  - Created `system-packages.txt` for all Ubuntu/Debian packages
  - Created `install-system-deps.sh` for one-command setup
  - Updated `setup.sh` to check for traceroute
  - Added traceroute to README installation steps
- ✅ **Tool Builder AVAILABLE_PACKAGES Sync** - Updated with all requirements.txt packages
  - Added 50+ packages from requirements.txt to prevent unnecessary pending reviews
  - Includes: psutil, numpy, scipy, fastapi, uvicorn, scikit-learn, textual, etc.
  - Tool Builder now knows which packages are already installed

**2025-12-01:**
- ✅ **Prompt Evolution System** - Self-evolving prompts and tool descriptions ⭐ MAJOR
  - Auto-improves tool descriptions based on feedback ratings (1-5 scale)
  - System prompt suggestions saved to Canvas for review
  - A/B testing, versioning, and auto-rollback on degradation
  - Random feedback collection during normal operation (`FEEDBACK_RANDOM_ENABLED`)
  - `./bin/evolve-prompts check --mode cloud` - See what needs improvement
  - `./bin/evolve-prompts auto --mode cloud` - Generate and deploy improvements
  - See: `docs/ADVANCED_AI_TECHNIQUES.md`, `docs/FEEDBACK_SYSTEM.md`
- ✅ **Dynamic Tool Builder** - Autonomous tool creation ⭐ MAJOR
  - Creates new tools when capability gaps detected
  - **Duplicate detection** - Checks ALL existing tools (local + MCP + auto-tools)
  - **Ouroboros Research** 🐍 - Tool Builder calls Jarvis for API research!
  - Syntax verification, import checks, runtime testing
  - Dependency gating (new packages require human approval)
  - API key awareness (flags tools needing new credentials)
  - Full audit trail with report cards
  - Grafana dashboard: `Jarvis Tool Builder`
  - `./bin/build-tool --mode cloud build "Get stock prices"`
  - See: `docs/TOOL_BUILDER.md`
- ✅ **Evolution Sync** - Cloud ↔ Local prompt version sync
  - Conflict detection with `--dry-run` preview
  - `--force` flag for override
  - `./bin/sync-evolution-db.py local --dry-run`
- ✅ **Grafana Dashboard Updates** - Mode dropdown for feedback/evolution
  - Toggle between cloud/local data in dashboards
  - All logs now include `mode` field for filtering
- ✅ **Canvas System** - Visual knowledge viewer for rich content
  - Beautiful dark-themed web UI at localhost:8890
  - Jarvis saves research results, comparisons, code snippets
  - Markdown rendering with syntax highlighting
  - Search, pin, edit, delete pages
  - Auto-saves to memory for recall
  - Live reload when new content added
  - Launch: `./bin/jarvis-canvas`
  - See: `docs/CANVAS_SYSTEM.md`
- ✅ **Calculator Tool** - Advanced math, statistics, unit conversions
  - Arithmetic, percentages (15% of 200)
  - Statistics (mean, median, stdev, variance)
  - Unit conversions (5 miles to km, 100°F to °C, 500 GB to TB)
  - Trigonometry, logarithms, factorials
  - Constants (pi, e, tau)
  - See: `skills/calculator.py`
- ✅ **Feedback System** - LLM self-critique and grading
  - `--feedback` flag on orchestrator for per-query feedback
  - `./bin/jarvis-feedback` standalone script (run, batch, summary, issues)
  - Cross-LLM grading (FEEDBACK_PROVIDER/FEEDBACK_MODEL)
  - Logs to `logs/feedback/feedback-YYYY-MM-DD.jsonl`
  - Full context (system prompt, tools, intelligence) for accurate critique
  - See: `docs/FEEDBACK_SYSTEM.md`
- ✅ **Dashboard Enhancements** - 70+ commands ⭐ ENHANCED
  - Canvas commands (start, health, pages)
  - Feedback commands (summary, issues, test)
  - Monitor commands (status, restart, backup)
  - API local mode support
  - Unique tmux sessions per service
  - Fixed SQL queries and log paths

**2025-11-29:**
- ✅ **Command Dashboard TUI** - Interactive terminal UI for all Jarvis commands
  - 60+ commands organized by category (Core, API, Memory, Intelligence, Tools, Logs, etc.)
  - Search/filter commands with `/` key
  - Tab-based navigation by category
  - Live system status (CPU, RAM, API health)
  - Run any command with Enter, view output in real-time
  - Launch: `./bin/jarvis-dashboard` or `jarvis-d` alias
- ✅ **Status Updates System** - Real-time voice progress during long tasks ⭐ MAJOR
  - **Phase 1**: Core infrastructure (StatusUpdater, TTS scripts, phrase config)
  - **Phase 2**: Orchestrator integration (tool-aware updates, error handling)
  - **Phase 3**: Optional LLM summaries from a bounded, sanitized execution snapshot
  - Configurable phrases with humor/encouragement toggles
  - Tool-specific updates (opencode, search, weather, fetch, etc.)
  - Non-blocking deadline fallback, debounce, rate limiting, error deduplication, and final-audio priority
  - Cloud/local native TTS plus Web status TTS with separate persistent caches
  - **Phrase modes**: `normal` (professional) or `unhinged` (chaotic/funny)
  - **Silence padding**: Prevents speaker wake-up cutoff (`STATUS_SILENCE_PAD_MS`)
  - **Audio caching**: Repeated static or dynamic phrases avoid another TTS call (`./bin/status-cache`)
  - Current guide: [`STATUS_UPDATES.md`](STATUS_UPDATES.md); original design: `archive/STATUS_UPDATES_DESIGN.md`
- ✅ **Weather Tool** - OpenWeatherMap integration with geocoding
  - Accurate location via Geocoding API (lat/lon)
  - US state code handling ("Denver, CO" → "Denver, Colorado")
  - wttr.in fallback if API unavailable
  - See: `skills/weather.py`

**2025-11-28:**
- ✅ **Intelligence Layer Phase 1.5** - Full insight lifecycle management ⭐ MAJOR
  - **Insight Tracking**: `times_applied`, `times_helpful`, `times_failed` now active
  - **Decay Job**: Auto-decay unused/failed insights, prune <0.15 confidence
  - **Anomaly Detection**: Flag high-turn or failed multi-turn experiences
  - **Meta-Cognition**: Detect blind spots, over-generalization, learning quality
  - **meta_knowledge Table**: Store learning system health findings
  - **Enhanced Reflection**: Now includes LLM response, tool results, available tools
  - **Content Quality Eval**: Reflection evaluates data relevance, not just tool success
  - See: `docs/INTELLIGENCE_LAYER.md`
- ✅ **Maintenance CLI** - `./bin/run-intelligence-maintenance.py`
  - Run decay, anomaly, meta-cognition jobs on demand
  - `--watch` mode to tail logs
- ✅ **Maintenance API Endpoints** - `/api/intelligence/maintenance/*`
  - `/decay`, `/anomaly`, `/meta-cognition`, `/all`
  - `/meta-knowledge` to view findings
- ✅ **13 Intelligence Log Events** - Full Grafana/Loki visibility
  - `insights_applied`, `experience_recorded`, `reflection_*`
  - `maintenance_run`, `decay_applied`, `insight_pruned`
  - `anomaly_detected`, `meta_cognition`

**2025-11-27:**
- ✅ **Intelligence Layer Phase 1** - Self-learning system with positive/negative constraints ⭐ MAJOR
  - Learns what works AND what to avoid (negative constraints)
  - Fact vs Procedural knowledge classification
  - Generalizability filtering (only stores reusable insights)
  - Confidence decay tracking for insight health
  - Separate databases for cloud/local (embedding dimension compatibility)
  - See: `docs/INTELLIGENCE_LAYER.md`
- ✅ **Intelligence Grafana Dashboard** - Real-time self-learning metrics
  - Experience/insight counts, confidence gauges
  - Positive vs Negative constraint breakdown
  - Pending reflections monitoring
  - Loki log integration for event stream
- ✅ **Conversation Audit v2 Dashboard** - Complete conversation drill-down
  - Tools selected vs tools executed comparison
  - Decision types (tool_call vs text response)
  - Activity timeline with LLM + Tool logs interleaved
  - Cost and token tracking over time
- ✅ **Intelligence API Endpoints** - `/api/intelligence/*`
  - Stats, health, metrics, insights, experiences
  - Manual reflection trigger
  - Meta-cognition evaluation
- ✅ **Prometheus Intelligence Metrics** - Exposed via `/metrics`
  - `jarvis_intelligence_experiences_total`
  - `jarvis_intelligence_insights_total{constraint_type}`
  - `jarvis_intelligence_avg_confidence`
  - `jarvis_intelligence_helpful_ratio`
- ✅ **Intelligence Health & Sync Tools**
  - `bin/check-intelligence-health.py` - Validate embeddings, check stats
  - `bin/sync-intelligence-db.py` - Sync between cloud/local modes
- ✅ **Embedding Fallback** - Deterministic hash-based fallback when APIs fail

**2025-11-25:**
- ✅ **Google Calendar Sync** - Bidirectional sync between Jarvis reminders and Google Calendar ⭐ MAJOR
  - n8n workflows for create/update/delete operations in both directions
  - Timezone-aware sync (UTC normalization with ISO 8601)
  - Sync loop prevention with metadata tracking
  - API routes for update/delete by Google Calendar event ID
  - See: `docs/n8n/docs/GOOGLE_CALENDAR_SYNC.md`
- ✅ **Modular Webhook System** - Centralized webhook management with authentication support
  - Webhook registry (`config/webhook_registry.json`) for named webhooks
  - Generic `send_webhook` tool with auth support (Bearer, API Key, Basic, JWT, Custom Headers)
  - Rate limiting per webhook
  - See: `docs/WEBHOOK_SYSTEM.md`
- ✅ **Email Tool** - Send emails via n8n SMTP integration
  - Contact management (`config/contacts.json`) with name → email resolution
  - Rich HTML email templates with Jarvis branding
  - Ghost tool (prioritized by Tool RAG when relevant and within the final schema cap)
  - See: `docs/n8n/docs/WEBHOOK_AND_EMAIL_SYSTEM.md`
- ✅ **Monitoring Stack** - Production-grade observability with Grafana, Prometheus, Loki ⭐ MAJOR
  - Real-time LLM call metrics (cost, latency, token usage, model comparison)
  - API metrics (request rate, response time, error tracking)
  - Log aggregation and visualization
  - Custom dashboards for system health
  - See: `docs/monitoring/`
- ✅ **LLM Call Logging** - Comprehensive telemetry for every LLM interaction
  - Cost tracking per call (input/output tokens, USD)
  - Multi-turn conversation flow analysis
  - Tool execution correlation
  - Grafana dashboard integration
  - See: `docs/monitoring/GRAFANA_DASHBOARDS.md`
- ✅ **Disaster Recovery Guide** - Complete system rebuild documentation
  - Step-by-step server rebuild (OS, audio, Python, n8n, services)
  - Hardware-specific configuration (audio devices, network IPs)
  - Data restoration procedures
  - Validation tests for each component
  - See: `docs/INSTALL_GUIDE.md`
- ✅ **Ghost Tools Pattern** - Critical tools prioritized via `GHOST_TOOLS` env var
  - Merged with semantic results before the final Tool RAG schema cap is applied
  - Helps reliable tool discovery (e.g., send_email, send_webhook)
  - Configurable per deployment mode (cloud/local)

**2025-11-22:**
- ✅ **Tool RAG System** - Dynamic tool retrieval using vector embeddings for infinite scalability
  - Loads only relevant tools per query (5-15 tools instead of all 32+)
  - Vector-based semantic search with configurable similarity threshold
  - "Ghost tools" pattern for prioritizing core functionality inside the schema cap
  - Optimized for local models (smaller context windows)
  - See: `docs/TOOL_RAG_STRATEGY.md`, `docs/archive/TOOL_RAG_IMPLEMENTATION_SUMMARY.md` (historical)
- ✅ **Enhanced error propagation** - LLM now receives full error details from failed tools for self-healing
- ✅ **Test script Tool RAG integration** - All test scripts auto-sync tool embeddings after DB cleanup
- ✅ **Tool RAG debugging utilities** - `debug-tool-rag.py` for comprehensive retrieval analysis
  - Supports comparing stripped-query vs full-prompt retrieval when tuning `TOOL_SIMILARITY_THRESHOLD_FULL`

**2025-11-21:**
- ✅ **Randomized wake word greetings** - Dynamic greeting selection for personality
- ✅ **Proactive reminder guard** - Prevents unprompted reminder checks by local models
- ✅ **Voice timeout system** - 30-second hard timeout for recording to handle noisy environments
- ✅ **Samantha OS personality** - Added support for custom AI personalities with TTS instructions

**2025-11-22:**
- ✅ **Search Fallback System** - Multi-tier intelligent fallbacks for all search methods ⭐ MAJOR
  - FTS5: AND → OR → LIKE fallback chain with hyphen handling
  - Semantic: Falls back to FTS5 if threshold too high
  - Guarantees results for all queries (no more silent 0 results)
  - See: `docs/SEARCH_FALLBACK_SYSTEM.md`
- ✅ **Embedding Health Checks** - Automated validation of embedding dimensions on startup
  - Prevents silent semantic search failures from dimension mismatches
  - Integrated into `jarvis-services` and `jarvis-api` startup flows
  - See: `docs/EMBEDDING_HEALTH_CHECKS.md`

**2025-11-20:**
- ✅ **FTS5 Full-Text Search** - SQLite FTS5 with BM25 ranking for faster, more accurate searches
- ✅ **Levenshtein fuzzy matching** - Typo-tolerant reminder cancellation
- ✅ **Generic LLM prompting** - Removed hardcoded examples to improve universal understanding
- ✅ **Configurable Ollama context** - `OLLAMA_CONTEXT_WINDOW` now in `local.env`
- ✅ **MCP snake_case enforcement** - Fixed regression with MCP server name parsing
- ✅ **Comprehensive burn test** - Single modular test suite for all features (`tests/comprehensive_test.py`)
- ✅ **Intel ingestion improvements** - Better fact extraction from prose and headers

**2025-11-19:**
- ✅ **Auto-context system** - Short-term conversation memory across wake word cycles
- ✅ **Temperature control** - Dynamic LLM creativity settings (casual vs detailed modes)
- ✅ **Camera bridge integration** - Ubiquiti Protect webhook middleware (Dockerized)
- ✅ **Fuzzy reminder cancellation** - Cancel reminders by partial title match with safety checks

**2025-11-18:**
- ✅ **Natural language time parsing** - Word numbers ("one hour") and special times ("noon", "midnight")
- ✅ **Enhanced tool descriptions** - Better LLM routing with explicit use cases
- ✅ **Conversation context improvements** - Fixed temporal vs topic-based query routing

**2026-04-14:**
- ✅ **Response style docs refresh** - Rewrote the response-style mental model around final `speech`
  - Clarified `casual` vs `auto` vs `detailed`
  - Documented direct-speech bypass tools and where tool-level `speech` becomes final output
  - Added tree-view examples for pure Q&A, single-tool, multi-tool, and bypass paths
  - Clarified that standard TTS normalization is a later playback layer, separate from response style
  - See: `docs/AUTO_MODE_EXPLAINED.md`, `docs/CASUAL_VS_DETAILED_MODE.md`
- ✅ **Auto mode tuning update** - Raised the hardcoded complex-tool threshold in `_format_auto_mode()`
  - Complex single-turn tool responses now stay raw only when they exceed 75 words (was 50)
  - Better balance between voice-friendly condensation and richer complex answers in `auto`
  - Updated code comments and docs to match
  - See: `orchestrator/orchestrator_v2.py`, `docs/AUTO_MODE_EXPLAINED.md`
- ✅ **Tool RAG typo hints** - Added typo/near-segment hinting to retrieval embeddings
  - Supports optimal-string-alignment typo detection against tool names and long snake_case segments
  - URL-like spans are removed before typo tokenization
  - Production routing now scans typo hints from the raw user request only, not the full Tool-RAG prompt
  - Debug tooling updated to reflect the live hinting path more closely
  - Config knobs added: `TOOL_RAG_TYPO_ENABLED`, `TOOL_RAG_TYPO_MAX_DISTANCE`, `TOOL_RAG_TYPO_MIN_TOKEN_LEN`, `TOOL_RAG_TYPO_MAX_HINTS`
  - See: `docs/TOOL_RAG_STRATEGY.md`, `lib/tool_rag_typo_hints.py`, `bin/debug-tool-rag.py`

**2025-11-11:**
- ✅ OpenCode integration complete
- ✅ Workspace isolation enforced
- ✅ Detailed logging system
- ✅ Documentation consolidated (9 → 1 doc)

**2025-11-10:**
- ✅ Memory system with semantic search
- ✅ Natural language responses
- ✅ MCP server integration

---

**Last Updated:** 2026-06-29
**Latest:** `create_social_clip` (MoneyPrinterTurbo B-roll), multi-image Web UI vision, modular stash video playback, and modular inline media display improvements
**Need help?** Check the relevant doc above or run the integration tests to verify your setup.
