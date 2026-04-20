# Jarvis Web UI

A modern, feature-rich web interface for Jarvis with real-time streaming, voice I/O, vision capabilities, and a cyberpunk aesthetic.

![jarvis-web](../docs/images/jarvis-web.png)

## Features

### 💬 Chat & Conversations
- **Real-time Streaming** - See responses and tool execution as they happen via WebSocket
- **Conversation History** - Full CRUD with persistent storage
- **Deep Search** - Search across all conversation messages
- **Export/Import** - Export to JSON or Markdown, import previous conversations
- **Auto-title Generation** - Conversations are auto-titled based on content

### 🎤 Voice I/O
- **Speech-to-Text (STT)** - Browser microphone recording
  - Cloud: OpenAI Whisper API
  - Local: faster-whisper
- **Text-to-Speech (TTS)** - Audio playback in browser
  - Cloud: ElevenLabs (high quality)
  - Local: Kokoro (fast, local)
- **Audio Toggle** - Enable/disable voice responses

### 🖼️ Vision & Images
- **Image Upload** - Attach images for LLM vision analysis
- **Smart Resize** - Auto-optimizes uploaded images (max 1024px)
- **Image Generation** - Generate images via DALL-E or Gemini
- **Lightbox Viewer** - Full-size image preview with download

### ⚙️ Settings & Configuration
- **Mode Switching** - Toggle between Cloud and Local mode
- **AI Config** - Select LLM provider, model, image provider
- **Tool Management** - Block/unblock specific tools for web
- **System Config** - View read-only env settings
- **API Key Status** - Check which APIs are configured
- **Glow Intensity** - Customize holographic effects (off/low/medium/high)

### 🔧 Developer Features
- **Real-time Server Logs** - Stream logs with source filters:
  - 🤖 LLM API calls
  - 🔧 Tool executions
  - 🔄 Workflow executions
  - 💻 OpenCode sessions
  - ⭐ Feedback ratings
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
- **Cross-UI Navigation** - Quick links to Canvas 📄, Memory 🧠, Intelligence 📊

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
├── server/                    # Flask + SocketIO backend
│   ├── app.py                # Main application
│   ├── config.py             # Configuration loader
│   ├── routes/
│   │   └── api.py            # REST API endpoints (chat, settings, /logs, media)
│   ├── sockets/
│   │   └── chat.py           # WebSocket handlers
│   └── services/
│       ├── tool_discovery.py # Tool loading & filtering
│       ├── settings_manager.py # Web-specific settings
│       ├── conversation_store.py # Conversation persistence
│       └── log_explorer.py   # Read-only log browser service for /logs
├── client/                    # Frontend (vanilla JS)
│   ├── index.html            # Main page
│   ├── logs.html             # Dedicated log browser page
│   ├── css/
│   │   ├── variables.css     # CSS custom properties
│   │   ├── main.css          # Core styles
│   │   ├── glow-refinements.css # Holographic effects
│   │   └── log-viewer.css    # /logs layout and viewer styles
│   └── js/
│       ├── app.js            # Main application
│       ├── chat.js           # Chat UI logic
│       ├── socket.js         # WebSocket connection
│       ├── logs.js           # Server log panel
│       ├── log-viewer.js     # /logs folder/file/viewer client
│       ├── proactive.js      # Proactive features
│       └── utils.js          # Utility functions
├── config/
│   └── web_config.json       # Web UI configuration
├── data/
│   ├── conversations/        # Conversation JSON files
│   ├── prompts/              # @prompt templates (*.md)
│   └── uploads/              # Uploaded images
└── requirements.txt
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
| `/api/settings/models/:provider` | GET | Get available models for provider |
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
| `/api/conversations/search` | GET | Search across all messages |
| `/api/conversations/:id/export` | GET | Export as JSON or Markdown |
| `/api/conversations/import` | POST | Import conversation |

### Voice & Media

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stt` | POST | Speech-to-text (upload audio) |
| `/api/tts` | POST | Text-to-speech (get audio) |
| `/api/upload-image` | POST | Upload image for vision |
| `/api/images/:filename` | GET | Serve generated images |
| `/api/uploads/:filename` | GET | Serve uploaded images |
| `/api/audio/:filename` | GET | Serve audio files |

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

**Client → Server:**
| Event | Description |
|-------|-------------|
| `chat:send` | Send a message (supports image attachment) |
| `chat:cancel` | Cancel current processing |
| `mode:set` | Change mode (cloud/local) |
| `tools:refresh` | Refresh tools list |

**Server → Client:**
| Event | Description |
|-------|-------------|
| `connected` | Session established |
| `chat:thinking` | Processing started |
| `tool:start` | Tool execution started |
| `tool:complete` | Tool execution finished |
| `chat:response` | Final response |
| `chat:error` | Error occurred |
| `log:entry` | Real-time log stream |

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

Workflows are deterministic multi-tool pipelines defined in `data/workflows/`:

```json
{
  "id": "deep_research",
  "name": "Deep Research Workflow",
  "description": "Comprehensive research with validation",
  "enabled": true,
  "triggers": {
    "explicit": ["/research"]
  },
  "steps": [
    {"step": 1, "tool": "stash.open_space", "params": {"name": "${topic}"}},
    {"step": 2, "tool": "brave_search", "params": {"query": "${topic}"}},
    {"step": 3, "tool": "crawl_url", "params": {"url": "${urls[:3]}"}}
  ]
}
```

Available workflows: `/research`, `/note`, `/archive`, `/health`

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

See [GLOW_IMPROVEMENTS_README.md](./GLOW_IMPROVEMENTS_README.md) for technical details.

## Mobile Support

At screen widths ≤768px:
- Sidebar collapses to hamburger menu
- Header adapts to mobile layout
- Touch-friendly interactions
- Full feature parity with desktop

## Security Notes

- **Local Network**: Binds to all interfaces (`0.0.0.0`) by default
- **No Authentication**: Auth is disabled (planned for future)
- **API Keys**: Never exposed to frontend; shown as "configured/not configured"
- **Image Processing**: Uploaded images are auto-resized and stored locally
- **Path Security**: File serving prevents directory traversal

## Cross-UI Navigation

Quick access to other Jarvis UIs via header icons:
- 📄 **Canvas** (port 8890) - Document creation and editing
- 🧠 **Memory Browser** (port 5002) - View/edit memories and intel
- 📊 **Intelligence Dashboard** (port 5003) - Self-learning insights

## Troubleshooting

### WebSocket connection fails
Check that you're accessing via the correct IP (not localhost if remote).

### STT not working
- Cloud: Verify `OPENAI_API_KEY` is set
- Local: Ensure faster-whisper is installed and ffmpeg is available

### TTS not playing
- Cloud: Verify `ELEVENLABS_API_KEY` is set
- Local: Check `TTS_URL` points to running Kokoro instance

### Images not generating
- Verify `IMAGE_TOOL_PROVIDER` is set (gemini/openai)
- Check corresponding API key is configured

## Future Enhancements

- [ ] Authentication (password/token)
- [ ] PWA support for mobile
- [ ] Voice activity detection (VAD)
- [ ] Conversation branching
- [ ] Custom themes

## Related Documentation

- [Glow Improvements](./GLOW_IMPROVEMENTS_README.md) - Holographic effect details
- [Memory Browser](../jarvis-memory/README.md) - Memory management UI
- [Intelligence Dashboard](../jarvis-intelligence/README.md) - Self-learning UI
- [Canvas](../bin/jarvis-canvas) - Document generation
