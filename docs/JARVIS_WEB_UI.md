# Jarvis Web UI - Planning Document

> **Status**: Planning Phase  
> **Goal**: A standalone, modular web application for Jarvis - the "pretty terminal with superpowers"

---

## 🎯 Vision

A **dedicated web application** (`jarvis-web`) that provides the full Jarvis experience through a modern chat interface:

- 🔌 **Pluggable**: Auto-discovers tools, MCPs, and features
- 🔄 **Real-time**: WebSocket-first architecture
- ⚙️ **Configurable**: Settings UI (no more editing .env files)
- 🎨 **Beautiful**: Modern, polished UI
- 📦 **Modular**: Easy to extend and maintain
- 🔮 **Future-proof**: Easy to swap providers, models, features

**This is NOT a replacement** - it's a new interface alongside:
- Terminal (`orchestrator_v2.py`) - Dev/testing
- Voice loop (`jarvis`) - Hands-free interaction  
- Canvas (`jarvis-canvas`) - Document management
- **Web UI (`jarvis-web`)** - Full-featured chat interface ← NEW

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         JARVIS WEB                              │
│  ┌──────────────────────┐    ┌───────────────────────────────┐ │
│  │      Frontend        │    │          Backend              │ │
│  │   (React/Vanilla)    │◄──►│     (Flask + SocketIO)        │ │
│  │                      │ WS │                               │ │
│  │  • Chat UI           │    │  • WebSocket handlers         │ │
│  │  • Settings Panel    │    │  • REST API routes            │ │
│  │  • Tool Visualizer   │    │  • Tool discovery             │ │
│  │  • Audio Handler     │    │  • Config management          │ │
│  └──────────────────────┘    └───────────────────────────────┘ │
│                                        │                        │
│                                        ▼                        │
│                    ┌─────────────────────────────────┐         │
│                    │      JARVIS CORE (shared)       │         │
│                    │  • orchestrator/                │         │
│                    │  • lib/ (memory, config, etc)   │         │
│                    │  • skills/*.tool.json           │         │
│                    │  • mcp servers                  │         │
│                    └─────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📁 Folder Structure

```
jarvis-voice/
├── jarvis-web/                    # NEW - Standalone web app
│   ├── server/                    # Backend (Python)
│   │   ├── __init__.py
│   │   ├── app.py                 # Main Flask app + SocketIO
│   │   ├── config.py              # Web app config loader
│   │   ├── routes/                # REST API endpoints
│   │   │   ├── __init__.py
│   │   │   ├── api.py             # General API routes
│   │   │   ├── settings.py        # Settings CRUD
│   │   │   ├── tools.py           # Tool listing/info
│   │   │   ├── conversations.py   # Conversation history
│   │   │   └── audio.py           # TTS/STT endpoints
│   │   ├── sockets/               # WebSocket event handlers
│   │   │   ├── __init__.py
│   │   │   ├── chat.py            # Chat message handling
│   │   │   └── tools.py           # Tool execution streaming
│   │   ├── services/              # Business logic
│   │   │   ├── __init__.py
│   │   │   ├── orchestrator.py    # Wrapper around core orchestrator
│   │   │   ├── tool_discovery.py  # Load tools from skills/
│   │   │   ├── mcp_discovery.py   # Load MCP servers
│   │   │   └── settings_manager.py # Config read/write
│   │   └── models/                # Data models
│   │       ├── __init__.py
│   │       ├── conversation.py
│   │       └── message.py
│   │
│   ├── client/                    # Frontend
│   │   ├── index.html             # Main HTML
│   │   ├── css/
│   │   │   ├── main.css           # Global styles
│   │   │   ├── chat.css           # Chat component
│   │   │   ├── settings.css       # Settings panel
│   │   │   └── variables.css      # CSS custom properties
│   │   ├── js/
│   │   │   ├── app.js             # Main app initialization
│   │   │   ├── socket.js          # WebSocket connection
│   │   │   ├── chat.js            # Chat UI logic
│   │   │   ├── tools.js           # Tool visualization
│   │   │   ├── settings.js        # Settings panel
│   │   │   ├── audio.js           # TTS/STT handling
│   │   │   └── utils.js           # Helpers
│   │   └── assets/
│   │       ├── icons/
│   │       └── sounds/
│   │
│   ├── config/                    # Web app specific config
│   │   └── web_defaults.json      # Default settings
│   │
│   ├── requirements.txt           # Python deps for web app
│   └── README.md                  # Web app documentation
│
├── bin/
│   └── jarvis-web                 # Launcher script
│
└── (existing folders unchanged)
```

---

## 🔌 API Design

### REST Endpoints (for static data, settings)

```
GET  /api/status              # Health check, mode, version
GET  /api/tools               # List all available tools
GET  /api/tools/:name         # Get tool details
GET  /api/mcps                # List MCP servers
GET  /api/conversations       # List conversation history
GET  /api/conversations/:id   # Get specific conversation
POST /api/conversations       # Create new conversation

GET  /api/settings            # Get current settings (safe subset)
PUT  /api/settings            # Update settings
GET  /api/settings/schema     # Get settings schema for UI

POST /api/audio/tts           # Generate speech from text
POST /api/audio/stt           # Transcribe audio to text
```

### WebSocket Events (for real-time)

```python
# ══════════════════════════════════════════════════════════════
# CLIENT → SERVER
# ══════════════════════════════════════════════════════════════

# Send a message/command
socket.emit('chat:send', {
    'message': 'What is bitcoin price?',
    'conversation_id': 'conv_123',  # optional
    'mode': 'cloud'  # or 'local'
})

# Voice input (audio blob)
socket.emit('audio:input', {
    'audio': base64_audio_data,
    'format': 'webm'
})

# Cancel current request
socket.emit('chat:cancel', {
    'conversation_id': 'conv_123'
})

# Request tool list refresh
socket.emit('tools:refresh')

# ══════════════════════════════════════════════════════════════
# SERVER → CLIENT
# ══════════════════════════════════════════════════════════════

# Connection established
socket.on('connected', {
    'session_id': 'sess_abc',
    'mode': 'cloud',
    'tools_count': 44
})

# Processing started
socket.on('chat:thinking', {
    'conversation_id': 'conv_123',
    'message_id': 'msg_456'
})

# Tool execution started
socket.on('tool:start', {
    'tool': 'crypto_price',
    'args': {'symbol': 'BTC'},
    'message_id': 'msg_456'
})

# Tool execution progress (for long-running tools)
socket.on('tool:progress', {
    'tool': 'generate_image',
    'progress': 45,
    'status': 'Generating with Gemini...'
})

# Tool execution complete
socket.on('tool:complete', {
    'tool': 'crypto_price',
    'result': {'price': 104523, 'change': '+2.3%'},
    'duration_ms': 342,
    'success': true
})

# Tool execution failed
socket.on('tool:error', {
    'tool': 'generate_image',
    'error': 'API rate limit exceeded',
    'recoverable': true
})

# Final response
socket.on('chat:response', {
    'message_id': 'msg_456',
    'conversation_id': 'conv_123',
    'text': 'Bitcoin is currently at $104,523...',
    'speech': 'Bitcoin is at 104 thousand...',  # TTS-friendly
    'data': {...},  # Structured data
    'tools_used': ['crypto_price'],
    'has_audio': true,
    'audio_url': '/api/audio/msg_456.mp3'
})

# Streaming text (for long responses)
socket.on('chat:stream', {
    'message_id': 'msg_456',
    'delta': 'Bitcoin is ',  # Incremental text
    'done': false
})

# Tools list updated
socket.on('tools:updated', {
    'tools': [...],
    'mcps': [...]
})
```

---

## 🎨 UI Components

### Main Layout
```
┌─────────────────────────────────────────────────────────────────┐
│ ┌─────┐                                                         │
│ │ 🤖  │  JARVIS              [Cloud ▼]  [🔊]  [⚙️]  [?]        │
│ └─────┘                                                         │
├────────────┬────────────────────────────────────────────────────┤
│            │                                                    │
│  History   │            Chat Area                               │
│  ────────  │                                                    │
│  > Today   │   ┌──────────────────────────────────────────┐    │
│    Conv 1  │   │ 👤 What's the bitcoin price?             │    │
│    Conv 2  │   └──────────────────────────────────────────┘    │
│  > Yester  │                                                    │
│    Conv 3  │   ┌──────────────────────────────────────────┐    │
│            │   │ 🤖 Processing...                          │    │
│  ────────  │   │                                           │    │
│  [+ New]   │   │  ┌─ crypto_price ──────────────────────┐ │    │
│            │   │  │ ✅ BTC: $104,523 (+2.3%)            │ │    │
│            │   │  └─────────────────────────────────────┘ │    │
│            │   │                                           │    │
│            │   │ Bitcoin is currently trading at...       │    │
│            │   └──────────────────────────────────────────┘    │
│            │                                                    │
│            ├────────────────────────────────────────────────────┤
│            │ ┌────────────────────────────────────────────────┐│
│            │ │ Ask Jarvis anything...                         ││
│            │ │                                    [🎤] [➤]    ││
│            │ └────────────────────────────────────────────────┘│
└────────────┴────────────────────────────────────────────────────┘
```

### Settings Panel (Modal/Slide-out)
```
┌─────────────────────────────────────────────────────────────────┐
│  ⚙️  Settings                                            [✕]   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  General                                                        │
│  ──────────────────────────────────────────────────────────    │
│  Mode:              [Cloud ▼]                                   │
│  Owner Name:        [Boss____________]                          │
│                                                                 │
│  AI Provider                                                    │
│  ──────────────────────────────────────────────────────────    │
│  LLM Provider:      [xAI ▼]                                    │
│  Model:             [grok-4-1-fast ▼]                          │
│                                                                 │
│  Voice                                                          │
│  ──────────────────────────────────────────────────────────    │
│  TTS Enabled:       [✓]                                        │
│  TTS Provider:      [ElevenLabs ▼]                             │
│  Voice:             [Jarvis ▼]                                 │
│  Auto-play:         [✓]                                        │
│                                                                 │
│  Image Generation                                               │
│  ──────────────────────────────────────────────────────────    │
│  Provider:          [Gemini ▼]                                 │
│  Model:             [gemini-3-pro-image-preview]               │
│                                                                 │
│  Advanced                                                       │
│  ──────────────────────────────────────────────────────────    │
│  Tool Similarity:   [0.26] ─────●─────                         │
│  Memory Threshold:  [0.28] ─────●─────                         │
│                                                                 │
│                              [Reset Defaults]  [Save]           │
└─────────────────────────────────────────────────────────────────┘
```

### Tool Execution Card (Expandable)
```
┌─────────────────────────────────────────────────────────────────┐
│  🔧 generate_image                              2.3s     [▼]   │
├─────────────────────────────────────────────────────────────────┤
│  Status:    ✅ Complete                                         │
│  Provider:  gemini                                              │
│  Model:     gemini-3-pro-image-preview                         │
│  ─────────────────────────────────────────────────────────────  │
│  Arguments:                                                     │
│    prompt: "A futuristic bitcoin infographic..."               │
│    aspect_ratio: "16:9"                                        │
│    use_grounding: true                                         │
│  ─────────────────────────────────────────────────────────────  │
│  Result:                                                        │
│    [Generated Image Preview]                                   │
│    Saved to: stash://space_123/image.jpg                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔧 Core Services

### 1. Tool Discovery Service
Auto-loads tools from `skills/*.tool.json`:

```python
# services/tool_discovery.py
class ToolDiscoveryService:
    def __init__(self, skills_path: str):
        self.skills_path = skills_path
        self.tools = {}
        self.load_tools()
    
    def load_tools(self):
        """Load all tool definitions from skills folder"""
        for tool_file in Path(self.skills_path).glob('*.tool.json'):
            tool = json.load(open(tool_file))
            if tool.get('enabled', True):
                self.tools[tool['name']] = tool
    
    def get_tools(self) -> list:
        """Return all enabled tools"""
        return list(self.tools.values())
    
    def refresh(self):
        """Reload tools (after sync)"""
        self.tools = {}
        self.load_tools()
```

### 2. MCP Discovery Service
Auto-loads MCP servers from config:

```python
# services/mcp_discovery.py
class MCPDiscoveryService:
    def __init__(self):
        self.servers = {}
        self.load_servers()
    
    def load_servers(self):
        """Load MCP server configs"""
        mcp_config = get_config_value('MCP_SERVERS', '{}')
        # Parse and validate servers
        ...
    
    def get_servers(self) -> list:
        """Return configured MCP servers"""
        return list(self.servers.values())
```

### 3. Settings Manager
Read/write settings with validation:

```python
# services/settings_manager.py
class SettingsManager:
    # Settings that are safe to expose to UI
    SAFE_SETTINGS = [
        'MODE', 'OWNER_NAME', 'LLM_PROVIDER', 'LLM_MODEL',
        'TTS_PROVIDER', 'IMAGE_TOOL_PROVIDER', 'GEMINI_IMAGE_MODEL',
        'TOOL_SIMILARITY_THRESHOLD', 'SEMANTIC_SIMILARITY_THRESHOLD',
        # ... etc
    ]
    
    # Settings that should NEVER be exposed (API keys)
    SENSITIVE_PATTERNS = ['API_KEY', 'SECRET', 'TOKEN', 'PASSWORD']
    
    def get_safe_settings(self) -> dict:
        """Return settings safe for UI display"""
        settings = {}
        for key in self.SAFE_SETTINGS:
            settings[key] = get_config_value(key)
        return settings
    
    def update_setting(self, key: str, value: str) -> bool:
        """Update a setting (validates against safe list)"""
        if key not in self.SAFE_SETTINGS:
            raise ValueError(f"Cannot modify setting: {key}")
        # Update config and optionally persist to file
        ...
    
    def get_schema(self) -> dict:
        """Return settings schema for UI form generation"""
        return {
            'MODE': {'type': 'select', 'options': ['cloud', 'local']},
            'LLM_PROVIDER': {'type': 'select', 'options': ['anthropic', 'xai', 'openai']},
            # ...
        }
```

### 4. Orchestrator Wrapper
Wraps core orchestrator with streaming callbacks:

```python
# services/orchestrator.py
class WebOrchestrator:
    def __init__(self, socketio, session_id):
        self.socketio = socketio
        self.session_id = session_id
    
    async def process(self, message: str, mode: str, conversation_id: str):
        """Process message with streaming updates"""
        
        def on_tool_start(tool_name, args):
            self.socketio.emit('tool:start', {
                'tool': tool_name,
                'args': args
            }, room=self.session_id)
        
        def on_tool_complete(tool_name, result, duration):
            self.socketio.emit('tool:complete', {
                'tool': tool_name,
                'result': result,
                'duration_ms': duration,
                'success': True
            }, room=self.session_id)
        
        # Import and use core orchestrator
        from orchestrator.orchestrator_v2 import process_query
        
        result = await process_query(
            message,
            mode=mode,
            on_tool_start=on_tool_start,
            on_tool_complete=on_tool_complete
        )
        
        return result
```

---

## 🎤 Voice Features

### Browser TTS Playback
```javascript
// client/js/audio.js
class AudioHandler {
    constructor() {
        this.enabled = true;
        this.audioQueue = [];
        this.playing = false;
    }
    
    async playResponse(audioUrl) {
        if (!this.enabled) return;
        
        const audio = new Audio(audioUrl);
        await audio.play();
    }
    
    toggle() {
        this.enabled = !this.enabled;
        return this.enabled;
    }
}
```

### Browser STT (Mic Input)
```javascript
// client/js/audio.js
class MicHandler {
    constructor(socket) {
        this.socket = socket;
        this.mediaRecorder = null;
        this.recording = false;
    }
    
    async startRecording() {
        const stream = await navigator.mediaDevices.getUserMedia({ 
            audio: true 
        });
        this.mediaRecorder = new MediaRecorder(stream);
        this.chunks = [];
        
        this.mediaRecorder.ondataavailable = (e) => {
            this.chunks.push(e.data);
        };
        
        this.mediaRecorder.onstop = () => {
            const blob = new Blob(this.chunks, { type: 'audio/webm' });
            this.sendAudio(blob);
        };
        
        this.mediaRecorder.start();
        this.recording = true;
    }
    
    stopRecording() {
        if (this.mediaRecorder && this.recording) {
            this.mediaRecorder.stop();
            this.recording = false;
        }
    }
    
    async sendAudio(blob) {
        const base64 = await this.blobToBase64(blob);
        this.socket.emit('audio:input', {
            audio: base64,
            format: 'webm'
        });
    }
}
```

---

## 🔐 Security

### API Key Protection
- **Never** expose API keys to frontend
- Settings UI shows "configured" / "not configured" for sensitive values
- Separate "admin" mode for key management (optional)

### Authentication Options
1. **Simple**: Password/PIN for access
2. **Token**: API key for programmatic access
3. **None**: Local network only (default)

```python
# config/web_defaults.json
{
    "auth": {
        "enabled": false,
        "type": "password",  // "password", "token", "none"
        "password_hash": null
    },
    "network": {
        "host": "0.0.0.0",
        "port": 5001,
        "allowed_origins": ["*"]
    }
}
```

---

## 🚀 Implementation Phases

### Phase 1: Foundation (MVP)
**Goal**: Working chat interface with tool execution

- [ ] Project structure setup
- [ ] Flask + SocketIO backend
- [ ] Basic chat UI (send/receive)
- [ ] WebSocket connection
- [ ] Tool execution with streaming
- [ ] Mode selection (cloud/local)
- [ ] Tool discovery service
- [ ] Basic styling (dark theme)

### Phase 2: Polish & Features
**Goal**: Full-featured chat experience

- [ ] Conversation history (persist)
- [ ] Tool execution cards (expandable)
- [ ] Image display in chat
- [ ] Settings panel (basic)
- [ ] Error handling & retry
- [ ] Loading states & animations
- [ ] Responsive design

### Phase 3: Voice
**Goal**: Full voice I/O in browser

- [ ] TTS playback toggle
- [ ] Mic input (push-to-talk)
- [ ] Audio visualization
- [ ] Voice activity detection
- [ ] Wake word (stretch)

### Phase 4: Advanced
**Goal**: Power user features

- [ ] Full settings management
- [ ] MCP server management
- [ ] Tool enable/disable
- [ ] Conversation search
- [ ] Export/import conversations
- [ ] Mobile PWA
- [ ] Multi-user support

---

## 📦 Dependencies

### Backend (Python)
```
flask>=3.0.0
flask-socketio>=5.3.0
flask-cors>=4.0.0
python-socketio>=5.10.0
eventlet>=0.35.0  # or gevent
```

### Frontend (Vanilla JS - no build step)
- Socket.IO client (CDN)
- Marked.js for markdown (CDN)
- Highlight.js for code (CDN)
- (Optional) Alpine.js for reactivity

---

## 🎯 Success Criteria

### MVP Complete When:
1. ✅ Can send message and receive response
2. ✅ See real-time tool execution
3. ✅ Switch between cloud/local mode
4. ✅ Tools auto-discovered from skills/
5. ✅ Looks polished (not "dev prototype")

### Full Release When:
1. ✅ Voice I/O working
2. ✅ Settings configurable via UI
3. ✅ Conversation history persisted
4. ✅ Mobile responsive
5. ✅ Documentation complete

---

## 💡 Future Ideas

- **Plugins system**: Third-party UI extensions
- **Themes**: User-selectable color schemes
- **Dashboards**: Analytics, usage stats
- **Collaboration**: Share conversations
- **Integrations**: Embed in other apps

---

*Created: December 2024*  
*Last Updated: December 2024*
