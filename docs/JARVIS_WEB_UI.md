# Jarvis Web UI

> **Status**: Implemented and actively maintained
> **Last Updated**: July 11, 2026

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
- Dashboard TUI (`bin/jarvis-dashboard`) - Terminal control surface
- **Web UI (`jarvis-web`)** - Full-featured chat interface ✅

![jarvis-web](images/jarvis-web.jpg)

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
| Status updates | ✅ | Non-blocking deadline/fallback stream to browser, not local speaker |
| Duplicate-call recovery status | ✅ | Blocked duplicate tool attempts surface as red status text, not fake failed tool cards |

### Phase 3: Voice - COMPLETE ✅

| Feature | Status | Details |
|---------|--------|---------|
| TTS playback | ✅ | Toggle audio, plays responses in browser |
| Mode-aware TTS | ✅ | Cloud=ElevenLabs, Local=Kokoro or Qwen3-TTS via provider-specific URL settings |
| Status TTS | ✅ | Cached, cancellable status speech when enabled; final audio has priority |
| **Push-to-talk STT** | ✅ | Click mic → speak → click again → transcribe → send |
| **Mode-aware STT** | ✅ | Cloud=OpenAI, Local=faster-whisper; compatible endpoint opt-in in either mode |
| **Audio playback controls** | ✅ | Speaker button with pause/resume/stop, progress animation  |
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
| Dynamic media provider | ✅ | Switch image, video, and music providers on-the-fly |
| Response style overrides | ✅ | Per-mode overrides for response style, Q&A word limit, and multi-turn word limit |
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
| **🔄 File Conversion** | ✅ | Convert images/video/audio between formats |
| **Convert modal** | ✅ | Format selector with preview, descriptions, and advanced options |
| **Advanced convert options** | ✅ | Resize, quality, bitrate, FPS, etc. per format type |
| **Inline converted media** | ✅ | Shows image/video/audio with download button |
| Tool enable/disable | ⏳ | Planned (per-tool granular control) |

### Phase 5: Input Enhancement - COMPLETE ✅

| Feature | Status | Details |
|---------|--------|---------|
| **Slash commands** | ✅ | `/canvas`, `/search`, `/recall`, etc. - modify behavior |
| **@prompts** | ✅ | `@research`, `@quick`, `@compare` - inject methodologies |
| **#tool hints** | ✅ | `#weather`, `#youtube_transcript`, etc. - softly prefer one or more tools |
| **Command autocomplete** | ✅ | Type `/`, `@`, or standalone `#` to see suggestions |
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
| **Pinned-safe cleanup** | ✅ | `cleanup-all` removes unpinned chats older than 90 days; pinned chats are preserved |

### Phase 7: Developer Tools - COMPLETE ✅

| Feature | Status | Details |
|---------|--------|---------|
| **Server Logs Panel** | ✅ | Real-time log streaming at bottom of UI  |
| **LLM call logs** | ✅ | Model, tokens, cost, duration, tool called  |
| **Tool call logs** | ✅ | Tool name, duration, success/error, result preview  |
| **Source toggles** | ✅ | Enable/disable LLM, Tools, OpenCode, Feedback  |
| **Expandable details** | ✅ | Click entry to see full parsed JSON  |
| **Resizable panel** | ✅ | Drag to resize, state persisted  |
| **`/logs` browser** | ✅ | Read-only log explorer for `.jsonl`, `.log`, and `.md` with search, lazy loading, and mobile drill-down |

### Phase 8: Manual Feedback - COMPLETE ✅

| Feature | Status | Details |
|---------|--------|---------|
| **Feedback toggle** | ✅ | 📊 button to enable LLM feedback analysis |
| **`--feedback` inline** | ✅ | Type `--feedback` in message to trigger |
| **Feedback card** | ✅ | Purple tool card shows rating, summary, issues |
| **Feedback gating** | ✅ | Explicit Web feedback waits for Completion Guard settlement before grading |
| **Random feedback coordination** | ✅ | Orchestrator random feedback can emit cards normally, but is disabled while Web Completion Guard is active |
| **Expand/collapse** | ✅ | Click header to toggle details |
| **Toast notification** | ✅ | 6-second toast with rating summary |
| **Always logged** | ✅ | Manual feedback always saved to logs |

### Phase 9: Completion Guard - COMPLETE ✅

| Feature | Status | Details |
|---------|--------|---------|
| **Completion Guard card** | ✅ | Inline `Completed correctly?` card on assistant responses |
| **Manual prompt countdown** | ✅ | Active manual cards show a small countdown and default to 10 minutes |
| **Stale prompt settlement** | ✅ | Expired cards settle as `expired`; older unanswered cards settle as `superseded` when the conversation continues |
| **Manual repair pass** | ✅ | Clicking `No` runs one bounded repair pass |
| **Repair status updates** | ✅ | Repair emits normal Jarvis thinking/status/tool events |
| **Repair tickets** | ✅ | Unresolved failures write markdown tickets to `logs/completion-guard/` |
| **Tool-aware exclusions** | ✅ | Skips workflows and fire-and-forget/sensitive tools |
| **Conversation export metadata** | ✅ | Markdown export includes Completion Guard status/note/ticket data when present |
| **Prompt/runtime repair context** | ✅ | Repair uses original query, raw LLM response, tool outputs, and user note |
| **Auto mode evaluator** | ✅ | Background evaluator can auto-trigger repair using the raw final answer |
| **`tighten_only` outcome** | ✅ | After a **repair** pass, wording-only settlement without a second assistant message; judge JSON `tighten_only` (no repair) settles as `auto_accepted` |
| **Visible repair delta-gating** | ✅ | Separate repaired answers now require a real evidence or tool-path delta |
| **Repair cancel support** | ✅ | Stop button now cleanly cancels an in-flight repair pass |
| **Auto threshold override** | ✅ | AI Config exposes per-mode threshold override for auto mode |
| **Accepted state persistence** | ✅ | Clicking `Yes` now persists to conversation history and exports |
| **Intelligence bridge** | ✅ | Accepted/repaired/ticketed/cancelled outcomes feed back into reflection data; expired/superseded settle neutrally |
| **Corrected-path learning** | ✅ | Repaired answers, tools, and tool results are folded back into the original experience for reflections |
| **Feedback-aware settlement** | ✅ | Final web feedback runs on the settled Completion Guard outcome and includes CG metadata in grading |
| **Provider-split auto evaluator** | ✅ | Auto eval can run on a different provider/model than the main chat response |
| **Eval provider/model overrides** | ✅ | AI Config exposes per-mode Completion Guard eval provider/model controls |
| **Ollama cloud judge support** | ✅ | Cloud Ollama eval uses cloud-only model lists and defensive JSON parsing/budgeting for auto eval |

### Tool Cards, Status, and Reload Behavior

- `tool:start`, `tool:complete`, and `tool:error` drive the live tool cards shown during a request.
- Real tool failures show a red tool card because the tool actually executed and returned an error.
- Duplicate-guard blocks are different: the repeated tool call is stopped before execution, so the UI shows a red status/progress message instead of a failed tool card.
- Routing status text can include turn-aware messages like `Turn 3: using serpapi_search...`, which follow the orchestrator's `MAX_TOOL_TURNS` loop.
- Tool cards rendered after a page reload are rebuilt from the saved conversation message, not from the original live WebSocket event stream.
- Because of that, historical reload is best at restoring successful tool outcomes. Live-only per-call events such as intermediate failures or duplicate-guard status lines are not guaranteed to reappear unless they were explicitly persisted in the saved message data.

### Large Tool Result Context

- The orchestrator may truncate large prior tool payloads before sending them back to the LLM on later turns.
- Jarvis now marks these previews with explicit metadata such as `result_truncated`, `result_chars_shown`, and `result_chars_total`.
- When truncation is needed, later routing turns now receive a valid JSON `Result Preview:` block instead of a raw sliced JSON fragment.
- When the full prior result fits in budget, the turn context still shows `Result:` with the full serialized payload.
- `ok=true` still means the tool succeeded even if the LLM only sees a preview of the payload in later turns.
- This helps reduce redundant rereads of large transcript- or stash-based results during multi-turn recovery.

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
├── server/                         # Flask + SocketIO (threading + WebSocket)
│   ├── app.py                      # App entry; serves /, /logs, /login, /stash/view/...
│   ├── config.py                   # Loads cloud.env / local.env + web_config
│   ├── routes/
│   │   ├── api.py                  # REST: tools, settings, conversations, media, workflows, prompts, logs
│   │   └── auth.py                 # Optional auth (/api/auth/login, /api/auth/status, …)
│   ├── sockets/
│   │   └── chat.py                 # WebSocket: chat stream, tools, completion guard, log tail, proactive
│   └── services/
│       ├── tool_discovery.py       # Enabled tools from skills/ + MCP + profiles
│       ├── settings_manager.py     # Web overrides (mode, models, blocked tools)
│       ├── conversation_store.py   # Chat persistence → ../data/web_conversations/
│       ├── log_explorer.py         # /logs folder listing, search, file content
│       ├── log_streamer.py         # Live log tail to connected clients
│       ├── proactive_service.py    # Proactive alerts / reminders over WebSocket
│       ├── completion_guard.py     # Post-turn quality check and bounded repair
│       └── followup_extractor.py   # Follow-up ticket extraction from guard feedback
│
├── client/
│   ├── index.html                  # Main chat UI
│   ├── login.html                  # Optional login gate
│   ├── logs.html                   # Dedicated /logs log viewer
│   ├── stash-viewer.html           # Render stash text/markdown at /stash/view/<space>/<file>
│   ├── css/
│   │   ├── variables.css           # Theme tokens
│   │   ├── main.css                # Chat UI
│   │   ├── glow-refinements.css    # Holographic effects
│   │   ├── log-viewer.css          # /logs page
│   │   └── fonts.css               # @font-face for self-hosted fonts
│   ├── js/
│   │   ├── app.js                  # Shell, settings, navigation
│   │   ├── chat.js                 # Messages, tools, uploads, workflows
│   │   ├── socket.js               # WebSocket client
│   │   ├── logs.js                 # In-app server log panel
│   │   ├── log-viewer.js           # /logs folder + file viewer
│   │   ├── proactive.js            # Proactive notification UI
│   │   └── utils.js                # Shared helpers
│   ├── fonts/                      # Self-hosted Inter + JetBrains Mono (woff2)
│   └── vendor/                     # Bundled socket.io + marked (CDN fallback in HTML)
│
├── config/
│   ├── web_config.json             # Web-specific overrides (copy from example)
│   └── web_config.json.example
│
├── data/                           # Web-local assets (not conversation history)
│   ├── prompts/                    # Shared @prompt templates (*.md)
│   │   └── personal/               # Git-ignored personal prompts + tracked README
│   └── uploads/                    # Chat image uploads for vision
│
├── requirements.txt
└── README.md

Repo root (shared with core Jarvis — outside jarvis-web/):
├── data/web_conversations/         # Saved chats (index.json + <id>.json)
└── data/workflows/                 # Slash-command workflow definitions (*.json)
```

### Conversation Retention

`data/web_conversations/` is maintained by `./bin/cleanup-web-conversations`, normally through the cron-friendly `./bin/cleanup-all` wrapper.

- Default retention is 90 days for unpinned Web UI conversations.
- Pinned conversations are preserved regardless of age.
- Cleanup uses the saved conversation timestamp, preferring `updated_at` and falling back to `created_at` if needed.
- Preview with `./bin/cleanup-web-conversations --dry-run` before a live run.

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
| POST | `/api/settings/reset` | Reset the explicitly selected mode to its env defaults (`{"mode":"cloud"}` or `{"mode":"local"}`) |
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
| GET | `/api/conversations/<id>/export?format=` | Export conversation (json/markdown, includes Completion Guard metadata when available) |
| POST | `/api/conversations/import` | Import conversation from JSON file |
| POST | `/api/stash/upload` | Upload file to stash (for conversion) |
| GET | `/api/stash/<space_id>/<file_id>` | Serve file from stash |
| GET | `/api/music/<filename>` | Serve generated music files |
| GET | `/api/videos/<filename>` | Serve generated video files |
| GET | `/api/logs/folders` | List folders containing `.jsonl`, `.log`, or `.md` |
| GET | `/api/logs/files` | List files in a folder, newest-first, with optional search |
| GET | `/api/logs/content` | Fetch paged content for the selected log file |

### WebSocket Events

#### Client → Server

```javascript
// Send chat message
socket.emit('chat:send', {
    message: 'What is bitcoin price?',
    conversation_id: 'conv_123',
    mode: 'cloud'
});

// After creating a conversation (client/REST), the server emits conversation:created.
// Load an existing conversation:
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
// Session connected (server emits `connected`, not session:ready)
socket.on('connected', {
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

// Feedback analysis started
socket.on('feedback:start', {
    message_id: 'msg_456',
    conversation_id: 'conv_123',
    status: 'analyzing'
});

// Feedback analysis complete
socket.on('feedback:complete', {
    message_id: 'msg_456',
    conversation_id: 'conv_123',
    rating: 5,
    summary: 'Task completed efficiently',
    positive: 'Correct tool selection',
    issues: [],
    tool_ratings: { get_time: { rating: 5, note: 'Worked correctly' } },
    duration_ms: 3200,
    success: true
});
```

---

## ⚙️ Configuration

### Two Config Worlds

| Config | Source | Affects | Editable |
|--------|--------|---------|----------|
| Core Settings | `cloud.env` / `local.env` | Terminal/TUI/Web | ❌ Restart required |
| Web Overrides | `web_config.json` | Web only | ✅ On-the-fly |

**Overridable Settings (per-mode):**

| Setting | Dropdown | Options |
|---------|----------|---------|
| LLM Provider | AI Config → LLM Provider | xAI, Anthropic, OpenAI, Ollama |
| LLM Model | AI Config → Model | Dynamic per provider |
| Image Provider | AI Config → Image Provider | xAI Grok, Google Gemini, OpenAI DALL-E |
| Video Provider | AI Config → Video Provider | xAI Grok, Google Gemini Veo |
| Music Provider | AI Config → Music Provider | ElevenLabs Music, Google Gemini Lyria |

**Credential-aware provider availability:** dropdown options for providers
whose API key is missing/blank in the active mode's env file are annotated
(e.g. `Anthropic — ANTHROPIC_API_KEY not configured in cloud.env`) and cannot
be newly selected. The server also validates saves: choosing an unconfigured
provider returns HTTP 400 with `{field, provider, reason}` and nothing is
persisted, while unrelated settings still save normally. Ollama in cloud mode
is reported as `unknown` until the live Ollama Cloud sign-in check runs. Key
*values* are never sent to the client — only configured/missing status.

The System tab's read-only **Features** section shows the active mode's startup
`IMAGE_TOOL_PROVIDER`, `VIDEO_TOOL_PROVIDER`, and `MUSIC_TOOL_PROVIDER` env
values. AI Config separately shows whether a per-mode Web override is active.

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
    "router_prompt_version": null,
    "image_provider": null,  // null = use cloud.env IMAGE_TOOL_PROVIDER
    "video_provider": null,  // null = use cloud.env VIDEO_TOOL_PROVIDER
    "music_provider": null,  // null = use cloud.env MUSIC_TOOL_PROVIDER
    "tts_provider": null,
    "response_style": null,
    "tool_rag_limit": null,
    "qa_word_limit": null,
    "multi_turn_word_limit": null
  },
  "local": {
    "llm_provider": null,    // null = use local.env default (ollama)
    "llm_model": null,       // null = use local.env model
    "router_prompt_version": null,
    "image_provider": null,  // null = use local.env IMAGE_TOOL_PROVIDER
    "video_provider": null,  // null = use local.env VIDEO_TOOL_PROVIDER
    "music_provider": null,  // null = use local.env MUSIC_TOOL_PROVIDER
    "tts_provider": null,
    "response_style": null,
    "tool_rag_limit": null,
    "qa_word_limit": null,
    "multi_turn_word_limit": null
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

### Request Scopes and `JARVIS_OVERRIDE_` Child Exports

Web UI settings for image/video providers live in a request-local config scope.
When Jarvis launches a child tool, the scoped values are exported to that
child with a `JARVIS_OVERRIDE_` prefix so the tool can safely reload its env
file without losing the request choice.

**The Problem:**
Child tool scripts (for example `generate_image.py`) call `load_config()` in
their own process. An ordinary unprefixed provider value would be replaced by
the selected env file during that reload, so scoped values need an
authoritative child-export form.

**The Solution:**
```
chat.py scope:    IMAGE_TOOL_PROVIDER=gemini
                  VIDEO_TOOL_PROVIDER=gemini
                  MUSIC_TOOL_PROVIDER=gemini
        ↓
executor.py:      export_config_environment() builds child-only env
                  JARVIS_OVERRIDE_IMAGE_TOOL_PROVIDER=gemini
                  JARVIS_OVERRIDE_VIDEO_TOOL_PROVIDER=gemini
                  JARVIS_OVERRIDE_MUSIC_TOOL_PROVIDER=gemini
        ↓
tool main():      load_config() → skips IMAGE_TOOL_PROVIDER because
                  JARVIS_OVERRIDE_IMAGE_TOOL_PROVIDER exists
        ↓
tool reads:       get_config_value('IMAGE_TOOL_PROVIDER')
                  → checks JARVIS_OVERRIDE_ prefix first → returns 'gemini'
```

**Key Files:**
- `lib/config_loader.py` — owns request-local `config_scope()` and exports scoped values as `JARVIS_OVERRIDE_{key}` only for child processes
- `jarvis-web/server/sockets/chat.py` — builds per-request override values from `web_config.json` without mutating the Web process environment

**Supported Overrides:**

| Setting | Env Var | Override Var | Options |
|---------|---------|-------------|---------|
| Router Prompt Version | `JARVIS_ROUTER_PROMPT_VERSION` | `JARVIS_OVERRIDE_JARVIS_ROUTER_PROMPT_VERSION` | v1, v2, … |
| Image Provider | `IMAGE_TOOL_PROVIDER` | `JARVIS_OVERRIDE_IMAGE_TOOL_PROVIDER` | xai, gemini, openai |
| Video Provider | `VIDEO_TOOL_PROVIDER` | `JARVIS_OVERRIDE_VIDEO_TOOL_PROVIDER` | xai, gemini |
| Music Provider | `MUSIC_TOOL_PROVIDER` | `JARVIS_OVERRIDE_MUSIC_TOOL_PROVIDER` | elevenlabs, gemini |
| TTS Provider | `TTS_PROVIDER` | `JARVIS_OVERRIDE_TTS_PROVIDER` | cloud: openai, elevenlabs, xai, qwen3-tts; local: kokoro, qwen3-tts |
| Response Style | `JARVIS_RESPONSE_STYLE` | `JARVIS_OVERRIDE_JARVIS_RESPONSE_STYLE` | auto, casual, detailed |
| QA Word Limit | `JARVIS_QA_WORD_LIMIT` | `JARVIS_OVERRIDE_JARVIS_QA_WORD_LIMIT` | integer |
| Multi-Turn Word Limit | `JARVIS_MULTI_TURN_WORD_LIMIT` | `JARVIS_OVERRIDE_JARVIS_MULTI_TURN_WORD_LIMIT` | integer |
| Tool RAG Limit | `CLOUD_TOOL_RAG_LIMIT` / `LOCAL_TOOL_RAG_LIMIT` | `JARVIS_OVERRIDE_CLOUD_TOOL_RAG_LIMIT` / `JARVIS_OVERRIDE_LOCAL_TOOL_RAG_LIMIT` | integer |

**Adding New Overrides:**
1. Add the setting-to-config-key mapping to the scoped override builder in `chat.py`.
2. Read it through `get_config_value()` in-process; child tools receive the exported `JARVIS_OVERRIDE_{KEY}` automatically.

### Blocked Tools

Web-specific tool blocking is read for each chat request and does not affect
terminal/voice or scheduled-task execution:

```bash
# View blocked tools
curl http://localhost:5001/api/settings/blocked-tools

# Update blocked tools
curl -X PUT http://localhost:5001/api/settings/blocked-tools \
  -H "Content-Type: application/json" \
  -d '{"blocked": ["get_recent_conversations", "some_tool"]}'
```

The Web block list is the last gate after manifest enablement, active profile,
and mode/config availability. Blocked names are removed from Tool RAG and passed
to `ToolExecutor`, so the LLM cannot bypass the UI by naming a blocked tool
directly.

Blocking `workflow` disables autonomous `workflow(search|describe|run)` calls
from Web chat. It does not currently disable explicit `/workflow-name` commands
or scheduled workflows, which are independent entry points. To hide/block a
specific workflow in Web slash suggestions and execution, block or disable any
component tool used by that workflow; workflow admission is strict and the
entire recipe becomes unavailable.

Tool, prompt, and workflow discovery APIs accept the currently selected
cloud/local mode. Their lists combine that mode's effective profile and
availability with the Web block list, so switching the browser selection does
not keep showing the startup mode's catalog.

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
- **AI Config Tab**: LLM provider/model dropdowns (per-mode), Image provider, Video provider, Music provider, History limit, Reset button
- **Tools Tab**: Blocked tools list, add/remove UI, blocked/MCP visual indicators
- **System Tab**: Mode-specific .env values (thresholds, TTS settings, features) - shows cloud.env OR local.env
- **API Keys Tab**: Status indicators (configured/missing)

---

## 🚀 Running

### Start Server

```bash
# From project root
./bin/jarvis-web

# The launcher also accepts an explicit startup mode
./bin/jarvis-web local
```

### Access
- **Local**: http://localhost:5001
- **Network**: http://YOUR_IP:5001

---

## 🔍 Key Implementation Details

### Status Updates

Status updates route to the browser instead of the server's local speaker:

```python
# In orchestrator_v2.py
orchestrator.set_status_callback(callback)

# Callback emits via WebSocket
def status_callback(message):
    socketio.emit('chat:status', {'status': message})
```

Status generation does not block the tool. The orchestrator starts execution
immediately while the optional Status LLM races a short deadline; fast tools may
finish during the debounce and emit no phrase. Tool cards use the separate
`tool:*` event stream and can appear before a dynamic phrase.

When browser audio is enabled, status speech calls `/api/tts` with
`purpose=status`. Those responses use a persistent status-only cache. Final
responses, errors, cancellation, and mode changes abort pending status TTS and
stop status playback so progress audio cannot interrupt the answer. See
[`STATUS_UPDATES.md`](STATUS_UPDATES.md).

For ElevenLabs, `ELEVENLABS_STATUS_TTS_MODEL` can select a faster status-only
model without changing the final-answer model or `ELEVENLABS_TTS_VOICE`.

### Conversation Context

Web conversations use a **completely separate** context system from CLI/TUI:

```python
# Last 20 messages from web conversation JSON file
result = orchestrator.process(
    message,
    conversation_history=history,  # Web's own history from JSON
    excluded_tools=blocked_tools   # Web-blocked tools
)
```

**⚠️ IMPORTANT: Web UI context is NOT the same as AUTO_CONTEXT_* settings!**

| Setting | Used By | Config |
|---------|---------|--------|
| `AUTO_CONTEXT_WINDOW` / `AUTO_CONTEXT_MINUTES` | CLI/TUI only | `config/cloud.env` |
| `conversation.history_limit` | Web UI only | `jarvis-web/config/web_config.json` |

The orchestrator checks: if `conversation_history` is passed (web UI always passes it), use that. Otherwise fall back to `AUTO_CONTEXT_*` settings (CLI/TUI).

**What's included in web context (per message):**
- `role`: user or assistant
- `content`: the message text
- `tools_used`: array of tool names used (for assistant messages)
- `tool_results`: extracted follow-up data (stash refs, IDs, providers) for actionable tools

For an autonomous or explicit workflow response, Web keeps the nested
step-by-step result and also creates compact component projections using the
normal per-tool follow-up adapters. Repeated component tools remain lists of
runs/candidates. This preserves Canvas page ids, Stash refs, source URLs, and
bounded summaries so a later turn can update an artifact or call an individual
tool without rerunning the recipe.

Generated-music follow-up data keeps the provider, model, title, duration and
format metadata, plus the durable Stash/file references. ElevenLabs and Gemini
therefore use the same compact follow-up contract, and a later Send to Canvas
turn can carry the saved audio reference into a Canvas page.

This means the LLM sees previous messages like:
```
User: whats the current price of bitcoin?
Jarvis [tools: crypto_price]: Bitcoin is currently $70,741...
User: download a youtube transcript for <url>
Jarvis [tools: youtube_transcript]: Downloaded transcript for "How AI Works"
  └─ youtube_transcript data: video_title=How AI Works, md_stash_ref=stash://space_xxx/f_zzz
User: summarize that transcript
```

The `[tools: ...]` tag helps the LLM understand what tools were used. The `└─ data:` lines give the LLM actionable references (stash refs, IDs, providers) so follow-up requests like "email that", "edit that video", or "cancel that reminder" work across separate LLM API calls.

**Follow-up data extraction** is defined in
`jarvis-web/server/services/followup_extractor.py`. It builds a compact,
strict-JSON projection rather than replaying the raw tool payload. A bounded
default preserves safe scalar handles and candidate lists for conventional
results; dedicated adapters retain nested artifacts, source excerpts, and
tool-specific state where later turns need them. Meaningful `false` and `0`
values survive, while empty values may be omitted. Intentional text truncation
is labeled `truncated for follow-up context`, and structural compaction uses
`_followup_truncated` metadata instead of sliced JSON.

When adding or changing a tool, add its representative payload to
`tests/test_followup_tool_coverage.py`, then add a `FOLLOWUP_FIELDS` entry or
dedicated adapter if the default projection is not sufficient.
`jarvis-web/server/sockets/chat.py` keeps small compatibility delegates for
older tests and call sites. See the "New Tool Checklist" in
`docs/TOOL_CALLING_SYSTEM.md`.

See `docs/AUTO_CONTEXT_SYSTEM.md` for full details on CLI/TUI context.

### TTS Generation (Mode-Aware)

TTS provider is determined by the current mode's `.env` file:

| Mode | Provider | Config |
|------|----------|--------|
| **Cloud** | ElevenLabs, xAI, or OpenAI | `TTS_PROVIDER=elevenlabs`, `xai`, or `openai` in cloud.env |
| **Local** | Kokoro or Qwen3-TTS | `TTS_PROVIDER=kokoro` + `KOKORO_TTS_URL`, or `TTS_PROVIDER=qwen3-tts` + `QWEN3_TTS_URL`, in local.env |

```python
# In api.py - mode-aware TTS
@api_bp.route('/tts', methods=['POST'])
def text_to_speech():
    mode = request.json.get('mode')  # Client sends current mode
    load_jarvis_config(mode)

    provider = get_jarvis_setting('TTS_PROVIDER')
    if provider == 'kokoro':
        # Local Kokoro: call KOKORO_TTS_URL directly (OpenAI-compatible)
        return call_kokoro_tts(text)
    elif provider == 'qwen3-tts':
        # Local Qwen3-TTS: call QWEN3_TTS_URL directly (OpenAI-compatible)
        return call_qwen3_tts(text)
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

See [Speech-to-Text](SPEECH_TO_TEXT.md) for complete provider configuration,
self-hosted Parakeet setup, fallback behavior, and non-browser microphone paths.

| Mode | Provider | Config |
|------|----------|--------|
| **Cloud** | OpenAI Whisper | `STT_PROVIDER=openai` + `STT_MODEL` in cloud.env |
| **Local** | faster-whisper | `STT_PROVIDER=faster-whisper` in local.env |
| **Either (opt-in)** | OpenAI-compatible endpoint | `STT_PROVIDER=openai-compatible` + `STT_BASE_URL`, `STT_API_KEY`, and `STT_MODEL` |

The compatible endpoint has its own URL and credential. It does not reuse
`OPENAI_API_KEY` and may point to a fully local server such as Parakeet on a LAN
GPU host. `STT_BASE_URL` accepts the server root, its `/v1` base, or the full
`/v1/audio/transcriptions` URL.

STT is a hard failure by default. Set `STT_FALLBACK_PROVIDER` to a different
provider to opt into fallback. Fallback is attempted only for connection
failures, timeouts, HTTP 408/425/429, or upstream 5xx responses. Authentication,
model, endpoint/configuration errors, and an empty/silent transcript do not
fall back. `STT_FALLBACK_MODEL` optionally selects the fallback model; otherwise
the fallback provider's default is used. For cloud mode, `faster-whisper` is the
safest fallback because it adds no network egress or API billing.

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
    return transcribe_configured(audio_path, mode, provider)
```

### Image Upload & Vision Analysis (Built-in, NOT a tool)

The web UI has **native image upload** - this is NOT a tool call, it's built directly into the chat. Analyze mode supports multiple images in one message: up to 6 images in cloud mode and 2 images in local mode. Image-to-image and image-to-video still use the first uploaded image as the reference image.

**How to Upload:**
1. **Click** the 🖼️ button next to input
2. **Drag-drop** one or more images onto the chat
3. **Paste** images from clipboard (Ctrl+V)

**What Happens:**
1. Each upload is resized/compressed before storage when needed
2. Images are saved to `jarvis-web/data/uploads/`
3. The socket message sends lightweight upload metadata (`url`, `filename`); the server reloads image bytes from disk for analysis
4. Vision model analyzes the image set (mode-aware)
5. For simple questions ("what is this?") → returns analysis directly
6. For complex requests ("save to canvas") → passes analysis to orchestrator

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
- Saved in conversation history with `image_urls` plus first-image `image_url` compatibility
- Thumbnails display when you reload the conversation
- Vision analysis stored in `data.vision_analysis` for expand details

**Auto-Stash:**
- After vision analysis, uploaded images are automatically stashed to `data/stash/`
- A `stash_artifact` entry is created in `memory_db` with:
  - `source="web_upload"`
  - `metadata` (stash_ref, file_id, tags, vision_analysis snippet)
- This enables cross-tool workflows: "Email the image I uploaded earlier"
- Multi-image uploads store `uploaded_images[]` follow-up metadata so requests like "look at the second image again" can map to the exact stash reference
- Multi-image stash artifacts also get searchable labels/tags such as `multi_image_upload`, `batch_vision_analysis`, and `image_2_of_4`
- Stash has 7-day TTL, but memory entry persists for recall

---

### generate_music Tool (NEW)

ElevenLabs music generation integrated into Jarvis with automatic stash storage and web UI playback:

See the canonical [`generate_music` tool guide](tools/generate-music-tool/README.md)
for the current provider, storage, Audio Gallery, and FastAPI boundaries.

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
- `instrumental` (optional): Whether vocals should be excluded (default: false)
- `duration_seconds` (optional): 3-600 seconds (default: 60)

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
"Compare these images https://example.com/before.png and https://example.com/after.png"
"What's in stash://space_20251218_094432/f_abc123?"
"Analyze ~/photos/vacation.jpg and tell me where it was taken"
```

**When to Use:**
- Web UI image upload: Built-in vision (NOT this tool)
- Analyze URL/file/stash via voice/CLI: Use this tool

---

### 🔄 File Conversion (NEW)

A dedicated **🔄 button** in the input bar for converting files between formats. This bypasses vision analysis and goes directly to the `convert_file` tool.

**How to Use:**
1. Click the **🔄 button** (next to 🖼️ attach)
2. Select any media file (image, video, or audio)
3. Modal opens with file preview and format selector
4. Choose target format from dropdown
5. Click "Convert"

**Why Use the 🔄 Button (vs 🖼️)?**

| Button | Behavior |
|--------|----------|
| **🖼️ Attach** | Triggers vision analysis first → may say "can't convert" → then convert |
| **🔄 Convert** | Uploads to stash directly → calls `convert_file` → no vision confusion |

**Supported Formats:**

| Category | Formats |
|----------|---------|
| **Images** | PNG, JPG, WebP, GIF, SVG, BMP, ICO, TIFF |
| **Video** | MP4, WebM, MOV, AVI, MKV |
| **Audio** | MP3, WAV, FLAC, OGG, AAC, M4A |
| **Extract** | Extract audio from video → MP3/WAV |

**Conversion Modal Features:**
- **File preview**: Image thumbnail, video preview, or audio player
- **Format dropdown**: Grouped by type (Image/Video/Audio/Extract)
- **Format descriptions**: Explains each format (lossless, compressed, etc.)
- **Smart pre-selection**: Suggests complementary format based on source
- **Advanced options** (collapsible): Fine-tune conversion parameters

**Advanced Options by Format Type:**

| Target Type | Options Available |
|-------------|-------------------|
| **Images** | Resize (e.g., "800x600" or "50%"), Quality (1-100), Strip EXIF metadata, Convert to grayscale |
| **SVG** | Threshold (black/white cutoff), Speckle size (suppress small artifacts) |
| **Video** | Resolution, CRF quality (0-51, lower=better), Frame rate (FPS), Max duration (trim) |
| **Audio** | Bitrate (128k-320k), Sample rate (44.1kHz-96kHz), Channels (mono/stereo) |

**Output Display:**
- **Images**: Inline thumbnail with lightbox + ⬇️ Download button
- **Video**: Video player with controls + ⬇️ Download button
- **Audio**: Audio player with controls + ⬇️ Download button
- **Other**: Download card with file info

**Technical Flow:**
```
🔄 button → File picker → Modal (preview + format)
     ↓
POST /api/stash/upload (bypasses vision)
     ↓
Message: "Convert stash://xxx to PNG using convert_file tool"
     ↓
Orchestrator → convert_file tool → ImageMagick/FFmpeg/Potrace
     ↓
Result displayed inline with download button
```

**Local Processing:**
- Uses ImageMagick for image conversions
- Uses Potrace for raster→SVG (best for logos, line art)
- Uses FFmpeg for video/audio conversions
- No external APIs - all processing on your server

**Documentation:** See `docs/tools/convert-file-tool/README.md` for full details.

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

---

## 🚀 Web-Unique Features to Leverage

### Canvas Integration

| Feature | Status | Description |
|---------|--------|-------------|
| **Canvas header icon** | ✅ Done | 📄 button opens Canvas in new tab |
| **`/canvas` command** | ✅ Done | Type `/canvas query` to research + save to Canvas |
| **Send to Canvas button** | ✅ Done | Second icon in the consolidated latest-response action rail; creates a Canvas page from that response and its supporting conversation context |
| **Inline Canvas preview** | ✅ Done | Show a compact clickable page thumbnail and direct Canvas link after successful page creation |

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
| `@generate_music` | ElevenLabs music generation best practices  |
| `@email` | Professional email composition with send_email tool format  |
| `@daily` | Daily briefing (time, weather, reminders, crypto prices)  |

**Context-First Injection (v2.0):**
Prompts are injected **BEFORE** the user's message to provide context first:
```
[System instruction from @prompt]
---
[User's actual message/task]
```
This ensures the LLM understands the methodology before seeing the task.

This: Uses research methodology → Gathers comprehensive info → Saves to Canvas

#### Shared and personal prompt files

- Shared prompts live in `jarvis-web/data/prompts/*.md` and are committed with the repository.
- Personal prompts live in `jarvis-web/data/prompts/personal/*.md`, are ignored by Git, and can contain machine-specific instructions.
- A personal prompt overrides a shared prompt with the same filename.
- `jarvis-web/data/prompts/personal/README.md` is tracked documentation and is never loaded as `@readme`.
- The Markdown filename is the command name: `personal/social_clip.md` is invoked as `@social_clip your topic`.

A basic personal prompt is just Markdown:

```markdown
# My Prompt

Apply these reusable instructions to the user's request below.
```

Tool-specific prompts can declare an automatic tool hint in YAML frontmatter:

```markdown
---
tool_hints:
  - create_social_clip
---

# Social Clip

Create the requested social clip and call `create_social_clip`.
```

When `tool_hints` contains exactly one tool, that tool is treated as a prerequisite for listing the prompt. If the tool is absent, disabled by the active profile, unavailable because required configuration is missing, or blocked in Jarvis Web, the prompt does not appear in `@` autocomplete or the prompt API. The hint itself remains a strong routing preference rather than a forced tool call.

Leave `tool_hints` out of general prompts and prompts that can use several tools or native provider capabilities. This prevents an optional tool from unnecessarily hiding a useful prompt.

Prompt and tool badges are saved as message metadata (`prompt` and `tool_hints`) and reconstructed when conversation history reloads. The badge shows the selectors while the user-message bubble shows only the clean task text.

See `jarvis-web/data/prompts/personal/README.md` for the short authoring guide.

---

### #Tool Hints

Type a standalone `#` anywhere in the chat input to browse enabled, non-blocked tools. Tool hints are soft preferences for the current request; they do not force the route and they can be ignored when another tool is a better fit.

Examples:

```text
#weather will it rain tonight?
#crypto_price ethereum
#supa_crawl_knowledge #canvas research this and save the useful parts
```

**Behavior:**
- `#` autocomplete uses `/api/tools?summary=true&include_blocked=false`, so the list reflects enabled tools, web-blocked tools, MCP/database tools, and active tool profiles.
- A prompt can attach hints automatically through its YAML `tool_hints` frontmatter; the server validates availability and the client handles them exactly like explicitly selected hints.
- Unlike `/workflow` and `@prompt`, tool hints can appear more than once and can be inserted anywhere as standalone tokens.
- Selecting a tool from `#` autocomplete turns it into a removable chip above the input. The raw `#partial` token is removed from the textarea so the task stays readable.
- Typed or pasted `#tool_name` tokens still work as a plain-text fallback. The UI removes recognized tokens from the clean user query and sends canonical tool names as metadata.
- Ambient tool suggestions may appear while typing a normal request. These are optional suggested chips based on the current text and the enabled tool registry; clicking one adds it as a selected tool hint.
- Ambient suggestions are not `GHOST_TOOLS`. Ghost tools are environment/config tools prioritized by Tool RAG; ambient suggestions are visible user choices and are only sent if clicked.
- `tool_search` and `workflow` are mandatory discovery candidates only while enabled in this effective Web tool surface. A profile or Web block can remove either helper.
- The server validates hints again, dedupes them, caps them at 5, and injects a compact context block:

```text
[CONTEXT - Tool preference for this request]

Selected tool hints: crypto_price.
Treat these as strong preferences for this turn. If one fits the user's request, use it before artifact/memory tools such as canvas; ignore a hinted tool only if it clearly does not fit or fails.

[END CONTEXT]

User's request: ethereum
```

**Enhance compatibility:**
The ✨ Enhance button sends validated tool hints as separate enhancement
context, enhances only the clean task text, and then keeps the selected hints as
chips beside the rewritten input. Hints help the enhancer understand the target
capability without placing internal tool names or parameters in the rewritten
prompt.

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
  - Up to 100 available tool names and concise descriptions
  - Any explicitly selected tool hints
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
- Receives descriptions, not tool parameter schemas
- Only enhances text - the SEND goes through full orchestrator
- Won't enhance if input starts with `/` or `@` (those are explicit)
- Validates and prioritizes `#tool` hints while keeping them separate from the clean task text
- For media requests, enriches creative direction without inventing provider,
  model, duration, dimensions, file type, output format, or other operational
  values the user did not supply

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
│  │  • Tool descriptions + validated hints  │                    │
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

### `/logs` Read-Only Browser (NEW)

A dedicated page at `/logs` for browsing structured and plain-text logs without leaving Jarvis Web UI.

**Features:**
- **Read-only by design** - No editing, deletion, or file writes
- **Auth-protected** - Reuses the existing Jarvis Web auth/session checks
- **Focused file types** - Shows only folders containing `.jsonl`, `.log`, or `.md`
- **Predictable navigation** - Folders stay A-Z while files inside each folder stay newest-first
- **Folder-level search** - Search ranks matching files and carries the filter into the viewer
- **JSONL rendering** - Parses each line, nestifies dotted keys, and renders YAML-style cards newest-first
- **Markdown rendering** - `.md` files render as markdown in both the viewer and modal
- **Lazy loading** - Large files page in more content instead of loading the entire file at once
- **Mobile drill-down** - Small screens switch to folder → files → viewer with back arrows

**Routes and APIs:**
- `GET /logs` - Dedicated viewer page
- `GET /api/logs/folders` - List allowed folders
- `GET /api/logs/files` - List files in a folder with search/sort context
- `GET /api/logs/content` - Fetch paged content for a selected file

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

### Manual Feedback Analysis (NEW)

Trigger LLM-as-QA feedback directly from the WebUI to analyze response quality.

**Two Ways to Trigger:**

1. **📊 Toggle Button** - Click the feedback button (next to ✨ Enhance) to enable for all messages
2. **`--feedback` Inline** - Add `--feedback` anywhere in your message

Random feedback can also be sampled by the orchestrator when `FEEDBACK_RANDOM_ENABLED=true` and `FEEDBACK_RANDOM_CHANCE` is greater than zero. Jarvis Web displays pre-collected random feedback as the normal purple card when Completion Guard is not active; while Completion Guard is active, Web disables the orchestrator random path so only explicit feedback waits behind guard settlement.

**What Happens:**
1. Your query processes normally (tool calls, response)
2. After response, async feedback collection starts
3. A purple "Feedback Analysis" card appears
4. Card shows rating (1-5 stars), summary, issues, tool ratings
5. Toast notification appears with quick summary

**Feedback Card Contents:**

| Section | Description |
|---------|-------------|
| **Rating** | 1-5 stars with color coding (green=good, yellow=ok, red=bad) |
| **Summary** | One-line description of what happened |
| **What went well** | Positive aspects of the response |
| **Issues** | Problems found (with category: system_prompt, tool_description, etc.) |
| **Tool Performance** | Per-tool ratings if multiple tools were used |

**Click to Expand/Collapse:**
- Card starts expanded to show all details
- Click header (with ▼ indicator) to collapse/expand

**Always Logged:**
- Manual feedback is ALWAYS logged to `logs/feedback/feedback-YYYY-MM-DD.jsonl`
- Random feedback samples are also logged when collected; current feedback logging writes one JSONL entry per completed feedback run

**Use Cases:**
- Verify tool selection is correct
- Debug why a specific query behaved unexpectedly
- Check if system prompt rules are being followed
- Validate tool descriptions are accurate

---

## 📋 TODO / Gaps

### High Priority (Do First)
- [x] **Browser STT** - Push-to-talk with mic button ✅ DONE
  - Click-to-toggle: click to start, click again to stop
  - Mode-aware defaults plus OpenAI-compatible endpoint opt-in in either mode
  - Visual states: preparing (blue), recording (green), processing (yellow)
  - Auto-sends transcript as chat message
- [x] **Proactive integration** - Show alerts/reminders in UI ✅ DONE
  - Polls jarvis-api every 10 seconds for pending alerts/triggered reminders
  - Browser notifications (Notifications API) for new items
  - TTS playback when audio is enabled
  - Notification panel with acknowledge buttons

### Medium Priority
- [x] Conversation search (filter by keyword/date) ✅ DONE
- [x] Export conversations (JSON/Markdown) ✅ DONE
- [x] Import conversations (JSON) ✅ DONE
- [ ] Tool enable/disable per-tool in UI
- [ ] MCP server status indicator (running/stopped/error)
- [ ] Canvas integration (embed pages or link)

### Low Priority
- [x] Authentication (JWT token-based) ✅ DONE
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
- [x] Mode-aware STT - Cloud=OpenAI, Local=faster-whisper, compatible endpoint opt-in
- [x] Recording visual states - Blue/green/yellow feedback
- [x] Proactive notifications - Polls jarvis-api for alerts/reminders
- [x] Browser notifications - Notifications API integration
- [x] Notification panel - View/acknowledge alerts & reminders
- [x] Local audio fix - Now serves from audio/local/tts too
- [x] **Audio playback controls** - Speaker button with pause/resume/stop
- [x] **Progress animation** - Visual pulse during playback
- [x] **Smart auto-hide** - 10s after audio ends, instant on new message
- [x] **ElevenLabs music generation** - `generate_music` tool with stash integration
- [x] **Music playback in web UI** - Generated music plays inline
- [x] **@prompts system** - Context-first injection for LLM guidance
- [x] **deep_memory_search tool** - Multi-source search across all data
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
- [x] **Slash commands** - `/canvas`, `/search`, `/recall`, `/detailed`, etc.
- [x] **@prompts system** - `@research`, `@quick`, `@compare`, etc.
- [x] **#tool hints** - Soft per-request tool preferences with chips, full autocomplete, and ambient suggestions
- [x] **Command autocomplete** - Type `/`, `@`, or standalone `#` for suggestions
- [x] **✨ Enhance with AI** - Transform rough input into optimal prompts
- [x] **Tool exclusion** - Commands can exclude tools to force native search
- [x] **Canvas command** - `/canvas` researches + saves to Canvas viewer
- [x] **Conversation quick filter** - Filter by title in sidebar
- [x] **Deep search modal** - Search all message content with highlighted snippets
- [x] **Export conversations** - JSON and Markdown formats
- [x] **Import conversations** - Restore from JSON files
- [x] **Server Logs Panel** - Real-time streaming at bottom of UI
- [x] **LLM + Tool logs** - Parsed, color-coded, expandable details
- [x] **Log source toggles** - Enable/disable LLM, Tools, OpenCode, Feedback
- [x] **Resizable log panel** - Drag to resize, state persisted in localStorage
- [x] **`/logs` browser** - Read-only log explorer with folder search, YAML-style JSONL rendering, markdown viewing, and mobile drill-down
- [x] **Manual Feedback Analysis** - 📊 button + `--feedback` inline trigger
- [x] **Feedback Card** - Purple tool card with rating, summary, issues, tool ratings
- [x] **Feedback Toast** - 6-second notification with rating summary
- [x] **Always-log manual feedback** - Manual triggers always saved to logs
- [x] **🔄 File Conversion button** - Convert images/video/audio between formats
- [x] **Conversion modal** - Format selector with preview and descriptions
- [x] **Stash upload endpoint** - `/api/stash/upload` for direct stash uploads
- [x] **Inline converted media** - Images/video/audio display with ⬇️ Download button
- [x] **SVG/BMP/ICO/FLAC support** - Extended stash MIME types
- [x] **Advanced convert options** - Resize, quality, bitrate, FPS, etc. in collapsible panel
- [x] **Video provider dropdown** - Switch video generation between xAI Grok and Google Gemini Veo or Openai Sora on-the-fly
- [x] **Image provider xAI option** - Added xAI Grok as image provider alongside Gemini and OpenAI
- [x] **JARVIS_OVERRIDE_ mechanism** - Provider overrides survive tool subprocess `load_config()` via prefixed env vars
- [x] **Image gallery provider badges** - Shows xAI/Gemini/OpenAI badges on generated images in Canvas gallery

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
| Local TTS fails silently | Check the selected provider server is running at `KOKORO_TTS_URL` or `QWEN3_TTS_URL` |
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
- ✅ **`/logs` browser**: Dedicated auth-protected viewer for `.jsonl`, `.log`, and `.md` (DONE!)
- 🔮 **Cost tracker**: Daily/weekly/monthly spend summary
- 🔮 **A/B test viewer**: See prompt evolution experiments

### UX Improvements
- **Keyboard shortcuts**: Ctrl+Enter send, Ctrl+N new chat, etc.
- ✅ **Drag-drop files**: Upload images/files directly (DONE)
- ✅ **Paste images**: Paste from clipboard (DONE)
- ✅ **Latest-response action rail**: Copy Markdown, Send to Canvas, and conditional positive/negative Intelligence feedback share one compact mobile-friendly row
- **Message editing**: Edit sent messages

---

## ⚖️ Web vs Terminal: Key Differences

| Aspect | Terminal/TUI/Jarvis | Web UI |
|--------|---------------------|--------|
| **Conversation History** | `memory_db` + `AUTO_CONTEXT_*` (cloud.env, local.env) | JSON files + `conversation.history_limit` (web_config.json) - **COMPLETELY SEPARATE SYSTEMS** |
| **LLM Provider** | `.env` file (restart to change) | `web_config.json` per-mode (on-the-fly) |
| **Blocked Tools** | None (all tools available) | `tools.blocked` array |
| **Status Updates** | Local speaker with cancellable cached playback | Browser WebSocket + optional cancellable cached TTS |
| **TTS** | Mode-specific shell scripts | Direct provider API; status cache is separate from final TTS |
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
- `data/web_conversations/` - Saved chat history (repo root; one JSON file per conversation + `index.json`)

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
*v2.1: Manual Feedback Analysis - 📊 toggle, --feedback inline, feedback cards - January 23, 2026*
*v2.2: 🔄 File Conversion - convert button, format modal, inline media display with download - February 5, 2026*
*v2.3: Provider switching - Video provider dropdown, xAI image option, JARVIS_OVERRIDE_ mechanism, gallery provider badges - February 6, 2026*
*v2.4: OpenAI Sora - Third video provider with native audio, image-to-video, remix support - February 9, 2026*
*v2.5: AI Config response-style overrides - Per-mode `JARVIS_RESPONSE_STYLE`, `JARVIS_QA_WORD_LIMIT`, and `JARVIS_MULTI_TURN_WORD_LIMIT` with live prompt/runtime alignment - March 29, 2026*
*v2.6: Completion Guard - inline completion card, one-pass manual repair loop, tool-aware exclusions, repair tickets, and export metadata - March 30, 2026*
*v2.7: Completion Guard auto mode - background evaluator, threshold override, persisted accept state, and intelligence-layer outcome tracking - March 30, 2026*
*v2.8: Completion Guard learning model - repair cancel support, structured learning on the original experience, and corrected-path reflection context - March 30, 2026*
*v2.9: Completion Guard tighten-only path, visible repair delta-gating, evaluator/provider split, and provider-error formatter fallback - April 2, 2026*
*v2.10: Completion Guard eval provider/model overrides, cloud/local Ollama model separation in AI Config, and Ollama cloud auto-eval JSON compatibility fixes - April 3, 2026*
*v2.11: Duplicate-tool recovery status, explicit large-result truncation metadata, and retry-state-preserving tool-card behavior - April 10, 2026*
*v2.12: Dedicated `/logs` browser with auth protection, folder search, YAML-style JSONL rendering, markdown viewing, and mobile drill-down - April 12, 2026*
*v2.13: Completion Guard manual countdown, expired/superseded neutral settlement, and random-feedback coordination docs - April 17, 2026*
*v2.14: `#tool` hints for soft per-request tool preference, full enabled-tool autocomplete, server validation, and ✨ Enhance preservation - April 20, 2026*
*v2.15: Tool hint chips and ambient tool suggestions for optional per-request tool preferences - April 20, 2026*
*v2.16: Mode-aware tool/prompt/workflow discovery, autonomous foreground workflow tool cards/follow-up context, and workflow Completion Guard exclusion - July 23, 2026*
