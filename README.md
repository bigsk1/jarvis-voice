![jarvis-social](https://imagedelivery.net/WfhVb8dSNAAvdXUdMfBuPQ/gallery/2026-06-19/generated/professional_wide_github_repository_soci_20260619__da8ee89d/public)

## What is Jarvis?

Jarvis is a self-hosted AI assistant for voice, chat, automation, memory, and coding. It can answer questions, call tools, run repeatable workflows, manage local knowledge, create and organize artifacts, control external services, and hand larger software tasks to an autonomous coding workspace.

At its core, Jarvis is an orchestration layer. A request can be handled as simple Q&A, routed to one tool, expanded into a multi-tool plan, executed through a deterministic workflow, or delegated to an autonomous agent. Tool RAG keeps the active tool list focused, MCP support makes the system extensible, and persistent memory lets Jarvis reuse what it learns across sessions.

Jarvis can run with cloud LLMs or in a fully local/offline mode using local models, speech-to-text, text-to-speech, self-hosted assets, and tool profiles that disable internet-dependent capabilities. Profiles let you swap between setups such as full cloud power, local-first privacy, development, Docker-safe tools, or a locked-down offline assistant.

The project includes several ways to use and inspect the system:

- **Voice, CLI, Web UI, and TUI** entry points for talking to Jarvis, sending commands, and running workflows.
- **Chat UI** with streaming tools, mode switching, prompt enhancement, file/image uploads, conversation search, exports, pinned-safe cleanup, and live logs.
- **[Background tasks and task callbacks](docs/BACKGROUND-TASKS.md#how-background-work-finishes)** let reviewed long-running Web tools release the chat, then return a saved card and answer; local skills, API waits, and callback services share one task system.
- **[Source library](docs/SOURCE_LIBRARY.md)** for retaining original documents and retrieving verifiable passages across conversations, with page/line citations and separate cloud/local collections.
- **Video understanding** for clips and silent screen recordings, with sampled timestamps, optional speech transcription, and follow-up questions about specific intervals. See [Video analysis](docs/tools/video/ANALYSIS.md).
- **Canvas plus Image, Audio, and Video Galleries** for saved notes, generated artifacts, media browsing, favorites, and visual reports.
- **Memory Dashboard** for knowledge, conversations, scheduled tasks, reminders, and database maintenance.
- **Intelligence Dashboard** for self-learning insights, tool performance, experience history, confidence tracking, and repair feedback.
- **Docs Viewer** for browsing the project documentation with an assistant grounded in the local `docs/` folder.
- **Logs Viewer and full API** for debugging, automation, webhooks, monitoring, reminders, workflows, images, Canvas, memory, and intelligence data.

The `jarvis-dashboard` TUI is the terminal control center: one place to launch commands, inspect status, reach common tools, and operate Jarvis without opening a browser.

Deterministic workflows are Jarvis's reliable automation path. Instead of asking an LLM to improvise every step, a workflow defines the exact tools, order, retries, timeouts, validation, and output handling. That makes repeated jobs predictable, inspectable, and easier to debug.

[![Jarvis Voice runtime architecture](docs/diagrams/jarvis-voice-runtime.svg)](https://bigsk1.com/jarvis-voice/docs/diagrams/jarvis-runtime-architecture.html)

## Jarvis Head

Jarvis Head is an optional Matrix-style face and Linux virtual-console kiosk. It coalesces from the rain when Jarvis wakes, reacts to listening and speech, tracks TTS with audio-driven mouth shapes, and dissolves back into the rain without owning or supervising the core voice processes.

https://github.com/user-attachments/assets/101c682d-7ed3-4734-b156-fc238d2d4077

[Setup, rendering options, configuration, and troubleshooting](docs/JARVIS_HEAD.md)

## Prerequisites

Bare minimum to try Jarvis in the **browser** (Web UI chat — no local mic or speakers required):

Every mode requires an [Ollama](docs/ollama/README.md) daemon reachable through
`OLLAMA_BASE_URL`, on localhost or a LAN host, with the pinned
[Jarvis Embedding](docs/ollama/JARVIS_EMBEDDING_MODEL.md) artifact installed:

```bash
ollama pull bigsk1/jarvis-embedding:bf16-v1
```

| Path | Native (Ubuntu 24.04+, Python 3.12+) | Windows / macOS |
|------|----------------------------------------|-----------------|
| **Cloud** | `OPENAI_API_KEY` in `config/cloud.env` + Ollama with Jarvis Embedding | [Docker](docs/docker/MAC-WINDOWS.md) + `OPENAI_API_KEY` + Ollama with Jarvis Embedding on the host/LAN |
| **Local** | Ollama with Jarvis Embedding and a local chat model + a local TTS server (default in example: Kokoro — see `config/local.env.example`) | [Docker](docs/docker/MAC-WINDOWS.md) + Ollama with Jarvis Embedding and a local chat model on the host/LAN + Kokoro or Qwen3-TTS |

Jarvis currently uses Ollama-native `/api/tags` and `/api/embed` endpoints and
verifies the published model manifest digest. A bare llama.cpp or
`llama-server` endpoint is not a supported replacement, even if it loads the
same GGUF file.

Native `./install.sh` also sets up wake word and host TTS playback — that path assumes a working mic and speakers. Use the Web UI first if you only want chat in the browser.

> **Quick start**
> 1. Clone the repo so it ends up at **`$HOME/jarvis-voice`**
> 2. Run **`./install.sh`** on Ubuntu 24.04+ with Python 3.12+
> 3. Add your API keys, audio settings, and intended **`OLLAMA_BASE_URL`** hosts in **`config/cloud.env`** and **`config/local.env`**
> 4. Pull **`bigsk1/jarvis-embedding:bf16-v1`** on every selected Ollama host, then run **`./bin/check-embeddings-health.py --both --runtime-only`**
> 5. Re-run **`./verify-env.sh`**, then start with **`./bin/start`**
>
> The base installer handles the core Jarvis setup only: system deps, `uv`, the `~/jarvis-venv` environment, config seeding, and project setup. Optional extras like OpenCode and n8n come later and are not required for a normal install.
>
> Full walkthrough: [Install Guide](docs/INSTALL_GUIDE.md)
> Config details: [config/README.md](config/README.md)
> Web UI guide: [docs/JARVIS_WEB_UI.md](docs/JARVIS_WEB_UI.md)
> Speech-to-text guide: [docs/SPEECH_TO_TEXT.md](docs/SPEECH_TO_TEXT.md)
>
> **macOS and Windows:** The experimental Docker Desktop path runs the Web UIs without a native Ubuntu or Python installation. See [Mac and Windows Docker Installation](docs/docker/MAC-WINDOWS.md) for Terminal, PowerShell, and Command Prompt steps, limitations, and troubleshooting.

## ✨ Key Features

![jarvis-web](docs/images/jarvis-web-ui.png)

### Web Interface
- **Jarvis Web UI** - Full-featured chat interface at localhost:5001
  - Real-time WebSocket communication with tool streaming
  - **[Task recovery](docs/WEB_TASK_RECOVERY.md)**: Reload or reconnect to running work, restore Stop, and recover missed answers without replaying speech
  - Mode switching (cloud/local) with per-mode settings
  - **Audio playback controls**: Speaker button with pause/resume/stop
  - **[Hands-free Talk](docs/WEB_TALK.md)**: Speak, pause to send, hear the answer, and continue in the same conversation; Pause, Interrupt, and End controls
  - **[Firefox Talk](docs/FIREFOX_TALK.md)**: Use the same hands-free conversation from the companion sidebar or pop-out
  - **[Firefox extension source](https://github.com/bigsk1/jarvis-firefox-extension)**: Independent versions, public source, and [unlisted signing instructions](jarvis-firefox-extension/REVIEW.md) for installation that survives restarts
  - **Music generation**: ElevenLabs music plays inline in chat
  - **Server Logs Panel**: Real-time LLM + Tool log streaming (simpler than Grafana!)
  - **`/logs` Log Viewer**: Read-only browser for `.jsonl`, `.log`, and `.md` logs with folder drill-down, search, lazy loading, and YAML-style JSONL rendering
  - **Workflow commands**: `/archive`, `/research`, `/note`, `/health` - deterministic multi-tool pipelines
  - **Workflow hover tooltips**: Hover over `/` suggestions to see steps and descriptions
  - **Prompt hover tooltips**: Hover over `@` suggestions to see key points
  - **@prompt guidance**: `@research`, `@quick`, `@compare`, `@generate_music`, `@email`, `@daily`
  - **Context-first guidance**: Saved prompt instructions are placed before the required task you type; an empty chat box is rejected
  - **Tool Hints**: Start typing to get tool suggestions as you type or use #tool_name to add a tool to the request
  - **Chat only**: Use `#chat_only` to keep a sticky no-tools conversation mode that skips Tool RAG schemas and provider-hosted tools until its mode chip is removed
  - **✨ Enhance with AI**: Magic button transforms input into optimal prompts
  - **Conversation search/export**: Filter, deep search, JSON/Markdown export, pinned-safe 90-day cleanup via `cleanup-all`
  - **Completion Guard**: Manual `Completed correctly?` card plus auto-evaluator mode, one bounded repair pass, stop/cancel support for repair runs, follow-up tickets, workflow/fire-and-forget exclusions, exported metadata, and intelligence-layer corrected-path learning
  - **Image upload**: Drag-drop/paste/click with multi-image vision analysis (up to 6 cloud / 2 local)
  - **[Mixed attachments](docs/MIXED_SOURCE_ATTACHMENTS.md)**: Combine PDFs, notes, recordings, and analysis images in one request; keep source references for follow-ups (6 total cloud / 2 local)
  - **Structured result previews**: Focused cards, lists, metrics, and image galleries for search, shopping, local, travel, trends, and news tools
  - **Mode-aware TTS/STT**: Cloud vs Local providers
  - Dynamic LLM/model switching on-the-fly
  - Launch: `./bin/jarvis-web`
  - See [`docs/JARVIS_WEB_UI.md`](docs/JARVIS_WEB_UI.md)


### Intelligence & Self-Learning
- **Intelligence Layer**: Self-learning system that improves over time
  - Records interactions and reflects on them into reusable procedural insights
  - **Positive constraints**: "Use mcp_fetch_fetch for server status checks"
  - **Negative constraints**: "Avoid search_memory for real-time data"
  - **Tool provenance**: Source experience, web conversation ID, source tool sequence, and evidence trail for insight audits
  - **Preferred sequences**: Stores advisory multi-tool sequences plus primary intent/supporting tools without forcing rigid workflows
  - **Workflow attribution**: Reflection separates workflow selection from recipe-owned component order and stores only specific, currently runnable `preferred_workflow_id` recommendations
  - Generalizability filtering (only stores reusable insights)
  - **Insight tracking**: times_applied, times_helpful, times_failed are updated when retrieved insights are later used
  - **Reflection observability**: Lifetime reflection tokens/cost and last reflection provider/model on insight records
  - **Selective decay**: Protects proven strategies, bounds long-gap catch-up, retires unsafe legacy negatives, previews changes, and creates a verified pre-write backup
  - **Anomaly detection**: Flags unusual experiences
  - **Meta-cognition**: Analyzes learning health
  - Separate cloud/local learning databases with one fingerprinted 768D embedding contract
  - See [`docs/INTELLIGENCE_LAYER.md`](docs/INTELLIGENCE_LAYER.md)

![Jarvis Intelligence insights](docs/images/jarvis-intelligence-ui.png)

- **Intelligence Dashboard** at localhost:5003
  - Server-side paginated experience/insight lists with scroll loading and lightweight summary counts
  - Experience cards show IDs; sort by date, turns, tool count, Completion Guard status
  - Filter by success/fail, tool count, specific tool, Completion Guard status
  - Experience details show configured-local + UTC time, Completion Guard metadata, and stored raw JSON
  - Sort insights by applied, helpful, preferred/avoided tools
  - 5-tier confidence filtering (Elite/High/Good/Medium/Low)
  - Insight details show preferred workflow/sequence, source experience/web conversation, evidence trail, and reflection cost/tokens
  - Tool performance plus optional lifetime Completion Guard repaired/status totals
  - Maintenance actions include safer decay confirmation; CLI/API dry-run available for previews
  - Launch: `./bin/jarvis-intelligence`

### Tool System
- **Tool profile overlays** (optional): JSON files under `skills/profiles/` merge with each tool’s `enabled` flag — set `JARVIS_TOOL_PROFILE` in `config/local.env` or `config/cloud.env` to the profile name (e.g. offline). Copy starters from [`skills/profiles/examples/`](skills/profiles/examples/). After switching profile, restart services and run `./bin/sync-tools.py local` or `cloud`. CLI: `./bin/manage-tools.py -h`. Details: [`skills/README.md`](skills/README.md) (section *Tool profiles*).
- **Tool RAG System**: Dynamic tool retrieval - loads only relevant tools for each query
  - Scales to 100+ tools without context flooding
  - Vector-based semantic search for tool discovery
  - Ghost tools plus enabled `tool_search` and `workflow` discovery helpers are prioritized inside the final schema cap
  - Effective order: manifest → profile override → mode/config availability → live registry → Web/request blocks → Tool RAG shortlist
  - See [`docs/TOOL_RAG_STRATEGY.md`](docs/TOOL_RAG_STRATEGY.md)
- **Versioned Router Prompts**: selectable `v1`-`v4` system prompts for routing
  - `v1` provides the full routing instructions; `v2`, `v3`, and `v4` use more compact prompts with the same routing responsibilities
  - `v4` is the local-mode default in `config/local.env.example`; cloud examples stay on `v1` unless changed in env or Web Settings
  - See [`orchestrator/router_prompts/README.md`](orchestrator/router_prompts/README.md)
- **Advanced Tool Calling**: LLM-powered routing with 100+ tools
- **OpenAI Responses API support**: Optional `/v1/responses` routing for OpenAI tool-capable turns, in-flight client-tool continuation, hosted-tool gates, prompt-cache hints, and safe Chat Completions fallback
- **Multi-Turn Orchestration**: Chains multiple tools to complete complex tasks
- **Optional Auto-Context**: Short-term recall of recent conversations
  - When enabled, supplies recent exchanges without requiring an explicit recall tool call
  - Configurable independently of saved Web conversation history and long-term memory
  - See [`docs/AUTO_CONTEXT_SYSTEM.md`](docs/AUTO_CONTEXT_SYSTEM.md)
- **Intelligent Memory**: Semantic search + conversation history with auto-save
- **OpenCode Integration**: Autonomous coding agent for building projects
- **MCP Support**: Extensible via Model Context Protocol servers
  - Optional [Google Workspace Docker service](google-workspace/README.md) for a dedicated account, with headless OAuth setup and Gmail/Drive/Docs/Sheets tools.
  - Optional [Apify Actor gateway](docs/mcp/APIFY.md) for catalog discovery and
    one shared run/read interface, with run limits and background recovery.
  - Optional [email command inbox](docs/tools/email-inbox-tool/README.md) for approved senders and threaded replies through a scheduled workflow. See the published [sequence](https://bigsk1.com/jarvis-voice/docs/diagrams/jarvis-email-inbox-sequence.html) and [data-flow](https://bigsk1.com/jarvis-voice/docs/diagrams/jarvis-email-inbox-dataflow.html) charts.

### Proactive System
- **Event-Driven API**: Receive webhooks from external systems (port 8880)
  - **Optional API Authentication**: Bearer token auth (`JARVIS_API_AUTH=true/false`)
  - Localhost whitelisted, public paths always accessible
  - See [`docs/SECURITY_HARDENING.md`](docs/SECURITY_HARDENING.md)
- **Auto-Resolve**: URL-based and agent-based automatic issue resolution
- **Background Services**: 24/7 daemons for follow-ups, healing, reminders, and scheduled task execution
- **Scheduled Tasks**: Native scheduler for one-time or recurring Jarvis queries and workflows
  - Natural schedule parsing like `tomorrow at 1pm`, `April 4th at 4pm`, `4/4 at 4pm`, and `every weekday at 9am`
  - Mode-specific task registry with run history, `run_now`, and cancel/delete controls
  - Managed by `scheduled_task_runner` alongside the other background services
  - Full task management in the Memory Browser UI Scheduled tab
  - See [`docs/tools/scheduled-tasks/scheduled-tasks.md`](docs/tools/scheduled-tasks/scheduled-tasks.md)
- **Smart Reminders**: Time-based reminders with natural language parsing and recurring support
- **Remote Monitoring**: Deploy [Jarvis Monitor](https://github.com/bigsk1/jarvis-monitor) (Docker) anywhere to send health checks and alerts
- **Voice Notifications**: Jarvis speaks alerts and reminders via TTS
- **Quiet Notifications**: Shared tool/API/cron helper with optional ntfy delivery and Web **Settings → Notifications** history; [setup and usage](docs/tools/notification-tool/README.md)

### Integrations & Automation
- **AI Phone Calls via Vapi.ai**: Outbound AI phone calls on your behalf
  - "Call Boss and ask if he wants to see Gladiator II tonight"
  - Multiple personas: Jarvis (default), James (professional), Jay (casual), Samantha (female)
  - Custom Vapi dashboard characters with dynamic variables (`{{owner}}`, `{{task}}`)
  - Voicemail detection and handling
  - Auto-save transcripts to Canvas and memory for later recall
  - Contact management: save numbers by name
  - See [`docs/tools/phone/PHONE_CALLS.md`](docs/tools/phone/PHONE_CALLS.md)
- **Spotify Integration**: Full music control via Spotify API
  - "Play Chill Vibes playlist", "Skip this song", "What's playing?"
  - Search your library first, then public Spotify
  - Multi-device support (Fire TV, Echo, phone, desktop)
  - Queue management, shuffle, repeat, volume control
  - Share what's playing via email with album art
  - See [`docs/tools/spotify/SPOTIFY.md`](docs/tools/spotify/SPOTIFY.md)
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
- **OpenClaw Multi-Agent Integration**: Secondary AI assistant on a remote OpenClaw gateway
  - Real-time chat via `openclaw` tool (OpenAI-compatible API)
  - Fire-and-forget webhooks for Discord/Telegram posting
  - The remote agent can POST back to Jarvis API (intel, canvas, alerts, voice)
  - **Multi-agent voice**: a remote agent can speak with its own cloned voice through Jarvis's speakers
  - Priority levels (urgent/normal/background) and configurable timeouts
  - Division of labor: Jarvis = local/home, OpenClaw = web/social
- **Cloudflare Images CDN**: Permanent image hosting for multi-agent workflows
  - Upload from file, URL, base64, or stash reference
  - Organized paths: `{uploader}/{date}/{category}/{filename}`
  - Metadata storage (prompt, tags, provider) for tracking
  - Enables Samantha to share generated images via permanent URLs
  - API: `POST /api/images`, `POST /api/images/base64`
  - See [`docs/api/IMAGES.md`](docs/api/IMAGES.md)
- **Generated Images API**: Full management of AI-generated images
  - **3 providers**: Gemini (grounding), OpenAI (best text), xAI (fast & cheap!)
  - **Image-to-image editing**: Edit existing images via `reference_image` parameter
  - **Batch generation**: xAI supports `n=1-10` for multiple variations ($0.02/image!)
  - List, search, download, delete local images
  - Generate new images with optional `upload_to_cdn` for one-step CDN URL
  - CDN catalog (`cdn_catalog.json`) caches URLs - no re-uploads needed
  - API: `/api/generated-images/*`
  - See [`docs/api/GENERATED_IMAGES.md`](docs/api/GENERATED_IMAGES.md)
- **Generated Music API**: Catalog-backed AI music generation
  - Generate songs, instrumentals, jingles, and soundtracks with duration,
    genre, mood, tempo, quality, and structured composition options
  - ElevenLabs (`music_v1` or `music_v2`) and Google Gemini Lyria Clip/Pro
    adapters; `MUSIC_TOOL_PROVIDER` and per-request `provider` choose the provider
  - API: `POST /api/generated-music/generate`
  - See [`docs/tools/generate-music-tool/README.md`](docs/tools/generate-music-tool/README.md)
  - See [`docs/api/GENERATED_MUSIC.md`](docs/api/GENERATED_MUSIC.md)
- **Optional HeyGen video**: `HEYGEN_API_KEY` enables text/image clips and short
  Avatar IV presenter videos, with Stash inputs, saved gallery output, and
  native job receipts for checking or collecting existing work. Without the
  key, HeyGen stays hidden in the Web UI. See [setup and demo](docs/HEYGEN.md).
- **Feedback System**: LLM self-critique for continuous improvement
  - Per-query feedback: `--feedback` flag on orchestrator
  - Batch testing: `./bin/jarvis-feedback batch tests/queries.txt`
  - Cross-model grading via `FEEDBACK_PROVIDER`/`FEEDBACK_MODEL`
  - View issues: `./bin/jarvis-feedback issues --days 7`


![memory-browser](docs/images/jarvis-memory-ui.png)

### Memory System
- **Dual Database**: Separate cloud/local data sets using the same fingerprinted Jarvis Embedding vectors
- **Auto-Sync**: Bidirectional sync between modes on startup
- **FTS5 Full-Text Search**: SQLite FTS5 with BM25 ranking for fast, accurate keyword searches
- **Knowledge Base**: Facts, preferences, technical info with embeddings
- **Conversation History**: Full logging with metadata (cost, tokens, model)
- **Semantic Search**: AI embeddings with configurable similarity threshold (tune via .env)
- **Hybrid Search**: Combines keyword (FTS5) and semantic (embeddings) for comprehensive results
- **Auto-Save**: Automatically remembers project locations, commands, solutions
- **Tool Management**: Enable/disable tools per mode to optimize context window

### Dual Mode Operation
- **Cloud Mode**: OpenAI (shipped default), xAI Grok (`grok-4.7` recommended for xAI), Anthropic Claude, or Ollama Cloud (`*:cloud` / `*-cloud` models through a signed-in Ollama daemon)
  - OpenAI can use Chat Completions by default or opt into Responses API routing for tool-capable turns with `OPENAI_API_MODE=responses` + `OPENAI_RESPONSES_TOOLS=true`
- **Local Mode**: Ollama (`gemma4` default) + faster-whisper + Kokoro/Qwen3-TTS (free, offline)
- **Optional Helper LLM**: Native and Docker installs can use the versioned MiniCPM5-1B helper through an external Ollama daemon for zero-API-cost status phrases and Stash metadata summaries, using CPU or automatic GPU acceleration without changing the primary chat provider. Roles are opt-in and retain their existing fallbacks; see the [setup and benchmark guide](docs/ollama/README.md#optional-helper-model).
- **Mode is not provider selection**: `JARVIS_MODE` chooses config/data boundaries; `LLM_PROVIDER` chooses the chat backend. See [`docs/ollama/README.md`](docs/ollama/README.md).
- **Model Prompt Overrides**: Small provider/model-specific YAML prompt overlays in `config/models/`
  - Lets you patch stable model quirks without changing the global prompts for every provider
  - Supports exact model folders plus deterministic aliases for dated model names and runtime suffixes like `:latest` and `:cloud`
  - See [`docs/MODEL_PROMPT_OVERRIDES.md`](docs/MODEL_PROMPT_OVERRIDES.md)

### TTS Providers
| Provider | Mode | Quality | Cost | Notes |
|----------|------|---------|------|-------|
| **ElevenLabs** | Cloud | Excellent | Paid | Best quality, expressive voices |
| **xAI TTS** | Cloud | Good | Paid | Native xAI TTS using `XAI_API_KEY`; built-in and custom voice IDs; optional expressive speech tags |
| **Qwen3-TTS** | Both | Excellent | Free | 28 cloned voices (Jarvis, Samantha, etc.), local network |
| **Kokoro** | Local | Good | Free | Lightweight, fast, Nicole+Sarah voices |
| **OpenAI TTS** | Cloud | Good | Paid | alloy, echo, fable, onyx, nova, shimmer |

Configure via `TTS_PROVIDER` in `cloud.env` or `local.env`. ElevenLabs v4 is available with `TTS_PROVIDER=elevenlabs` and `ELEVENLABS_TTS_MODEL=eleven_v4` (or `eleven_v4_turbo`); `ELEVENLABS_TTS_STYLE_TAGS_ENABLED=true` allows reviewed audio cues in final speech, while displayed chat removes them. V2 and v3 remain selectable; explicit supported audio cues are preserved for v3. xAI TTS uses its native `/v1/tts` API and supports optional final-speech tags via `XAI_TTS_STYLE_TAGS_ENABLED`; Qwen3-TTS uses an OpenAI-compatible API.
See: [`docs/qwen3-tts/QWEN3_TTS_INTEGRATION_GUIDE.md`](docs/qwen3-tts/QWEN3_TTS_INTEGRATION_GUIDE.md)

**Voice API** (`/api/voice/speak`): Supports per-request TTS provider/voice overrides for multi-agent voice identity
See: [`docs/api/VOICES.md`](docs/api/VOICES.md)

**Cloud Chat Default:** OpenAI. For xAI, the tracked recommended model is **Grok 4.5**; Grok 4.3 remains available for 1M context or non-reasoning use.

### Voice & Wake Word
- **Wake Detection**: "Hey Jarvis" using OpenWakeWord
- **Fine-tuned Audio**: Optimized for noisy environments + far-field mic
- **Smart Response Formatting**: Auto-condenses verbose outputs for voice
- **Status Updates**: Real-time voice progress during long tasks
  - "Searching the web", "Building with OpenCode", "Checking the weather"
  - Optional LLM summaries run concurrently and never delay tool execution
  - 250 ms debounce skips unnecessary speech between fast tool calls
  - Bounded, sanitized execution context with static phrase fallback
  - Configurable phrases with humor/encouragement toggles
  - Phrase modes: `normal` or `unhinged` (chaotic/funny)
  - Native and Web status-audio caching for repeated phrases
  - See [`docs/STATUS_UPDATES.md`](docs/STATUS_UPDATES.md)


![jarvis-tui](docs/images/jarvis-tui.png)

### Developer Experience
- **Command Dashboard TUI**: Interactive terminal UI with 70+ commands
  - Browse, search, and run any Jarvis command from one place
  - Organized by category (Core, API, Memory, Intelligence, Tools, Logs, etc.)
  - Live system status (CPU, RAM, API health)
  - Separate full-stack and UI-only startup actions for cloud/default and local env modes
  - Launch: `./bin/jarvis-dashboard` or `jarvis-d` alias
- **Intelligence Dashboard**: Visual dashboard for self-learning at localhost:5003
  - Experience sorting (date, turns, tool count) and filtering (success/fail, tool count, specific tool)
  - Insight sorting (applied, helpful, preferred/avoided tools, confidence)
  - 5-tier confidence: Elite (96%+), High (85-95%), Good (75-84%), Medium (50-74%), Low (0-49%)
  - Tool performance showing ALL tools with prefer/avoid stats
  - **Feedback tab** - View all feedback logs with rating/time filters, expandable details, no terminal needed
  - Mobile responsive: hamburger menu at ≤730px
  - Launch: `./bin/jarvis-intelligence`
- **Memory Browser UI**: Web interface for memory management at localhost:5002
  - View, search, add, edit, delete memories from `knowledge_base`
  - Intel file manager (create, upload, edit, ingest `.md`/`.txt` files)
  - Conversation browser with full detail popup
  - Scheduled Tasks tab for creating, editing, running, cancelling, deleting, filtering, and inspecting scheduled jobs
  - FTS5 search, dual database (cloud/local), re-embed after edits
  - Mobile responsive: hamburger menu at ≤730px
  - Launch: `./bin/jarvis-memory`

![jarvis-docs](docs/images/jarvis-docs.jpg)

- **Docs viewer** (`jarvis-docs`): Dedicated markdown workspace for everything under `docs/` at localhost:5004
  - Reader-first layout with global search across markdown files
  - Section rail + document feed + rendered article canvas
  - Optional in-place `.md` editing via `DOCS_UI_EDIT_ENABLED=true`
  - **Docs Assistant** — In-panel LLM chat with read-only answers from retrieved `docs/` excerpts; retrieval uses **[QMD](docs/qmd/README.md)** when installed, otherwise **ripgrep** (no crash if neither is present)
  - Launch: `./bin/jarvis-docs`
- **Canvas Viewer**: Visual knowledge display at localhost:8890
  - Jarvis saves research results, code snippets, comparisons
  - Beautiful dark UI with Markdown rendering
  - Search, pin, edit, delete pages
  - Mobile responsive: hamburger menu at ≤730px
  - Launch: `./bin/jarvis-canvas`

![jarvis-canvas](docs/images/jarvis-canvas-ui.png)

---

- **Image Gallery UI**: Browse generated images in Canvas web UI
  - Grid view with thumbnails, search, favorites filter, and date/name/size/CDN cached sorting
  - Lightbox viewer, favorite, download, get CDN URL, delete
  - Favorites are preserved by generated-image cleanup; uncached CDN uploads require confirmation
  - Access via "🖼️ Gallery" link in Canvas header

![jarvis-image-gallery](docs/images/jarvis-image-gallery.png)

---

- **Audio Gallery UI**: Browse retained generated music in Canvas
  - Playback with a live spectrum, search, filtering, favorites, download, and delete
  - Share retained tracks as temporary xAI waveform videos
  - Access via the "🎵 Audio" link in the Canvas header

![jarvis-audio-gallery](docs/images/jarvis-audio.jpg)

---

- **Video Gallery UI**: Browse generated videos in Canvas web UI (Feb 2026)
  - Grid view with hover preview, provider badges (xAI/Gemini)
  - Lightbox viewer with video controls
  - Search, sort by date/name/size/duration
  - Download and delete functionality
  - Access via "🎬 Videos" link in Canvas header

![jarvis-video-gallery](docs/images/jarvis-video-gallery.png)

### Jarvis Logs Viewer

Dedicated **read-only** log triage inside Jarvis Web (`./bin/jarvis-web`): open **`http://localhost:5001/logs`** (same host/port as chat; respects Web UI auth if enabled).

- **Scope** — Browses repo log folders that contain `.jsonl`, `.log`, or `.md`; no uploads, edits, or deletes
- **Navigation** — Folder list (sorted A→Z); files newest-first inside each folder; folder search narrows files before you open them
- **Viewing** — JSONL lines render as expandable YAML-style cards (good for LLM/tool/jsonl traces); markdown files render as Markdown; large files load in pages instead of dumping the whole file at once
- **Mobile** — Drill-down flow (folder → file list → viewer) with back navigation on small screens
- **Compared to chat** — The in-chat **Server Logs Panel** streams live tail; **`/logs`** is for paging through dated files under `logs/` (e.g. `llm-calls-*`, `tools/tool-calls-*`, `opencode`, `feedback`, web errors)

![jarvis-logs](docs/images/jarvis-logs-viewer.png)

Full detail: [Logging guide](docs/logging/README.md#web-ui-log-viewer) and
[Web UI guide](docs/JARVIS_WEB_UI.md#logs-read-only-browser).

---

### Speech Modes - Smart Adaptive Response System

Jarvis adapts its response style based on your environment and task complexity:

**🎙️ Casual Mode** (Default for Voice)
- Concise responses with configurable word limits (75/50/35 words)
- Strips `stash://` refs, long URLs, file paths from speech
- Perfect for: Voice interactions, speakers, TTS

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
JARVIS_RESPONSE_STYLE="detailed" # Always verbose (CLI) and full Web UI display (no tts)
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
├── api/                      # Proactive Assistant FastAPI app (routes, managers; run via bin/jarvis-api :8880)
├── audio/                    # TTS/STT-related dirs (cloud/ vs local/)
├── bin/                      # Executable scripts & utilities (50+)
│   ├── wake-jarvis.py        # Cloud wake word loop
│   ├── wake-jarvis-local.py  # Local wake word loop
│   ├── say.sh / say-local.sh # Text-to-speech
│   ├── jarvis-api            # API server (port 8880)
│   ├── jarvis-services       # Background services supervisor
│   ├── jarvis-dashboard      # Command dashboard TUI
│   ├── jarvis-web            # Main chat Web UI (port 5001)
│   ├── jarvis-docs           # docs/ browser + assistant UI (port 5004)
│   ├── jarvis-canvas         # Canvas & gallery (port 8890)
│   ├── jarvis-memory         # Memory browser (port 5002)
│   ├── jarvis-intelligence   # Intelligence UI (port 5003)
│   ├── jarvis-feedback       # Feedback CLI
│   ├── build-tool            # Tool builder
│   ├── manage-tools.py       # Enable/disable tools, profile helpers
│   ├── sync-memory-db.py     # Memory DB maintenance
│   ├── sync-tools.py         # Tool RAG: embed registry into memory DB
│   ├── cleanup-intelligence.py
│   ├── spotify-auth          # Spotify OAuth setup
│   ├── memory                # Memory CLI
│   └── question*.sh          # Q&A entry points
├── lib/                      # Shared Python modules (~45)
│   ├── config_loader.py      # Env & project config
│   ├── memory_db.py          # SQLite memory + tool embedding index
│   ├── llm_provider.py       # xAI / Anthropic / OpenAI / Ollama
│   ├── tool_schema.py        # Tool registry, MCP merge, Tool RAG helpers
│   ├── tool_profiles.py      # JARVIS_TOOL_PROFILE overlays
│   ├── tool_search_runtime.py # tool_search implementation
│   ├── tts_normalizer.py     # Speech-oriented text cleanup
│   ├── model_catalog.py      # Model metadata & defaults
│   ├── intelligence.py       # Self-learning core
│   ├── intelligence_hooks.py
│   ├── tool_builder.py
│   ├── mcp_client.py / opencode_client.py
│   ├── stash_helper.py / embeddings.py / feedback.py
│   └── …                     # loggers, cost_estimator, routing helpers, etc.
├── orchestrator/             # Multi-turn orchestration (uses lib/, not a copy of it)
│   ├── orchestrator_v2.py
│   ├── router_v2.py          # Routing + Tool RAG selection
│   ├── executor.py
│   ├── context_assembler.py  # Conversation & tool-result context
│   ├── response_formatter.py # Final display / speech shaping
│   ├── workflow_loader.py
│   ├── workflow_tool_runtime.py # Autonomous workflow search/describe/run
│   └── pipeline_executor.py
├── skills/                   # Tools: *.py + *.tool.json
│   ├── profiles/             # Tool profile overlays (JARVIS_TOOL_PROFILE)
│   │   ├── default.json
│   │   └── examples/         # Tracked templates (copy to profiles/<name>.json)
│   ├── auto-tools/           # Tool-builder outputs (network_tools, text_summarizer, …)
│   ├── personal/             # Private scripts/manifests (only README tracked)
│   ├── tool_search.py        # Summary-first discovery
│   ├── workflow.py           # Compact deterministic-workflow meta-tool
│   ├── canvas.py / stash.py / memory tools / generate_* / crawl_url / serpapi_* …
│   └── *.tool.json
├── config/                   # Environment & wiring
│   ├── cloud.env / local.env # Active (gitignored); from *.example
│   ├── cloud.env.example / local.env.example
│   ├── mcp-servers.json      # MCP server definitions
│   ├── webhook_registry.json / contacts.json / ssh.json (often gitignored)
│   └── …
├── data/                     # SQLite DBs, canvas, stash, workflows, chat exports, backups
│   ├── jarvis_memory*.db / jarvis_intelligence*.db
│   ├── workflows/            # e.g. deep_research, daily_status, web_archive, …
│   ├── canvas/ stash/ generated_* / web_conversations/ backups/
│   └── …
├── logs/                     # tools/, llm-calls-*, api/, services/, intelligence/, tool-rag/, …
├── jarvis-web/               # Main Web UI — client/, server/, data/prompts/
├── jarvis-docs/              # docs/ reader — client/, server/ (:5004)
├── jarvis-canvas/            # Canvas UI — client/ (static/, templates/), server/
├── jarvis-intelligence/      # Intelligence dashboard — client/, server/
├── jarvis-memory/            # Memory browser — client/, server/
├── jarvis-monitor/           # Remote agent — monitor.py, Docker assets, README
├── jarvis-intel/             # Private knowledge tree (often gitignored)
├── services/                 # Python daemons (reminders, follow-up, self-healing, scheduled tasks) + webhook helpers
├── systemd/                  # systemd unit templates
├── monitoring/               # Grafana + Prometheus + Loki
├── tests/                    # Unit, integration, e2e
├── docs/                     # Markdown docs (QMD-indexed); subfolders api/, n8n/, …
├── jarvis / jarvis-local     # Cloud vs local launchers
├── VERSION                   # App version (see bin/bump-version)
├── pyproject.toml / uv.lock  # Packaging
├── requirements.txt
├── setup.sh / install*.sh / verify-env.sh / …
└── README.md                 # This file
```

</details>


---

## 🚀 Quick Start

<details>
<summary><strong>Quick Start (click to expand)</strong></summary>

### 1. Initial Setup

See [INSTALL_GUIDE.md](docs/INSTALL_GUIDE.md) or
[QUICKSTART.md](docs/QUICKSTART.md) for detailed instructions.

### 1.1. Clone the repository
```bash
git clone https://github.com/bigsk1/jarvis-voice.git
cd jarvis-voice
```

```bash
cd ~/jarvis-voice
chmod +x install.sh
./install.sh
```

This will:
- Install system dependencies
- Create the shared Python environment from the lockfile
- Seed missing configuration files without overwriting existing ones
- Run project setup and environment verification

### 2. Configure

Edit the configuration files created by the installer:

```bash
# Cloud mode ships with OpenAI as the default provider
nano config/cloud.env

# Optional xAI alternative
# LLM_PROVIDER="xai"
# XAI_AUTH_MODE="auto"   # API key when set; otherwise a current `grok login`
# XAI_API_KEY="xai-..."  # Optional for chat/OAuth vision; required for xAI generation/TTS/search APIs
# XAI_MODEL="grok-4.7"
# XAI_OAUTH_MODEL="grok-4.6"

# Ollama Cloud alternative (signed-in daemon path):
# LLM_PROVIDER="ollama"
# OLLAMA_BASE_URL="http://your-ollama-host:11434"
# OLLAMA_CLOUD_MODEL="minimax-m3:cloud"
# Or set OLLAMA_API_KEY for direct ollama.com access; see docs/ollama/README.md.

# Local mode uses Ollama with gemma4 by default
nano config/local.env
# ALLOW_OLLAMA_CLOUD=true optionally exposes signed-daemon cloud cards locally.
```

Every mode uses Ollama for the shared 768D Jarvis Embedding contract, even when
cloud chat uses OpenAI, xAI, or Anthropic. The versioned artifact is an exact
BF16 copy of EmbeddingGemma. Set `OLLAMA_BASE_URL` in both ENV files to localhost
or the intended LAN daemon host(s), run `ollama pull
bigsk1/jarvis-embedding:bf16-v1` on every selected host, then verify the runtime:

```bash
./bin/check-embeddings-health.py --both --runtime-only
```

The installer does not install Ollama, start a daemon, or pull models
automatically because the configured service may live on another machine.

See [`config/README.md`](config/README.md), [`docs/XAI_PROVIDER.md`](docs/XAI_PROVIDER.md),
and [`docs/ollama/README.md`](docs/ollama/README.md) for detailed configuration options.

</details>

### Optional Docker Web Stack

Jarvis can run its Web UIs, API, Canvas, and background services in Docker while wake word, CLI, TUI, and host-integrated tools remain native. Existing databases and runtime files are reused through bind mounts.

```bash
cp docker.env.example .env
docker compose build
docker compose --profile extras up -d
```

The `extras` profile also starts the background task worker; individual background tools still require enabling in Web Settings. The safe Docker tool profile is enabled by default. Hybrid users can select the full `default` profile and block container-incompatible tools only in Web UI Settings. See the **[Docker Guide](docs/docker/README.md)** for setup, LAN access, authentication, shell/CLI examples, and native/Docker coexistence.

### Optional Database Browser

The standalone [SQLite browser](sqlitebrowser/README.md) provides a browser-accessible DB Browser for SQLite for Memory, Intelligence, background-task and Source Library databases. Its own Compose project uses read-only data mounts by default; `./start --edit` explicitly enables edits. See its tracked [example configuration](sqlitebrowser/.env.example) for HTTPS access, credentials and host data paths.

### 4. Run Wake Word or CLI

```bash
source ~/jarvis-venv/bin/activate

# Cloud mode (provider comes from config/cloud.env)
./jarvis

# Local mode (Ollama)
./jarvis-local

# CLI mode: production venv, answer-only output
./bin/jarvis-cli "What time is it?"
./bin/jarvis-local-cli "What time is it?"

# Structured agent results; diagnostics are opt-in
./bin/jarvis-cli "Inspect Craft capabilities" --json --no-context
./bin/jarvis-cli "What time is it?" --json --verbose

# Optional final voice output
./bin/jarvis-cli "What time is it?" --speak

# Command Dashboard (all commands in one TUI!)
./bin/jarvis-dashboard
```
See the [complete CLI guide](jarvis-cli/README.md) and [agent skill](jarvis-cli/SKILL.md) for flags, exit codes, stdin, remote usage and structured file/job results.

### Terminal Wake Word Mode

![jarvis-voice](docs/images/voice.png)

Say **"Hey Jarvis"** to wake it up!

### 5. Start All Services (Recommended)

Start everything with one command using tmux sessions (make sure cloud.env and/or local.env is all setup first!):

```bash
# Start ALL services (API, background services, all UIs)
./bin/start

# Local-only startup (uses config/local.env)
./bin/start --local

# Or start only what you need:
./bin/start --ui-only    # Just the web UIs (no API/services)
./bin/start --ui-only --local  # Local-env web UIs
./bin/start --list       # Check status of all sessions
./bin/start --stop       # Stop everything
```

The command dashboard exposes the same choices as **Start All Services**,
**Start All Services (Local)**, **Start UI Only**, and **Start UI Only
(Local)**. Cloud remains the default; local actions require
`config/local.env`.

**Services started:**
| Session | Port | Description |
|---------|------|-------------|
| `jarvis-api` | 8880 | Proactive API (webhooks, reminders) |
| `jarvis-services` | - | Background services (auto-resolve) |
| `jarvis-web` | 5001 | Web UI chat interface |
| `jarvis-canvas` | 8890 | Canvas & Gallery viewer |
| `jarvis-memory` | 5002 | Memory Browser UI |
| `jarvis-intelligence` | 5003 | Intelligence Dashboard |
| `jarvis-docs` | 5004 | `docs/` viewer/editor + Docs Assistant chat |

```bash
# Attach to any session to see logs
tmux attach -t jarvis-web

# Detach without stopping: Ctrl+B then D
```



### 6. Proactive API & Reminders

Enable event-driven alerts, notifications, and smart reminders:

If you prefer to start services individually (instead of `./bin/start`):

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

### 7. Remote Monitoring Agent (Optional)

Deploy the **[Jarvis Monitor](./jarvis-monitor/README.md)** (Docker) on remote servers for health checks and alerts:

```bash
# On remote server (Docker required)
docker run -d \
  --name jarvis-monitor \
  --restart unless-stopped \
  -e JARVIS_API="http://your-jarvis-server:8880/api/alerts" \
  -e JARVIS_API_KEY="your-api-key-if-JARVIS_API_AUTH-is-enabled" \
  -e MONITOR_URLS="MyApp|http://localhost:8080/health" \
  -e SOURCE_NAME="remote-server" \
  -e CHECK_INTERVAL=60 \
  bigsk1/jarvis-monitor:latest

# Monitor sends alerts to Jarvis API when issues detected
# Jarvis speaks alerts via voice TTS
# Auto-resolve when service recovers
```

See the [Jarvis Monitor repo](https://github.com/bigsk1/jarvis-monitor) for configuration options and Docker Compose examples.


---

## 🛠️ Tool System

### Available Skills (100+)

**Memory Management:**
- `remember` - Store facts, preferences, technical info
- `recall` - Retrieve specific memories by category/key
- `search_memory` - **FTS5 full-text search** with BM25 ranking (keyword/entity searches)
- `semantic_recall` - AI-powered conceptual search (natural language questions)
- `update_memory` - Modify existing memories
- `forget` - Delete memories
- `memory_deduper` - **Memory cleanup**: detect duplicates/conflicts, propose safe deletions (analyze first, apply when approved)
- `get_recent_conversations` - Access conversation history
- `search_conversations` - Search past interactions

**Action Tools:**
- `send_email` - Send emails with contact lookup and HTML templates
- `send_webhook` - Trigger named webhooks (Slack, n8n, APIs) with auth
- `api_call` - Generic HTTP API calls
- `crypto_price` - Get cryptocurrency prices
- `crypto_chart` - **Crypto chart history**: CoinGecko time-series for price, market cap, and volume; shaped for web UI charts and Canvas
- `get_time` - Current time
- `calculator` - **Advanced math**: arithmetic, percentages, statistics, unit conversions, trig
- `canvas` - **Visual viewer**: save rich content (research, code, comparisons) to web UI
- `weather` - Weather via OpenWeatherMap with Open-Meteo daily forecasts
- `phone_call` - **AI Phone Calls**: outbound calls via Vapi.ai with personas, voicemail detection, transcripts
- `spotify` - **Music control**: play, pause, skip, queue, search, device switching, share via email
- `network_tools` - **Network diagnostics**: ping (with stats), DNS lookup, port checks, HTTP/HTTPS status, traceroute
- [`external_network_intel`](docs/tools/external-network-intel-tool/README.md) - **Passive public network intelligence**: IP/domain ownership, ASN/routing, DNS, official cloud ranges, Shodan InternetDB, and optional AbuseIPDB reputation (no scanning)
- `system_monitor` - **System resources**: CPU, RAM, disk, processes, network I/O, uptime
- `text_summarizer` - **Text processing**: summarization, keyword extraction, word count, sentiment analysis
- `stock_price` - **Stock/futures prices**: stocks (TSLA, AAPL), futures (GC=F gold, SI=F silver), forex (EURUSD=X)
- `price_alert` - **Price alerts**: Create crypto/stock alerts monitored by n8n (above/below thresholds)
- `status_recap` - **Daily status**: aggregates weather, crypto, stocks, alerts, reminders, system health → Canvas + Stash
- `schedule_task` - **Scheduled tasks**: create/list/update/cancel/delete future query or workflow runs, inspect run history, and queue `run_now`
- `workflow` - **Deterministic workflow discovery**: search/describe eligible shared or personal recipes and synchronously run one in the current orchestration turn
- [`generate_music`](docs/tools/generate-music-tool/README.md) - **AI Music**: provider-ready music generation with genres, moods, tempo, stash integration
- `generate_password` - **Password generation**: Secure passwords with length, complexity, memorable options
- `openclaw` - **Multi-agent**: Chat with a remote OpenClaw agent, delegate tasks, fire-and-forget webhooks
- `deep_memory_search` - **Comprehensive search**: Multi-source search across memory, conversations, intel, canvas, stash
- `search_docs` - **Internal knowledge Q&A**: Semantic search over Jarvis docs (capabilities, parameters, features)
- `ssh_remote` - **Remote execution**: SSH into remote hosts, run commands, apt management, multi-command sequences
- `youtube_transcript` - **YouTube transcripts**: Download video transcripts as .srt/.md files
- `youtube_video` - **YouTube download**: Download videos or audio-only via yt-dlp, save to stash
- `bookmark_search` - **Firefox bookmarks**: Search bookmark export (HTML) by keyword, tags, folders, domains (`*` in Web UI)
- `crawl_url` - **Web scraping**: Crawl4AI to extract markdown from any webpage (stealth mode, JS wait)
- `supa_crawl_knowledge` - **Supa-Crawl-Chat corpus**: read-only search and site/page inspection over your self-hosted Supabase/pgvector index (configure `SUPA_CRAWL_CHAT_URL`; optional API auth via `SUPA_API_KEY` / `SUPA_API_KEY_STYLE`)
- `brave_llm_context` - **Brave LLM Context API**: compact source snippets for LLM grounding (retrieval/context, not a final-answer generator)
- `screenshot_url` - **Screenshot + vision**: Full-page capture with AI analysis (bypasses anti-bot)

**Optional Trakt movie and TV tools (`TRAKT_API_KEY` Client ID):**

- [`trakt_movies`](docs/tools/trakt-movies-tool/README.md) - **Public movie discovery**: Mood-aware and related-title recommendations, search/details, trending/popular/anticipated/streaming-ranked/box-office lists, and public trailer/video metadata without account OAuth
- [`trakt_account`](docs/tools/trakt-account-tool/README.md) - **Optional read-only Trakt account context**: OAuth recommendations, night-workflow watched filtering, watchlist, history, ratings, favorites, personal/smart lists, and up-next progress without account mutations
- [`trakt_tv_shows`](docs/tools/trakt-tv-shows-tool/README.md) - **Public TV-show discovery**: Mood-aware and related-series recommendations, search/details, trending/popular/anticipated/streaming-ranked lists, local negative-genre filtering including no-animation requests, typical episode runtime, and public trailer/video metadata without account OAuth

**Optional TMDB movie and TV tools (`TMDB_ACCESS_TOKEN` or `TMDB_API_KEY`):**

- [`tmdb_movies`](docs/tools/tmdb-movies-tool/README.md) - **Standalone movie discovery + artwork**: Search/details, posters/backdrops/logos, cast/crew, collections, certifications, videos, recommendations/similar titles, filtered discovery, and current TMDB lists without user OAuth or a Trakt dependency
- [`tmdb_tv_shows`](docs/tools/tmdb-tv-shows-tool/README.md) - **Standalone TV discovery + artwork**: Search/details, posters/backdrops/logos, aggregate cast/crew, creators, networks, seasons, content ratings, recommendations/similar shows, included/excluded-genre discovery, future first-air windows, and current TMDB TV lists

**Optional [SearXNG search](docs/tools/searxng/README.md) (`SEARXNG_BASE_URL`):**

- `searxng_search` - Search a configured local or remote SearXNG JSON endpoint for web, news, image, or video sources; no SearXNG API key is needed. Reverse-proxy authentication is optional.

**Optional [Project NOMAD tool](docs/tools/project-nomad/README.md) (`PROJECT_NOMAD_BASE_URL`):**

- `project_nomad` - Ask a configured NOMAD knowledge base, list its stored files and installed ZIMs, and read supported uploaded text. NOMAD remains a separate server and archive; the tool does not administer it.

**Optional [SerpApi tool suite](docs/tools/serp-api-tool/README.md) (`SERP_API_KEY`):**

- `serpapi_amazon_search` - **SerpApi Amazon Search**: Amazon listing discovery and focused ASIN/product details with price, rating, Prime, delivery, stock, images, and links
- `serpapi_google_shopping_light` - **SerpApi Google Shopping Light**: Fast multi-retailer shopping results with current and prior prices, merchants, ratings, delivery, sale/free-shipping filters, thumbnails, and offer links
- `serpapi_google_immersive_product` - **SerpApi Google Immersive Product**: Rich product details, features, review insights, user reviews, media, variants, and expanded store offers using the exact token returned by Google Shopping Light
- `serpapi_google_sports` - **SerpApi Google Sports**: Current schedules, scores, game details, standings, players, brackets, league statistics, and rankings with query-to-KGMID resolution or direct deterministic IDs
- `serpapi_search_index` - **SerpApi Search Index**: Structured indexed-web source discovery with exact URLs, snippets, standard/deep recall, and workflow-ready pagination for later fetch/crawl steps
- `serpapi_google_images_light` - **SerpApi Google Images Light**: Search existing web images with full-size URLs, thumbnails, source pages, dimensions, filters, workflow-ready references, and optional strict top-result Stash download
- `serpapi_google_news_light` - **SerpApi Google News Light**: Fast topic-specific recent-news discovery with headlines, sources, snippets, grouped Top Stories, and exact article URLs
- `serpapi_google_trends` - **SerpApi Google Trends**: Analyze supplied topics over time, compare regional interest, and discover rising or top related queries/topics for monitoring and workflows
- `serpapi_google_trending_now` - **SerpApi Google Trends Trending Now**: Discover current trends without a seed topic, then explicitly retrieve associated news for a selected trend token
- `serpapi_ebay_search` - **SerpApi eBay**: Marketplace keyword or category search; compact listings with price, condition, listing URL, product ID hints for follow-up
- `serpapi_ebay_product` - **SerpApi eBay product**: Single listing detail by item ID or product URL—price, condition, seller, media/images—for drill-down after search
- `serpapi_home_depot` - **SerpApi Home Depot**: Product search with price, rating, product ID, store/ZIP availability, and follow-up candidate context
- [`serpapi_google_events`](docs/tools/google-events-tool/README.md) - **SerpApi Google Events**: Upcoming concerts, festivals, comedy, family activities, conferences, and virtual events with dates, venues, ticket links, public maps, images, date filters, and active-mode location fallback
- `serpapi_google_local` - **SerpApi Google Local**: Nearby business discovery using an explicit or mode-default location, with ratings, hours, service options, sponsored listings, related searches, and pagination
- `serpapi_google_local_services` - **SerpApi Google Local Services**: Screened US professional-service providers with Google badges, contact/availability details, focused provider drill-down, and explicit city-CID resolution cost
- `serpapi_maps_search` - **SerpApi Maps**: Google Maps place and local business search with normalized address/rating/contact fields
- `serpapi_hotel_search` - **SerpApi Hotels**: Google Hotels search with check-in/out, guest, price, and rating filters
- [`serpapi_travel_explore`](docs/tools/travel-explore-tool/README.md) - **SerpApi Travel Explore**: Flexible destination discovery from an origin with suggested dates, headline flight/hotel planning prices, airport handoffs, and public Google Travel links
- `serpapi_tripadvisor` - **SerpApi Tripadvisor**: Search destinations, hotels, restaurants, attractions, and forums; retrieve place details, nearby suggestions, and filtered reviews by `place_id`
- `serpapi_open_table_reviews` - **SerpApi OpenTable Reviews**: Retrieve paginated diner reviews, detailed category ratings, rating summaries, restaurant responses, and review photos from an OpenTable restaurant ID or URL; supports JSON, HTML, and Markdown output
- `serpapi_yelp_search` - **SerpApi Yelp**: Local places (restaurants, coffee, bars) by description + location; filters, sort, optional reviews
- `serpapi_youtube_search` - **SerpApi YouTube search**: Keyword search with video-first results (title, channel, views, duration, thumbnails)
- `serpapi_youtube` - **SerpApi YouTube details**: Video metadata and transcript by URL or `video_id` (useful when `youtube_video` / yt-dlp hits auth or cookie limits)

The 23 `serpapi_*` tools require a nonblank key in the active mode's env file.
Without it they are not callable or included in that mode's Tool RAG sync. Jarvis
Web shows the free Account API quota card only when Settings → System is opened
and the selected mode has a valid key.

**Related flight tool:**

- `flight_search` - **Flight search**: Future airfare and itinerary options through SerpApi Google Flights when configured, with a keyless `fast-flights` fallback

**Artifact & Output Tools:**
- [`document_ocr`](docs/tools/document-ocr-tool/README.md) - **Optional self-hosted OCR**: page-attributed Markdown from scanned PDFs/images, OVIS-hosted structured extraction, and ZIP artifacts with readiness preflight and Stash handoff
- [`transcribe_audio`](docs/SPEECH_TO_TEXT.md#existing-audio-files-transcribe_audio) - **Existing audio to text**: Web uploads, Stash files, or approved local recordings through OpenAI, Faster-Whisper, or an OpenAI-compatible `/v1/audio/transcriptions` endpoint, with bounded long-file chunking and full transcript Stash handoff
- `convert_file` - **Local media conversion**: ImageMagick, FFmpeg, Potrace
  - Images: JPG ↔ PNG ↔ WebP ↔ GIF ↔ BMP ↔ TIFF ↔ ICO
  - Raster to vector: PNG/JPG → SVG (Potrace tracing for logos, line art)
  - Video: MP4 ↔ WebM ↔ MOV ↔ AVI ↔ MKV
  - Audio: MP3 ↔ WAV ↔ FLAC ↔ OGG ↔ AAC ↔ M4A
  - Extract audio from video (MP4 → MP3/WAV)
  - Advanced options: resize, quality, bitrate, FPS, threshold, speckle size
  - **Web UI 🔄 button** with format selector and inline results
  - No API costs - all processing local
- `generate_image` - **AI image generation & editing**: Gemini, OpenAI, or xAI
  - **3 providers**: Gemini (grounding), OpenAI (best text), xAI (fast & cheap - $0.02/image!)
  - **Image-to-image editing**: Upload an image + describe changes → edited image
  - **Batch generation**: xAI `n=1-10` for multiple variations in one request
  - Supports aspect ratios (1:1, 16:9, 9:16, etc.), styles, negative prompts
  - **Gemini Search Grounding** - Real-time data in images (weather, crypto prices, news)
  - Auto-saves original provider bytes to Generated Images storage and an unchanged Stash copy, with catalog metadata; public-URL reference inputs are strictly validated and bounded before provider upload
- `generate_video` - **AI video generation**: xAI Grok or Gemini Veo
  - xAI: 1-15s duration, 7 aspect ratios, video editing ($0.05/s)
  - Gemini: 4/6/8s, native audio, up to 4K resolution ($0.15/s)
  - Text-to-video and image-to-video modes (all providers)
  - Auto-saves to stash + memory for cross-session recall
- [`craft_image`, `craft_pdf`, `craft_photos`, `craft_video`, `craft_motion`, `craft_inspect`](jarvis-craft-tools/README.md) - **Optional self-hosted Craft editing**: reproducible gateway setup, native image/PDF/photo/video/title edits, project files and Stash delivery; includes an [agent setup skill](jarvis-craft-tools/SKILL.md).
- `create_social_clip` - **Social B-roll clips**: MoneyPrinterTurbo (self-hosted Docker) — stock footage + AI script + TTS + subtitles + BGM
  - TikTok, Reels, Shorts, faceless YouTube — **not** `generate_video` (that tool is Grok/Veo AI animation)
  - Configure `MONEYPRINTER_API_URL`, `MONEYPRINTER_VOICE`, `MONEYPRINTER_MAX_WAIT_SEC` in `config/cloud.env`
  - Polls MPT `/api/v1/videos`, downloads `final-*.mp4`, saves to stash; web UI inline player for stash videos
- `analyze_image` - **Vision analysis**: Analyze one or more images from URLs, files, or stash refs
  - Cloud=Grok/Claude/GPT-4o, Local=llava
  - Multi-image analysis and comparison: up to 6 images in cloud mode, 2 in local mode
  - SSRF protection (blocks private IPs), path traversal protection
  - Auto-stashes analyzed images + creates memory_db entry
  - Example: "Compare these images https://example.com/a.png and https://example.com/b.png"
- `stash` - **Artifact storage**: download URLs, store files/images/JSON for multi-step workflows
  - Central workshop for temporary files (7-day TTL)
  - `stash://` references work across tools (printer, email, pdf_create, analyze_image)
  - `kind=image_url` strictly validates, bounds, and records provenance for untrusted public raster images
- `pdf_create` - **PDF generation**: create PDFs from stash files, images, or text
  - Now auto-saves to memory with stash reference for recall
- `pdf_read` - **PDF reading**: extract text, images, merge, split, search PDFs
  - Page range support, image extraction to stash, text search with context
- `printer` - **Print output**: print from stash refs, file paths, or Canvas pages (CUPS)
  - Accepts `stash://space_xxx/file_id` references directly
- `speaker_volume` - **Audio control**: get/set/adjust system speaker volume
- `upload_cloudflare` - **CDN upload**: Upload images to Cloudflare for permanent public URLs
  - Supports file, URL, base64, stash references
  - Metadata tracking (prompt, tags, provider)
- `qr_code_generator` - **QR codes**: Generate QR codes for URLs, text, WiFi, contacts; save PNG to stash

**Development:**
- `opencode` - Autonomous coding agent (builds apps, games, APIs)
- `check_opencode_sessions` - Monitor OpenCode progress
- `ingest_intel` - Bulk import knowledge from markdown files
- `git_release_notes` - **GitHub release notes**: Analyze releases, generate summaries with commit/PR/issue breakdown, risk flags
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

### Optional Google Workspace MCP

Connect a dedicated Google account through the optional
[Google Workspace Docker service](google-workspace/README.md). Its pinned
complete tier exposes 111 MCP tools for Gmail, Drive, Calendar, Docs, Sheets,
Slides, Forms, Tasks, Contacts and Apps Script.

- Search mail, create drafts, send messages, and manage Gmail labels.
- Find, upload and share Drive files; create and edit documents, spreadsheets,
  presentations and forms; manage calendar events and tasks.
- Set `stash=true` on supported downloads for a persistent Jarvis file and Web
  download link. Use `stash_ref` on supported uploads/imports to transfer a
  selected Stash file for follow-up work.

The service runs independently of Jarvis and owns OAuth consent and token
refresh. A fresh clone leaves it disabled; each cloud/local mode opts in with
`GOOGLE_WORKSPACE_MCP_ENABLED` after setup. Enabled tools use the
`mcp_google_workspace_*` prefix and enter the existing Tool RAG system. Jarvis
supplies the dedicated account identity automatically on tool calls.

Use `bin/jarvis-google` for setup, consent, health checks and activation. Native
headless installs can complete browser consent through an SSH tunnel to the
localhost callback. See the [setup guide](google-workspace/README.md) for Google
Cloud APIs, OAuth client settings, production consent status and the optional
Jarvis Docker overlay.

### How Tool Calling Works - Basic Flow

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
- Workflows (pre-determinded tools structure)
- Error recovery with retries
- Timeout handling
- Cost tracking (cloud mode)
- Metadata logging
- Permission system - for tools not implemented fully

### Managing Tools (Enable/Disable)

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

See [`docs/TOOL_MANAGEMENT.md`](docs/TOOL_MANAGEMENT.md) for details.

---

## 🔄 Workflow Orchestration

Workflows are deterministic multi-tool pipelines that execute predefined sequences of tools. Unlike normal LLM routing (where the LLM decides which tools to use), workflows guarantee consistent, repeatable execution.

### Workflow Entry Points

| Method | Trigger | Who Decides Tools | Use Case |
|--------|---------|-------------------|----------|
| **LLM Routing** | Any query | LLM analyzes and selects | General questions, flexible tasks |
| **Explicit workflow** | `/command`, API, or schedule | User/task names recipe; JSON defines steps | Repeatable or scheduled automation |
| **Autonomous workflow** | Normal chat/voice request | LLM uses compact `workflow` metadata; JSON defines steps | Reuse an existing recipe without knowing its slash command |

`tool_search` and `workflow` are mandatory discovery candidates only while
enabled in the effective registry. A manifest, tool profile, or Web/request
block can remove either one. Disabling `workflow` turns off autonomous recipe
selection for that surface; it does not disable independent slash commands or
scheduled workflow tasks.

### Workflow Examples

The live list is mode/profile-aware and may also include private
`data/workflows/personal/*.json` recipes. Use `/api/workflows` or the Web slash
picker for the authoritative current surface.

| Command | Description | Tools Used |
|---------|-------------|------------|
| `* [query]` | Search Firefox bookmarks (like * in address bar) | bookmark_search (requires `data/bookmarks.html`) |
| `/archive <url>` | Archive webpage to stash with Canvas summary | crawl_url, stash, canvas |
| `/buying_brief <product>` | Compare Google Shopping Light, Amazon, and eBay and create a localized buying recommendation | serpapi_google_shopping_light, serpapi_amazon_search, serpapi_ebay_search, stash, canvas |
| `/crypto [coins]` | Crypto prices, news, analysis, email report | get_time, crypto_price, crypto_chart, mcp_brave_search_brave_web_search, crawl_url, stash, canvas, send_email |
| `/deep_dive <url>` | Screenshot + crawl URL, comprehensive canvas summary | screenshot_url, crawl_url, stash, text_summarizer, canvas |
| `/game_brief <sport> <team>` | Create a current game Canvas brief with status, score, line or period scoring, key performers, and returned watch or recap links; optional Brave sources add narrative context | serpapi_google_sports, optional brave_llm_context, optional mcp_brave_search_brave_web_search, canvas |
| `/github_ai_radar` | Find current GitHub AI project signals and refresh a rolling Canvas report | mcp_brave_search_brave_web_search, brave_llm_context, optional serpapi_youtube_search, crawl_url, stash, canvas |
| `/health [host]` | SSH health check (default: vps2) | get_time, ssh_remote, stash, canvas |
| `/jarvis_self_check` | Check local Jarvis health, refresh its Canvas report, and create a deduplicated alert for problems | get_time, system_monitor, check_tool_logs, query_service_logs, create_alert, canvas |
| `/local_services_compare <service>` | Compare local providers, screening signals, business details, ratings, and bounded Yelp review excerpts using the active mode location | serpapi_google_local_services, serpapi_google_local, serpapi_yelp_search, stash, canvas |
| `/memory_scan` | Run memory dedupe analysis, save reports to stash + canvas | memory_deduper |
| `/movie_night <mood, constraints, or favorite movies>` | Build a decisive Trakt-based movie shortlist with related-title signals, optional account recommendations and watched-title filtering, TMDB artwork, trailers, current streaming evidence, and a dated Canvas recommendation | trakt_movies, optional trakt_account, optional tmdb_movies, optional serpapi_youtube_search, optional brave_llm_context, canvas |
| `/night_out <occasion or preference>` | Build a date-aware local evening plan; an explicit destination wins, otherwise use the active mode default location/postal code, and weather is skipped when the requested date exceeds the 10-day horizon | optional weather, serpapi_google_local, optional serpapi_yelp_search, optional serpapi_tripadvisor, canvas |
| `/note <text>` | Save note to memory + Canvas | get_time, remember, canvas |
| `/research <topic>` | Multi-source research with Brave + crawling | mcp_brave_search_brave_web_search, crawl_url, stash, remember, canvas |
| `/serpapi_amazon <query>` | SerpApi Amazon workflow: listings + Stash export + Canvas comparison | serpapi_amazon_search, stash, canvas |
| `/status` | Daily status briefing (weather, crypto, stocks, alerts) | get_time, weather, crypto_price, crypto_chart, stock_price, list_alerts, list_reminders, system_monitor, canvas |
| `/status_visual` | Status briefing + AI-generated dashboard image + same Canvas crypto charts as `/status` | get_time, weather, crypto_price, crypto_chart, stock_price, list_alerts, list_reminders, system_monitor, generate_image, canvas |
| `/team_outlook <sport> <team>` | Create a current-centered team outlook with recent and upcoming games, standings, roster context, and optional current news | serpapi_google_sports, optional serpapi_google_news_light, canvas |
| `/trend_reality_check <topic>` | Test whether a topic shows sustained interest, a transient spike, or weak evidence using topic trends, the seedless current feed, news, and indexed source discovery | serpapi_google_trends, optional serpapi_google_trending_now, optional serpapi_google_news_light, optional serpapi_search_index, canvas |
| `/tv_night <mood, constraints, or favorite shows>` | Build a decisive Trakt-based TV shortlist with related-series signals, optional account recommendations and watched-show filtering, TMDB artwork/commitment metadata, trailers, current streaming evidence, and a dated Canvas recommendation | trakt_tv_shows, optional trakt_account, optional tmdb_tv_shows, optional serpapi_youtube_search, optional brave_llm_context, canvas |
| `/upcoming_movie_radar <genre criteria>` | Find a new upcoming movie, maintain a rolling Canvas page per primary genre, and optionally email the pick with shared cross-genre deduplication | get_time, stash, tmdb_movies, optional brave_llm_context, canvas, optional send_email |
| `/upcoming_tv_radar <genre criteria>` | Find a new TV-series premiere in a bounded future window, exclude unwanted genres such as Animation, maintain a rolling Canvas page per primary genre, and optionally email the pick with shared cross-genre deduplication | get_time, stash, tmdb_tv_shows, optional brave_llm_context, canvas, optional send_email |
| `/weather_watch` | Weather watch for default location (`JARVIS_DEFAULT_LOCATION`); alerts for cold, wind, heat, or severe conditions | get_time, weather, create_alert, canvas |
| `/url_ingest <url>` | Crawl URL, create intel file, ingest to memory | crawl_url, stash, text_summarizer, manage_intel, ingest_intel |
| `/vacation_reconnaissance <location>` | Required-location vacation reconnaissance with forecast, attractions, food, local pulse, images, optional Stash evidence, and Canvas | weather, serpapi_tripadvisor, serpapi_google_local, serpapi_google_news_light, serpapi_google_images_light, stash, canvas |
| `/youtube_ingest <url>` | Download video + transcript, summarize, create study brief | youtube_transcript, youtube_video, stash, text_summarizer, canvas |
| `/youtube_research <url>` | Download transcript, summarize, create study notes | youtube_transcript, stash, text_summarizer, canvas |
| `/yt_dlp_release_watch` | Check for a stable yt-dlp release, create Canvas release notes, alert once, and acknowledge it | release_watch, git_release_notes, create_alert |

### Workflow Features

- **Variable System**: Extract parameters from queries, pass data between steps
- **LLM Parameter Filling**: Dynamic parameter resolution via `llm_prompt`
- **Content Validation**: Heuristic validation with min_length, reject_patterns
- **Retry Logic**: Automatic retries with configurable limits
- **Required-Tool Availability**: Disabled, unavailable, or surface-blocked required tools block the recipe; explicit `required: false` tools are skipped and reported as degraded
- **Autonomous Foreground Runs**: Normal orchestration can search compact workflow metadata and wait for one deterministic recipe to finish
- **Safe Follow-Ups**: Web history preserves component Canvas/Stash handles and bounded summaries for later edits or individual tool calls
- **Loop Protection**: One workflow run may start per user request, and Completion Guard does not replay workflow turns

### Token Efficiency

Explicit workflows bypass normal LLM routing overhead, making them ideal for
local models with limited context. Autonomous selection uses a small number of
router calls for discovery and final synthesis, but still avoids sending every
component schema and re-planning every recipe step:

| Execution method | Routing cost |
|------------------|--------------|
| Normal multi-tool chat | Router/tool-schema context can repeat across component turns |
| Explicit slash/API/scheduled workflow | No routing calls; only declared workflow helper/component LLM calls |
| Autonomous `workflow` run | Discovery/final-answer routing plus declared workflow helper/component LLM calls |

The outer autonomous workflow call has no generic 60/75-second subprocess cap;
each component retains its normal or tool-specific timeout. Results are
step-aware and bounded for final synthesis while the canonical Web result
remains available for follow-up extraction.

### API Access

```bash
# List workflows
curl http://localhost:8880/api/workflows | jq

# Execute workflow
curl -X POST http://localhost:8880/api/workflows/crypto_market_report/execute

# View history
curl http://localhost:8880/api/workflows/history | jq
```

See:
- [`docs/WORKFLOW_ORCHESTRATION.md`](docs/WORKFLOW_ORCHESTRATION.md) - Full workflow system documentation
- [`docs/api/WORKFLOWS.md`](docs/api/WORKFLOWS.md) - Workflows API reference
- [`data/workflows/`](data/workflows/) - Workflow JSON definitions

---

## 🧠 Memory System

### Knowledge Base

Stores facts, preferences, and technical information with **hybrid search** (FTS5 + semantic):

```bash
# Store a fact (substitute your network range)
"Remember my WireGuard VPN uses <vpn-subnet>"

# Retrieve via keyword search (FTS5 with BM25 ranking)
"Search for VPN network"  # Uses FTS5 for fast, accurate results

# Retrieve via semantic search (AI embeddings)
"What's my VPN network?"  # Uses embeddings for conceptual matching

# View all memories
./bin/memory list

# Tune semantic search sensitivity (in config/cloud.env or local.env)
SEMANTIC_SIMILARITY_THRESHOLD=0.30  # Default: 0.30 (balanced)
# Lower (0.30-0.35) = more results, may include loosely related
# Higher (0.45-0.50) = fewer results, only close matches
```

**Search Strategy:**
- **Keyword/Entity searches** (1-3 words, technical terms): Use `search_memory` → FTS5
- **Natural language questions** (conceptual or mixed with exact terms): Use `semantic_recall` → fused embeddings + FTS5/BM25

See [`docs/FTS5_SEARCH_SYSTEM.md`](docs/FTS5_SEARCH_SYSTEM.md) and [`docs/SEMANTIC_THRESHOLD_TUNING.md`](docs/SEMANTIC_THRESHOLD_TUNING.md) for details.

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

**Key Principles**:
- Everything is continuous (vectors), not discrete rules
- Learning generalizes through semantic similarity
- Positive AND negative constraints (what to do AND what NOT to do)
- Structured negative constraints are request-scoped: a stored trigger must match the clean user request before a tool is penalized
- Fact vs Procedural classification (only skills stored, not facts)
- Generalizability filtering (low-value insights filtered out)

**Experience Recording**:
- Query (as embedding)
- Tools used (in order)
- Turns taken
- Success/failure
- User satisfaction signals
- LLM response & tool results (for content quality eval)

**Insights Generated**:
- Pattern: "Status queries need real-time tools"
- Applies to: "Server health, uptime checks"
- Trigger signals: exact request words/phrases required by narrow negative constraints
- Preferred approach: "Use fetch tools directly"
- Confidence: 0.0-1.0
- Tracking: times_applied, times_helpful, times_failed

**Maintenance Jobs**:
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
5. Track which insights were applied
6. Update helpful/failed counts after interaction

See [`docs/INTELLIGENCE_LAYER.md`](docs/INTELLIGENCE_LAYER.md) for details.


---

## 🤖 OpenCode Integration

OpenCode is an optional autonomous coding agent that can build entire projects.
Jarvis requires an **OpenCode 2.x** server and the matching V2 workspace plugin.
The native Linux integration runs a separate supervised systemd service;
OpenCode Console is optional and direct provider credentials are supported.

### Usage

```bash
# Via voice
"Use OpenCode to create a Flask API on port 8091"

# Via CLI
./bin/jarvis-cli "Use OpenCode to build a Tetris game"
```

### What OpenCode Can Do

- Build web apps (Flask, Express, React)
- Create games (Tetris, Snake, etc.)
- Write scripts and tools
- Install dependencies
- Test and verify builds

### Configuration

```bash
# In cloud.env or local.env (explicit cloud-provider example)
OPENCODE_ENABLED=true
OPENCODE_PROVIDER="xai"
OPENCODE_MODEL="grok-4.7"
OPENCODE_BASE_URL="http://localhost:4096"
# Set matching server credentials in Jarvis and the OpenCode service environment.
OPENCODE_SERVER_PASSWORD="replace-with-a-long-random-password"
```

**Workspace:** Coding projects go to `~/jarvis-workspace/projects/` by default.
The native service combines a workspace plugin with systemd filesystem write
restrictions. A local OpenCode service can still call paid cloud models.
Its child processes share writable access to OpenCode's session/credential
storage and caches; see the integration guide for those boundaries.

See [`docs/opencode/OPENCODE.md`](docs/opencode/OPENCODE.md) for details.

---

## 💾 Database & Costs

### Memory Database (Dual System)

Jarvis uses separate databases for cloud and local modes:


**Cloud Mode** - `data/jarvis_memory.db`:
- Uses Ollama `bigsk1/jarvis-embedding:bf16-v1` embeddings (768 dimensions)
- Remains separate from the selected cloud chat provider

**Local Mode** - `data/jarvis_memory_local.db`:
- Uses the same fingerprinted Ollama `bigsk1/jarvis-embedding:bf16-v1` artifact (768 dimensions)
- Remains a separate local data set

**Auto-Sync**: On startup, newer memories are synced between databases. Incompatible or partially rebuilt vector namespaces fail closed while FTS remains available. See [`docs/DUAL_DATABASE_SYSTEM.md`](docs/DUAL_DATABASE_SYSTEM.md).

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
- [`config/README.md`](config/README.md) - Configuration guide
- [`config/models/README.md`](config/models/README.md) - Model prompt override config layout
- [`docs/QUICKSTART.md`](docs/QUICKSTART.md) - Quick setup guide
- [`docs/TAILSCALE_HTTPS.md`](docs/TAILSCALE_HTTPS.md) - Optional private HTTPS with Tailscale: UI setup, navigation, troubleshooting, and rollback
- [`docs/TOOL_CALLING_SYSTEM.md`](docs/TOOL_CALLING_SYSTEM.md) - How tools work
- [`docs/MODEL_PROMPT_OVERRIDES.md`](docs/MODEL_PROMPT_OVERRIDES.md) - Provider/model-specific runtime prompt tuning
- [`docs/SPEECH_TO_TEXT.md`](docs/SPEECH_TO_TEXT.md) - **Speech-to-text** providers, self-hosted Parakeet, fallback behavior, and browser microphone requirements
- [`docs/qwen3-tts/QWEN3_TTS_INTEGRATION_GUIDE.md`](docs/qwen3-tts/QWEN3_TTS_INTEGRATION_GUIDE.md) - **Qwen3-TTS** (28 cloned voices, local network)

**Proactive System:**
- [`docs/api/`](docs/api/) - **Proactive API** documentation (webhooks, alerts, monitoring)
- [`docs/api/API_OVERVIEW.md`](docs/api/API_OVERVIEW.md) - **FastAPI** (Memory, Query, Workflows, Stash, Canvas, Intel, Images, Conversations) ⭐ ENHANCED
- [`docs/api/INTEL.md`](docs/api/INTEL.md) - **Intel API** (CRUD for jarvis-intel files, ingestion, stats)
- [`docs/api/IMAGES.md`](docs/api/IMAGES.md) - **Images API** (Cloudflare CDN upload, multi-agent image sharing)
- [`docs/api/GENERATED_MUSIC.md`](docs/api/GENERATED_MUSIC.md) - **Generated Music API** (generation, readiness, saved-track streaming)
- [`docs/api/WORKFLOWS.md`](docs/api/WORKFLOWS.md) - **Workflows API** (list, execute, history)
- [`docs/service/`](docs/service/) - **Background Services** documentation (daemons, auto-resolve)
- [`docs/tools/scheduled-tasks/scheduled-tasks.md`](docs/tools/scheduled-tasks/scheduled-tasks.md) - **Scheduled Tasks** (scheduler, parser, API, runner, Memory UI)
- **[Jarvis Monitor](https://github.com/bigsk1/jarvis-monitor)** - Docker agent for remote health checks

**Workflow Orchestration:**
- [`docs/WORKFLOW_ORCHESTRATION.md`](docs/WORKFLOW_ORCHESTRATION.md) - **Full workflow system** (pipelines, variables, validation)
- [`docs/api/WORKFLOWS.md`](docs/api/WORKFLOWS.md) - **Workflows API** (programmatic execution)
- [`data/workflows/AGENTS.md`](data/workflows/AGENTS.md) - Workflow building guide
- [`data/workflows/README.md`](data/workflows/README.md) - Workflow recipes reference

**Core System:**
- [`docs/tools/phone/PHONE_CALLS.md`](docs/tools/phone/PHONE_CALLS.md) - **AI Phone Calls** (Vapi.ai, personas, transcripts, contacts)
- [`docs/tools/spotify/SPOTIFY.md`](docs/tools/spotify/SPOTIFY.md) - **Spotify Integration** (playback control, search, multi-device)
- [`docs/tools/generate-music-tool/README.md`](docs/tools/generate-music-tool/README.md) - **Music Generation** (providers, parameters, storage, Audio Gallery, FastAPI)
- [`docs/STASH_SYSTEM.md`](docs/STASH_SYSTEM.md) - **Artifact storage** (multi-step workflows, URL downloads, SSRF protection)
- [`docs/INTELLIGENCE_LAYER.md`](docs/INTELLIGENCE_LAYER.md) - **Self-learning system** (reflection, reusable insights, and maintenance)
- [`docs/AUTO_CONTEXT_SYSTEM.md`](docs/AUTO_CONTEXT_SYSTEM.md) - Short-term conversation memory
- [`docs/JARVIS_WORKFLOW.md`](docs/JARVIS_WORKFLOW.md) - Complete request flow with examples
- [`docs/TOOL_CALLING_SYSTEM.md`](docs/TOOL_CALLING_SYSTEM.md) - How tool routing works

**Monitoring & Dashboards:**
- [`monitoring/README.md`](monitoring/README.md) - Grafana + Prometheus + Loki stack
- **Grafana Dashboards:**
  - `Jarvis Intelligence Layer` - Self-learning metrics, insights, confidence
  - `Jarvis - Conversation Audit v2` - Deep drill-down into LLM decisions
  - Plus: LLM Performance, Tool Analysis, API Performance

**Memory System (Updated Nov 2025):**
- [`docs/FTS5_SEARCH_SYSTEM.md`](docs/FTS5_SEARCH_SYSTEM.md) - **NEW**: FTS5 full-text search with BM25 ranking
- [`docs/DUAL_DATABASE_SYSTEM.md`](docs/DUAL_DATABASE_SYSTEM.md) - Cloud/local DB architecture with auto-sync
- [`docs/SEMANTIC_THRESHOLD_TUNING.md`](docs/SEMANTIC_THRESHOLD_TUNING.md) - How to tune similarity threshold
- [`docs/MEMORY_SYSTEM.md`](docs/MEMORY_SYSTEM.md) - Memory & knowledge base overview
- [`docs/MEMORY_SYSTEM_TUNING.md`](docs/MEMORY_SYSTEM_TUNING.md) - Memory system optimization

**Tool Management:**
- [`docs/TOOL_MANAGEMENT.md`](docs/TOOL_MANAGEMENT.md) - Enable/disable tools, create profiles
- [`docs/TOOL_CALLING_SYSTEM.md`](docs/TOOL_CALLING_SYSTEM.md) - How tool system works

**Features:**
- [`docs/opencode/OPENCODE.md`](docs/opencode/OPENCODE.md) - OpenCode integration
- [`docs/MULTI_TURN_ORCHESTRATION.md`](docs/MULTI_TURN_ORCHESTRATION.md) - How tool chaining works
- [`docs/METADATA_SYSTEM.md`](docs/METADATA_SYSTEM.md) - Cost tracking & metadata

**Advanced:**
- [`docs/opencode/OPENCODE_API_REFERENCE.md`](docs/opencode/OPENCODE_API_REFERENCE.md) - OpenCode V2 API used by Jarvis
- [`docs/opencode/OPENCODE_AGENTS.md`](docs/opencode/OPENCODE_AGENTS.md) - OpenCode V2 agent selection
- [`docs/mcp/MCP_QUICKSTART.md`](docs/mcp/MCP_QUICKSTART.md) - MCP server integration
- [`docs/ERROR_RECOVERY.md`](docs/ERROR_RECOVERY.md) - Error handling

---

## 🔧 Development

<details>
<summary><strong>Adding a New Tool (click to expand)</strong></summary>

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

</details>

### Shell shortcuts

Install the managed Bash/Zsh command set with `./update-aliases.sh`. Useful operator commands include `jarvis-d`, `jarvis-start`, `jarvis-start-local`, `jarvis-stop`, `jarvis-status`, and the Web-only `jarvis-web-stop`; `jarvis-cli` and `jarvis-local-cli` run the full text-only orchestrator with quiet answers by default. Use `--json` for agent results and `--verbose` for diagnostics; see the [CLI guide and agent skill](jarvis-cli/README.md). Run `jarvis-help` whenever you need the complete shortcut list. See [the install guide](docs/INSTALL_GUIDE.md#step-9-setup-aliases) for explicit Zsh selection.

### Tool Builder

- [Tool Builder](docs/TOOL_BUILDER.md) - Optional terminal command to draft a basic tool; finish its Jarvis integration in an IDE


```bash
./bin/build-tool --mode cloud build "Tool description here"
```


### Testing

Use the repository `.venv` for development tests. Prepare it with
`uv sync --dev --frozen` if needed; production launchers and Tool RAG sync retain
their external `~/jarvis-venv` environment.

```bash
# Complete deterministic core suite (Python and core UI Node tests)
./bin/test-suite

# Focused smoke group while developing
.venv/bin/python -m pytest -q \
  tests/test_docs_integrity.py tests/test_mode_plumbing_scripts.py

# Maintained integration wrappers are also no-cost by default
./tests/integration/test-thinking-mode.sh
./tests/integration/test-opencode-integration.sh

# Explicit live checks (provider cost/logs or OpenCode sessions may apply)
./tests/integration/test-thinking-mode.sh --live cloud
./tests/integration/test-opencode-integration.sh --health cloud

# Test specific tool
./orchestrator/orchestrator_v2.py cloud "remember test fact"
```

See the [testing guide and authoring contract](docs/TESTING.md) for sandbox
preflight handling, saved reports, focused checks, and live-test boundaries.
The separately packaged Firefox extension has its own `npm test` command in
`jarvis-firefox-extension/`; report it separately from the core suite. Tests do
not rotate or restore active databases.


---

## 🐛 Troubleshooting

<details>
<summary><strong>Troubleshooting (click to expand)</strong></summary>

### Common Issues

**"OpenCode server not reachable"**
```bash
sudo systemctl start opencode-jarvis.service
./tests/integration/test-opencode-integration.sh --health cloud
```

**"Ollama connection failed"**
```bash
curl http://localhost:11434
ollama serve
```

**"Model not found"**
```bash
ollama pull gemma4
ollama pull bigsk1/jarvis-embedding:bf16-v1
```

**"Permission denied" when running a tool script**
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
./bin/sync-memory-db.py --from local --to cloud  # Sync local → cloud
./bin/sync-memory-db.py --from cloud --to local  # Sync cloud → local

# Tool RAG (tool_definitions) is per-mode and not copied by sync-memory-db — run separately:
./bin/sync-tools.py cloud   # or: local
./bin/sync-tools.py cloud --force   # re-embed every tool (e.g. after embedding model change)

# Verify mode-specific databases and embeddings without replacing them
./bin/check-embeddings-health.py --both --json
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

</details>

---

## 📝 License

Source Available — free for personal use, modification, and non-commercial redistribution with attribution. Commercial use requires permission. See [LICENSE](LICENSE) for details.


**Current Version:** v2.56.2 (October 2026)
