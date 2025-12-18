# Jarvis Web UI

> **Status**: MVP Complete (v1.3)  
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

### Phase 3: Voice - COMPLETE ✅

| Feature | Status | Details |
|---------|--------|---------|
| TTS playback | ✅ | Toggle audio, plays responses in browser |
| Mode-aware TTS | ✅ | Cloud=ElevenLabs, Local=Kokoro (via TTS_URL) |
| Status TTS | ✅ | Status updates play as TTS when audio enabled |
| **Push-to-talk STT** | ✅ | Click mic → speak → click again → transcribe → send ⭐ NEW |
| **Mode-aware STT** | ✅ | Cloud=OpenAI Whisper, Local=faster-whisper ⭐ NEW |
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

### STT (Push-to-Talk) - Mode-Aware

STT provider is determined by the current mode's `.env` file:

| Mode | Provider | Config |
|------|----------|--------|
| **Cloud** | OpenAI Whisper | `STT_PROVIDER=openai` + `STT_MODEL` in cloud.env |
| **Local** | faster-whisper | `STT_PROVIDER=faster-whisper` in local.env |

**User Flow:**
1. Click mic button 🎤 → Blue "preparing" state
2. Grant mic permission (first time only)
3. Green "recording" state → Speak your message
4. Click mic again → Yellow "processing" state
5. Audio sent to `/api/stt` → Transcribed → Auto-sent as chat

**Keyboard:** Press `Esc` to cancel recording

```python
# In api.py - mode-aware STT
@api_bp.route('/stt', methods=['POST'])
def speech_to_text():
    mode = request.form.get('mode')
    load_jarvis_config(mode)
    
    provider = get_jarvis_setting('STT_PROVIDER')
    if provider == 'faster-whisper':
        # Local: use stt_local.py script
        return transcribe_local(audio_path)
    else:
        # Cloud: OpenAI Whisper API
        return transcribe_openai(audio_path)
```

---

## 🔍 Gaps: Web vs Terminal/TUI

### What Web CAN'T Do (Yet)

| Gap | Why | Priority |
|-----|-----|----------|
| **Wake word detection** | Needs browser VAD (voice activity detection) | Medium |
| **Continuous voice loop** | listen → respond → listen cycle | Medium |
| **Local speaker volume** | Hardware control is local-only | N/A (by design) |
| **Audio device selection** | Browser uses system default | Low |
| **Memory sync on startup** | Terminal does auto-sync, web doesn't | Low |
| **Proactive notifications** | Alerts/reminders don't push to web UI | High |
| **Canvas viewer integration** | Canvas runs separately on :8890 | Medium |

### What Terminal/TUI CAN'T Do

| Gap | Web Advantage |
|-----|---------------|
| **Visual tool cards** | See tool args, results, timing inline |
| **Image preview** | Lightbox with download, no file manager needed |
| **Conversation management** | Save/load/delete/search history |
| **On-the-fly settings** | Change LLM/model without restart |
| **Remote access** | Access from any device on network |
| **No TTS cutoff** | Browser audio cleaner than speaker wake-up |
| **Visual status updates** | See progress without audio |
| **Tool blocking** | Restrict tools for web without affecting terminal |

---

## 🚀 Web-Unique Features to Leverage

### Already Implemented
- ✅ Visual tool execution cards with timing
- ✅ Image generation inline display + lightbox
- ✅ Conversation persistence (save/load/delete)
- ✅ Per-mode settings without touching .env
- ✅ Dynamic model discovery (Ollama)
- ✅ System config visibility (read-only .env view)
- ✅ Tool blocking for web-only restrictions
- ✅ Real-time status streaming (WebSocket)

### Planned / Ideas
- 🔮 **Proactive notifications** - Alerts/reminders popup in browser
- 🔮 **Memory management UI** - View/edit/delete memories visually
- 🔮 **Intelligence dashboard** - See insights, confidence, decay
- 🔮 **Canvas embed** - Show canvas pages inline in chat
- 🔮 **Multi-conversation tabs** - Multiple chats open
- 🔮 **Export conversations** - JSON/Markdown download
- 🔮 **Voice recording indicator** - Visual feedback during STT
- 🔮 **Tool execution history** - View past tool calls across sessions
- 🔮 **Cost tracking display** - Show token usage and $ spent
- 🔮 **Mobile PWA** - Install as app on phone

---

## 📋 TODO / Gaps

### High Priority (Do First)
- [x] **Browser STT** - Push-to-talk with mic button ✅ DONE
  - Click-to-toggle: click to start, click again to stop
  - Mode-aware: Cloud=OpenAI Whisper, Local=faster-whisper
  - Visual states: preparing (blue), recording (green), processing (yellow)
  - Auto-sends transcript as chat message
- [ ] **Proactive integration** - Show alerts/reminders in UI
  - Connect to jarvis-api WebSocket or poll endpoint
  - Desktop notifications when alert triggers
- [ ] **Test mode switching thoroughly**
  - Cloud→Local: TTS should use Kokoro
  - Local→Cloud: TTS should use ElevenLabs
  - Intelligence insights should work in both modes

### Medium Priority
- [ ] Conversation search (filter by keyword/date)
- [ ] Export conversations (JSON/Markdown)
- [ ] Tool enable/disable per-tool in UI
- [ ] MCP server status indicator (running/stopped/error)
- [ ] Mobile responsive improvements
- [ ] Canvas integration (embed pages or link)

### Low Priority
- [ ] Authentication (password/PIN for remote access)
- [ ] Multi-user support (separate conversation namespaces)
- [ ] PWA manifest (installable app)
- [ ] Light theme option
- [ ] Keyboard shortcuts (Ctrl+Enter send, etc.)

### ✅ Recently Completed (v1.3)
- [x] MCP tool discovery (reads from memory_db)
- [x] Settings UI for blocked tools
- [x] Dynamic LLM provider/model switching
- [x] System config tab (mode-specific .env values)
- [x] Conversation history limit setting
- [x] Config cache reload on settings save
- [x] **Mode-aware TTS** - Cloud=ElevenLabs, Local=Kokoro
- [x] **Per-mode settings** - cloud/local sections in web_config.json
- [x] **Dynamic Ollama models** - fetches from server in local mode
- [x] **Clean mode switching** - resets Intelligence singleton
- [x] **Push-to-talk STT** - Click-to-toggle voice input ⭐ NEW
- [x] **Mode-aware STT** - Cloud=OpenAI Whisper, Local=faster-whisper ⭐ NEW
- [x] **Recording visual states** - Blue/green/yellow feedback ⭐ NEW

---

## ⚠️ Known Issues & Gotchas

### Mode Switching
| Issue | Workaround |
|-------|------------|
| Embedding dimension mismatch after switch | Page refresh resets all singletons cleanly |
| Intelligence insights from wrong mode | Fixed in v1.2 (singleton reset), but refresh is safer |
| Settings show stale values | Click Settings tab again to reload |

### TTS
| Issue | Workaround |
|-------|------------|
| Local TTS fails silently | Check Kokoro server is running at TTS_URL |
| Audio doesn't play | Check browser autoplay policy, click somewhere first |
| TTS too slow | Status updates have 1s delay by design |

### Tools
| Issue | Workaround |
|-------|------------|
| Tool not found | Refresh tools list, check if blocked |
| MCP tool missing | Ensure MCP server ran at least once (registers to memory_db) |
| `generate_image` timeout | Increased to 5 min, but grounding can be slow |

### Conversations
| Issue | Workaround |
|-------|------------|
| Old conversation shows wrong images | Image URLs may expire, re-generate |
| Context too short | Increase `conversation.history_limit` in settings |
| Terminal doesn't see web conversations | By design - separate history systems |

### Performance
| Issue | Workaround |
|-------|------------|
| Slow in local mode | Ollama model loading takes time on first query |
| WebSocket disconnects | Auto-reconnects, but may lose in-flight message |
| Memory usage grows | Refresh page periodically for long sessions |

---

## 🧪 Testing Checklist

### Basic Functionality
- [ ] Send message, receive response
- [ ] Tool execution shows card with args/result
- [ ] Multi-tool response chains correctly
- [ ] Q&A responses (no tool call) work
- [ ] Long responses render with markdown

### Mode Switching
- [ ] Start in cloud mode, switch to local
- [ ] Start in local mode, switch to cloud
- [ ] TTS uses correct provider per mode
- [ ] Settings → System shows correct .env values
- [ ] No embedding dimension errors in console

### TTS (Audio Output)
- [ ] Enable TTS, send message, hear response
- [ ] Disable TTS, no audio plays
- [ ] Status updates play TTS (when enabled)
- [ ] Cloud mode: ElevenLabs voice
- [ ] Local mode: Kokoro voice

### STT (Voice Input)
- [ ] Click mic, see blue "preparing" state
- [ ] Grant permission, see green "recording" state
- [ ] Speak, click mic again, see yellow "processing"
- [ ] Transcript appears in input and auto-sends
- [ ] Cloud mode: OpenAI Whisper (check server logs)
- [ ] Local mode: faster-whisper (check server logs)
- [ ] Press Esc to cancel recording

### Images
- [ ] `generate_image` shows thumbnail inline
- [ ] Click thumbnail opens lightbox
- [ ] Download button works
- [ ] Image in tool card expandable section

### Conversations
- [ ] New chat clears messages
- [ ] Send message creates conversation in sidebar
- [ ] Click conversation loads it
- [ ] Delete conversation removes it
- [ ] Conversation context sent to LLM (check server logs)

### Settings
- [ ] Change LLM provider, new message uses it
- [ ] Change LLM model, new message uses it
- [ ] Reset to defaults clears overrides
- [ ] Block a tool, verify it's not called
- [ ] Unblock a tool, verify it works again

### Tools Tab
- [ ] Shows all local tools
- [ ] Shows MCP tools (if any registered)
- [ ] Shows blocked tools with indicator
- [ ] Refresh button reloads list

### Terminal Regression (Non-Web)
- [ ] `./jarvis` voice loop works normally
- [ ] `./orchestrator/orchestrator_v2.py cloud "test"` works
- [ ] Status updates play on LOCAL speaker (not browser)
- [ ] All tools available (web-blocked tools work)
- [ ] Memory search/recall works

---

## 🔮 Future Feature Ideas

### Voice (Phase 3 completion)
- ✅ **Push-to-talk**: Click to record → speak → click to send (DONE)
- **Continuous mode**: Optional always-listening with VAD
- **Wake word**: "Hey Jarvis" in browser (privacy implications)
- **Auto-listen after response**: Automatically start recording after TTS finishes

### Proactive Integration
- **Alert notifications**: Browser notification when alert triggers
- **Reminder popup**: Modal when reminder fires
- **Follow-up prompts**: "Your task is ready, want to review?"
- **Health status**: Show API/services health in header

### Memory & Intelligence
- **Memory browser**: View/search/edit/delete memories
- **Intelligence dashboard**: Insights, confidence scores, decay status
- **Learning history**: See what Jarvis learned from interactions
- **Manual insight creation**: Teach Jarvis directly via UI

### Developer Features
- **Tool logs viewer**: See recent tool executions
- **LLM call inspector**: View full prompts/responses
- **Cost tracker**: Daily/weekly/monthly spend
- **A/B test viewer**: See prompt evolution experiments

### UX Improvements
- **Keyboard shortcuts**: Ctrl+Enter send, Ctrl+N new chat, etc.
- **Drag-drop files**: Upload images/files directly
- **Paste images**: Paste from clipboard
- **Message reactions**: Thumbs up/down for feedback
- **Message editing**: Edit sent messages

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
*v1.2: Mode-aware TTS, per-mode settings, clean mode switching - December 17, 2025*  
*v1.3: Push-to-talk STT with mode-aware providers (OpenAI/faster-whisper) - December 17, 2025*
