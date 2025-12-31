# Jarvis Web UI

> **Status**: MVP Complete (v2.0)  
> **Last Updated**: December 31, 2025

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

![jarvis-web](images/jarvis-web.png)

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
| **Push-to-talk STT** | ✅ | Click mic → speak → click again → transcribe → send |
| **Mode-aware STT** | ✅ | Cloud=OpenAI Whisper, Local=faster-whisper |
| **Audio playback controls** | ✅ | Speaker button with pause/resume/stop, progress animation ⭐ NEW |
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
| System config view | ✅ | Mode-specific .env values in Settings → System |
| Per-mode settings | ✅ | `cloud`/`local` sections in web_config.json |
| Dynamic Ollama models | ✅ | Fetches available models from Ollama server |
| Clean mode switching | ✅ | Resets Intelligence singleton on mode change |
| Proactive alerts | ✅ | Polls jarvis-api for alerts/reminders |
| Browser notifications | ✅ | Notifications API for new alerts/reminders |
| **Image upload** | ✅ | Drag-drop/paste/click to attach images |
| **Vision analysis** | ✅ | Mode-aware: Cloud=Grok/Claude, Local=llava |
| **Expand details button** | ✅ | Show full LLM response before voice shortening |
| **Auto-stash uploads** | ✅ | Uploaded images auto-stash + memory_db entry |
| **analyze_image tool** | ✅ | Analyze URLs, files, stash refs with vision |
| Tool enable/disable | ⏳ | Planned (per-tool granular control) |

### Phase 5: Input Enhancement - COMPLETE ✅

| Feature | Status | Details |
|---------|--------|---------|
| **Slash commands** | ✅ | `/canvas`, `/search`, `/recall`, etc. - modify behavior |
| **@prompts** | ✅ | `@research`, `@quick`, `@compare` - inject methodologies |
| **Command autocomplete** | ✅ | Type `/` or `@` to see suggestions |
| **✨ Enhance with AI** | ✅ | Magic button transforms rough input into optimal prompt |
| **Tool exclusion** | ✅ | Commands can exclude tools (force native search) |

### Phase 6: Conversation Management - COMPLETE ✅

| Feature | Status | Details |
|---------|--------|---------|
| **Quick filter** | ✅ | Filter conversations by title in sidebar |
| **Deep search** | ✅ | Search across all message content with snippets |
| **Export JSON** | ✅ | Download conversation as JSON file |
| **Export Markdown** | ✅ | Download conversation as formatted Markdown |
| **Import JSON** | ✅ | Upload JSON to restore conversation |

### Phase 7: Developer Tools - COMPLETE ✅

| Feature | Status | Details |
|---------|--------|---------|
| **Server Logs Panel** | ✅ | Real-time log streaming at bottom of UI ⭐ NEW |
| **LLM call logs** | ✅ | Model, tokens, cost, duration, tool called ⭐ NEW |
| **Tool call logs** | ✅ | Tool name, duration, success/error, result preview ⭐ NEW |
| **Source toggles** | ✅ | Enable/disable LLM, Tools, OpenCode, Feedback ⭐ NEW |
| **Expandable details** | ✅ | Click entry to see full parsed JSON ⭐ NEW |
| **Resizable panel** | ✅ | Drag to resize, state persisted ⭐ NEW |

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
| GET | `/api/commands` | List all slash commands |
| GET | `/api/commands/<name>` | Get specific command |
| GET | `/api/prompts` | List all @prompts |
| GET | `/api/prompts/<name>` | Get specific prompt |
| POST | `/api/enhance-prompt` | ✨ AI-powered prompt enhancement |
| GET | `/api/conversations/search?q=` | Search message content across all conversations |
| GET | `/api/conversations/<id>/export?format=` | Export conversation (json/markdown) |
| POST | `/api/conversations/import` | Import conversation from JSON file |

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

### Audio Playback Controls (NEW)

A speaker button appears in the input bar when audio is playing, providing visual feedback and playback control:

**Visual Design:**
- Positioned on the **far left** of the input bar (prevents accidental clicks)
- Subtle **teal color scheme** (not bright green) that integrates with the glow intensity system
- Animated pulse effect during playback

**User Interactions:**

| Action | Result |
|--------|--------|
| **Single click** (while playing) | Pause audio |
| **Single click** (while paused) | Resume audio |
| **Double-click** | Stop audio completely and hide button |
| **Type new message** | Stops audio and hides button (ready for new response) |

**Button States:**

| State | Icon | Visual |
|-------|------|--------|
| **Playing** | 🔊 | Teal background with pulse animation |
| **Paused** | ⏸️ | Teal outline, no animation |
| **Hidden** | - | Button not visible |

**Behavior:**
- Button **appears** when TTS audio starts playing
- Button **stays visible** for **10 seconds** after audio finishes
- Button **immediately hides** if user types a new message
- Integrates with existing audio toggle (🔊 in header enables/disables TTS)

**CSS Classes:**
```css
.speaker-btn           /* Base button */
.speaker-btn.playing   /* Active playback state */
.speaker-btn.paused    /* Paused state */
```

---

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

### Image Upload & Vision Analysis (Built-in, NOT a tool)

The web UI has **native image upload** - this is NOT a tool call, it's built directly into the chat:

**How to Upload:**
1. **Click** the 📎 button next to input
2. **Drag-drop** an image onto the chat
3. **Paste** from clipboard (Ctrl+V)

**What Happens:**
1. Image is resized to max 1024px (keeps base64 small for socket)
2. Image is saved to `jarvis-web/data/uploads/`
3. Vision model analyzes the image (mode-aware)
4. For simple questions ("what is this?") → returns analysis directly
5. For complex requests ("save to canvas") → passes analysis to orchestrator

**Vision Models (Mode-Aware):**

| Mode | Provider | Model | Config |
|------|----------|-------|--------|
| **Cloud** | xAI Grok | `VISION_MODEL` | cloud.env |
| **Cloud** | Anthropic | Claude with vision | cloud.env |
| **Cloud** | OpenAI | GPT-4o | cloud.env |
| **Local** | Ollama | `OLLAMA_VISION_MODEL` | local.env (default: llava:latest) |

**Simple vs Complex Questions:**

The system detects if you're asking a simple question or want actions:

| Question Type | Example | Behavior |
|---------------|---------|----------|
| **Simple** | "What is this?" "Describe this" | Vision → Summary → Direct response (no tools) |
| **Complex** | "Save this to canvas" "Create similar" | Vision → Orchestrator → Tool calls |

Simple patterns: "what is this", "describe", "identify", "who/where/when is this"
Action keywords: "create", "save", "canvas", "generate", "similar", "search"

**Uploaded Images Persist:**
- Saved in conversation history with `image_url`
- Thumbnails display when you reload the conversation
- Vision analysis stored in `data.vision_analysis` for expand details

**Auto-Stash (NEW):**
- After vision analysis, images are automatically stashed to `data/stash/`
- A `stash_artifact` entry is created in `memory_db` with:
  - `source="web_upload"`
  - `metadata` (stash_ref, file_id, tags, vision_analysis snippet)
- This enables cross-tool workflows: "Email the image I uploaded earlier"
- Stash has 7-day TTL, but memory entry persists for recall

---

### generate_music Tool (NEW)

ElevenLabs music generation integrated into Jarvis with automatic stash storage and web UI playback:

**How It Works:**
1. User requests music generation (e.g., "Create an epic intro for my podcast")
2. Tool calls ElevenLabs Music API with prompt, genre, mood, tempo, duration
3. Generated audio saved to `data/generated_music/`
4. Stash reference created for artifact management
5. Memory entry saved for future recall
6. Web UI renders inline audio player

**Parameters:**
- `prompt` (required): Music description/concept
- `genre` (optional): Electronic, Cinematic, Rock, Jazz, Classical, Hip-Hop, etc.
- `mood` (optional): Epic, Mysterious, Uplifting, Dark, Energetic, Calm, etc.
- `tempo` (optional): Slow, Medium, Fast, or BPM number
- `instrumental` (optional): Whether vocals should be excluded (default: true)
- `duration_seconds` (optional): 30-300 seconds (default: 60)

**Web UI Integration:**
- Audio player renders in tool result card
- Uses `/api/music/<filename>` or `/api/stash/<space>/<file>` endpoints
- Supports both direct file paths and stash references

**@generate_music Prompt:**
A dedicated prompt (`jarvis-web/data/prompts/generate_music.md`) provides best practices for music prompts based on ElevenLabs guidelines.

**Timeout:** Extended to 10 minutes (600s) for longer generations.

---

### analyze_image Tool (NEW)

A dedicated tool for analyzing images from various sources:

**Supported Sources:**
| Source Type | Example | Description |
|-------------|---------|-------------|
| **URL** | `https://example.com/image.jpg` | Downloads with SSRF protection |
| **Local file** | `/home/user/photo.jpg` | Reads from filesystem |
| **Stash reference** | `stash://space_xxx/file_id` | Loads from stash system |

**Parameters:**
- `image` (required): URL, file path, or stash reference
- `question` (optional): Specific question about the image (default: "Describe this image")
- `stash_after` (optional): Save to stash after analysis (default: true)

**Security:**
- Uses `safe_download()` from stash_helper for URL downloads
- SSRF protection (blocks private IPs: localhost, 192.168.x.x, 10.x.x.x)
- `sanitize_filename()` prevents path traversal attacks
- 20MB max download size

**Example Usage:**
```
"Analyze this image https://example.com/chart.png"
"What's in stash://space_20251218_094432/f_abc123?"
"Analyze /home/boss/photos/vacation.jpg and tell me where it was taken"
```

**When to Use:**
- Web UI image upload: Built-in vision (NOT this tool)
- Analyze URL/file/stash via voice/CLI: Use this tool

---

### Expand Details Button

Each assistant message may have a **"▶ Show details"** button to reveal the full LLM response:

**When it appears:**
- Response was shortened for voice output (casual/auto mode)
- Image was analyzed (full vision analysis vs short summary)
- Multi-tool complex results condensed for speech

**When it won't appear:**
- Simple Q&A where full response = speech
- Detailed mode (no shortening needed)
- Response is already short

**What it shows:**
- `raw_llm_response`: Original LLM output before voice formatting
- `vision_analysis`: Full image description before summarization
- Tool results and reasoning that didn't make it to speech

---

### Proactive Notifications

The web UI polls `jarvis-api` (port 8880) for pending alerts and triggered reminders:

**What Gets Notified:**
- **Alerts**: From Uptime Kuma, Coolify, cron scripts, UniFi Protect, etc.
- **Reminders**: Scheduled reminders, Google Calendar synced events

**How It Works:**
1. Web UI polls every 10 seconds:
   - `GET /api/alerts?status=pending`
   - `GET /api/reminders?status=triggered`
2. New items broadcast to all connected clients
3. Browser notification shown (if permission granted)
4. TTS plays the alert/reminder (if audio enabled)

**Notification Panel:**
- 🔔 Badge in header shows pending count
- Click badge to open notification panel
- Click ✓ to acknowledge items
- Items are removed from both jarvis-api and UI

**Requirements:**
- `jarvis-api` must be running for notifications to work
- Grant browser notification permission when prompted
- Works with both cloud and local modes (same DB per mode)

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
- 🔮 **Memory management UI** - View/edit/delete memories visually
- 🔮 **Intelligence dashboard** - See insights, confidence, decay
- 🔮 **Canvas embed** - Show canvas pages inline in chat
- 🔮 **Multi-conversation tabs** - Multiple chats open
- 🔮 **Export conversations** - JSON/Markdown download
- 🔮 **Tool execution history** - View past tool calls across sessions
- 🔮 **Cost tracking display** - Show token usage and $ spent
- 🔮 **Mobile PWA** - Install as app on phone
- 🔮 **Cross-tool stash flows** - "Email the image I uploaded" (needs send_email stash support)

### Canvas Integration

| Feature | Status | Description |
|---------|--------|-------------|
| **Canvas header icon** | ✅ Done | 📄 button opens Canvas in new tab |
| **`/canvas` command** | ✅ Done | Type `/canvas query` to research + save to Canvas |
| **Save to Canvas button** | 🔮 Planned | Button on messages to save to Canvas |
| **Inline Canvas preview** | 🔮 Planned | Show canvas pages inline in chat |

---

### Slash Commands (`/commands`)

Type `/` in the chat input to see available commands. Commands modify how Jarvis processes your request.

| Command | Icon | Description |
|---------|------|-------------|
| `/canvas` | 📄 | Research topic, then save comprehensive results to Canvas |
| `/search` | 🌐 | Force native web search (excludes external search tools) |
| `/recall` | 🧠 | Search memories and past conversations |
| `/remember` | 💾 | Save information to long-term memory |
| `/detailed` | 📝 | Get comprehensive response (no voice shortening) |
| `/image` | 🖼️ | Generate an image with AI |
| `/email` | ✉️ | Compose and send an email |
| `/call` | 📞 | Make a phone call |
| `/weather` | 🌤️ | Get weather information |
| `/bash` | 💻 | Execute a shell command |

**How Commands Work:**
1. Commands inject instructions AFTER your message (so task executes first)
2. Some commands exclude competing tools (e.g., `/search` excludes `mcp_fetch_fetch`)
3. Commands can set response style (e.g., `/detailed` sets `response_style: detailed`)

**File Location:** `jarvis-web/data/commands/*.json`

**Example command definition (`canvas.json`):**
```json
{
  "name": "canvas",
  "description": "Use native search, then save to Canvas",
  "icon": "📄",
  "instruction": "USE YOUR NATIVE WEB SEARCH - NOT EXTERNAL TOOLS!...",
  "exclude_tools": ["crypto_price", "mcp_fetch_fetch", "mcp_brave_search"],
  "response_style": "detailed"
}
```

---

### @Prompts

Type `@` in the chat input to see available prompts. Prompts inject methodology/guidelines for how to approach a task.

| Prompt | Description |
|--------|-------------|
| `@research` | Multi-source research methodology with citations |
| `@quick` | Concise, direct answers without elaboration |
| `@compare` | Side-by-side comparison format |
| `@code_review` | Code review guidelines (security, performance, style) |
| `@blog_post` | Blog writing structure and tone |
| `@summary` | Summarization guidelines (key points, brevity) |
| `@explain` | ELI5-style explanations |
| `@step_by_step` | Step-by-step instruction format |
| `@debug` | Debugging methodology |
| `@generate_music` | ElevenLabs music generation best practices ⭐ NEW |
| `@email` | Professional email composition with send_email tool format ⭐ NEW |
| `@daily` | Daily briefing (time, weather, reminders, crypto prices) ⭐ NEW |

**Context-First Injection (v2.0):**
Prompts are injected **BEFORE** the user's message to provide context first:
```
[System instruction from @prompt]
---
[User's actual message/task]
```
This ensures the LLM understands the methodology before seeing the task.

**Combining Commands + Prompts:**
```
/canvas @research kubernetes security best practices
```
This: Uses research methodology → Gathers comprehensive info → Saves to Canvas

**File Location:** `jarvis-web/data/prompts/*.md`

---

### ✨ Enhance with AI

The **✨ button** next to the chat input transforms rough input into an optimal prompt.

**How It Works:**
```
User types: "bitcoin news"
       ↓
Clicks ✨ button
       ↓
LLM enhances with Jarvis context:
  - Available tools (30+)
  - Native search capabilities
  - Best practices
       ↓
Returns: "What's the latest Bitcoin news and price action? 
         Include the current price, significant price movements 
         in the last 24 hours, and the top 3-5 major news 
         headlines. Summarize key analyst predictions."
       ↓
Replaces input field text
```

**Key Points:**
- Uses direct LLM call (fast, ~1-2 seconds)
- Does NOT go through orchestrator (no tool execution)
- Only enhances text - the SEND goes through full orchestrator
- Won't enhance if input starts with `/` or `@` (those are explicit)

**API Endpoint:** `POST /api/enhance-prompt`

**When to Use:**
- Quick polish for casual queries
- When you're not sure how to phrase something
- To add specificity (time ranges, sources, format)

**When NOT to Use:**
- Already using `/command` or `@prompt`
- Input is already detailed and specific
- You want exact control over the request

---

### Input Enhancement Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     INPUT ENHANCEMENT FLOW                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  User types: "/canvas @research kubernetes security"             │
│                 │                                                │
│                 ▼                                                │
│  ┌─────────────────────────────────────────┐                    │
│  │        Frontend Parser (chat.js)        │                    │
│  │  • Detects /canvas → loads command.json │                    │
│  │  • Detects @research → loads prompt.md  │                    │
│  │  • Extracts message: "kubernetes..."    │                    │
│  └─────────────────────────────────────────┘                    │
│                 │                                                │
│                 ▼                                                │
│  ┌─────────────────────────────────────────┐                    │
│  │      Backend Handler (chat.py)          │                    │
│  │  • Combines command + prompt instruc.   │                    │
│  │  • APPENDS instruction AFTER message    │                    │
│  │  • Applies exclude_tools to router      │                    │
│  └─────────────────────────────────────────┘                    │
│                 │                                                │
│                 ▼                                                │
│  ┌─────────────────────────────────────────┐                    │
│  │    Orchestrator (with insights/feedback) │                    │
│  │  • Full intelligence system applied      │                    │
│  │  • Tools excluded per command config     │                    │
│  │  • Native search preferred when enabled  │                    │
│  └─────────────────────────────────────────┘                    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                   ✨ ENHANCE FLOW (Separate)                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  User types: "bitcoin news" → clicks ✨                          │
│                 │                                                │
│                 ▼                                                │
│  ┌─────────────────────────────────────────┐                    │
│  │   POST /api/enhance-prompt              │                    │
│  │  • Direct LLM call (bypasses orchestr.) │                    │
│  │  • System prompt with tool knowledge    │                    │
│  │  • Returns enhanced text only           │                    │
│  └─────────────────────────────────────────┘                    │
│                 │                                                │
│                 ▼                                                │
│  Input field updated → User reviews → Sends normally            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Canvas + Stash + Web UI Flow:**
```
Web UI → Upload image → Stash (temp) → /canvas → Canvas (permanent)
                                    ↓
                            Phone call ends → Auto-save transcript to Canvas
                                    ↓
                            generate_image → Image + prompt to Canvas
```

---

### Server Logs Panel (NEW)

A collapsible panel at the bottom of the UI that streams server logs in real-time. Simpler than Grafana for quick debugging!

**UI Layout:**
```
┌─────────────────────────────────────────────────────────────────┐
│  Chat Area (main content)                                        │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│ ▼ Server Logs         [🤖 LLM] [🔧 Tools] [💻 Code] [⭐ FB]  🗑️ ⬇️ │
│ 03:21:09 LLM  xai/grok-4... → 18505 tokens ($0.0021) [3.5s]      │
│ 03:23:02 LLM  xai/grok-4... → 11589 tokens ($0.0023) [2.5s] 🔧gen│
│ 03:23:25 TOOL generate_image → 22.1s ✓                           │
│ 03:23:28 LLM  xai/grok-4... → 11882 tokens ($0.0024) [2.5s]      │
└──────────────────────────────────────────────────────────────────┘
```

**Features:**
- **Real-time streaming** - Tails log files, shows only NEW entries after subscribing
- **Source toggles** - Enable/disable: LLM, Tools, OpenCode, Feedback
- **Color-coded** - Purple=LLM, Green=Tools, Blue=OpenCode, Pink=Feedback
- **Status colors** - Green=success, Red=error, Yellow=warning
- **Expandable details** - Click any entry to see full parsed JSON
- **Resizable** - Drag top edge to resize (100-600px)
- **Auto-scroll** - Toggle on/off with ⬇️ button
- **Clear** - Clears UI only (disk logs preserved)
- **Persisted state** - Height, collapsed state, enabled sources saved to localStorage

**Log Sources:**

| Source | File | Content |
|--------|------|---------|
| **LLM** | `logs/llm-calls-{date}.jsonl` | Model, tokens, cost, duration, tool called |
| **Tools** | `logs/tools/tool-calls-{date}.jsonl` | Tool name, args, result, duration, success |
| **OpenCode** | `logs/opencode/opencode-{date}.jsonl` | Session events, status |
| **Feedback** | `logs/feedback/feedback-{date}.jsonl` | Ratings, feedback text |

**WebSocket Events:**
- `logs:subscribe` - Start streaming (joins `logs_subscribers` room)
- `logs:unsubscribe` - Stop streaming
- `logs:entry` - Receives parsed log entry
- `logs:set_sources` - Enable/disable specific sources

**When to Use:**
- Quick debugging during development
- Watch LLM decisions and tool calls in real-time
- Track costs per conversation
- Simpler than opening Grafana for quick checks

---

## 📋 TODO / Gaps

### High Priority (Do First)
- [x] **Browser STT** - Push-to-talk with mic button ✅ DONE
  - Click-to-toggle: click to start, click again to stop
  - Mode-aware: Cloud=OpenAI Whisper, Local=faster-whisper
  - Visual states: preparing (blue), recording (green), processing (yellow)
  - Auto-sends transcript as chat message
- [x] **Proactive integration** - Show alerts/reminders in UI ✅ DONE
  - Polls jarvis-api every 10 seconds for pending alerts/triggered reminders
  - Browser notifications (Notifications API) for new items
  - TTS playback when audio is enabled
  - Notification panel with acknowledge buttons
- [ ] **Test mode switching thoroughly**
  - Cloud→Local: TTS should use Kokoro
  - Local→Cloud: TTS should use ElevenLabs
  - Intelligence insights should work in both modes

### Medium Priority
- [x] Conversation search (filter by keyword/date) ✅ DONE
- [x] Export conversations (JSON/Markdown) ✅ DONE
- [x] Import conversations (JSON) ✅ DONE
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

### ✅ Recently Completed (v2.0)
- [x] MCP tool discovery (reads from memory_db)
- [x] Settings UI for blocked tools
- [x] Dynamic LLM provider/model switching
- [x] System config tab (mode-specific .env values)
- [x] Conversation history limit setting
- [x] Config cache reload on settings save
- [x] Mode-aware TTS - Cloud=ElevenLabs, Local=Kokoro
- [x] Per-mode settings - cloud/local sections in web_config.json
- [x] Dynamic Ollama models - fetches from server in local mode
- [x] Clean mode switching - resets Intelligence singleton
- [x] Push-to-talk STT - Click-to-toggle voice input
- [x] Mode-aware STT - Cloud=OpenAI Whisper, Local=faster-whisper
- [x] Recording visual states - Blue/green/yellow feedback
- [x] Proactive notifications - Polls jarvis-api for alerts/reminders
- [x] Browser notifications - Notifications API integration
- [x] Notification panel - View/acknowledge alerts & reminders
- [x] Local audio fix - Now serves from audio/local/tts too
- [x] **Audio playback controls** - Speaker button with pause/resume/stop ⭐ NEW
- [x] **Progress animation** - Visual pulse during playback ⭐ NEW
- [x] **Smart auto-hide** - 10s after audio ends, instant on new message ⭐ NEW
- [x] **ElevenLabs music generation** - `generate_music` tool with stash integration ⭐ NEW
- [x] **Music playback in web UI** - Generated music plays inline ⭐ NEW
- [x] **@prompts system** - Context-first injection for LLM guidance ⭐ NEW
- [x] **deep_memory_search tool** - Multi-source search across all data ⭐ NEW
- [x] **Image upload** - Drag-drop/paste/click, auto-resize to 1024px
- [x] **Mode-aware vision** - Cloud=Grok/Claude, Local=llava
- [x] **Expand details button** - Show full LLM response, tool results
- [x] **Tool cards show results** - Fixed data.data nesting bug
- [x] **Native search prompt** - Tells LLM to prefer built-in search
- [x] **Config loading fix** - load_jarvis_config before Orchestrator
- [x] **Auto-stash uploaded images** - Images saved to stash + memory_db
- [x] **analyze_image tool** - Analyze URLs, files, stash refs with SSRF protection
- [x] **generate_image memory fix** - Now saves source + metadata for semantic recall
- [x] **Safe URL downloads** - Uses stash_helper's safe_download + sanitize_filename
- [x] **Slash commands** - `/canvas`, `/search`, `/recall`, `/detailed`, etc. ⭐ NEW
- [x] **@prompts system** - `@research`, `@quick`, `@compare`, etc. ⭐ NEW
- [x] **Command autocomplete** - Type `/` or `@` for suggestions ⭐ NEW
- [x] **✨ Enhance with AI** - Transform rough input into optimal prompts ⭐ NEW
- [x] **Tool exclusion** - Commands can exclude tools to force native search ⭐ NEW
- [x] **Canvas command** - `/canvas` researches + saves to Canvas viewer
- [x] **Conversation quick filter** - Filter by title in sidebar ⭐ NEW
- [x] **Deep search modal** - Search all message content with highlighted snippets ⭐ NEW
- [x] **Export conversations** - JSON and Markdown formats ⭐ NEW
- [x] **Import conversations** - Restore from JSON files
- [x] **Server Logs Panel** - Real-time streaming at bottom of UI ⭐ NEW
- [x] **LLM + Tool logs** - Parsed, color-coded, expandable details ⭐ NEW
- [x] **Log source toggles** - Enable/disable LLM, Tools, OpenCode, Feedback ⭐ NEW
- [x] **Resizable log panel** - Drag to resize, state persisted in localStorage ⭐ NEW

---

## ⚠️ Known Issues & Gotchas

### 🔥 CRITICAL: Config Loading Order

**The #1 source of "it works in terminal but not web" bugs!**

**How Terminal Works:**
```python
# jarvis command loads config FIRST, before any imports
load_config('cloud')  # Line 25 - BEFORE orchestrator import
# Then imports happen
from orchestrator_v2 import Orchestrator
```

**How Web Works:**
```python
# jarvis-web imports modules, THEN loads config per-request
from orchestrator_v2 import Orchestrator  # Imports happen at startup
# Later, in _process_message:
load_jarvis_config(mode)  # Must be called BEFORE creating Orchestrator
orchestrator = Orchestrator(mode=mode)
```

**The Gotcha:**
If `load_jarvis_config(mode)` is NOT called before the Orchestrator is created, settings like `XAI_SEARCH`, `LLM_PROVIDER`, `TTS_PROVIDER` etc. will have WRONG values (stale from previous mode or missing).

**Always ensure this order in web handlers:**
1. `load_jarvis_config(mode)` - Load .env for current mode
2. Import/create Orchestrator
3. Process message

**Debug tip:** Add logging to verify config loaded correctly:
```python
xai_search = get_jarvis_setting('XAI_SEARCH', 'false')
print(f"[CHAT] Config loaded: XAI_SEARCH={xai_search}")
```

---

### Native Search (XAI_SEARCH / ANTHROPIC_SEARCH)

**Gotcha:** Even when `XAI_SEARCH=true`, Grok might use `mcp_fetch` instead of native search!

**Why:** Grok in "auto" mode sees both options and might prefer tools.

**Fix:** The router now adds system prompt instruction when native search is enabled:
```
NATIVE SEARCH ENABLED:
Use your NATIVE SEARCH - DO NOT use mcp_fetch, brave_search...
```

**Verify it's working:** Check for `tools=[]` in response (no tool calls = native search used).

---

### Mode Switching
| Issue | Workaround |
|-------|------------|
| Embedding dimension mismatch after switch | Page refresh resets all singletons cleanly |
| Intelligence insights from wrong mode | Fixed in v1.2 (singleton reset), but refresh is safer |
| Settings show stale values | Click Settings tab again to reload |
| Config not loaded for new mode | Fixed - `load_jarvis_config(mode)` now called before Orchestrator |

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

### Images (Generated)
- [ ] `generate_image` shows thumbnail inline
- [ ] Click thumbnail opens lightbox
- [ ] Download button works
- [ ] Image in tool card expandable section

### Images (Uploaded)
- [ ] Click 📎 button opens file picker
- [ ] Drag-drop image onto chat area works
- [ ] Paste image (Ctrl+V) works
- [ ] Preview appears before sending
- [ ] "What is this?" uses vision model, no tools
- [ ] "Save to canvas" uses vision + canvas tool
- [ ] Cloud mode: Grok/Claude vision works
- [ ] Local mode: llava vision works
- [ ] Large images auto-resize to 1024px
- [ ] Uploaded images persist in conversation history

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

### Expand Details
- [ ] Tool-using response shows "▶ Show details" button
- [ ] Click expands to show full LLM response
- [ ] Click again collapses
- [ ] Simple Q&A (no tools) may not show button (response = speech)
- [ ] Vision analysis shows full description in details
- [ ] Details persist when reloading conversation

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
- ✅ **Alert notifications**: Browser notification when alert triggers (DONE) -doesnt work! 
- ✅ **Reminder popup**: Browser notification when reminder fires (DONE) - doesnt work! 
- **Follow-up prompts**: "Your task is ready, want to review?"
- **Health status**: Show API/services health in header

### Memory & Intelligence
- **Memory browser**: View/search/edit/delete memories
- **Intelligence dashboard**: Insights, confidence scores, decay status
- **Learning history**: See what Jarvis learned from interactions
- **Manual insight creation**: Teach Jarvis directly via UI

### Developer Features
- ✅ **Server Logs Panel**: Real-time LLM + Tool logs at bottom of UI (DONE!)
- ✅ **LLM call inspector**: Model, tokens, cost, duration, tool called (DONE!)
- ✅ **Tool logs viewer**: See tool executions with expandable details (DONE!)
- 🔮 **Cost tracker**: Daily/weekly/monthly spend summary
- 🔮 **A/B test viewer**: See prompt evolution experiments

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
*v1.4: Proactive notifications (alerts/reminders from jarvis-api) - December 17, 2025*  
*v1.5: Image upload with vision analysis, expand details, config loading fixes - December 17, 2025*  
*v1.6: Auto-stash uploads, analyze_image tool, SSRF-protected downloads - December 18, 2025*  
*v1.7: Slash commands, @prompts, ✨ Enhance with AI, Canvas command - December 19, 2025*  
*v1.8: Conversation search, export (JSON/Markdown), import - December 19, 2025*  
*v1.9: Server Logs Panel - Real-time LLM + Tool streaming - December 19, 2025*  
*v2.0: Audio playback controls, ElevenLabs music generation, deep_memory_search tool - December 31, 2025*
