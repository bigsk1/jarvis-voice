# Jarvis Web UI

A modern web-based chat interface for Jarvis with real-time tool execution streaming.

## Features

- 💬 **Chat Interface** - Send messages and receive responses in a ChatGPT-like UI
- 🔧 **Real-time Tool Streaming** - See tool execution as it happens via WebSocket
- ☁️ **Mode Switching** - Toggle between Cloud and Local mode
- 🎨 **Dark Theme** - Beautiful dark UI inspired by Canvas
- 📱 **Responsive** - Works on desktop and mobile
- ⚡ **No Build Step** - Vanilla JS, just run and go

## Quick Start

```bash
# From jarvis-voice directory
./bin/jarvis-web

# Or with options
./bin/jarvis-web local              # Use local mode
./bin/jarvis-web --port 8080        # Custom port
./bin/jarvis-web --debug            # Debug mode
```

Then open: `http://your-server-ip:5001`

## Installation

Dependencies should be installed automatically, but you can install manually:

```bash
cd jarvis-web
pip install -r requirements.txt
```

## Architecture

```
jarvis-web/
├── server/                 # Flask + SocketIO backend
│   ├── app.py             # Main application
│   ├── config.py          # Configuration loader
│   ├── routes/            # REST API endpoints
│   │   └── api.py         # /api/* routes
│   ├── sockets/           # WebSocket handlers
│   │   └── chat.py        # Chat message handling
│   └── services/          # Business logic
│       ├── tool_discovery.py
│       └── settings_manager.py
├── client/                 # Frontend (vanilla JS)
│   ├── index.html         # Main page
│   ├── css/               # Styles
│   │   ├── variables.css  # CSS custom properties
│   │   └── main.css       # Main styles
│   └── js/                # JavaScript modules
│       ├── utils.js       # Utility functions
│       ├── socket.js      # WebSocket connection
│       ├── chat.js        # Chat UI logic
│       └── app.js         # Main app
├── config/
│   └── web_config.json    # Web UI configuration
└── requirements.txt
```

## API Endpoints

### REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Health check, mode, version |
| `/api/tools` | GET | List all available tools |
| `/api/tools/:name` | GET | Get specific tool details |
| `/api/tools/refresh` | POST | Reload tools from disk |
| `/api/settings` | GET | Get current settings |
| `/api/mode` | GET/PUT | Get/set current mode |

### WebSocket Events

**Client → Server:**
- `chat:send` - Send a message
- `chat:cancel` - Cancel current processing
- `mode:set` - Change mode
- `tools:refresh` - Refresh tools list

**Server → Client:**
- `connected` - Session established
- `chat:thinking` - Processing started
- `tool:start` - Tool execution started
- `tool:complete` - Tool execution finished
- `chat:response` - Final response
- `chat:error` - Error occurred

## Configuration

Edit `config/web_config.json`:

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

## Security Notes

- **Local Network**: By default, binds to all interfaces (`0.0.0.0`)
- **No Auth**: Authentication is disabled by default (planned for future)
- **API Keys**: Never exposed to the frontend; shown as "configured/not configured"

## Future Enhancements

- [ ] Authentication (password/token)
- [ ] Conversation history persistence
- [ ] Voice input (browser microphone)
- [ ] TTS playback in browser
- [ ] Full settings editor
- [ ] File upload support
- [ ] Mobile PWA

## Troubleshooting

### Port in use
```bash
./bin/jarvis-web --port 5002
```

### Can't connect from other devices
Make sure firewall allows the port:
```bash
sudo ufw allow 5001
```

### WebSocket connection fails
Check that you're accessing via the correct IP (not localhost if remote).

