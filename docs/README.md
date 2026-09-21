# Jarvis Voice Assistant Documentation

![jarvis-info-graph](images/jarvis-info-graph.jpeg)

## 📚 Core Documentation

### Getting Started
- **[JARVIS_WORKFLOW.md](JARVIS_WORKFLOW.md)** - 🆕 **Complete workflow guide with visual flowcharts** (START HERE!)
- **[QUICKSTART.md](QUICKSTART.md)** - Quick setup guide
- **[INSTALL_GUIDE.md](INSTALL_GUIDE.md)** - 🆕 **Complete installation guide** (clone to `~/jarvis-voice`, run `./install.sh`, then configure keys/audio) ⭐ CRITICAL
- **[docker/README.md](docker/README.md)** - 🐳 **Docker guide** — run Web UIs + API in containers (commands, `.env`, hybrid mode)
- **[TAILSCALE_HTTPS.md](TAILSCALE_HTTPS.md)** - Private HTTPS for the UIs and Firefox extension: Serve setup, navigation, troubleshooting, and rollback
- **[../config/README.md](../config/README.md)** - Configuration guide
- **[NETWORK_PROXY.md](NETWORK_PROXY.md)** - **HTTP proxy chain** (`LOCAL_PROXY` / `LOCAL_PROXY2`, `http_client`, yt-dlp, stock tool)
- **[tools/external-network-intel-tool/README.md](tools/external-network-intel-tool/README.md)** - **Passive public IP/domain intelligence** (RDAP, routing, DNS, official cloud ranges, Shodan InternetDB, optional AbuseIPDB; no scanning)
- **[SPEECH_TO_TEXT.md](SPEECH_TO_TEXT.md)** - **Speech-to-text guide** (OpenAI, Faster-Whisper, self-hosted compatible endpoints, browser/wake-word STT, and long-file `transcribe_audio` policy)
- **[XAI_PROVIDER.md](XAI_PROVIDER.md)** - 🆕 **xAI Grok provider** (`grok-4.6` recommended default; also `grok-4.5`, `grok-4.3`, `grok-build-0.1`, native search/TTS, in-flight continuation) ⭐ RECOMMENDED
- **[OPENAI_PROVIDER.md](OPENAI_PROVIDER.md)** - 🆕 **OpenAI provider** (Chat Completions default, optional Responses API routing, hosted tools, in-flight continuation)
- **[ollama/README.md](ollama/README.md)** - **Ollama local + Ollama Cloud guide** (`OLLAMA_MODEL` vs `OLLAMA_CLOUD_MODEL`, vision uses cloud model in cloud mode / `OLLAMA_VISION_MODEL` in local mode, signed-in daemon, Docker addressing, troubleshooting)
- **[ollama/JARVIS_EMBEDDING_MODEL.md](ollama/JARVIS_EMBEDDING_MODEL.md)** - Pinned Jarvis Embedding registry artifact, exact digests, host verification, and immutable version policy

### Main Features
- **[JARVIS_WEB_UI.md](JARVIS_WEB_UI.md)** - 🌐 **Web Interface** (sticky Chat only, mode-scoped settings, Completion Guard, multi-image vision, server logs) ⭐ ENHANCED
- **[../jarvis-memory/README.md](../jarvis-memory/README.md)** - 🧠 **Memory Browser UI** (view/search/edit memories, intel files, conversations)
- **[api/API_OVERVIEW.md](api/API_OVERVIEW.md)** - 🔌 **Comprehensive FastAPI** (Memory, Query, Stash, Canvas, Conversations, Intelligence, Intel, Voice) ⭐ ENHANCED
- **[api/VOICES.md](api/VOICES.md)** - 🔊 **Voice API** (TTS playback with multi-agent voice identity support)
- **[MEMORY_SYSTEM.md](MEMORY_SYSTEM.md)** - Memory database with semantic search + auto-injection
- **[SOURCE_LIBRARY.md](SOURCE_LIBRARY.md)** - Retained original documents, passage search, citations, and the Web source library
- **[tools/phone/PHONE_CALLS.md](tools/phone/PHONE_CALLS.md)** - 📞 **AI Phone Calls** (outbound calls via Vapi.ai, personas, transcripts)
- **[tools/spotify/SPOTIFY.md](tools/spotify/SPOTIFY.md)** - 🎵 **Spotify Control** (play, pause, skip, queue, search, multi-device)
- **[STASH_SYSTEM.md](STASH_SYSTEM.md)** - 📦 **Artifact storage** (multi-step workflows, URL downloads, **Memory+Stash architecture**, **stash.remember with PDF/LLM summarization** ⭐ ENHANCED)
- **[INTELLIGENCE_LAYER.md](INTELLIGENCE_LAYER.md)** - 🧠 **Self-learning system** (tool traces, feedback metadata, Completion Guard outcomes, trigger-gated negative constraints) ⭐ ENHANCED
- **[CANVAS_SYSTEM.md](CANVAS_SYSTEM.md)** - 🎨 **Visual knowledge viewer** (rich content display, research results)
- **[JARVIS_HEAD.md](JARVIS_HEAD.md)** - Optional on-host matrix face kiosk (rain + wake/TTS mouth)
- **[CANVAS_PDF_SHARING.md](CANVAS_PDF_SHARING.md)** - 📄 **Canvas PDF export and optional xAI public URLs** (preview, safety scan, expiry, history, revoke)
- **[api/IMAGES.md](api/IMAGES.md)** - 🖼️ **Cloudflare CDN Upload** (permanent image hosting, multi-agent sharing, metadata tracking)
- **[FEEDBACK_SYSTEM.md](FEEDBACK_SYSTEM.md)** - 📝 **LLM self-critique** (feedback grading, improvement suggestions, intelligence outcome updates)
- **[COMPLETION_GUARD.md](COMPLETION_GUARD.md)** - 🛡️ **Completion Guard** (same-runtime repair loop, completion check, escalation tickets) 🆕
- **[tools/scheduled-tasks/scheduled-tasks.md](tools/scheduled-tasks/scheduled-tasks.md)** - ⏱️ **Scheduled Tasks** (implemented foundation for recurring queries, workflows, parser, API, and runner) 🆕
- **[BACKGROUND-TASKS.md](BACKGROUND-TASKS.md)** - Plain-English overview of local, remote-wait, and callback jobs; Web task management, worker setup, diagnostics, and recovery
- **[BROWSER-USE-CLOUD.md](BROWSER-USE-CLOUD.md)** - Optional hosted Browser Use V4 research, live viewer, cost cap, and background result delivery
- **[TASK-CALLBACKS.md](TASK-CALLBACKS.md)** - Optional authenticated task callbacks, integration controls, credential/key lifecycle, and the isolated local HTTP proof
- **[BROWSER-USE.md](BROWSER-USE.md)** - Opt-in browser research, Docker Chromium isolation, saved Stash evidence, and the first local callback tool binding
- **[DUAL_DATABASE_SYSTEM.md](DUAL_DATABASE_SYSTEM.md)** - Cloud/local DB architecture
- **[SEMANTIC_THRESHOLD_TUNING.md](SEMANTIC_THRESHOLD_TUNING.md)** - Tune search sensitivity
- **[WEBHOOK_SYSTEM.md](WEBHOOK_SYSTEM.md)** - Modular webhook system (email, n8n, external APIs with auth)
- **[opencode/OPENCODE.md](opencode/OPENCODE.md)** - Autonomous coding agent
- **[TOOL_CALLING_SYSTEM.md](TOOL_CALLING_SYSTEM.md)** - Tool orchestration system + `tool_search` and autonomous `workflow` discovery flows ⭐ ENHANCED
- **[WORKFLOW_ORCHESTRATION.md](WORKFLOW_ORCHESTRATION.md)** - 🔄 **Multi-tool workflow system** (slash/API/scheduled plus autonomous foreground execution, required-tool availability with explicit optional degradation, follow-up context) ⭐ IMPLEMENTED
- **[TOOL_MANAGEMENT.md](TOOL_MANAGEMENT.md)** - Manifest/profile/mode/Web precedence; enabled vs credential **available** status (`--mode`)
- **[../skills/README.md](../skills/README.md)** - **Tool profile overlays** (`JARVIS_TOOL_PROFILE`, `skills/profiles/<name>.json`, `bin/manage-tools.py profile …`); git tracks `default.json` and `skills/profiles/examples/*.json` (copy to `profiles/<name>.json` for use). After changing profile: restart services, then `./bin/sync-tools.py local` or `cloud`
- **[tools/status-tool/README.md](tools/status-tool/README.md)** - 📊 **Status Recap Tool v1.4** (weather, crypto, stocks/futures, alerts, reminders, system health, canvas + stash)
- **[tools/serp-api-tool/README.md](tools/serp-api-tool/README.md)** - 🔎 **SerpApi Tools** (Amazon, Google Shopping, Search Index, images, news, trends, marketplaces, local places/services, travel, and YouTube; includes mode availability, quota, proxy, cache, and request-cost behavior)
- **[tools/travel-explore-tool/README.md](tools/travel-explore-tool/README.md)** - 🌍 **Travel Explore Tool** (flexible destination discovery, planning-price semantics, exact-search handoffs, and workflow fields)
- **[tools/document-ocr-tool/README.md](tools/document-ocr-tool/README.md)** - 🔎 **Optional OVIS OCR** (scanned PDFs/images, Markdown/JSON extraction, archives, readiness checks, and Stash follow-ups)
- **[tools/flight-search-tool/README.md](tools/flight-search-tool/README.md)** - ✈️ **Flight Search Tool** (future options, prices, dates, and times)

### Document Processing
- **PDF Read Tool** (`skills/pdf_read.py`) - 📄 **PDF reading and manipulation**
  - Extract text from PDFs (with page ranges)
  - Extract embedded images to stash
  - Merge multiple PDFs, split PDFs
  - Convert pages to PNG/JPEG images
  - Search text within PDFs with context
  - Integrated with `stash.remember` for automatic PDF text extraction
- **Document OCR Tool** (`skills/document_ocr.py`) - OCR scanned PDFs and text-heavy images through an optional OVIS service; saves full Markdown/JSON/ZIP outputs to Stash

### Remote & Infrastructure
- **[tools/ssh/README.md](tools/ssh/README.md)** - 🔐 **SSH Remote Tool** (execute commands on remote hosts, apt management, multi-command)
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
| **[tools/external-network-intel-tool/README.md](tools/external-network-intel-tool/README.md)** | Passive public IP/domain ownership, routing, DNS, and reputation lookup |
| **[tools/serp-api-tool/README.md](tools/serp-api-tool/README.md)** | SerpApi search tool guide (setup, params, examples, troubleshooting) |
| **[tools/travel-explore-tool/README.md](tools/travel-explore-tool/README.md)** | Flexible destination discovery and flight/hotel handoff guide |
| **[tools/flight-search-tool/README.md](tools/flight-search-tool/README.md)** | Flight options and prices via SerpApi Google Flights or keyless fallback |
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
| **ADVANCED_AI_TECHNIQUES.md** | 🚀 **AGI Roadmap** - Tool builder, self-play, parallel subagents ⭐ ENHANCED |
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
| **Tool Builder** | Optional terminal starter for a basic tool; finish the integration in an IDE - `./bin/build-tool --mode cloud build "..."` |
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

---

**Last Updated:** 2026-09-19 (v2.55.9)
