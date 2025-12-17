# Jarvis Web UI

> **Status**: MVP Complete (v1.2)  
> **Last Updated**: December 17, 2025

---

## 🎯 Overview

A **standalone web application** (`jarvis-web`) providing the full Jarvis experience through a modern chat interface.

- 🔌 **Pluggable**: Auto-discovers tools from `skills/*.tool.json` + MCP tools from `memory_db`
- 🔄 **Real-time**: WebSocket-first architecture with status streaming
- ⚙️ **Configurable**: Settings UI with provider/model dropdowns, on-the-fly switching
- 🎨 **Beautiful**: Modern dark theme with tool cards and image lightbox
- 📦 **Modular**: Separate from core - doesn't break terminal/TUI
- 🔮 **Future-proof**: Web overrides don't affect cloud.env
- 🧠 **Full Intelligence**: Uses same orchestrator → insights/feedback/self-learning works

**This is NOT a replacement** - it's a new interface alongside:
- Terminal (`orchestrator_v2.py`) - Dev/testing
- Voice loop (`jarvis`) - Hands-free interaction  
- TUI (`bin/tui`) - Terminal UI
- **Web UI (`jarvis-web`)** - Full-featured chat interface ✅

---

## ✅ Implemented Features

### Phase 1: Foundation - COMPLETE ✅

| Feature | Status | Details |
|---------|--------|---------|
| Project structure | ✅ | `jarvis-web/` with server/client separation |
| Flask + SocketIO backend | ✅ | Real-time WebSocket communication |
| Basic chat UI | ✅ | Send messages, receive responses |
| WebSocket events | ✅ | `chat:send`, `chat:response`, `chat:status`, `tool:*` |
| Tool execution streaming | ✅ | Tool cards show progress and results |
| Mode selection | ✅ | Cloud/Local toggle in header |
| Tool discovery | ✅ | Auto-loads from `skills/*.tool.json` |
| Dark theme | ✅ | CSS variables, modern styling |

### Phase 2: Features - COMPLETE ✅

| Feature | Status | Details |
|---------|--------|---------|
| Conversation history | ✅ | Save/load/delete, sidebar list |
| Tool execution cards | ✅ | Expandable with args/results |
| Image display | ✅ | Thumbnails + lightbox with download |
| Settings panel | ✅ | Tabbed modal (General/AI/API Keys) |
| Provider dropdowns | ✅ | xAI/Anthropic/OpenAI/Ollama with model options |
| Error handling | ✅ | Toast notifications, error messages |
| Status updates | ✅ | Stream to browser, not local speaker |

### Phase 3: Voice - PARTIAL ✅

| Feature | Status | Details |
|---------|--------|---------|
| TTS playback | ✅ | Toggle audio, plays responses in browser |
| Mode-aware TTS | ✅ | Cloud=ElevenLabs, Local=Kokoro (via TTS_URL) ⭐ NEW |
| Status TTS | ✅ | Status updates play as TTS when audio enabled |
| Mic input | ⏳ | Planned - push-to-talk (STT_PROVIDER ready) |
| Wake word | ⏳ | Planned - browser-based VAD |

### Phase 4: Advanced - COMPLETE ✅

| Feature | Status | Details |
|---------|--------|---------|
| Web blocked tools | ✅ | `tools.blocked` in web_config.json, UI to manage |
| Blocked tools UI | ✅ | Settings → Tools tab to add/remove |
| Conversation context | ✅ | Configurable limit (default 20) passed to LLM |
| Settings persistence | ✅ | `web_config.json` with per-mode overrides |
| Reset to defaults | ✅ | Button to clear web overrides for current mode |
| Dynamic LLM switching | ✅ | Change provider/model on-the-fly, takes effect immediately |
| MCP tool discovery | ✅ | Reads from memory_db, shows in Tools tab |
| System config view | ✅ | Mode-specific .env values in Settings → System ⭐ NEW |
| Per-mode settings | ✅ | `cloud`/`local` sections in web_config.json ⭐ NEW |
| Dynamic Ollama models | ✅ | Fetches available models from Ollama server ⭐ NEW |
| Clean mode switching | ✅ | Resets Intelligence singleton on mode change ⭐ NEW |
| Tool enable/disable | ⏳ | Planned (per-tool granular control) |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         JARVIS WEB                              │
│  ┌──────────────────────┐    ┌───────────────────────────────┐ │
│  │      Frontend        │    │          Backend              │ │
│  │   (Vanilla JS)       │◄──►│     (Flask + SocketIO)        │ │
│  │                      │ WS │                               │ │
│  │  • Chat UI           │    │  • WebSocket handlers         │ │
│  │  • Settings Modal    │    │  • REST API routes            │ │
│  │  • Tool Cards        │    │  • Tool discovery             │ │
│  │  • Image Lightbox    │    │  • TTS generation             │ │
│  │  • Audio Playback    │    │  • Conversation store         │ │
│  └──────────────────────┘    └───────────────────────────────┘ │
│                                        │                        │
│                                        ▼                        │
│                    ┌─────────────────────────────────┐         │
│                    │      JARVIS CORE (shared)       │         │
│                    │  • orchestrator/orchestrator_v2 │         │
│                    │  • lib/ (memory, config, etc)   │         │
│                    │  • skills/*.tool.json           │         │
│                    └─────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📁 Folder Structure

```
jarvis-web/
├── server/
│   ├── __init__.py
│   ├── app.py                 # Flask + SocketIO app
│   ├── config.py              # Config loader (cloud.env + web_config)
│   ├── routes/
│   │   ├── __init__.py
│   │   └── api.py             # REST endpoints
│   ├── sockets/
│   │   ├── __init__.py
│   │   └── chat.py            # WebSocket handlers
│   └── services/
│       ├── __init__.py
│       ├── tool_discovery.py  # Load tools from skills/
│       ├── settings_manager.py # Settings with overrides
│       └── conversation_store.py # Chat history
│
├── client/
│   ├── index.html             # Main HTML
│   ├── css/
│   │   ├── variables.css      # CSS custom properties
│   │   └── main.css           # All styles
│   └── js/
│       ├── app.js             # Main app
│       ├── socket.js          # WebSocket client
│       ├── chat.js            # Chat UI
│       └── utils.js           # Helpers
│
├── config/
│   └── web_config.json        # Web-specific settings
│
├── data/
│   └── conversations/         # Saved chat history
│
├── requirements.txt
└── README.md
```

---

## 🔌 API Reference

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Health check, mode, tools count |
| GET | `/api/tools` | List all enabled tools |
| GET | `/api/tools/<name>` | Get tool details |
| GET | `/api/settings` | Get settings for UI |
| PUT | `/api/settings/web` | Update web overrides |
| POST | `/api/settings/reset` | Reset to cloud.env defaults |
| GET | `/api/settings/blocked-tools` | Get blocked tools list |
| PUT | `/api/settings/blocked-tools` | Update blocked tools |
| GET | `/api/conversations` | List saved conversations |
| POST | `/api/conversations` | Create new conversation |
| GET | `/api/conversations/<id>` | Load conversation |
| DELETE | `/api/conversations/<id>` | Delete conversation |
| POST | `/api/tts` | Generate TTS audio |
| GET | `/api/audio/<filename>` | Serve audio files |
| GET | `/api/images/<filename>` | Serve generated images |

### WebSocket Events

#### Client → Server

```javascript
// Send chat message
socket.emit('chat:send', {
    message: 'What is bitcoin price?',
    conversation_id: 'conv_123',
    mode: 'cloud'
});

// Create new conversation
socket.emit('conversation:new', {});

// Load conversation
socket.emit('conversation:load', {
    conversation_id: 'conv_123'
});

// Set mode
socket.emit('mode:set', { mode: 'cloud' });

// Refresh tools
socket.emit('tools:refresh');
```

#### Server → Client

```javascript
// Session ready
socket.on('session:ready', {
    session_id: 'sess_abc',
    mode: 'cloud',
    tools_count: 35
});

// Processing started
socket.on('chat:thinking', {
    message_id: 'msg_456',
    conversation_id: 'conv_123'
});

// Status update (progress)
socket.on('chat:status', {
    message_id: 'msg_456',
    status: 'Checking the weather...',
    timestamp: 1734412345
});

// Tool started
socket.on('tool:start', {
    tool: 'weather',
    args: { location: 'NYC' }
});

// Tool complete
socket.on('tool:complete', {
    tool: 'weather',
    result: { temp: 45, conditions: 'Sunny' },
    duration_ms: 342,
    success: true
});

// Final response
socket.on('chat:response', {
    message_id: 'msg_456',
    text: 'The weather in NYC is...',
    speech: 'The weather in NYC is...',
    data: { weather: {...} },
    tools_used: ['weather'],
    audio_url: '/api/audio/tts_123.mp3'
});
```

---

## ⚙️ Configuration

### Two Config Worlds

| Config | Source | Affects | Editable |
|--------|--------|---------|----------|
| Core Settings | `cloud.env` | Terminal/TUI/Web | ❌ Restart required |
| Web Overrides | `web_config.json` | Web only | ✅ On-the-fly |

### web_config.json

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 5001
  },
  "defaults": {
    "mode": "cloud"      // Default mode on startup
  },
  "audio": {
    "tts_enabled": true,
    "tts_autoplay": true
  },
  "cloud": {
    "llm_provider": null,    // null = use cloud.env default (xai)
    "llm_model": null,       // null = use cloud.env model
    "image_provider": null   // null = use cloud.env (gemini)
  },
  "local": {
    "llm_provider": null,    // null = use local.env default (ollama)
    "llm_model": null,       // null = use local.env model
    "image_provider": null   // null = use local.env (gemini)
  },
  "conversation": {
    "history_limit": 20      // Messages to include as LLM context
  },
  "tools": {
    "blocked": ["get_recent_conversations"],
    "notes": "Tools blocked for web only. Terminal unaffected."
  }
}
```

> **Note**: Settings are per-mode! Cloud and local have separate overrides. Thresholds are read-only from the active .env file.

### Blocked Tools

Web-specific tool blocking (doesn't affect terminal):

```bash
# View blocked tools
curl http://localhost:5001/api/settings/blocked-tools

# Update blocked tools
curl -X PUT http://localhost:5001/api/settings/blocked-tools \
  -H "Content-Type: application/json" \
  -d '{"blocked": ["get_recent_conversations", "some_tool"]}'
```

---

## 🎨 UI Components

### Main Layout
- **Header**: Logo, mode selector, audio toggle, settings button
- **Sidebar**: Chat/Tools tabs, conversation history, new chat button
- **Main Area**: Chat messages, tool cards, input field
- **Modals**: Settings panel, image lightbox

### Tool Cards
- Expandable with click
- Show: tool name, status, duration
- Expanded: arguments, full result, images

### Settings Panel (5 Tabs)
- **General Tab**: Mode (cloud/local), TTS toggle, mode-aware help text
- **AI Config Tab**: LLM provider/model dropdowns (per-mode), Image provider, History limit, Reset button
- **Tools Tab**: Blocked tools list, add/remove UI, blocked/MCP visual indicators
- **System Tab**: Mode-specific .env values (thresholds, TTS settings, features) - shows cloud.env OR local.env
- **API Keys Tab**: Status indicators (configured/missing)

---

## 🚀 Running

### Start Server

```bash
# From project root
./bin/jarvis-web

# Or directly
cd jarvis-voice
source ~/jarvis-venv/bin/activate
python jarvis-web/bin/jarvis-web
```

### Access
- **Local**: http://localhost:5001
- **Network**: http://YOUR_IP:5001

---

## 🔍 Key Implementation Details

### Status Updates

Status updates route to browser instead of local speaker:

```python
# In orchestrator_v2.py
orchestrator.set_status_callback(callback)

# Callback emits via WebSocket
def status_callback(message):
    socketio.emit('chat:status', {'status': message})
```

### Conversation Context

Web conversations are passed to LLM (separate from terminal's memory_db):

```python
# Last 20 messages from web conversation
result = orchestrator.process(
    message,
    conversation_history=history,  # Web's own history
    excluded_tools=blocked_tools   # Web-blocked tools
)
```

### TTS Generation (Mode-Aware)

TTS provider is determined by the current mode's `.env` file:

| Mode | Provider | Config |
|------|----------|--------|
| **Cloud** | ElevenLabs | `TTS_PROVIDER=elevenlabs` in cloud.env |
| **Local** | Kokoro | `TTS_PROVIDER=kokoro` + `TTS_URL` in local.env |

```python
# In api.py - mode-aware TTS
@api_bp.route('/tts', methods=['POST'])
def text_to_speech():
    mode = request.json.get('mode')  # Client sends current mode
    load_jarvis_config(mode)
    
    provider = get_jarvis_setting('TTS_PROVIDER')
    if provider == 'kokoro':
        # Local: call TTS_URL directly (OpenAI-compatible)
        return call_kokoro_tts(text)
    else:
        # Cloud: ElevenLabs or OpenAI API
        return call_cloud_tts(text)
```

---

## 📋 TODO / Gaps

### High Priority
- [ ] Browser STT (mic input with push-to-talk)
- [ ] Full cloud.env settings display (read-only with editable subset)

### Medium Priority
- [ ] Conversation search
- [ ] Export/import conversations
- [ ] Tool enable/disable per-tool in UI
- [ ] Mobile responsive improvements
- [ ] MCP server status indicator (running/stopped)

### Low Priority
- [ ] Authentication (password/PIN)
- [ ] Multi-user support
- [ ] PWA manifest
- [ ] Themes (light mode)

### ✅ Recently Completed
- [x] MCP tool discovery (reads from memory_db)
- [x] Settings UI for blocked tools
- [x] Dynamic LLM provider/model switching
- [x] System config tab (mode-specific .env values)
- [x] Conversation history limit setting
- [x] Config cache reload on settings save
- [x] **Mode-aware TTS** - Cloud=ElevenLabs, Local=Kokoro ⭐ NEW
- [x] **Per-mode settings** - cloud/local sections in web_config.json ⭐ NEW
- [x] **Dynamic Ollama models** - fetches from server in local mode ⭐ NEW
- [x] **Clean mode switching** - resets Intelligence singleton ⭐ NEW
- [x] **STT_PROVIDER config** - ready for push-to-talk (faster-whisper/openai) ⭐ NEW

---

## 🧪 Testing Checklist

### Web UI
- [ ] Chat send/receive works
- [ ] Tool cards display correctly
- [ ] Images display with lightbox
- [ ] TTS plays when enabled
- [ ] Status updates show (not on local speaker)
- [ ] Settings save/load correctly
- [ ] Conversations save/load/delete
- [ ] Blocked tools not available to LLM

### Terminal Regression
- [ ] `./jarvis` voice loop works
- [ ] Terminal orchestrator works
- [ ] Status updates play on local speaker
- [ ] All tools available (including blocked-for-web)
- [ ] Memory/context works as before

---

## ⚖️ Web vs Terminal: Key Differences

| Aspect | Terminal/TUI/Jarvis | Web UI |
|--------|---------------------|--------|
| **Conversation History** | `memory_db` + `AUTO_CONTEXT_*` | JSON files + `conversation.history_limit` |
| **LLM Provider** | `.env` file (restart to change) | `web_config.json` per-mode (on-the-fly) |
| **Blocked Tools** | None (all tools available) | `tools.blocked` array |
| **Status Updates** | Local speaker | Browser WebSocket + optional TTS |
| **TTS** | Shell scripts (mode-specific) | Direct API (ElevenLabs/Kokoro based on mode) |
| **Intelligence/Insights** | ✅ Full (same orchestrator) | ✅ Full (singleton resets on mode switch) |
| **Tool RAG** | ✅ Full | ✅ Full |
| **Memory System** | ✅ Full (mode-specific DB) | ✅ Full (mode-specific DB) |
| **MCP Tools** | Started on demand | Pre-registered in memory_db |

### What's Shared (Same Code Path)
- `orchestrator/orchestrator_v2.py` - Core processing
- `orchestrator/router_v2.py` - LLM routing  
- `lib/tool_schema.py` - Tool RAG
- `lib/memory_db.py` - Memory/semantic search
- `lib/intelligence.py` - Self-learning insights
- All tools in `skills/`

### What's Web-Specific
- `jarvis-web/server/` - Flask+SocketIO backend
- `jarvis-web/client/` - Vanilla JS frontend
- `jarvis-web/config/web_config.json` - Web overrides
- `jarvis-web/data/conversations/` - Chat history as JSON

---

*Created: December 2025*  
*MVP Complete: December 17, 2025*  
*v1.1: Settings improvements, dynamic LLM switching - December 17, 2025*  
*v1.2: Mode-aware TTS/STT, per-mode settings, clean mode switching - December 17, 2025*
