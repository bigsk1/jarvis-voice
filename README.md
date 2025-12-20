# Jarvis Voice Assistant

A self-hosted, intelligent voice assistant with advanced tool calling, memory, and autonomous coding capabilities.

![jarvis-info-graph](docs/images/jarvis-info-graph.jpeg)

---

## 🎯 Current Status (December 2025)

**Production Ready** ✅
- **AI Image Generation** - Google Gemini 3 Pro with Search Grounding ⭐ NEW
  - "Generate a bitcoin infographic" → creates image with real-time price data
  - Supports aspect ratios, styles, negative prompts
  - Auto-saves to stash + memory for cross-session recall
- **AI Phone Calls** - Outbound AI calls via Vapi.ai with personas and transcripts ⭐ NEW
- **Native Web Search** - Built-in real-time search for xAI and Anthropic ⭐ NEW
  - `XAI_SEARCH=true`: Grok searches web + X posts internally (no tool calls!)
  - `ANTHROPIC_SEARCH=true`: Claude's web search tool with citations
  - Auto mode: Only searches when query needs real-time data
  - Eliminates endless search tool loops, cleaner context
- **Stash System** - Artifact storage for multi-step workflows (URL downloads, SSRF protection) ⭐ NEW
- **PDF Create** - Generate PDFs from stash files, images, or text ⭐ NEW
- **Printer Tool** - Print from stash, files, or Canvas pages (CUPS integration) ⭐ NEW
- **Speaker Volume** - Control system audio volume via voice ⭐ NEW
- **Network Tools** - Ping, DNS, port checks, HTTP/HTTPS status, traceroute
- **System Monitor** - CPU, RAM, disk, processes, network I/O, uptime
- **Text Summarizer** - Summarization, keywords, sentiment, word count
- **Prompt Evolution** - Self-evolving prompts and tool descriptions
- **Dynamic Tool Builder** - Autonomous tool creation with safety checks
- **Canvas System** - Visual knowledge viewer for rich content display
- **Calculator Tool** - Advanced math, statistics, unit conversions
- **Feedback System** - LLM self-critique and cross-model grading
- **Tool RAG System** - Dynamic tool retrieval for infinite scalability
- Multi-turn tool orchestration with LLM routing
- 46+ working skills (memory, bash, OpenCode, stash, printer, pdf, image generation, analyze_image, phone calls, spotify, reminders, canvas, etc.)
- **Proactive API** for event-driven alerts and notifications
- **Background services** for auto-resolve and follow-ups
- **Dual database system** with auto-sync (cloud ↔ local)
- **Intelligent memory** with semantic search + configurable thresholds
- OpenCode integration for autonomous coding tasks
- **Tool management** system (enable/disable per mode)
- **Model comparison framework** for testing different LLMs
- MCP server support for extensibility
- Cost tracking and metadata logging
- Dual mode operation (cloud/local)

---

## ✨ Key Features

### Intelligence & Self-Learning ⭐ ENHANCED
- **Intelligence Layer**: Self-learning system that improves over time
  - Learns from every interaction (what worked, what didn't)
  - **Positive constraints**: "Use mcp_fetch for server status checks"
  - **Negative constraints**: "Avoid search_memory for real-time data"
  - Generalizability filtering (only stores reusable insights)
  - **Insight tracking**: times_applied, times_helpful, times_failed ⭐ NEW
  - **Decay job**: Auto-prunes stale/failed insights ⭐ NEW
  - **Anomaly detection**: Flags unusual experiences ⭐ NEW
  - **Meta-cognition**: Analyzes learning health ⭐ NEW
  - Separate databases for cloud/local (1536 vs 768 dimensions)
  - See [`docs/INTELLIGENCE_LAYER.md`](docs/INTELLIGENCE_LAYER.md)

### Tool System
- **Tool RAG System**: Dynamic tool retrieval - loads only relevant tools for each query
  - Scales to 100+ tools without context flooding
  - Vector-based semantic search for tool discovery
  - "Ghost tools" always available for core functionality
  - See [`docs/TOOL_RAG_STRATEGY.md`](docs/TOOL_RAG_STRATEGY.md)
- **Advanced Tool Calling**: LLM-powered routing with 32+ skills
- **Multi-Turn Orchestration**: Chains multiple tools to complete complex tasks
- **Auto-Context System**: Automatic short-term memory of recent conversations
  - Remembers what you just discussed without needing explicit "remember" commands
  - Catches contradictions, continues workflows seamlessly, learns from failures
  - See [`docs/AUTO_CONTEXT_SYSTEM.md`](docs/AUTO_CONTEXT_SYSTEM.md)
- **Intelligent Memory**: Semantic search + conversation history with auto-save
- **OpenCode Integration**: Autonomous coding agent for building projects
- **MCP Support**: Extensible via Model Context Protocol servers

### Proactive System
- **Event-Driven API**: Receive webhooks from external systems (port 8880)
- **Auto-Resolve**: URL-based and agent-based automatic issue resolution
- **Background Services**: 24/7 daemons for follow-ups, healing, and reminders
- **Smart Reminders**: Time-based reminders with natural language parsing and recurring support
- **Remote Monitoring**: Deploy [Jarvis Agent](https://github.com/bigsk1/jarvis-voice) (Docker) anywhere to send health checks and alerts
- **Voice Notifications**: Jarvis speaks alerts and reminders via TTS

### Integrations & Automation ⭐ NEW
- **AI Phone Calls via Vapi.ai**: Outbound AI phone calls on your behalf ⭐ NEW
  - "Call Boss and ask if he wants to see Gladiator II tonight"
  - Multiple personas: Jarvis (default), James (professional), Jay (casual), Samantha (female)
  - Custom Vapi dashboard characters with dynamic variables (`{{owner}}`, `{{task}}`)
  - Voicemail detection and handling
  - Auto-save transcripts to Canvas and memory for later recall
  - Contact management: save numbers by name
  - See [`docs/phone/PHONE_CALLS.md`](docs/phone/PHONE_CALLS.md)
- **Spotify Integration**: Full music control via Spotify API ⭐ NEW
  - "Play Chill Vibes playlist", "Skip this song", "What's playing?"
  - Search your library first, then public Spotify
  - Multi-device support (Fire TV, Echo, phone, desktop)
  - Queue management, shuffle, repeat, volume control
  - Share what's playing via email with album art
  - See [`docs/spotify/SPOTIFY.md`](docs/spotify/SPOTIFY.md)
- **Modular Webhook System**: Named webhook registry for triggering external services
  - `send_email` - Send emails via SMTP with beautiful HTML templates
  - `send_webhook` - Trigger any webhook (Slack, Discord, APIs, custom endpoints)
  - Contact management with name resolution ("email Andrew" → looks up email)
  - Multiple auth methods (Bearer, Basic, API Key, JWT, custom headers)
  - Rate limiting to prevent duplicates
  - See [`docs/WEBHOOK_SYSTEM.md`](docs/WEBHOOK_SYSTEM.md)
- **Google Calendar Sync**: Bidirectional reminder ↔ calendar event sync via n8n
  - Create reminder in Jarvis → syncs to Google Calendar
  - Create event in Google Calendar → syncs to Jarvis
  - Full CRUD support (create, update, delete) with metadata tracking
  - Timezone handling (UTC normalization for correct comparison)
  - See [`docs/n8n/docs/GOOGLE_CALENDAR_SYNC.md`](docs/n8n/docs/GOOGLE_CALENDAR_SYNC.md)
- **n8n Workflow Engine**: Extensible automation workflows
  - Email sending with SMTP
  - Calendar sync orchestration
  - Custom webhook endpoints
  - OAuth2 handling and token refresh
  - See [`docs/n8n/docs/`](docs/n8n/docs/)

### Memory System
- **Dual Database**: Separate DBs for cloud (OpenAI embeddings) and local (nomic embeddings)
- **Auto-Sync**: Bidirectional sync between modes on startup
- **FTS5 Full-Text Search**: SQLite FTS5 with BM25 ranking for fast, accurate keyword searches ⭐ NEW
- **Knowledge Base**: Facts, preferences, technical info with embeddings
- **Conversation History**: Full logging with metadata (cost, tokens, model)
- **Semantic Search**: AI embeddings with configurable similarity threshold (tune via .env)
- **Hybrid Search**: Combines keyword (FTS5) and semantic (embeddings) for comprehensive results
- **Auto-Save**: Automatically remembers project locations, commands, solutions
- **Tool Management**: Enable/disable tools per mode to optimize context window

### Dual Mode Operation
- **Cloud Mode**: **xAI Grok** (2M context, 10-15x cheaper!), Anthropic Claude, OpenAI GPT
- **Local Mode**: Ollama (qwen3-coder, mistral-nemo) + faster-whisper + Kokoro TTS (free, offline)

**Recommended Cloud Provider**: **xAI Grok-4-fast** ($0.20/$0.50 per 1M tokens, 2M context window, automatic caching with 90% discount)

### Voice & Wake Word
- **Wake Detection**: "Hey Jarvis" using OpenWakeWord
- **Fine-tuned Audio**: Optimized for noisy environments + far-field mic
- **Smart Response Formatting**: Auto-condenses verbose outputs for voice
- **Status Updates**: Real-time voice progress during long tasks ⭐ NEW
  - "Searching the web", "Building with OpenCode", "Checking the weather"
  - LLM-generated dynamic summaries from tool output
  - Configurable phrases with humor/encouragement toggles
  - Phrase modes: `normal` or `unhinged` (chaotic/funny)
  - Audio caching for instant playback of repeated phrases
  - See [`docs/STATUS_UPDATES_DESIGN.md`](docs/STATUS_UPDATES_DESIGN.md)

![jarvis-web](docs/images/jarvis-web.png)

### Web Interface ⭐ ENHANCED
- **Jarvis Web UI v1.9** - Full-featured chat interface at localhost:5001
  - Real-time WebSocket communication with tool streaming
  - Mode switching (cloud/local) with per-mode settings
  - **Server Logs Panel**: Real-time LLM + Tool log streaming (simpler than Grafana!) ⭐ NEW
  - **Slash commands**: `/canvas`, `/search`, `/detailed` - modify behavior
  - **@prompts**: `@research`, `@quick`, `@compare` - inject methodologies
  - **✨ Enhance with AI**: Magic button transforms input into optimal prompts
  - **Conversation search/export**: Filter, deep search, JSON/Markdown export
  - **Image upload**: Drag-drop/paste/click with vision analysis
  - **Mode-aware TTS/STT**: Cloud vs Local providers
  - Dynamic LLM/model switching on-the-fly
  - Launch: `./bin/jarvis-web`
  - See [`docs/JARVIS_WEB_UI.md`](docs/JARVIS_WEB_UI.md)

![jarvis-tui](docs/images/jarvis-tui.png)

### Developer Experience ⭐ ENHANCED
- **Command Dashboard TUI**: Interactive terminal UI with 70+ commands
  - Browse, search, and run any Jarvis command from one place
  - Organized by category (Core, API, Memory, Intelligence, Tools, Logs, etc.)
  - Live system status (CPU, RAM, API health)
  - Launch: `./bin/jarvis-dashboard` or `jarvis-d` alias
- **Canvas Viewer**: Visual knowledge display at localhost:8890
  - Jarvis saves research results, code snippets, comparisons
  - Beautiful dark UI with Markdown rendering
  - Search, pin, edit, delete pages
  - Launch: `./bin/jarvis-canvas`

![jarvis-canvas](docs/images/jarvis-canvas.png)

- **Feedback System**: LLM self-critique for continuous improvement
  - Per-query feedback: `--feedback` flag on orchestrator
  - Batch testing: `./bin/jarvis-feedback batch tests/queries.txt`
  - Cross-model grading via `FEEDBACK_PROVIDER`/`FEEDBACK_MODEL`
  - View issues: `./bin/jarvis-feedback issues --days 7`

### Speech Modes - Smart Adaptive Response System

![speech-modes-info-graph](docs/images/speech-modes-info-graph.jpeg)

Jarvis adapts its response style based on your environment and task complexity:

**🎙️ Casual Mode** (Default for Voice)
- Always 8-12 words for voice output
- Perfect for: Voice interactions, speakers, TTS
- Example: *"Website built with dark mode and login system"* (9 words)

**🖥️ Detailed Mode** (Best for CLI/Debugging)
- Full LLM response with complete context
- Perfect for: CLI testing, debugging, logs
- Example: Full technical breakdown with file lists, URLs, next steps

**🤖 Auto Mode** ⭐ (Smart Adaptive)
- **Search tools** → Always formatted (removes URLs, summarizes)
- **Simple queries** → Keep short if already concise
- **Complex builds** → Detailed if >50 words (keeps technical context)
- **Multi-turn** → Formatted summary
- Perfect for: Mixed usage, general assistant work

**Configuration:**
```bash
# Set in config/cloud.env or config/local.env
JARVIS_RESPONSE_STYLE="auto"    # Smart adaptive (recommended)
JARVIS_RESPONSE_STYLE="casual"  # Always short (voice default)
JARVIS_RESPONSE_STYLE="detailed" # Always verbose (CLI)
```

See full guide: [`docs/AUTO_MODE_EXPLAINED.md`](docs/AUTO_MODE_EXPLAINED.md)

---

## 🔍 How It Works

**New to Jarvis?** See these comprehensive guides:

**Reactive Mode** (Current):
- 📊 **[Complete Workflow Guide](docs/JARVIS_WORKFLOW.md)** - How Jarvis processes your requests
  - Visual flowcharts, memory strategy, tool selection
  - Multi-turn orchestration, configuration impact
  - Real-world examples with thinking mode enabled

**Proactive Mode** (Current):
- 🔮 **[Proactive Assistant API](docs/api/API_OVERVIEW.md)** - Event-driven webhook system
  - Receives webhooks from any external system
  - Auto-resolves issues when services recover
  - Background services for follow-ups and reminders
  - Remote monitoring with agent templates
  - See also: [API Docs](docs/api/), [Service Docs](docs/service/)

**Quick Overview:**
```
User Query → Router (LLM analyzes) → Memory Check → Tool Selection → 
Execute Tool(s) → Multi-Turn if Needed → Format Response → User
```

Key decision points:
- **Memory First**: Always checks stored info before external calls
- **Thinking Mode**: See LLM's reasoning process (toggle via `--debug-thinking`)
- **Smart Tool Selection**: Keyword search vs semantic search vs direct tool call
- **Multi-Turn**: Chains tools automatically for complex tasks

---

## 📁 Project Structure

<details>
<summary><strong>Project Directory Structure (click to expand)</strong></summary>

```
jarvis-voice/
├── bin/                      # Executable scripts & utilities
│   ├── wake_jarvis.py        # Cloud wake word loop
│   ├── wake_jarvis_local.py  # Local wake word loop
│   ├── say.sh / say-local.sh # Text-to-speech
│   ├── jarvis-api            # Proactive API server
│   ├── jarvis-services       # Background services daemon
│   ├── restart-api           # Restart API server
│   ├── restart-services      # Restart background services
│   ├── question*.sh          # Q&A entry points
│   ├── memory                # Memory CLI tool
│   ├── manage-tools.py       # Enable/disable tools
│   ├── sync-memory-db.py     # Manual database sync
│   └── setup-memory-db.sh    # Initialize databases
├── lib/                      # Core libraries
│   ├── config_loader.py      # Configuration management
│   ├── memory_db.py          # SQLite memory system
│   ├── llm_provider.py       # LLM provider abstraction
│   ├── opencode_client.py    # OpenCode API client
│   ├── cost_estimator.py     # Token cost calculation
│   └── local_model_corrections.py # Post-processing for local models
├── orchestrator/             # Tool orchestration system
│   ├── orchestrator_v2.py    # Main orchestration logic
│   ├── router_v2.py          # LLM-based routing
│   ├── executor.py           # Tool execution engine
│   └── tool_schema.py        # Tool discovery & validation
├── skills/                   # Tool scripts (24+)
│   ├── remember.py           # Store facts
│   ├── recall.py             # Retrieve facts
│   ├── forget.py             # Delete memories
│   ├── update_memory.py      # Modify existing memories
│   ├── search_memory.py      # Keyword search
│   ├── semantic_recall.py    # AI-powered semantic search
│   ├── get_recent_conversations.py # Conversation history
│   ├── search_conversations.py # Search past conversations
│   ├── execute_bash.py       # Shell command execution
│   ├── opencode.py           # Autonomous coding agent
│   ├── check_opencode_sessions.py # OpenCode progress monitoring
│   ├── send_webhook.py       # HTTP POST/GET requests
│   ├── api_call.py           # Generic API calls
│   ├── crypto_price.py       # Crypto prices
│   ├── get_time.py           # Current time/date
│   ├── create_reminder.py    # Time-based reminders
│   ├── list_reminders.py     # Show reminders
│   ├── acknowledge_reminders.py # Cancel/complete reminders
│   ├── list_alerts.py        # Show alerts (from API)
│   ├── acknowledge_alerts.py # Acknowledge alerts
│   ├── query_service_logs.py # Service status checks
│   ├── ingest_intel.py       # Bulk knowledge import
│   ├── manage_intel.py       # Manage intel files
│   ├── check_tool_logs.py    # Debug tool failures
│   └── *.tool.json           # Tool definitions (JSON schema)
├── config/                   # Configuration files
│   ├── cloud.env             # Cloud mode settings
│   ├── local.env             # Local mode settings
│   ├── cloud.env.example     # Template (safe for git)
│   ├── local.env.example     # Template (safe for git)
│   └── README.md             # Config documentation
├── data/                     # Runtime data
│   ├── jarvis_memory.db      # Cloud mode database (OpenAI embeddings)
│   └── jarvis_memory_local.db # Local mode database (nomic embeddings)
├── logs/                     # Execution logs
│   ├── tools/                # Tool call logs
│   ├── opencode/             # OpenCode session logs
│   ├── api/                  # API server logs
│   └── services/             # Background services logs
├── tests/                    # Test suites
│   ├── integration/          # Integration tests
│   │   ├── compare-models.sh # Model comparison framework
│   │   ├── test-memory-*.sh  # Memory system tests
│   │   └── logs/             # Test results and analysis
│   ├── e2e/                  # End-to-end tests (future)
│   └── unit/                 # Unit tests (future)
├── docs/                     # Documentation
│   ├── api/                  # Proactive API documentation
│   ├── service/              # Background services documentation
│   ├── AUTO_CONTEXT_SYSTEM.md # Short-term conversation memory
│   ├── MEMORY_SYSTEM.md      # Long-term memory architecture
│   ├── DUAL_DATABASE_SYSTEM.md # Cloud/local DB system
│   ├── JARVIS_WORKFLOW.md    # Complete request workflow
│   └── *.md                  # Core system documentation
├── jarvis-intel/             # Private knowledge base (gitignored)
├── jarvis                    # Launcher (cloud mode)
├── jarvis-local              # Launcher (local mode)
├── test-all-tools.sh         # Run all tool tests (cloud)
├── test-all-tools-local.sh   # Run all tool tests (local)
└── README.md                 # This file
```

</details>


---

## 🚀 Quick Start

### 1. Initial Setup

```bash
cd /home/boss/jarvis-voice
./setup.sh
```

This will:
- Check dependencies
- Create directories
- Initialize git repository
- Create convenience symlinks

### 2. Configure

Copy and edit the example configs:

```bash
# For cloud mode (xAI/Anthropic/OpenAI)
cp config/cloud.env.example config/cloud.env
nano config/cloud.env  # Add your API keys

# Recommended cloud provider: xAI Grok
# LLM_PROVIDER="xai"
# XAI_API_KEY="xai-..."  # Get from https://console.x.ai
# XAI_MODEL="grok-4-fast-reasoning-latest"  # 2M context, $0.20/$0.50, reasoning mode

# For local mode (Ollama)
cp config/local.env.example config/local.env
nano config/local.env  # Adjust Ollama endpoint
```

See `config/README.md` and `docs/XAI_PROVIDER.md` for detailed configuration options.

### 3. Install Dependencies

```bash
# Python environment
python3 -m venv ~/jarvis-venv
source ~/jarvis-venv/bin/activate
pip install -r requirements.txt

# System packages (Ubuntu/Debian)
sudo apt install sox ffmpeg jq sqlite3 traceroute inetutils-traceroute

# See system-packages.txt for complete list of system dependencies

# Ollama (for local mode)
curl https://ollama.ai/install.sh | sh
ollama pull qwen3-vl
ollama pull nomic-embed-text

# OpenCode (optional, for coding tasks)
# See docs/opencode/OPENCODE.md for installation
```

### 4. Run Jarvis

```bash
source ~/jarvis-venv/bin/activate

# Cloud mode (Anthropic Claude)
./jarvis

# Local mode (Ollama)
./jarvis-local

# CLI mode (no voice)
./orchestrator/orchestrator_v2.py cloud "What time is it?"
./orchestrator/orchestrator_v2.py local "What time is it?"

# Command Dashboard (all commands in one TUI!) ⭐ NEW
./bin/jarvis-dashboard
```

Say **"Hey Jarvis"** to wake it up!

### 5. Proactive API & Reminders

Enable event-driven alerts, notifications, and smart reminders:

![reactive-vs-proactive-info-graph](docs/images/reactive-vs-proactive-info-graph.jpeg)


```bash
# Start API server (receives webhooks, processes reminders)
./bin/jarvis-api

# Start background services (auto-resolve, follow-ups, reminder scheduler)
./bin/jarvis-services
```

**Create reminders via voice:**
```bash
./jarvis
# Say: "Hey Jarvis, remind me in 4 hours to check dinner"
# Say: "Hey Jarvis, remind me every Friday at 5pm to submit timesheets"
# Say: "Hey Jarvis, what reminders do I have?"
```

**Supported time expressions:**
- "in 30 minutes", "in 4 hours", "in 2 days"
- "tomorrow at 3pm", "at 5pm", "on the 15th"
- "every Wednesday" (weekly, 10am default)
- "every Friday at 5pm" (weekly with time)
- "every month on the 10th" (monthly, 10am default)

See [Proactive API docs](docs/api/) and [Reminder System](docs/api/REMINDER_SYSTEM.md) for details.

### 6. Remote Monitoring Agent (Optional)

Deploy the **[Jarvis Agent](https://github.com/bigsk1/jarvis-voice)** (Docker) on remote servers for health checks and alerts:

![jarvis-monitoring-agent-info-graph](docs/images/jarvis-monitoring-agent-info-graph.jpeg)

```bash
# On remote server (Docker required)
docker run -d \
  --name jarvis-agent \
  --restart unless-stopped \
  -e JARVIS_API_URL="http://your-jarvis-server:8880" \
  -e SERVICE_NAME="my-app" \
  -e CHECK_INTERVAL=300 \
  bigsk1/jarvis-agent:latest

# Agent sends webhooks to Jarvis when issues detected
# Jarvis speaks alerts via voice TTS
# Auto-resolve when service recovers
```

See the [Jarvis Agent repo](https://github.com/bigsk1/jarvis-voice) for templates and configuration options.

---

## 🛠️ Tool System

### Available Skills (46+)

**Memory Management:**
- `remember` - Store facts, preferences, technical info
- `recall` - Retrieve specific memories by category/key
- `search_memory` - **FTS5 full-text search** with BM25 ranking (keyword/entity searches)
- `semantic_recall` - AI-powered conceptual search (natural language questions)
- `update_memory` - Modify existing memories
- `forget` - Delete memories
- `get_recent_conversations` - Access conversation history
- `search_conversations` - Search past interactions

**Action Tools:**
- `execute_bash` - Run shell commands
- `send_email` - Send emails with contact lookup and HTML templates
- `send_webhook` - Trigger named webhooks (Slack, n8n, APIs) with auth
- `api_call` - Generic HTTP API calls
- `crypto_price` - Get cryptocurrency prices
- `get_time` - Current time
- `calculator` - **Advanced math**: arithmetic, percentages, statistics, unit conversions, trig
- `canvas` - **Visual viewer**: save rich content (research, code, comparisons) to web UI
- `weather` - Weather forecasts with OpenWeatherMap
- `phone_call` - **AI Phone Calls**: outbound calls via Vapi.ai with personas, voicemail detection, transcripts
- `spotify` - **Music control**: play, pause, skip, queue, search, device switching, share via email
- `network_tools` - **Network diagnostics**: ping (with stats), DNS lookup, port checks, HTTP/HTTPS status, traceroute
- `system_monitor` - **System resources**: CPU, RAM, disk, processes, network I/O, uptime
- `text_summarizer` - **Text processing**: summarization, keyword extraction, word count, sentiment analysis

**Artifact & Output Tools:** ⭐ ENHANCED
- `generate_image` - **AI image generation**: Google Gemini 3 Pro with Search Grounding
  - Supports aspect ratios (1:1, 16:9, 9:16, etc.), styles, negative prompts
  - **Google Search Grounding** - Real-time data in images (weather, crypto prices, news)
  - Auto-saves to stash + memory for cross-session recall
  - Multi-tool ready: generate → email, generate → print, generate → canvas
- `analyze_image` - **Vision analysis**: Analyze images from URLs, files, or stash refs ⭐ NEW
  - Cloud=Grok/Claude/GPT-4o, Local=llava
  - SSRF protection (blocks private IPs), path traversal protection
  - Auto-stashes analyzed images + creates memory_db entry
  - Example: "Analyze this image https://example.com/chart.png"
- `stash` - **Artifact storage**: download URLs, store files/images/JSON for multi-step workflows
  - Central workshop for temporary files (7-day TTL)
  - `stash://` references work across tools (printer, email, pdf_create, analyze_image)
- `pdf_create` - **PDF generation**: create PDFs from stash files, images, or text
  - Now auto-saves to memory with stash reference for recall
- `printer` - **Print output**: print from stash refs, file paths, or Canvas pages (CUPS)
  - Accepts `stash://space_xxx/file_id` references directly
- `speaker_volume` - **Audio control**: get/set/adjust system speaker volume

**Development:**
- `opencode` - Autonomous coding agent (builds apps, games, APIs)
- `check_opencode_sessions` - Monitor OpenCode progress
- `ingest_intel` - Bulk import knowledge from markdown files
- `check_tool_logs` - View tool execution history

**Proactive System:**
- `list_alerts` - View active alerts
- `acknowledge_alerts` - Clear alerts
- `create_reminder` - Create time-based reminders (one-time or recurring)
- `list_reminders` - View scheduled/triggered reminders
- `acknowledge_reminders` - Clear/acknowledge reminders
- `query_service_logs` - Check background service status
- `manage_intel` - Create/manage intel files

**System:**
- MCP servers (DuckDuckGo search, web fetch, etc.)

### How Tool Calling Works

```
User: "Build a Flask API and test it"
  ↓
LLM Router: Analyzes request
  ↓
Turn 1: Call 'opencode' → Build Flask API
  ↓
Turn 2: Call 'api_call' → Test endpoint
  ↓
Turn 3: Q&A response → "Flask API running on port 8091"
```

**Features:**
- Multi-turn orchestration (chains tools automatically)
- Error recovery with retries
- Timeout handling
- Cost tracking (cloud mode)
- Metadata logging
- Permission system

### Managing Tools (Enable/Disable)

![tool-rag-info-graph](docs/images/tool-rag-info-graph.jpeg)

Control which tools are loaded to optimize context window and performance:

```bash
# List all tools and their status
./bin/manage-tools.py list

# Disable a tool
./bin/manage-tools.py disable crypto_price

# Enable a tool
./bin/manage-tools.py enable crypto_price

# Enable all tools
./bin/manage-tools.py enable-all

# Disable multiple tools for local mode (reduce context)
./bin/manage-tools.py disable opencode check_opencode_sessions ingest_intel
```

**Benefits:**
- Reduce token count for local models (Ollama has smaller context windows)
- Create tool profiles (development vs. production)
- Disable experimental/buggy tools without deleting code
- All tools auto-discovered on startup (only enabled ones load)

See `docs/TOOL_MANAGEMENT.md` for details.

---

## 🧠 Memory System

### Knowledge Base

Stores facts, preferences, and technical information with **hybrid search** (FTS5 + semantic):

![memory-info-graph](docs/images/memory-info-graph.jpeg)

```bash
# Store a fact
"Remember my WireGuard VPN is 192.168.70.0/24"

# Retrieve via keyword search (FTS5 with BM25 ranking)
"Search for VPN network"  # Uses FTS5 for fast, accurate results

# Retrieve via semantic search (AI embeddings)
"What's my VPN network?"  # Uses embeddings for conceptual matching

# View all memories
./bin/memory list

# Tune semantic search sensitivity (in config/cloud.env or local.env)
SEMANTIC_SIMILARITY_THRESHOLD=0.40  # Default: 0.40 (balanced)
# Lower (0.30-0.35) = more results, may include loosely related
# Higher (0.45-0.50) = fewer results, only close matches
```

**Search Strategy:**
- **Keyword/Entity searches** (1-3 words, technical terms): Use `search_memory` → FTS5
- **Natural language questions** (4+ words, conceptual): Use `semantic_recall` → Embeddings

See `docs/FTS5_SEARCH_SYSTEM.md` and `docs/SEMANTIC_THRESHOLD_TUNING.md` for details.

### Auto-Save Memory

Jarvis automatically remembers:
- ✅ Project locations and run commands (after OpenCode builds)
- ✅ Working solutions (port conflicts, config changes)
- ✅ URLs and endpoints you create/use
- ✅ Technical facts from intel files
- ❌ Ephemeral data (current time, transient prices)

### Conversation History

Full conversation logging with metadata:
- User queries and responses
- Tools used per session
- Model, tokens, and cost tracking
- Session IDs for grouping

---

## 🧠 Intelligence Layer

The Intelligence Layer is Jarvis's self-learning system. It observes interactions, reflects on what worked and what didn't, and applies learned insights to improve future routing decisions.

![Intelligence Layer Info Graph](docs/images/intelligence-info-graph.jpeg)


**Key Principles**:
- Everything is continuous (vectors), not discrete rules
- Learning generalizes through semantic similarity
- Positive AND negative constraints (what to do AND what NOT to do)
- Fact vs Procedural classification (only skills stored, not facts)
- Generalizability filtering (low-value insights filtered out)

**Experience Recording**:
- Query (as embedding)
- Tools used (in order)
- Turns taken
- Success/failure
- User satisfaction signals
- LLM response & tool results (for content quality eval) ⭐ NEW

**Insights Generated**:
- Pattern: "Status queries need real-time tools"
- Applies to: "Server health, uptime checks"
- Preferred approach: "Use fetch tools directly"
- Confidence: 0.0-1.0
- Tracking: times_applied, times_helpful, times_failed ⭐ NEW

**Maintenance Jobs** ⭐ NEW:
```bash
# Run all maintenance (decay, anomaly, meta-cognition)
./bin/run-intelligence-maintenance.py --watch

# Or via API
curl -X POST http://localhost:8880/api/intelligence/maintenance/all
```

**How Insights Apply**:
When a new query comes in:
1. Generate query embedding
2. Find similar insights (cosine similarity)
3. Weight by confidence and relevance
4. Inject into routing context
5. Track which insights were applied ⭐ NEW
6. Update helpful/failed counts after interaction ⭐ NEW

See `docs/INTELLIGENCE_LAYER.md` for details.


---

## 🤖 OpenCode Integration

OpenCode is an autonomous coding agent that can build entire projects.

![opencode-info-graph](docs/images/opencode-info-graph.jpeg)

### Usage

```bash
# Via voice
"Use OpenCode to create a Flask API on port 8091"

# Via CLI
./orchestrator/orchestrator_v2.py cloud "Build a Tetris game"
```

### What OpenCode Can Do

- Build web apps (Flask, Express, React)
- Create games (Tetris, Snake, etc.)
- Write scripts and tools
- Install dependencies
- Test and verify builds

### Configuration

```bash
# In cloud.env or local.env
OPENCODE_MODEL="claude-sonnet-4-20250514"  # Or qwen2.5-coder:32b
OPENCODE_PROVIDER="anthropic"              # Or ollama
OPENCODE_BASE_URL="http://localhost:4096"
```

**Workspace:** All OpenCode projects go to `~/jarvis-workspace/projects/`

See `docs/opencode/OPENCODE.md` for details.

---

## 💾 Database & Costs

### Memory Database (Dual System)

Jarvis uses separate databases for cloud and local modes:

![sync-info-graph](docs/images/sync-info-graph.jpeg)


**Cloud Mode** - `data/jarvis_memory.db`:
- Uses OpenAI embeddings (1536 dimensions)
- Optimized for Claude/GPT

**Local Mode** - `data/jarvis_memory_local.db`:
- Uses nomic-embed-text (768 dimensions)
- Optimized for Ollama models

**Auto-Sync**: On startup, newer memories are synced between databases with re-embedded vectors for the target mode's model. See `docs/DUAL_DATABASE_SYSTEM.md`.

**Tables**:
- `knowledge_base` - Facts, preferences, embeddings
- `conversations` - Full conversation history with metadata

### Cost Tracking (Cloud Mode)

Every conversation logs:
- Model used
- Input/output tokens
- Cost in USD
- Tool count
- Execution time

View costs:
```bash
sqlite3 data/jarvis_memory.db "
SELECT 
  date(timestamp) as date,
  SUM(json_extract(metadata, '$.cost_usd')) as total_cost,
  COUNT(*) as conversations
FROM conversations
GROUP BY date(timestamp)
ORDER BY date DESC
LIMIT 7;"
```

---

## 📚 Documentation

### Key Documents

**Getting Started:**
- `config/README.md` - Configuration guide
- `docs/QUICKSTART.md` - Quick setup guide
- `docs/TOOL_CALLING_SYSTEM.md` - How tools work

**Proactive System:**
- `docs/api/` - **Proactive API** documentation (webhooks, alerts, monitoring)
- `docs/service/` - **Background Services** documentation (daemons, auto-resolve)
- **[Jarvis Agent](https://github.com/bigsk1/jarvis-voice)** - Docker agent for remote health checks

**Core System:**
- `docs/phone/PHONE_CALLS.md` - **AI Phone Calls** (Vapi.ai, personas, transcripts, contacts) ⭐ NEW
- `docs/spotify/SPOTIFY.md` - **Spotify Integration** (playback control, search, multi-device) ⭐ NEW
- `docs/STASH_SYSTEM.md` - **Artifact storage** (multi-step workflows, URL downloads, SSRF protection)
- `docs/INTELLIGENCE_LAYER.md` - **Self-learning system** (Phase 1: positive/negative constraints)
- `docs/AUTO_CONTEXT_SYSTEM.md` - Short-term conversation memory
- `docs/JARVIS_WORKFLOW.md` - Complete request flow with examples
- `docs/TOOL_CALLING_SYSTEM.md` - How tool routing works

**Monitoring & Dashboards:**
- `monitoring/README.md` - Grafana + Prometheus + Loki stack
- **Grafana Dashboards:**
  - `Jarvis Intelligence Layer` - Self-learning metrics, insights, confidence
  - `Jarvis - Conversation Audit v2` - Deep drill-down into LLM decisions
  - Plus: LLM Performance, Tool Analysis, API Performance

**Memory System (Updated Nov 2025):**
- `docs/FTS5_SEARCH_SYSTEM.md` - **NEW**: FTS5 full-text search with BM25 ranking
- `docs/DUAL_DATABASE_SYSTEM.md` - Cloud/local DB architecture with auto-sync
- `docs/SEMANTIC_THRESHOLD_TUNING.md` - How to tune similarity threshold
- `docs/MEMORY_SYSTEM.md` - Memory & knowledge base overview
- `docs/MEMORY_SYSTEM_TUNING.md` - Memory system optimization
- `docs/MEMORY_INTELLIGENCE_FIXES.md` - Auto-save improvements

**Tool Management:**
- `docs/TOOL_MANAGEMENT.md` - Enable/disable tools, create profiles
- `docs/TOOL_CALLING_SYSTEM.md` - How tool system works

**Features:**
- `docs/opencode/OPENCODE.md` - OpenCode integration
- `docs/MULTI_TURN_ORCHESTRATION.md` - How tool chaining works
- `docs/METADATA_SYSTEM.md` - Cost tracking & metadata

**Advanced:**
- `docs/opencode/OPENCODE_API_REFERENCE.md` - Full OpenCode API
- `docs/opencode/OPENCODE_AGENTS.md` - Agent system architecture
- `docs/MCP_QUICKSTART.md` - MCP server integration
- `docs/ERROR_RECOVERY.md` - Error handling

**Testing:**
- `tests/integration/compare-models.sh` - Model comparison framework
- `tests/integration/test-memory-tools.sh` - Memory tool selection tests
- `tests/integration/test-memory-real-world.sh` - Complex scenario tests

### Historical/Reference Docs

The following docs are kept for historical context but describe features that have been deprecated or improved:
- `CHANGELOG_2025-11-14.md` - Detailed change log
- `DATABASE_DEEP_DIVE.md` - Database evolution (mentions removed tables)
- `FIXES_2025-11-14.md` - Bug fix details
- `METADATA_POPULATION_STATUS.md` - Metadata implementation tracking

---

## 🔧 Development

### Adding a New Tool

1. **Create the tool script:**
   ```bash
   nano skills/my_tool.py
   ```

2. **Follow the standard interface:**
   ```python
   #!/usr/bin/env python3
   import sys
   import json
   
   def main():
       args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
       
       # Your logic here
       result = do_something(args)
       
       # Return JSON
       print(json.dumps({
           "ok": True,
           "speech": "Task completed",
           "data": result
       }))
   
   if __name__ == "__main__":
       main()
   ```

3. **Create tool definition:**
   ```bash
   nano skills/my_tool.tool.json
   ```
   ```json
   {
     "name": "my_tool",
     "description": "What the tool does",
     "input_schema": {
       "type": "object",
       "properties": {
         "param": {"type": "string", "description": "Parameter description"}
       },
       "required": ["param"]
     }
   }
   ```

4. **Make it executable:**
   ```bash
   chmod +x skills/my_tool.py
   ```

5. **Test it:**
   ```bash
   ./orchestrator/orchestrator_v2.py cloud "use my_tool with X"
   ```

The tool will be auto-discovered!

### Testing

```bash
# Test all tools (cloud)
./test-all-tools.sh

# Test all tools (local)
./test-all-tools-local.sh

# Test memory system (principle-based)
./tests/integration/test-memory-tools.sh

# Test real-world complex scenarios
./tests/integration/test-memory-real-world.sh

# Compare two models side-by-side (creates backups!)
./tests/integration/compare-models.sh local qwen3-vl qwen2.5:7b
./tests/integration/compare-models.sh cloud claude-sonnet-4-5 gpt-4o

# Test specific tool
./orchestrator/orchestrator_v2.py cloud "remember test fact"
```

**Note**: The model comparison script backs up your database before testing. Results are saved to `tests/integration/logs/` with AI-generated analysis.


---

## 🐛 Troubleshooting

### Common Issues

**"OpenCode server not reachable"**
```bash
systemctl --user start opencode
# or
cd ~/opencode && npm start
```

**"Ollama connection failed"**
```bash
curl http://192.168.70.226:11434
ollama serve
```

**"Model not found"**
```bash
ollama pull qwen3-vl
ollama pull nomic-embed-text
```

**"Permission denied on skills/tool.py"**
```bash
chmod +x skills/*.py
```

**Database issues**
```bash
# Check database
sqlite3 data/jarvis_memory.db ".tables"

# Backup before experiments
cp data/jarvis_memory.db data/jarvis_memory.db.backup
cp data/jarvis_memory_local.db data/jarvis_memory_local.db.backup

# Manual sync between cloud and local databases
./bin/sync-memory-db.py cloud  # Sync from local → cloud
./bin/sync-memory-db.py local  # Sync from cloud → local

# Restore from backup (after compare-models.sh tests)
mv data/jarvis_memory_local.db.backup-compare-models data/jarvis_memory_local.db
```

### Logs

Check logs for debugging:
```bash
# Tool execution logs
cat logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl

# OpenCode logs
cat logs/opencode/opencode-$(date +%Y-%m-%d).jsonl

# View recent tool calls
./orchestrator/orchestrator_v2.py cloud "show recent tool logs"
```

---

## 🎯 Roadmap

**Completed (December 2025):**
- ✅ **Jarvis Web UI v1.9** - Full-featured web interface ⭐ ENHANCED
  - **Server Logs Panel**: Real-time LLM + Tool streaming at bottom of UI ⭐ NEW
  - **Color-coded logs**: LLM (purple), Tools (green), with success/error status ⭐ NEW
  - **Expandable details**: Click log entry to see full parsed JSON ⭐ NEW
  - **Slash commands**: `/canvas`, `/search`, `/recall`, `/detailed` - modify behavior
  - **@prompts**: `@research`, `@quick`, `@compare` - inject methodologies
  - **✨ Enhance with AI**: Magic button transforms rough input into optimal prompts
  - **Conversation search**: Quick filter + deep search across all messages
  - **Export/Import**: Download as JSON/Markdown, restore from JSON
  - **Image upload**: Drag-drop/paste/click with vision analysis
  - Real-time WebSocket chat with tool streaming
  - See: `docs/JARVIS_WEB_UI.md`
- ✅ **AI Image Generation (Gemini 3 Pro)** - High-quality image generation ⭐ NEW
  - "Generate a bitcoin infographic with current price" → Gemini creates with real data
  - Aspect ratios (1:1, 16:9, 9:16, 3:4, etc.), styles, negative prompts
  - **Google Search Grounding** - Images can include real-time data (weather, prices, news)
  - Auto-saves to stash + memory for cross-session recall
  - Multi-tool workflows: generate → email, generate → print, generate → canvas
  - See: `skills/generate_image.py`
- ✅ **Stash + Memory Architecture** - Unified artifact workflow ⭐ ENHANCED
  - **Stash** = Workshop (temporary files, 7-day TTL, `stash://` references)
  - **Memory** = Index (permanent entries pointing to stash locations)
  - `safe_resolve_file()` gracefully handles expired stash with fallbacks
  - All artifact tools now: save to stash → create memory entry → enable multi-tool
- ✅ **AI Phone Calls via Vapi.ai** - Outbound AI phone calls ⭐ NEW
  - "Call Boss and ask about dinner plans" → Jarvis calls, has conversation, reports back
  - Multiple personas: Jarvis (default), James (professional), Jay (casual), Samantha (female)
  - Custom Vapi dashboard assistants with `{{owner}}`, `{{task}}`, `{{reason}}` variables
  - Voicemail detection: hangup, leave message, or disabled
  - Sync mode (wait 60s for result) or async mode (check later)
  - Auto-save transcripts to Canvas (`Phone Calls/` folder) and memory
  - Contact book: "Save Andrew's number as +15551234567"
  - See: `docs/phone/PHONE_CALLS.md`
- ✅ **Spotify Integration** - Full music playback control ⭐ NEW
  - "Play my Chill Vibes playlist", "Skip", "What's playing?", "Pause"
  - Searches your saved playlists/library first, then public Spotify
  - Multi-device support (Fire TV, Echo, phone, desktop, etc.)
  - Queue songs, shuffle, repeat, volume control
  - Share currently playing via email with album art and Spotify link
  - OAuth setup via `./bin/spotify-auth`
  - See: `docs/spotify/SPOTIFY.md`
- ✅ **Native Web Search** - Built-in real-time search for cloud providers ⭐ NEW
  - `XAI_SEARCH=true`: Grok live search (web + X posts, auto mode)
  - `ANTHROPIC_SEARCH=true`: Claude's web search tool with citations
  - No external tool calls - cleaner context, faster responses
- ✅ **Network Tools** - Network diagnostics (ping, DNS, port, HTTP/HTTPS, traceroute) ⭐ NEW
  - Enhanced ping with min/avg/max/loss statistics
  - HTTP/HTTPS checks with SSL verification and response times
  - Port connectivity with latency measurement
  - Cross-platform traceroute support
- ✅ **System Monitor** - Real-time system resource monitoring ⭐ NEW
  - CPU usage (total + per-core), memory (RAM + swap)
  - Disk usage per mount point, process list (sortable)
  - Network I/O stats, system uptime with boot time
- ✅ **Text Summarizer** - Text processing and analysis ⭐ NEW
  - Extractive summarization, keyword extraction
  - Word/character/sentence counting, sentiment analysis
- ✅ **Prompt Evolution System** - Self-evolving prompts ⭐ MAJOR
  - Auto-improves tool descriptions based on feedback (1-5 rating scale)
  - System prompt suggestions saved to Canvas for manual review
  - A/B testing, versioning, auto-rollback on degradation
  - Random feedback collection (`FEEDBACK_RANDOM_ENABLED=true`)
  - `./bin/evolve-prompts check cloud` - See what needs improvement
  - `./bin/evolve-prompts auto cloud` - Generate and deploy
  - See: `docs/ADVANCED_AI_TECHNIQUES.md`
- ✅ **Dynamic Tool Builder** - Autonomous tool creation ⭐ MAJOR
  - Creates new tools when capability gaps detected
  - **Duplicate detection** - Checks ALL existing tools (local + MCP + auto-tools)
  - **Ouroboros Research** 🐍 - Tool Builder calls Jarvis for live API research!
  - API key awareness (flags tools needing new credentials)
  - Syntax verification, import checks, runtime testing
  - Dependency gating (new packages require human approval)
  - Full audit trail with report cards + Grafana dashboard
  - `./bin/build-tool --mode cloud build "Check URL accessibility"`
  - See: `docs/TOOL_BUILDER.md`
- ✅ **Canvas System** - Visual knowledge viewer ⭐ NEW
  - Beautiful dark web UI at localhost:8890
  - Jarvis saves research, comparisons, code to visual pages
  - Evolution suggestions now auto-create Canvas pages
  - Markdown rendering, syntax highlighting, live reload
  - Search, pin, edit, delete - all auto-saved to memory
  - Launch: `./bin/jarvis-canvas`
- ✅ **Calculator Tool** - Advanced calculations ⭐ NEW
  - Arithmetic, percentages (15% of 200), statistics (mean, stdev)
  - Unit conversions (miles↔km, °F↔°C, GB↔TB, cups↔ml)
  - Trig (sin, cos, tan with degree variants), logarithms, factorials
- ✅ **Feedback System** - LLM self-critique ⭐ NEW
  - `--feedback` flag for per-query feedback
  - `./bin/jarvis-feedback` CLI (run, batch, summary, issues)
  - Cross-model grading (FEEDBACK_PROVIDER/FEEDBACK_MODEL)
  - Per-tool rating attribution (multi-tool fairness)
  - Full context analysis (system prompt, tools, intelligence)
- ✅ **Dashboard Enhancements** - 70+ commands
  - Evolution commands (check, list versions, auto, history)
  - Tool builder commands (list pending, approve, reject)
  - Canvas, feedback, monitoring commands
  - Unique tmux sessions per service

**Completed (November 2025):**
- ✅ **Command Dashboard TUI** - Interactive terminal UI for all Jarvis commands
  - 60+ commands organized by category
  - Search/filter, tab navigation, live system status
  - Run any command with Enter, view output in real-time
  - Launch: `./bin/jarvis-dashboard` or `jarvis-d` alias
- ✅ **Status Updates System** - Real-time voice progress during tasks ⭐ MAJOR
  - LLM dynamic summaries (gpt-4o-mini/qwen3 generates natural phrases)
  - Tool-aware updates (opencode, search, weather, fetch)
  - Rate limiting, error deduplication, collision prevention
  - Cloud (OpenAI TTS) + Local (Kokoro TTS) support
  - Phrase modes (`normal` / `unhinged`), audio caching, silence padding
- ✅ **Weather Tool** - OpenWeatherMap with geocoding for accurate locations
- ✅ **Intelligence Layer Phase 1.5** - Full insight lifecycle ⭐ MAJOR
  - Positive AND negative constraints (what to do AND what NOT to do)
  - Fact vs Procedural knowledge classification
  - Generalizability filtering, confidence decay tracking
  - **Insight tracking**: times_applied, helpful, failed now active
  - **Decay job**: Auto-prunes stale insights (<0.15 confidence)
  - **Anomaly detection**: Flags unusual experiences (high turns)
  - **Meta-cognition**: Detects blind spots, learning issues
  - **13 log events** for full Grafana/Loki visibility
  - Grafana dashboard with real-time metrics
  - API endpoints for debugging (`/api/intelligence/*`)
  - Maintenance CLI (`./bin/run-intelligence-maintenance.py`)
  - Health check and sync tools
- ✅ **Conversation Audit v2 Dashboard** - Deep drill-down into LLM decisions
  - Tools selected vs executed comparison
  - Activity timeline (LLM + Tool logs interleaved)
  - Cost/token tracking over time
- ✅ Multi-turn tool orchestration
- ✅ **xAI Grok integration** (2M context, 10-15x cheaper, automatic caching, reasoning mode) ⭐
- ✅ **Google Calendar bidirectional sync** (reminders ↔ events via n8n workflows) ⭐
- ✅ **Monitoring Stack** (Grafana + Prometheus + Loki for real-time observability) ⭐
- ✅ **LLM Call Logging** (comprehensive telemetry: cost, latency, tokens, multi-turn analysis) ⭐
- ✅ **Modular webhook system** (send_email, send_webhook with auth support)
- ✅ **Email tool** (contact management, HTML templates, SMTP via n8n)
- ✅ **Ghost tools pattern** (critical tools always available, bypasses semantic search)
- ✅ **Disaster recovery guide** (complete system rebuild documentation)
- ✅ **FTS5 full-text search** with BM25 ranking (faster, more accurate keyword searches)
- ✅ **Auto-context system** (short-term conversation memory across wake word cycles)
- ✅ **Comprehensive burn test** (modular test suite for all features)
- ✅ Intelligent memory system with **hybrid search** (FTS5 + semantic embeddings)
- ✅ **Proactive API & Background Services** (webhooks, auto-resolve, monitoring)
- ✅ **Dual database system** (cloud/local with auto-sync)
- ✅ **Tool management** (enable/disable per mode)
- ✅ **Model comparison framework** with AI analysis
- ✅ **Configurable semantic threshold** tuning
- ✅ **Dynamic wake word greetings** for personality
- ✅ **Voice timeout system** for noisy environments
- ✅ OpenCode integration
- ✅ Cost tracking and metadata logging
- ✅ MCP server support (with snake_case enforcement)
- ✅ Auto-save intelligence
- ✅ Conversation history

**In Progress:**
- Voice mode improvements
- Additional n8n workflow integrations
- Performance optimization for local models

**Planned (Advanced AI - See `docs/ADVANCED_AI_TECHNIQUES.md`):**
- ✅ **Phase 3: Self-Evolving Prompts** - COMPLETE! Auto-improve prompts, A/B testing, rollback
- ✅ **Phase 4: Dynamic Tool Creation** - COMPLETE! In-house tool builder with safety checks
- **Phase 5: Parallel Subagents** - Concurrent execution for multi-part queries (3x speedup)
- **Phase 6: Self-Play Optimization** - Nightly simulation to discover better routing strategies
- ✅ **Phase 7: Versioned Prompts** - COMPLETE! Auto-rollback on performance degradation

**Other Planned:**
- **Intelligence Layer Phase 2** - Implicit failure detection, tool trashing detection, conflict resolution
- **Intelligence Layer Phase 3** - User profile learning (communication style, shortcuts, preferences)
- Web UI for memory management and system health
- Home automation integrations (Home Assistant, MQTT)
- Multi-user support with isolated memory contexts
- Tool profiles for local vs cloud modes
- Single start / stop script for api, services, jarvis
- Custom wake word training
- Mobile app for remote control
- Additional n8n workflows to integrate features
- Test webhook system for universal effectiveness

---

## 📝 License

Private project - Not licensed for public use.


**Current Version:** v2.17 (December 2025)  
**Status:** Production Ready ✅  
**Latest Features:** Jarvis Web UI v1.9, Server Logs Panel, Real-time LLM + Tool Streaming
