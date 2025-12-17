# Jarvis Voice Assistant Documentation

![jarvis-info-graph](images/jarvis-info-graph.jpeg)

## 📚 Core Documentation

### Getting Started
- **[JARVIS_WORKFLOW.md](JARVIS_WORKFLOW.md)** - 🆕 **Complete workflow guide with visual flowcharts** (START HERE!)
- **[QUICKSTART.md](QUICKSTART.md)** - Quick setup guide
- **[DISASTER_RECOVERY.md](DISASTER_RECOVERY.md)** - 🆕 **Complete disaster recovery guide** (rebuild from scratch) ⭐ CRITICAL
- **[../config/README.md](../config/README.md)** - Configuration guide
- **[XAI_PROVIDER.md](XAI_PROVIDER.md)** - 🆕 **xAI Grok provider** (2M context, native search, 10-15x cheaper!) ⭐ RECOMMENDED

### Main Features
- **[JARVIS_WEB_UI.md](JARVIS_WEB_UI.md)** - 🌐 **Web Interface** (chat UI, mode switching, TTS, settings) ⭐ ENHANCED
- **[MEMORY_SYSTEM.md](MEMORY_SYSTEM.md)** - Memory database with semantic search
- **[phone/PHONE_CALLS.md](phone/PHONE_CALLS.md)** - 📞 **AI Phone Calls** (outbound calls via Vapi.ai, personas, transcripts) ⭐ NEW
- **[spotify/SPOTIFY.md](spotify/SPOTIFY.md)** - 🎵 **Spotify Control** (play, pause, skip, queue, search, multi-device) ⭐ NEW
- **[STASH_SYSTEM.md](STASH_SYSTEM.md)** - 📦 **Artifact storage** (multi-step workflows, URL downloads, **Memory+Stash architecture** ⭐ ENHANCED)
- **[INTELLIGENCE_LAYER.md](INTELLIGENCE_LAYER.md)** - 🧠 **Self-learning system** (learns from interactions, positive/negative constraints!) ⭐ ENHANCED
- **[CANVAS_SYSTEM.md](CANVAS_SYSTEM.md)** - 🎨 **Visual knowledge viewer** (rich content display, research results) ⭐ NEW
- **[FEEDBACK_SYSTEM.md](FEEDBACK_SYSTEM.md)** - 📝 **LLM self-critique** (feedback grading, improvement suggestions) ⭐ NEW
- **[DUAL_DATABASE_SYSTEM.md](DUAL_DATABASE_SYSTEM.md)** - Cloud/local DB architecture
- **[SEMANTIC_THRESHOLD_TUNING.md](SEMANTIC_THRESHOLD_TUNING.md)** - Tune search sensitivity
- **[WEBHOOK_SYSTEM.md](WEBHOOK_SYSTEM.md)** - Modular webhook system (email, n8n, external APIs with auth)
- **[opencode/OPENCODE.md](opencode/OPENCODE.md)** - Autonomous coding agent
- **[TOOL_CALLING_SYSTEM.md](TOOL_CALLING_SYSTEM.md)** - Tool orchestration system
- **[TOOL_MANAGEMENT.md](TOOL_MANAGEMENT.md)** - Enable/disable tools

### Monitoring & Observability ⭐ ENHANCED
- **[../monitoring/README.md](../monitoring/README.md)** - Grafana + Prometheus + Loki stack
- **Intelligence Dashboard** - Self-learning metrics (experiences, insights, confidence, decay)
- **Conversation Audit v2** - Deep drill-down into LLM decisions and tool calls
- **API Intelligence Endpoints** - `/api/intelligence/*` for stats, health, maintenance jobs
- **Maintenance Jobs** - Decay, anomaly detection, meta-cognition via API or CLI

### System Architecture
- **Tool system** - Located in `skills/` directory with JSON schemas
- **Orchestrator** - `orchestrator/orchestrator_v2.py` - Main routing logic
- **MCP Integration** - External tools via Model Context Protocol

## 🚀 Quick Start

```bash
# Cloud mode (xAI/Anthropic/OpenAI) - Recommended: xAI Grok
./jarvis

# Local mode (Ollama)
./jarvis-local

# Command Dashboard TUI (all commands in one place!) ⭐ NEW
./bin/jarvis-dashboard   # Or: jarvis-d (if alias set)

# Run tests
./test-all-tools.sh
./test-all-tools-local.sh
./tests/integration/test-memory-tools.sh
./tests/integration/compare-models.sh local qwen3-vl qwen2.5:7b
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
| **USER_PROFILE_SYSTEM.md** | User profile management (intel + dynamic memories) ⭐ NEW |
| **SEARCH_FALLBACK_SYSTEM.md** | Multi-tier search fallbacks (AND→OR→LIKE) |
| **FTS5_SEARCH_SYSTEM.md** | FTS5 full-text search with BM25 ranking |
| **DUAL_DATABASE_SYSTEM.md** | Cloud/local database with auto-sync |
| **EMBEDDING_HEALTH_CHECKS.md** | Embedding dimension validation |
| **SEMANTIC_THRESHOLD_TUNING.md** | How to tune similarity threshold |
| **MEMORY_SYSTEM_TUNING.md** | Advanced memory optimization |
| **MEMORY_INTELLIGENCE_FIXES.md** | Auto-save improvements |

### Tool System
| Document | Purpose |
|----------|---------|
| **TOOL_RAG_STRATEGY.md** | Tool RAG system - Dynamic tool retrieval ⭐ NEW |
| **TOOL_RAG_IMPLEMENTATION_SUMMARY.md** | Tool RAG implementation details ⭐ NEW |
| **TOOL_RAG_TROUBLESHOOTING.md** | Tool RAG debugging guide ⭐ NEW |
| **TEST_SCRIPT_TOOL_RAG_FIX.md** | Test script integration fixes ⭐ NEW |
| **TOOL_CALLING_SYSTEM.md** | Tool orchestration and routing |
| **TOOL_MANAGEMENT.md** | Enable/disable tools |
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

### Testing & Analysis
| Document | Purpose |
|----------|---------|
| **COMPREHENSIVE_TESTING.md** | Burn test suite for all features ⭐ NEW |
| **TESTING.md** | Comprehensive testing guide |
| **BASELINE_TOKEN_USAGE.md** | Token usage tracking |
| **../tests/README.md** | Test suite overview |

### System Understanding
| Document | Purpose |
|----------|---------|
| **JARVIS_WORKFLOW.md** | Complete workflow with visual flowcharts |
| **AUTO_CONTEXT_SYSTEM.md** | Short-term conversation memory ⭐ NEW |
| **CONVERSATION_STATE_ARCHITECTURE.md** | State management between cycles ⭐ NEW |
| **api/READY_TO_USE.md** | Proactive API (Phase 1 COMPLETE) - Webhook system for alerts |
| **api/PROACTIVE_ASSISTANT_SYSTEM.md** | Full architecture |

### Configuration & Setup
| Document | Purpose |
|----------|---------|
| **QUICKSTART.md** | Quick setup guide |
| **../config/README.md** | Configuration reference |
| **MCP_QUICKSTART.md** | MCP server setup |
| **MCP_NAMING_CONVENTIONS.md** | MCP snake_case requirements ⭐ NEW |
| **MCP_REGRESSION_FIX.md** | MCP parsing architecture ⭐ NEW |

### Advanced Features
| Document | Purpose |
|----------|---------|
| **PROMPT_CACHING.md** | Anthropic prompt caching |
| **EXTENDED_THINKING.md** | Extended thinking mode |
| **CASUAL_VS_DETAILED_MODE.md** | Response styles |
| **AUTO_MODE_EXPLAINED.md** | Auto formatting mode |
| **METADATA_SYSTEM.md** | Cost tracking and metadata |
| **VOICE_MODE_FIXES.md** | Voice mode improvements |

### Integrations & Webhooks
| Document | Purpose |
|----------|---------|
| **BLINKO_INTEGRATION_IDEAS.md** | 🆕 **Blinko note-taking integration** - Exploration of AI RAG note system integration with Jarvis |
| **WEBHOOK_SYSTEM.md** | **Modular webhook system** - Email, n8n, external APIs with auth examples ⭐ NEW |
| **n8n/docs/GOOGLE_CALENDAR_SYNC.md** | Bidirectional Google Calendar sync (reminders ↔ events) |
| **n8n/docs/WEBHOOK_AND_EMAIL_SYSTEM.md** | Email tool and webhook registry details |
| **n8n/docs/N8N_INTEGRATION.md** | n8n setup and workflow management |
| **api/REMINDER_SYSTEM.md** | Reminder API and voice commands |

### Intelligence & Learning
| Document | Purpose |
|----------|---------|
| **INTELLIGENCE_LAYER.md** | Self-learning system (Phase 1.5 - COMPLETE) ⭐ ENHANCED |
| **ADVANCED_AI_TECHNIQUES.md** | 🚀 **AGI Roadmap** - Self-evolving prompts, tool builder, parallel subagents ⭐ ENHANCED |
| **TOOL_BUILDER.md** | 🔧 **Dynamic Tool Creation** - Autonomous tool building with safety checks ⭐ NEW |
| **JARVIS_PLAYGROUND.md** | 🎮 **Playground Design** - Self-play, Docker, VM workspace, Carvis twin ⭐ NEW |
| **Psychological-Profile-Ideas.md** | **Phase 2 Roadmap** - User modeling, style reflection, behavioral intelligence ⭐ FUTURE |
| **STATUS_UPDATES_DESIGN.md** | **Voice progress updates** - Real-time feedback during tasks |
| **SYNC_ARCHITECTURE.md** | Memory, tool, and intelligence sync systems |

### Developer Tools
| Document | Purpose |
|----------|---------|
| **Command Dashboard** | TUI for all Jarvis commands - `./bin/jarvis-dashboard` ⭐ NEW |
| **Canvas Viewer** | Visual knowledge display - `./bin/jarvis-canvas` (localhost:8890) ⭐ NEW |
| **Feedback System** | LLM self-critique - `./bin/jarvis-feedback` or `--feedback` flag ⭐ NEW |
| **Prompt Evolution** | Self-improving prompts - `./bin/evolve-prompts check cloud` ⭐ NEW |
| **Tool Builder** | Dynamic tool creation - `./bin/build-tool --mode cloud build "..."` ⭐ NEW |

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
| **DATABASE_DEEP_DIVE.md** | Database evolution |
| **JARVIS_INTEL_SYSTEM.md** | Intel file ingestion |
| **FUTURE_ENHANCEMENTS.md** | Planned features |
| **archive/** | Historical docs and changelogs |

## 🔧 Configuration

**Main config files:**
- `config/cloud.env` - Cloud mode (OpenAI, Anthropic)
- `config/local.env` - Local mode (Ollama)
- `~/.config/opencode/opencode.json` - OpenCode config

**Key environment variables:**
- `LLM_PROVIDER` - openai | anthropic | ollama
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
# Test all tools (cloud)
./tests/integration/test-all-tools.sh

# Test all tools (local)
./tests/integration/test-all-tools-local.sh

# Test OpenCode
./tests/integration/test-opencode-integration.sh

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
systemctl status opencode-jarvis.service
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

**2025-12-17:**
- ✅ **Jarvis Web UI v1.2** - Mode-aware web interface ⭐ ENHANCED
  - **Mode-aware TTS**: Cloud=ElevenLabs, Local=Kokoro (via TTS_URL)
  - **Per-mode settings**: `cloud`/`local` sections in web_config.json
  - **Dynamic Ollama models**: Fetches available models from Ollama server
  - **Clean mode switching**: Intelligence singleton resets on mode change
  - **STT_PROVIDER config**: Ready for push-to-talk (faster-whisper/openai)
  - System tab shows mode-specific .env values
  - See: `docs/JARVIS_WEB_UI.md`

**2025-12-16:**
- ✅ **Google Gemini Image Generation** - AI image generation with Gemini 3 Pro ⭐ NEW
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
- ✅ **AI Phone Calls via Vapi.ai** - Outbound AI phone calls on your behalf ⭐ NEW
  - Multiple personas (Jarvis, James/professional, Jay/casual, Samantha/female)
  - Custom Vapi dashboard assistants with variable injection (`{{owner}}`, `{{task}}`)
  - Voicemail detection (hangup, leave message, or disabled)
  - Sync mode (wait for result) or async mode (check later)
  - Auto-save transcripts to Canvas and memory
  - Contact management (save phone numbers by name)
  - See: `docs/phone/PHONE_CALLS.md`
- ✅ **Spotify Integration** - Full music playback control ⭐ NEW
  - Play playlists, albums, artists, songs by voice
  - Searches your library first, then public Spotify
  - Multi-device support (Fire TV, Echo, phone, desktop)
  - Queue management, shuffle, repeat, volume
  - Share what's playing via email with album art
  - OAuth setup: `./bin/spotify-auth`
  - See: `docs/spotify/SPOTIFY.md`

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
- ✅ **Stash System** - Artifact storage for multi-step workflows ⭐ NEW
  - Temporary file/image/data storage across tool calls
  - URL downloads with SSRF protection (blocks private IPs)
  - Content-type validation, file size limits, quota management
  - Workflow pattern: `stash.save()` → `pdf_create()` → `printer.print()`
  - See: `docs/STASH_SYSTEM.md`
- ✅ **PDF Create Tool** - Generate PDF documents ⭐ NEW
  - Create PDFs from text, images, or stash files
  - Basic markdown header support (# ## ###)
  - Image centering and scaling
  - Saves back to stash for printing/emailing
  - See: `skills/pdf_create.py`
- ✅ **Printer Tool** - Print from stash, files, or text ⭐ NEW
  - CUPS integration for network printers
  - Color/grayscale, compact mode, quality settings
  - Print from file paths, stash refs, or Canvas pages
  - See: `skills/printer.py`
- ✅ **Speaker Volume Tool** - Control system audio ⭐ NEW
  - Get/set/adjust speaker volume via amixer
  - Uses OUT_DEV from cloud.env/local.env
  - See: `skills/speaker_volume.py`
- ✅ **Improved Tool Descriptions** - Better LLM routing
  - Added "Use this when / Do NOT use for" guidance to tools
  - Helps LLM distinguish document generation vs software development
  - opencode, pdf_create, stash descriptions updated

**2025-12-06:**
- ✅ **Network Tools** - Comprehensive network diagnostics ⭐ NEW
  - Ping with full statistics (min/avg/max latency, packet loss)
  - DNS lookup and resolution
  - Port connectivity checks with latency measurement
  - HTTP/HTTPS status checks with SSL verification
  - Traceroute (cross-platform: Linux/Windows/Mac)
  - Internet connectivity testing
  - See: `skills/auto-tools/network_tools.py`
- ✅ **System Monitor** - Real-time system resource monitoring ⭐ NEW
  - CPU usage (total + per-core percentages)
  - Memory stats (RAM + swap with GB conversions)
  - Disk usage for all mount points
  - Process list (top N by CPU or memory)
  - Network I/O statistics (bytes sent/received, errors, drops)
  - System uptime with boot time
  - See: `skills/auto-tools/system_monitor.py`
- ✅ **Text Summarizer** - Text processing and analysis ⭐ NEW
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
  - `./bin/evolve-prompts check cloud` - See what needs improvement
  - `./bin/evolve-prompts auto cloud` - Generate and deploy improvements
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
- ✅ **Canvas System** - Visual knowledge viewer for rich content ⭐ NEW
  - Beautiful dark-themed web UI at localhost:8890
  - Jarvis saves research results, comparisons, code snippets
  - Markdown rendering with syntax highlighting
  - Search, pin, edit, delete pages
  - Auto-saves to memory for recall
  - Live reload when new content added
  - Launch: `./bin/jarvis-canvas`
  - See: `docs/CANVAS_SYSTEM.md`
- ✅ **Calculator Tool** - Advanced math, statistics, unit conversions ⭐ NEW
  - Arithmetic, percentages (15% of 200)
  - Statistics (mean, median, stdev, variance)
  - Unit conversions (5 miles to km, 100°F to °C, 500 GB to TB)
  - Trigonometry, logarithms, factorials
  - Constants (pi, e, tau)
  - See: `skills/calculator.py`
- ✅ **Feedback System** - LLM self-critique and grading ⭐ NEW
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
- ✅ **Command Dashboard TUI** - Interactive terminal UI for all Jarvis commands ⭐ NEW
  - 60+ commands organized by category (Core, API, Memory, Intelligence, Tools, Logs, etc.)
  - Search/filter commands with `/` key
  - Tab-based navigation by category
  - Live system status (CPU, RAM, API health)
  - Run any command with Enter, view output in real-time
  - Launch: `./bin/jarvis-dashboard` or `jarvis-d` alias
- ✅ **Status Updates System** - Real-time voice progress during long tasks ⭐ MAJOR
  - **Phase 1**: Core infrastructure (StatusUpdater, TTS scripts, phrase config)
  - **Phase 2**: Orchestrator integration (tool-aware updates, error handling)
  - **Phase 3**: LLM dynamic summaries (natural language from tool output)
  - Configurable phrases with humor/encouragement toggles
  - Tool-specific updates (opencode, search, weather, fetch, etc.)
  - Rate limiting (20s default), error deduplication, collision prevention
  - Cloud (OpenAI TTS) and Local (Kokoro TTS) support
  - **Phrase modes**: `normal` (professional) or `unhinged` (chaotic/funny)
  - **Silence padding**: Prevents speaker wake-up cutoff (`STATUS_SILENCE_PAD_MS`)
  - **Audio caching**: Pre-gen static phrases to reduce TTS calls (`./bin/status-cache`)
  - See: `docs/STATUS_UPDATES_DESIGN.md`
- ✅ **Weather Tool** - OpenWeatherMap integration with geocoding
  - Accurate location via Geocoding API (lat/lon)
  - US state code handling ("Hillsboro, OR" → "Hillsboro, Oregon")
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
  - Ghost tool (always available to LLM)
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
  - See: `docs/DISASTER_RECOVERY.md`
- ✅ **Ghost Tools Pattern** - Critical tools always available via `GHOST_TOOLS` env var
  - Bypasses semantic search for frequently used tools
  - Ensures reliable tool discovery (e.g., send_email, send_webhook)
  - Configurable per deployment mode (cloud/local)

**2025-11-22:**
- ✅ **Tool RAG System** - Dynamic tool retrieval using vector embeddings for infinite scalability
  - Loads only relevant tools per query (5-15 tools instead of all 32+)
  - Vector-based semantic search with configurable similarity threshold
  - "Ghost tools" pattern for always-available core functionality
  - Optimized for local models (smaller context windows)
  - See: `docs/TOOL_RAG_STRATEGY.md`, `docs/TOOL_RAG_IMPLEMENTATION_SUMMARY.md`
- ✅ **Enhanced error propagation** - LLM now receives full error details from failed tools for self-healing
- ✅ **Test script Tool RAG integration** - All test scripts auto-sync tool embeddings after DB cleanup
- ✅ **Tool RAG debugging utilities** - `debug_tool_rag.py` for comprehensive retrieval analysis

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

**Last Updated:** 2025-12-17 (v2.14)  
**Latest:** Jarvis Web UI v1.2, AI Image Generation (Gemini 3 Pro), AI Phone Calls, Spotify  
**Need help?** Check the relevant doc above or run the integration tests to verify your setup.
