# Jarvis Web UI

A modern, feature-rich web interface for Jarvis with real-time streaming, voice I/O, vision capabilities, and a cyberpunk aesthetic.

![jarvis-web](../docs/images/jarvis-web.jpg)

## Features

### 💬 Chat & Conversations
- **Real-time Streaming** - See responses and tool execution as they happen via WebSocket
- **Conversation History** - Full CRUD with persistent storage
- **Deep Search** - Search across all conversation messages
- **Export/Import** - Export to JSON or Markdown, import previous conversations
- **Auto-title Generation** - Conversations are auto-titled based on content
- **Completion Guard** - Per-turn card to confirm tasks completed correctly (manual feedback), optional auto-evaluation path, bounded repair, follow-up ticket flow; streamed via WebSocket (`completion_guard:*`)
- **Token usage** - Footer hint with cumulative tokens and estimated cost when the model returns usage (hover for context-percent tooltip on long threads)

### 🎤 Voice I/O
- **Speech-to-Text (STT)** - Browser microphone recording
  - Cloud: OpenAI Whisper API
  - Local: faster-whisper
- **Text-to-Speech (TTS)** - Audio playback in browser (provider from `TTS_PROVIDER` in env)
  - Cloud: ElevenLabs, **xAI TTS**, or others as configured in `config/cloud.env`
  - Local: **Qwen3-TTS** via `QWEN3_TTS_URL`, or Kokoro via `KOKORO_TTS_URL`, per `config/local.env`
  - ElevenLabs character quota surfaced in Settings when relevant (`GET /api/tts/usage`)
- **Audio Toggle** - Enable/disable voice responses with pause/resume/stop on playback

### 🖼️ Vision & Images
- **Image Upload** - Attach one or more images for LLM vision analysis
- **Smart Resize** - Auto-optimizes uploaded images (max 1024px)
- **Image Generation** - Tool-backed generation with provider selection in Settings (**OpenAI**, **Google Gemini**, **xAI**) — not tied to one vendor
- **Music generation** - `generate_music` (e.g. ElevenLabs music) plays inline when returned as audio
- **Lightbox Viewer** - Full-size image preview with download

### ⚙️ Settings & Configuration
- **Mode Switching** - Toggle between Cloud and Local mode
- **AI Config** - Select LLM provider, model, **image** generation provider, **video** generation provider
- **Tool Management** - Block/unblock specific tools for web
- **System Config** - View read-only env settings
- **API Key Status** - Check which APIs are configured
- **Glow Intensity** - Customize holographic effects (off/low/medium/high)

### 🔧 Developer Features
- **Real-time Server Logs** - Stream logs with source filters (`logs:subscribe` / `log:entry`):
  - 🤖 LLM API calls
  - 🔧 Tool executions
  - 🔄 Workflow executions
  - 💻 OpenCode sessions
  - ⭐ Feedback ratings
- **Proactive alerts** - WebSocket `proactive:*` for pending API alerts/reminders; optional desktop notifications when enabled in the UI
- **Dedicated `/logs` Viewer** - Read-only log browser for `.jsonl`, `.log`, and `.md`
  - Folder list stays A→Z for predictable navigation
  - Files default to newest-first inside each folder
  - Folder search ranks files by content hits and filters the viewer to matching records/lines
  - JSONL entries render as nested YAML-style cards with modal expansion
  - Markdown files render cleanly in the viewer and modal
- **Tools Browser** - View all available tools with descriptions
- **Workflows System** - `/workflows` for deterministic multi-tool pipelines
- **Prompts System** - `@prompts` with Markdown templates
- **Tool Hints** - `#tool_name` softly prefers one or more enabled tools for a request
- **✨ Prompt Enhancement** - AI-powered prompt optimization

### 🎨 UI/UX
- **Dark Cyberpunk Theme** - Blade Runner-inspired aesthetic
- **Holographic Glow Effects** - Customizable intensity
- **Mobile Responsive** - Hamburger menu at ≤768px
- **Cross-UI Navigation** - Quick links to Canvas 📄, Memory 🧠, Intelligence 📊, Jarvis Docs 📚 (`./bin/jarvis-docs`, port **5004**)

## Quick Start

```bash
# From jarvis-voice directory
./bin/jarvis-web

# Or with options
./bin/jarvis-web local              # Start in local mode
./bin/jarvis-web --port 8080        # Custom port
./bin/jarvis-web --debug            # Debug mode
```

Then open: `http://your-server-ip:5001`

## Installation

Dependencies should be auto-installed, but you can install manually:

```bash
cd jarvis-web
pip install -r requirements.txt
```

## Architecture

```
jarvis-web/
├── server/                    # Flask + SocketIO (eventlet async)
│   ├── app.py                # App factory, `/`, `/logs`, `/login`, `/stash/view/...`
│   ├── config.py             # Configuration loader
│   ├── routes/
│   │   ├── api.py            # REST API (tools, settings, conversations, media, workflows, prompts)
│   │   └── auth.py           # Optional auth: `/api/auth/login`, `/api/auth/status`, …
│   ├── sockets/
│   │   └── chat.py           # WebSocket: chat, tools, completion guard, logs, proactive
│   └── services/
│       ├── tool_discovery.py
│       ├── settings_manager.py
│       ├── conversation_store.py
│       ├── log_explorer.py   # /logs file browser
│       ├── log_streamer.py   # Live tail to clients
│       ├── proactive_service.py
│       ├── completion_guard.py
│       └── followup_extractor.py
├── client/
│   ├── index.html
│   ├── login.html
│   ├── logs.html
│   ├── stash-viewer.html     # Render stash text/markdown via `/stash/view/<space>/<file>`
│   ├── css/ …
│   └── js/ (app, chat, socket, logs, log-viewer, proactive, utils, …)
├── config/web_config.json
├── data/                     # Per-UI: conversations, prompts, uploads
└── requirements.txt

Workflow definitions live at repo root: ../data/workflows/*.json (not under jarvis-web/).
```

## API Endpoints

### Status & Tools

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Health check, mode, version, tool count |
| `/api/tools` | GET | List all available tools |
| `/api/tools/:name` | GET | Get specific tool details |
| `/api/tools/refresh` | POST | Reload tools from disk |

### Settings

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/settings` | GET | Get all settings for UI |
| `/api/settings/schema` | GET | Get settings schema for forms |
| `/api/settings/system` | GET | Get read-only system config |
| `/api/settings/web` | PUT | Update web UI overrides |
| `/api/settings/reset` | POST | Reset to cloud.env defaults |
| `/api/settings/models/:provider` | GET | Models for provider (`openai`, `anthropic`, `xai`, `ollama`, …) |
| `/api/tts/usage` | GET | ElevenLabs subscription usage (when that provider is active) |
| `/api/settings/blocked-tools` | GET/PUT | Manage blocked tools |
| `/api/mode` | GET/PUT | Get/set current mode |

### Conversations

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/conversations` | GET | List all conversations |
| `/api/conversations` | POST | Create new conversation |
| `/api/conversations/:id` | GET | Get conversation with messages |
| `/api/conversations/:id` | DELETE | Delete conversation |
| `/api/conversations/:id/title` | PUT | Update conversation title |
| `/api/conversations/:id/state` | PATCH | Update stored UI/orchestrator conversation state |
| `/api/conversations/:id/clear` | POST | Clear messages while keeping the conversation |
| `/api/conversations/search` | GET | Search across all messages |
| `/api/conversations/:id/export` | GET | Export as JSON or Markdown |
| `/api/conversations/import` | POST | Import conversation |

### Voice & Media

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stt` | POST | Speech-to-text (upload audio) |
| `/api/tts` | POST | Text-to-speech (get audio) |
| `/api/upload-image` | POST | Upload one image for Web UI vision staging |
| `/api/upload-images` | POST | Upload multiple images for Web UI vision staging |
| `/api/images/:filename` | GET | Serve stored generated images |
| `/api/uploads/:filename` | GET | Serve uploaded images |
| `/api/music/:filename` | GET | Serve generated music assets |
| `/api/videos/:filename` | GET | Serve generated video assets |
| `/api/audio/:filename` | GET | Serve other audio files |
| `/api/stash/:space_id/:file_id` | GET | Download stash artifact raw |
| `/api/stash/upload` | POST | Upload into stash (multipart) |
| `/api/intel/upload` | POST | Upload intel Markdown/text into jarvis-intel |

### Authentication (when enabled)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/status` | GET | Whether auth is required + metadata |
| `/api/auth/login` | POST | Password login → JWT for session |

### Workflows & Prompts

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/workflows` | GET | List all /workflows |
| `/api/workflows/:id` | GET | Get specific workflow |
| `/api/prompts` | GET | List all @prompts |
| `/api/prompts/:name` | GET | Get specific prompt |
| `/api/enhance-prompt` | POST | AI-enhanced prompt generation |

### Logs Explorer

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/logs` | GET | Read-only log browser UI |
| `/api/logs/folders` | GET | List folders containing `.jsonl`, `.log`, or `.md` files |
| `/api/logs/files` | GET | List files for a folder with search, filters, and newest-first sorting |
| `/api/logs/content` | GET | Fetch paged file content for YAML/markdown/log rendering |

### WebSocket Events

Event names below are what the **server** emits / the **client** sends (see `client/js/socket.js` for any aliasing to camelCase app events).

**Client → Server:**

| Event | Description |
|-------|-------------|
| `chat:send` | Send a message (supports image attachment) |
| `chat:cancel` | Cancel current processing |
| `completion_guard:submit` | Completion Guard feedback / repair flow |
| `conversation:load` | Load a conversation by id |
| `mode:set` | Change mode (cloud/local) |
| `tools:refresh` | Refresh tools list |
| `logs:subscribe` / `logs:unsubscribe` / `logs:set_sources` | Log panel subscription |
| `proactive:subscribe` / `proactive:check` / `proactive:ack_alert` / `proactive:ack_reminder` | Proactive API polling and acks |

**Server → Client:**

| Event | Description |
|-------|-------------|
| `connected` | Session established |
| `chat:thinking` | Processing started |
| `chat:status` | Intermediate status / TTS lines during a turn |
| `tool:start` / `tool:progress` / `tool:complete` / `tool:error` | Tool execution lifecycle |
| `chat:response` | Final response payload (text, usage, completion guard snapshot, …) |
| `chat:error` / `chat:cancelled` | Errors and user cancel |
| `conversation:created` / `conversation:loaded` | Sidebar sync |
| `mode:changed` / `tools:updated` | Settings-driven updates |
| `cancel:ack` | Ack after cancel |
| `completion_guard:updated` / `completion_guard:ticket_created` / `completion_guard:error` | Completion Guard UI |
| `log:entry` | Real-time log stream line |
| `logs:*` | Subscribe/sources ack helpers |
| `proactive:counts` / `proactive:alert` / `proactive:reminder` | Proactive notifications |
| `feedback:start` / `feedback:complete` | Optional post-turn feedback trigger |

## Configuration

### Web Config (`config/web_config.json`)

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 5001,
    "debug": false
  },
  "ui": {
    "theme": "dark",
    "show_tool_details": true,
    "auto_scroll": true
  },
  "audio": {
    "tts_enabled": false,
    "tts_autoplay": true
  },
  "defaults": {
    "mode": "cloud"
  }
}
```

### Workflows System

Workflows are deterministic pipelines defined at the **repository root**: `data/workflows/*.json` (same files the CLI orchestrator uses). The Web UI lists them via `/api/workflows`; slash commands autocomplete from each workflow's `triggers`.

**Examples of explicit slash triggers** (see each JSON for full patterns/keywords):

| Slash (examples) | Workflow file |
|------------------|----------------|
| `/research` | `deep_research.json` |
| `/archive` | `web_archive.json` |
| `/note`, `/quicknote` | `quick_note.json` |
| `/health`, `/server_check` | `server_health_check.json` |
| `/serpapi` | `serpapi_search.json` |
| `/youtube_research`, `/yt_research` | `youtube_research.json` |
| `/youtube_ingest`, `/yt_ingest` | `youtube_ingest.json` |
| `/url_ingest`, `/learn_url` | `url_ingest.json` |
| `/deep_dive`, `/dive` | `deep_dive.json` |
| `/crypto` | `crypto_market_report.json` |
| `/status`, `/daily`, `/briefing`, `/recap` | `daily_status.json` |
| `/status_visual`, `/daily_visual`, `/status_image` | `daily_status_visual.json` |
| `/weather_watch`, `/garden_watch` | `weather_watch.json` |
| `/memory_scan`, `/dedupe_memory` | `memory_scan.json` |

Authoring guide: [`data/workflows/AGENTS.md`](../data/workflows/AGENTS.md) · Overview: [`docs/WORKFLOW_ORCHESTRATION.md`](../docs/WORKFLOW_ORCHESTRATION.md)

Minimal shape (abbreviated):

```json
{
  "id": "example",
  "name": "Example Workflow",
  "enabled": true,
  "triggers": { "explicit": ["/example"] },
  "steps": [
    { "step": 1, "tool": "weather", "params": { "location": "Seattle" } }
  ]
}
```

### Prompts System

Create `@prompts` by adding Markdown files to `data/prompts/`:

```markdown
# Code Review

Review the following code for:
- Security issues
- Performance problems
- Best practices
- Potential bugs
```

### Tool Hints

Type a standalone `#` anywhere in the chat input to autocomplete enabled, non-blocked tools. Selected hints are removed from the visible request sent to Jarvis and injected as soft preferences, so `#weather #create_reminder remind me if it rains tonight` nudges Tool RAG without forcing a route.

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Enter` | Send message |
| `Shift+Enter` | New line in input |
| `Escape` | Cancel processing / Close modals |

## Holographic Glow Effects

The UI features customizable cyberpunk glow effects:

- **Off** - Clean, minimal design
- **Low** - Subtle ambient glow (recommended)
- **Medium** - Balanced cyberpunk feel
- **High** - Full intensity (original bright glow)

Change in Settings → General → Holographic Glow Intensity.

## Mobile Support

At screen widths ≤768px:
- Sidebar collapses to hamburger menu
- Header adapts to mobile layout
- Touch-friendly interactions
- Full feature parity with desktop

## Security Notes

- **Local Network**: Binds to all interfaces (`0.0.0.0`) by default
- **Optional authentication**: Shared with other Jarvis web UIs via `lib/webui_auth.py`. Set **`WEBUI_PASSWORD`** (and optionally **`WEBUI_SECRET`** for JWT signing — if unset, a secret is persisted under `data/.webui_secret`). Without `WEBUI_PASSWORD`, the UI stays open access.
- **API Keys**: Never exposed to frontend; shown as "configured/not configured"
- **Image Processing**: Uploaded images are auto-resized and stored locally
- **Path Security**: File serving prevents directory traversal

## Cross-UI Navigation

Quick access to other Jarvis UIs via header icons:
- 📄 **Canvas** (port 8890) - Document creation and editing
- 🧠 **Memory Browser** (port 5002) - View/edit memories and intel
- 📊 **Intelligence Dashboard** (port 5003) - Self-learning insights
- 📚 **Jarvis Docs** (port **5004**) - Browse repo `docs/` — [`jarvis-docs/README.md`](../jarvis-docs/README.md)

## Troubleshooting

### WebSocket connection fails
Check that you're accessing via the correct IP (not localhost if remote).

### STT not working
- Cloud: Verify `OPENAI_API_KEY` is set
- Local: Ensure faster-whisper is installed and ffmpeg is available

### TTS not playing
- Check **`TTS_PROVIDER`** in `config/cloud.env` or `config/local.env` (`elevenlabs`, `xai`, `kokoro`, `qwen3-tts`, …).
- ElevenLabs: `ELEVENLABS_API_KEY`
- xAI TTS: `XAI_API_KEY`
- Local Qwen3-TTS: `QWEN3_TTS_URL` and matching service reachable from the web server host
- Local Kokoro: `KOKORO_TTS_URL` and matching service reachable from the web server host

### Images not generating
- Set **`IMAGE_TOOL_PROVIDER`** (`openai`, `gemini`, or `xai`) and the matching vendor API keys / env vars (`OPENAI_*`, `GEMINI_*`, `XAI_*` as documented in main config).


## Related Documentation

- [Jarvis Web UI (full)](../docs/JARVIS_WEB_UI.md) - Long-form feature reference and phased checklist
- [Memory Browser](../jarvis-memory/README.md) - Memory management UI
- [Intelligence Dashboard](../jarvis-intelligence/README.md) - Self-learning UI
- [Canvas](../jarvis-canvas/README.md) - Canvas viewer README
