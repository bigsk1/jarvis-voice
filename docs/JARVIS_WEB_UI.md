# Jarvis Web UI

Jarvis Web is the browser interface for chat, tools, workflows, attachments,
and voice conversations. It shares the core orchestrator, memory, and
Intelligence layer with the CLI and native voice interfaces, while keeping
its own saved conversations and per-mode settings.

Use it to:

- Chat with a configured cloud or local model and follow tool progress live.
- Attach images, documents, audio, and video, then ask follow-up questions.
- Run workflows, use saved prompts, and choose tool hints from the composer.
- Listen to responses, dictate a draft, or use hands-free Talk.
- Browse saved chats, generated media, notifications, and execution logs.

![jarvis-web](images/jarvis-web-ui.png)

For private HTTPS access from your other devices, see the
[Tailscale HTTPS guide](TAILSCALE_HTTPS.md). It covers Serve commands for all five
UIs, optional navigation URLs, browser microphone checks, and troubleshooting.

## 🚀 Running

After [setup](INSTALL_GUIDE.md), start the Web server from the repository root:

```bash
./bin/jarvis-web         # Cloud/default startup mode
./bin/jarvis-web local   # Explicit local startup mode
```

Open `http://localhost:5001` on the server, or use its reachable hostname/IP
from another device. Browser microphone features require HTTPS or localhost.
Use the configured login when Web authentication is enabled.

---

## Features

### Chat and tool execution

| Feature | Details |
|---------|---------|
| Project structure | `jarvis-web/` with server/client separation |
| Flask + SocketIO backend | Real-time WebSocket communication |
| Basic chat UI | Send messages, receive responses |
| WebSocket events | `chat:send`, `chat:response`, `chat:status`, `tool:*` |
| Tool execution streaming | Tool cards show progress and results |
| Tool approval | Foreground Web calls for tools with explicit `auto_approve: false` pause before execution; Allow once or Don't run in chat, Talk, or Firefox Companion |
| Mode selection | Cloud/Local toggle in header |
| Tool discovery | Auto-loads from `skills/*.tool.json` |
| Dark theme | CSS variables, modern styling |

### Conversations and settings

| Feature | Details |
|---------|---------|
| Conversation history | Save/load/delete, sidebar list |
| [Task recovery](WEB_TASK_RECOVERY.md) | Restore running work and Stop after reload; recover missed answers; reject overlapping turns |
| Tool execution cards | Expandable with args/results |
| Image display | Thumbnails + lightbox with download |
| Settings panel | General, AI Config, Tools, Prompts, Integrations, System, API Keys, and Profile tabs |
| Provider dropdowns | xAI/Anthropic/OpenAI/Ollama with model options |
| Error handling | Toast notifications, error messages |
| Status updates | Non-blocking deadline/fallback stream to browser, not local speaker |
| Duplicate-call recovery status | Blocked duplicate tool attempts surface as red status text, not fake failed tool cards |

### Browser voice and audio

| Feature | Details |
|---------|---------|
| TTS playback | Toggle audio, plays responses in browser |
| Mode-aware TTS | Uses the selected mode’s configured TTS provider and Web override |
| Status TTS | Cached, cancellable status speech when enabled; final audio has priority |
| **Voice dictation** | Click mic → speak → stop → review/edit transcript → Send |
| **[Hands-free Talk](WEB_TALK.md)** | Separate Talk button: speak → pause to send → hear answer → listen again; desktop and mobile |
| **Mode-aware STT** | Cloud=OpenAI, Local=faster-whisper; compatible endpoint opt-in in either mode |
| **Audio playback controls** | Speaker button with pause/resume/stop, progress animation  |

### Configuration and media

| Feature | Details |
|---------|---------|
| Web blocked tools | `tools.blocked` in web_config.json, UI to manage |
| Blocked tools UI | Settings → Tools tab to add/remove |
| Conversation context | Configurable limit (default 20) passed to LLM |
| Settings persistence | `web_config.json` with per-mode overrides |
| Reset to defaults | Button to clear web overrides for current mode |
| Dynamic LLM switching | Change provider/model on-the-fly, takes effect immediately |
| Dynamic media provider | Switch image, video, and music providers on-the-fly |
| Response style overrides | Per-mode overrides for response style, Q&A word limit, and multi-turn word limit |
| MCP tool discovery | Reads from memory_db, shows in Tools tab |
| System config view | Mode-specific .env values, lazy SerpApi quota, and [Ollama Cloud balance/usage](ollama/README.md#account-balance-and-usage-in-web-settings) in Settings → System |
| Per-mode settings | `cloud`/`local` sections in web_config.json |
| Dynamic Ollama models | Fetches available models from Ollama server |
| Mode switching | Keeps cloud/local settings and learning data separate |
| Proactive alerts | Polls jarvis-api for alerts/reminders |
| Browser notifications | Notifications API for new alerts/reminders |
| **Image upload** | Drag-drop/paste/click to attach images |
| **Vision analysis** | Uses the configured vision provider/model for the selected mode |
| **Expand details button** | Show full LLM response before voice shortening |
| **Auto-stash uploads** | Uploaded images auto-stash + memory_db entry |
| **analyze_image tool** | Analyze URLs, files, stash refs with vision |
| **🔄 File Conversion** | Convert images/video/audio between formats |
| **Convert modal** | Format selector with preview, descriptions, and advanced options |
| **Advanced convert options** | Resize, quality, bitrate, FPS, etc. per format type |
| **Inline converted media** | Shows image/video/audio with download button |

### Composer controls

| Feature | Details |
|---------|---------|
| **Slash commands** | `/canvas`, `/search`, `/recall`, etc. - modify behavior |
| **@prompts** | `@research`, `@quick`, `@compare` - inject methodologies |
| **#tool hints** | `#weather`, `#youtube_transcript`, etc. - softly prefer one or more tools |
| **Chat only policy** | `#chat_only` enables a sticky, explicitly selected no-tools mode |
| **Command autocomplete** | Type `/`, `@`, or standalone `#` to see suggestions |
| **✨ Enhance with AI** | Magic button transforms rough input into optimal prompt |
| **Tool exclusion** | Commands can exclude tools (force native search) |

### Saved conversations

| Feature | Details |
|---------|---------|
| **Quick filter** | Filter conversations by title in sidebar |
| **Deep search** | Search across all message content with snippets |
| **Export JSON** | Download conversation as JSON file |
| **Export Markdown** | Download conversation as formatted Markdown |
| **Import JSON** | Upload JSON to restore conversation |
| **Live sidebar sync** | Conversations created or updated through Firefox, mobile, or another Web tab appear automatically on connected Web clients |
| **Pinned-safe cleanup** | `cleanup-all` removes unpinned chats older than 90 days; pinned chats are preserved |

Sidebar updates use the existing authenticated Socket.IO connection. A short
debounce combines changes into a list refresh without adding a polling loop.
The selected chat, draft, attachments, active tools, and Talk are unaffected;
sidebar search, scroll position, and expanded archives are preserved. Reconnecting
refreshes the list to catch changes missed while offline. This synchronizes clients
using the same Jarvis Web server; it does not watch files edited by external processes.
Relative timestamps refresh locally once a minute while the page is visible and
when returning to the tab, without fetching conversations or rebuilding the list.

### Logs and diagnostics

| Feature | Details |
|---------|---------|
| **Server Logs Panel** | Real-time log streaming at bottom of UI  |
| **LLM call logs** | Model, tokens, cost, duration, tool called  |
| **Tool call logs** | Tool name, duration, success/error, result preview  |
| **Source toggles** | Enable/disable LLM, Tools, OpenCode, Feedback  |
| **Expandable details** | Click entry to see full parsed JSON  |
| **Resizable panel** | Drag to resize, state persisted  |
| **`/logs` browser** | Read-only log explorer for `.jsonl`, `.log`, and `.md` with search, lazy loading, and mobile drill-down |

### Response feedback

| Feature | Details |
|---------|---------|
| **Feedback toggle** | 📊 button to enable LLM feedback analysis |
| **`--feedback` inline** | Type `--feedback` in message to trigger |
| **Feedback card** | Feedback card shows rating, summary, and issues |
| **Feedback gating** | Explicit Web feedback waits for Completion Guard settlement before grading |
| **Random feedback coordination** | Orchestrator random feedback can emit cards normally, but is disabled while Web Completion Guard is active |
| **Expand/collapse** | Click header to toggle details |
| **Toast notification** | 6-second toast with rating summary |
| **Always logged** | Manual feedback always saved to logs |

### Completion Guard

| Feature | Details |
|---------|---------|
| **Completion Guard card** | Inline `Completed correctly?` card on assistant responses |
| **Manual prompt countdown** | Active manual cards show a small countdown and default to 10 minutes |
| **Stale prompt settlement** | Expired cards settle as `expired`; older unanswered cards settle as `superseded` when the conversation continues |
| **Manual repair pass** | Clicking `No` runs one bounded repair pass |
| **Repair status updates** | Repair emits normal Jarvis thinking/status/tool events |
| **Repair tickets** | Unresolved failures write markdown tickets to `logs/completion-guard/` |
| **Tool-aware exclusions** | Skips workflows and fire-and-forget/sensitive tools |
| **Conversation export metadata** | Markdown export includes Completion Guard status/note/ticket data when present |
| **Prompt/runtime repair context** | Repair uses original query, raw LLM response, tool outputs, and user note |
| **Auto mode evaluator** | Background evaluator can auto-trigger repair using the raw final answer |
| **`tighten_only` outcome** | After a **repair** pass, wording-only settlement without a second assistant message; judge JSON `tighten_only` (no repair) settles as `auto_accepted` |
| **Visible repair delta-gating** | Separate repaired answers require a real evidence or tool-path delta |
| **Repair cancel support** | Stop button cancels an in-flight repair pass |
| **Auto threshold override** | AI Config exposes per-mode threshold override for auto mode |
| **Accepted state persistence** | Clicking `Yes` persists to conversation history and exports |
| **Intelligence bridge** | Accepted/repaired/ticketed/cancelled outcomes feed back into reflection data; expired/superseded settle neutrally |
| **Corrected-path learning** | Repaired answers, tools, and tool results are folded back into the original experience for reflections |
| **Feedback-aware settlement** | Final web feedback runs on the settled Completion Guard outcome and includes CG metadata in grading |
| **Chat-only repair policy** | Manual/Auto evaluation remains available, but repairs inherit no-tools policy and use QA-only answer deltas |
| **Provider-split auto evaluator** | Auto eval can run on a different provider/model than the main chat response |
| **Eval provider/model overrides** | AI Config exposes per-mode Completion Guard eval provider/model controls |
| **Ollama cloud judge support** | Cloud Ollama eval uses cloud-only model lists and defensive JSON parsing/budgeting for auto eval |

Completion Guard's evaluator selection is independent of the main chat model.
Web uses its per-mode evaluator provider/model overrides; unset values use ENV
defaults. If Web selects a different evaluator provider and leaves the model at
default, that model comes from the selected provider's configuration. The ENV's
dedicated evaluator model applies when its provider matches. Settings and runtime
resolve the same pair, and evaluator calls disable provider-native search.


### Tool Cards, Status, and Reload Behavior

- A pending approval sits beside the active turn and describes its prepared action
  with a short risk warning and remaining time. **Don't run** stops the sequence before that call; the final reply keeps
  completed tool results for follow-up. A later request can ask again and gets a
  new one-time approval. Stop and approval expiry also end the pending sequence.
- Reloading or reconnecting to the same conversation restores its pending
  approval while the Web run is active.
- `tool:start`, `tool:complete`, and `tool:error` drive the live tool cards shown during a request.
- Real tool failures show a red tool card because the tool actually executed and returned an error.
- Duplicate-guard blocks are different: the repeated tool call is stopped before execution, so the UI shows a red status/progress message instead of a failed tool card.
- Routing status text can include turn-aware messages like `Turn 3: using serpapi_amazon_search...`, which follow the orchestrator's `MAX_TOOL_TURNS` loop.
- Tool cards rendered after a page reload are rebuilt from the saved conversation message, not from the original live WebSocket event stream.
- Because of that, historical reload is best at restoring successful tool outcomes. Live-only per-call events such as intermediate failures or duplicate-guard status lines are not guaranteed to reappear unless they were explicitly persisted in the saved message data.
- `client/js/assistant-message-renderer.js` renders tool-card lists, converted-file
  previews, and the legacy shopping fallback from supplied message data. It loads
  before `chat.js`; ChatUI retains request lifecycle and media selection.

### Structured Result Previews

- `client/js/structured-results.js` owns the shared card rail for structured
  search results. It is separate from execution-status tool cards and from
  content-native displays such as Canvas, generated media, YouTube embeds, and
  crypto charts.
- The renderer uses a registry of tool adapters. Each adapter maps its tool's
  payload onto the same bounded presentation model; the shared renderer then
  handles escaping, safe HTTP links, images, metadata chips, and actions. The
  presentation model supports `rail` for visual browsing, `list` for dense
  records, and `metrics` for compact measurements. Overflowing rails expose
  previous/next controls in the preview header without covering card content;
  touch swiping and the native scrollbar remain available.
- Shopping, search, and local/travel adapters live in
  `client/js/structured-results-shopping.js`, `structured-results-search.js`,
  and `structured-results-local-travel.js`. They load before the renderer as
  classic scripts and receive its shared formatting helpers.
- When the response is a completed workflow, the same adapters are composed
  into one workflow result surface in workflow step order. Each tool keeps its
  own heading, metadata, safe links, and layout inside that surface. A section
  containing one result uses a compact non-scrolling layout instead of an
  otherwise empty rail. Standalone and ordinary multi-tool responses keep the
  existing independent adapter cards.
- Current adapters cover Amazon and Google Shopping, Home Depot, eBay search
  and product details, Google Hotels, Yelp, Google Flights, Google Maps,
  Tripadvisor, Google Local and Local Services, Search Index, Google News Light,
  Google Trends and Trending Now, SerpApi Google Images Light and YouTube search,
  and weather forecasts.
- Google Images Light uses a dedicated remote-results gallery. It remains
  separate from generated-media catalogs and treats all image URLs and metadata
  as untrusted. Assistant Markdown images are independently constrained to the
  chat bubble width, so detailed responses cannot widen the conversation column;
  structured card rails retain their own bounded horizontal navigation.
- Standalone YouTube search uses the compact rail for the complete shortlist
  while Jarvis Web keeps one large playable top-result embed. In workflows the
  duplicate search rail is suppressed and the large playable top-result embed
  remains independent below the composite. Direct YouTube detail and
  downloaded-media results retain their existing specialized players.
- Downloaded media play through their Stash IDs. Unicode titles and filenames,
  including emoji, are preserved; the standard encoded `Content-Disposition`
  header supplies the filename without breaking file streaming or byte ranges.
- Add a future structured display with
  `window.structuredResultsRenderer.register(toolName, adapter)`. Keep provider
  payload parsing inside the adapter and return only the small shared
  presentation model instead of adding another conditional block to `chat.js`.

### Large Tool Result Context

- The orchestrator may truncate large prior tool payloads before sending them back to the LLM on later turns.
- Jarvis marks these previews with explicit metadata such as `result_truncated`, `result_chars_shown`, and `result_chars_total`.
- When truncation is needed, later routing turns receive a valid JSON `Result Preview:` block instead of a raw sliced JSON fragment.
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
│   ├── socket_auth.py              # WebUI token checks and socket expiry
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
│       ├── followup_extractor.py   # Stable follow-up entry point, metadata, and output bounds
│       └── followup/               # Tool-family field extraction
│           ├── __init__.py
│           ├── shopping.py
│           ├── search.py
│           ├── media.py
│           └── local_travel.py
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
│   │   ├── assistant-message-renderer.js # Tool cards, converted files, legacy shopping
│   │   ├── command-system.js       # Slash commands, prompt selection, and tool hints
│   │   ├── structured-results.js   # Adapter registry and shared result rendering
│   │   ├── structured-results-shopping.js # Shopping payload adapters
│   │   ├── structured-results-search.js   # Search payload adapters
│   │   ├── structured-results-local-travel.js # Local/travel payload adapters
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
| GET | `/api/prompts/manage` | List every prompt with source and availability diagnostics |
| POST | `/api/prompts/personal` | Create a personal prompt or explicit built-in override |
| PUT | `/api/prompts/personal/<name>` | Update an existing personal prompt |
| DELETE | `/api/prompts/personal/<name>` | Delete a personal prompt and reveal any built-in |
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

When `features.auth` is true in public `/api/status`, connect with the WebUI
token in Socket.IO `auth: {token}` and use the same bearer for HTTP uploads and
conversation requests. Every event is authenticated; token expiry also removes
idle subscriptions and emits `auth:required` before disconnection. Server-owned
runs remain recoverable after sign-in. Public `extension.api: 1` and
`extension.features` advertise the independently installed companion contract
(`chat`, `images`, `conversations`, `recovery`, `cancel`, and optional `text` for
page-text uploads). Companions can connect without `text`; capturing page
content as a durable source requires it. Restart Jarvis Web after adding that
feature before expecting page-text uploads.

The Firefox companion's **Include page** button attaches a reviewed title and
URL to the next chat message without capturing the page. YouTube video links
add a `youtube_transcript` tool hint through the existing chat path; the server
still validates tool availability. This link-only action works without the
optional `text` capability. See the [companion guide](../jarvis-firefox-extension/README.md#ask-about-the-current-page-or-video).

#### Client → Server

```javascript
// Send chat message
socket.emit('chat:send', {
    message: 'What is bitcoin price?',
    conversation_id: 'conv_123',
    mode: 'cloud',
    tool_policy: 'none' // Optional: Chat only; omit for normal Auto routing
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

### Core settings and Web overrides

| Config | Source | Affects | Editable |
|--------|--------|---------|----------|
| Core Settings | `cloud.env` / `local.env` | Terminal/TUI/Web | ❌ Restart required |
| Web Overrides | `web_config.json` | Web only | ✅ On-the-fly |

**Overridable Settings (per-mode):**

| Setting | Dropdown | Options |
|---------|----------|---------|
| LLM Provider | AI Config → LLM Provider | xAI, Anthropic, OpenAI, Ollama |
| LLM Model | AI Config → Model | Dynamic per provider |
| Image Provider | AI Config → Image Provider | xAI Grok, Google Gemini, OpenAI GPT Image |
| Image Model | AI Config → Image Model | Catalog models for the selected image provider |
| Video Provider | AI Config → Video Provider | xAI Grok, Google Gemini Veo |
| Video Model | AI Config → Video Model | Catalog models for the selected video provider |
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

Copy the complete [example configuration](../jarvis-web/config/web_config.json.example)
when setting up Jarvis Web. This abbreviated example shows the main settings;
`null` leaves an override unset so the selected mode's configuration applies.

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 5001
  },
  "defaults": {
    "mode": "cloud"
  },
  "audio": {
    "tts_enabled": false,
    "tts_autoplay": true
  },
  "cloud": {
    "llm_provider": null,
    "llm_model": null,
    "router_prompt_version": null,
    "image_provider": null,
    "image_models": {},
    "video_provider": null,
    "video_models": {},
    "music_provider": null,
    "tts_provider": null,
    "response_style": null,
    "tool_rag_limit": null,
    "qa_word_limit": null,
    "multi_turn_word_limit": null
  },
  "local": {
    "llm_provider": null,
    "llm_model": null,
    "router_prompt_version": null,
    "image_provider": null,
    "image_models": {},
    "video_provider": null,
    "video_models": {},
    "music_provider": null,
    "tts_provider": null,
    "response_style": null,
    "tool_rag_limit": null,
    "qa_word_limit": null,
    "multi_turn_word_limit": null
  },
  "conversation": {
    "history_limit": 20
  },
  "tools": {
    "blocked": ["get_recent_conversations"],
    "notes": "Tools blocked for web only. Terminal unaffected."
  }
}
```

Cloud and local have separate overrides. Thresholds are read from the active mode’s env file.

### Request Scopes and `JARVIS_OVERRIDE_` Child Exports

Web UI settings for image/video providers and their provider-scoped model pins
live in a request-local config scope.
When Jarvis launches a child tool, the scoped values are exported to that
child with a `JARVIS_OVERRIDE_` prefix so the tool can safely reload its env
file without losing the request choice.

The image-action modal is a final, one-request override: its provider/model is
forced into that tool call and is not written back to AI Config. For ordinary
tool calls, an explicit `model` argument wins; when omitted, the tool uses the
request-scoped Web/ENV pin and then the catalog default.

**Child configuration loading:**
Child tool scripts (for example `generate_image.py`) call `load_config()` in
their own process. An ordinary unprefixed provider value would be replaced by
the selected env file during that reload, so scoped values need an
authoritative child-export form.

**Override propagation:**
```
chat.py scope:    IMAGE_TOOL_PROVIDER=gemini
                  GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
                  VIDEO_TOOL_PROVIDER=gemini
                  GEMINI_VIDEO_MODEL=gemini-omni-flash-preview
                  MUSIC_TOOL_PROVIDER=gemini
        ↓
executor.py:      export_config_environment() builds child-only env
                  JARVIS_OVERRIDE_IMAGE_TOOL_PROVIDER=gemini
                  JARVIS_OVERRIDE_GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
                  JARVIS_OVERRIDE_VIDEO_TOOL_PROVIDER=gemini
                  JARVIS_OVERRIDE_GEMINI_VIDEO_MODEL=gemini-omni-flash-preview
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
| Image Model | `XAI_IMAGE_MODEL` / `GEMINI_IMAGE_MODEL` / `OPENAI_IMAGE_MODEL` | Matching `JARVIS_OVERRIDE_…` var | Catalog models for selected provider |
| Video Provider | `VIDEO_TOOL_PROVIDER` | `JARVIS_OVERRIDE_VIDEO_TOOL_PROVIDER` | xai, gemini |
| Video Model | `XAI_VIDEO_MODEL` / `GEMINI_VIDEO_MODEL` | Matching `JARVIS_OVERRIDE_…` var | Catalog models for selected provider |
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
- **Context badge**: Shows the latest request's context count and its capacity warning colors. Hover, or tap/click for a details panel with cumulative processed tokens, input/output totals, model calls, cache details, and cost. Tap outside, tap the badge again, or press Escape to dismiss the panel. The details also show the recent-message history window and how many older messages fall outside it. Both user and Jarvis messages count; messages outside the window remain saved in the conversation.
- **Modals**: Settings panel, image lightbox

### Tool Cards
- Expandable with click
- Show: tool name, status, duration
- Expanded: arguments, full result, images

### Settings Panel
- **General Tab**: Mode (cloud/local), TTS toggle, mode-aware help text
- **AI Config Tab**: LLM provider/model dropdowns (per-mode), Image provider, Video provider, Music provider, History limit, Reset button
- **Tools Tab**: Blocked tools list, add/remove UI, blocked/MCP visual indicators
- **Prompts Tab**: Browse shared prompts and create or edit personal overrides
- **Integrations Tab**: Configure supported integrations and inspect their availability
- **System Tab**: Mode-specific .env values (thresholds, TTS settings, features), plus a SerpApi quota card fetched only when the tab is opened. The card stays absent when the selected mode has no valid `SERP_API_KEY`; SerpApi does not count Account API lookups against monthly search quota.
- **API Keys Tab**: Status indicators (configured/missing)
- **Profile Tab**: Current version linked to GitHub releases, auth/mode status, and a safe rendered view/editor for `jarvis-intel/user-profile.md`. **Save & ingest** uses the existing FastAPI Intel CRUD route; the Profile Card cache refreshes immediately for the selected mode plus an already-existing, configured sibling while background ingestion updates Profile Reference facts in those same modes.
- **Profile Appearance**: Set a display name and upload a PNG, JPEG, or WebP avatar (up to 5 MB and 16 million pixels), then **Save appearance**. The server crops the image to 256×256, removes metadata, and stores it with the name in the ignored `data/web_profile_appearance.json`. **Use default image** restores the existing Jarvis image; a blank name restores **Administrator**. Appearance is shared across modes and connected Firefox companions through the authenticated `/api/profile-appearance` endpoint. It changes display only; login credentials and the Intelligence Profile Card are separate.

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

The sibling `followup/` package groups shopping, search, local/travel, and media
projections. `media.py` handles Trakt and TMDB; `shopping.py` also joins Amazon
discovery and product-detail runs. The facade retains shared metadata, workflow
handling, and output bounds.

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

### Audio Playback Controls

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
3. Red recording indicator → Speak your message
4. Click mic again → Yellow "processing" state
5. Audio sent to `/api/stt` → Transcript appended to the current input
6. Review, edit, or record another section → Click Send when ready

Dictation never sends the chat automatically. The existing Send button temporarily
becomes **× Cancel dictation** while preparing, recording, or transcribing; it
returns to Send afterward. No additional composer button is added. Cancel or
`Esc` discards the current dictation and keeps the existing draft. Text typed or
edited while transcription runs is preserved. Changing conversation or mode
discards pending dictation so it cannot appear in another chat.

Transcription appears after stopping; the current STT endpoint does not stream
partial text. Cancelling a pending transcription ignores its result and aborts
the browser request; server/provider processing may already be underway.

On mobile, Jarvis's microphone button remains hidden to preserve composer space.
Use the phone keyboard's dictation microphone to enter and review text instead.
The separate **Talk** button remains visible on mobile for automatic spoken turns.

Web microphone audio is temporary: the server removes the uploaded recording
after transcription. Local faster-whisper also removes its converted WAV after
use, including partial WAV output from failed or timed-out conversions. These
microphone clips are not archived in Stash or conversation history.

### Hands-free Talk

Click **Talk** for a continuous conversation through the configured STT, chat, and
TTS providers. Speech is sent automatically after a pause. Jarvis disables input
capture while working or speaking, then listens for the next turn. Pause,
Interrupt, and End controls are always available in the session panel. Talk uses
short response formatting for its own turns and leaves saved settings unchanged.
See [Web Talk](WEB_TALK.md) for controls, browser requirements, task cancellation,
privacy behavior, and troubleshooting.

### Mixed-source attachments

Use the paperclip or drag-and-drop to combine PDFs, UTF-8 text/Markdown notes,
recordings, videos, and analysis images in one request. The shared limit is 6 sources
in cloud mode and 2 in local mode; text files must total at most 100KB.
Each source has its own preview/removal control, and saved references remain
available for follow-up questions after reload. Failed uploads keep the draft
available for retry instead of submitting a partial selection.

See [Mixed-source requests](MIXED_SOURCE_ATTACHMENTS.md) for limits, source
grounding, partial failures, cancellation, retention, and verification steps.

### Video understanding

Attach a video or silent screen recording and ask about visible steps, errors,
or spoken content. Jarvis samples timestamped frames and optionally transcribes
the same interval, with a readable result card and original-source playback.
Follow up about a narrower time range or save the findings to Canvas.
See [Video analysis](tools/video/ANALYSIS.md) for limits, provider selection,
partial results, and setup.

### Existing Audio Attachment Transcription

The regular 📎 attachment picker also accepts AAC, FLAC, M4A, MP3, MP4,
MPEG/MPGA, OGG, WAV, and WebM recordings. Selection alone is local: the file
is uploaded only after Send, inspected server-side, and committed atomically to
Stash. The chat turn receives trusted metadata and an exact `stash://` reference,
then uses `transcribe_audio`; it never treats the filename as a transcript.
The upload includes the visible cloud/local mode and uses the same bounded
size/duration policy as the transcription tool.
Containers with a video stream use video understanding; audio-only containers
continue through transcription.

The browser shows a local, non-autoplaying player while the recording is
selected. After Send, a player for the exact Stash copy sits directly beneath
the user-message bubble; conversation reload restores it from the persisted
attachment metadata.
Generic audio downloaded to Stash by a tool is rendered after the assistant
response. Every player includes an open/download fallback for formats the
browser cannot decode even though the transcription provider accepts them.

This path is separate from push-to-talk and wake-word STT. It uses
`AUDIO_TRANSCRIBE_*` limits/provider policy, supports the same OpenAI-compatible
`/v1/audio/transcriptions` contract, chunks long remote recordings, and saves
the complete transcript back to Stash. See
[Speech-to-Text](SPEECH_TO_TEXT.md#existing-audio-files-transcribe_audio).

Chat only must be off because transcription is a tool action. A host can also
disable `transcribe_audio` in its active tool profile without affecting the mic,
wake-word scripts, or `bin/stt.py`.

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

The web UI has **native image upload** - this is NOT a tool call, it's built directly into the chat. Analyze mode supports multiple images alongside other attachments: up to 6 total sources in cloud mode and 2 in local mode. Image-to-image and image-to-video require exactly one reference image.

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

**Vision provider and model:**

Cloud mode uses the selected provider/model, including Web overrides where
present; choose a model that accepts images. Ollama cloud vision uses
`OLLAMA_CLOUD_MODEL` or an explicit Web model override. Local mode uses Ollama
with `OLLAMA_VISION_MODEL`, falling back to `OLLAMA_MODEL`. See
[Ollama vision configuration](ollama/README.md#vision-and-image-analysis) for
the model-selection rules.

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

### generate_music Tool

Ask Jarvis to create music, then play or download the result inline. The tool
uses the configured music provider, saves audio and Stash references, and records
metadata for later follow-up requests. Provider capabilities and duration limits
differ; choose the provider in **Settings → AI Config** or the selected mode’s env
file.

Use `@generate_music` to apply the shared music-prompt guidance before your own
request. See the [`generate_music` tool guide](tools/generate-music-tool/README.md)
for supported parameters, provider limits, storage, Audio Gallery, and FastAPI use.

---

### analyze_image Tool

A dedicated tool for analyzing images from various sources:

**Supported Sources:**
| Source Type | Example | Description |
|-------------|---------|-------------|
| **URL** | `https://example.com/image.jpg` | Downloads with SSRF protection |
| **Local file** | `/home/user/photo.jpg` | Reads from filesystem |
| **Stash reference** | `stash://space_xxx/file_id` | Loads from stash system |

**Parameters:**
- `image`: URL, file path, or stash reference; required unless `images` is supplied
- `images`: Multiple sources to compare (up to 6 in cloud mode or 2 in local mode); overrides `image`
- `question` (optional): Specific question about the image (default: "Describe this image in detail.")
- `stash_after` (optional): Save URL-sourced images to stash after analysis (default: false)

**Result context:** The answer model receives up to 10,000 characters of image-tool result context. Larger results use a dedicated preview that preserves up to 8,000 characters of analysis alongside source metadata and Stash references, with explicit truncation markers. JSON encoding overhead and provider-specific continuation limits can shorten that preview further. The full canonical tool result remains available locally; screenshot pixel limits are separate and unchanged.

**Security:**
- Uses `safe_download()` from stash_helper for URL downloads
- URL/DNS checks block internal addresses, including Tailscale's `100.64.0.0/10` range, IPv6 unique-local addresses, and IPv4-mapped equivalents; redirects are checked too
- `sanitize_filename()` prevents path traversal attacks
- 20MB max download size

These are outbound download checks. They do not restrict browser/extension access through Tailscale or reading existing `stash://` files. The downloader does not pin DNS across validation and HTTP/proxy connection; see [Stash URL security](STASH_SYSTEM.md#41-url-download-security-redirect-aware-ssrf-protection).

**Example Usage:**
```
"Analyze this image https://example.com/chart.png"
"Compare these images https://example.com/before.png and https://example.com/after.png"
"What's in stash://space_20251218_094432/f_abc123?"
"Analyze ~/photos/vacation.jpg and tell me where it was taken"
```

**When to Use:**
- Web UI image upload: Built-in vision (NOT this tool)
- Analyze URL/file/stash via chat, the Firefox companion, voice, or CLI: Use this tool

---

### 🔄 File Conversion

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
- Additional response detail and tool results omitted from the shortened display text

---

### Proactive Notifications

Routine notices and outbound delivery history are available separately in
**Settings → Notifications**. That tab contains ntfy status/test controls,
source switches, and mode/source-type/channel/state filters. `create_notification`
records a quiet notice without adding an urgent bell item or spoken follow-ups.
History also shows delivery receipts for existing alerts, reminders, and
background tasks; their management stays in the existing interfaces. See
[quiet notifications](tools/notification-tool/README.md). History and local
notification creation do not require FastAPI; delivery uses the independently
supervised worker.

The web UI polls `jarvis-api` (port 8880) for pending alerts and triggered reminders:

**What Gets Notified:**
- **Alerts**: From Uptime Kuma, Coolify, cron scripts, UniFi Protect, etc.
- **Reminders**: Triggered Jarvis reminders; optional Calendar synchronization is configured separately

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
- Reminder timestamps show the scheduled notification time in your browser's local timezone; an appointment time stays in the title or description.
- Click ✓ to acknowledge items
- Acknowledged items leave the pending list; the saved alert or reminder remains available in Memory

**Requirements:**
- `jarvis-api` must be running for notifications to work
- Grant browser notification permission when prompted
- Works with both cloud and local modes (same DB per mode)

---

## Interface capabilities and limits

Jarvis Web provides browser playback, visual results, conversation management,
and hands-free [Talk](WEB_TALK.md). The native voice loop remains the interface
for host wake-word detection. Canvas, Memory, and Intelligence run as separate
applications and open through the shared navigation links.

| Boundary | What to expect |
|----------|----------------|
| Browser microphone | Requires browser permission and a secure context (HTTPS or localhost) |
| Server speakers | Browser playback and host speech are separate outputs |
| Conversation history | Web uses saved JSON chats and its history limit; CLI and native voice use their own context path |
| Multiple clients | Clients on the same Web server share saved chats; there are no separate per-user chat namespaces |
| Service availability | Notifications require the FastAPI service; Canvas and other dashboards require their own running services |

See [Task recovery](WEB_TASK_RECOVERY.md) for reload/reconnect behavior and
[Background tasks](BACKGROUND-TASKS.md) for tools that can finish after the
initial response.

## Composer and connected applications

### Canvas Integration

| Feature | Description |
|---------|-------------|
| **Canvas header icon** | Opens Canvas in a new tab |
| **`/canvas` command** | Researches the supplied query and saves a Canvas page |
| **Send to Canvas button** | Creates a Canvas page from the latest response and supporting conversation context |
| **Inline Canvas preview** | Opens the saved page; previews and matching reply links use the configured browser-reachable Canvas origin |

### @Prompts

**A saved `@prompt` is guidance placed before whatever task you type. The chat
box is still the task, and an empty task is rejected.** Prompt guidance can shape
a video look, music style, review method, or writing format. Select
`@code_review` and paste the code or diff into the same chat input. The saved
text should describe how Jarvis handles the request, not be the whole job. Manage `@prompts` in **Settings → Prompts**, or add Markdown files directly to `jarvis-web/data/prompts/personal/`. If looking for fixed single or multi-step sequences, use `/workflows`.

Type `@` in the chat input to see available prompt guidance.

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
| `@debug` | Evidence-first diagnosis without implied authorization to fix |
| `@generate_music` | ElevenLabs music generation best practices  |
| `@email` | Email drafting; sends only when explicitly requested |
| `/status` | Deterministic daily briefing workflow (replaces the former `@daily`) |
| `/research` | Deterministic deep-research workflow (replaces the former `@deep_research`) |

The former shared `@ssh` prompt is operator-specific. Use `#ssh_remote` directly
or keep host-specific SSH guidance in a private personal prompt.

**Prompt guidance in the request:**
Prompts are injected **BEFORE** the user's message as saved guidance:
```
[CONTEXT - Saved prompt @prompt_name]
[Reusable prompt guidance]
[END SAVED PROMPT]

User's request: [actual message/task]
```
The user's explicit request, current capabilities, tool schemas, and returned data
remain authoritative. Use `/workflows` when a fixed multi-step sequence is required.

#### Shared and personal prompt files

- Shared prompts live in `jarvis-web/data/prompts/*.md` and are committed with the repository.
- Personal prompts live in `jarvis-web/data/prompts/personal/*.md`, are ignored by Git, and can contain machine-specific instructions.
- A personal prompt overrides a shared prompt with the same filename.
- `jarvis-web/data/prompts/personal/README.md` is tracked documentation and is never loaded as `@readme`.
- The Markdown filename is the command name: `personal/social_clip.md` is invoked as `@social_clip your topic`.
- Settings → Prompts lists built-ins, personal prompts, overrides, malformed files,
  and current mode/profile availability. Built-ins remain read-only; saving an
  edit creates a personal override.

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

When two or more hints are present, the prompt remains visible under the existing
group rule and inactive individual hints are filtered by the normal send path.
Settings labels this as reduced or inactive hints; those diagnostics do not change
runtime behavior.

Leave `tool_hints` out of general prompts and prompts that can use several tools or native provider capabilities. This prevents an optional tool from unnecessarily hiding a useful prompt.

Prompt and tool badges are saved as message metadata (`prompt` and `tool_hints`) and reconstructed when conversation history reloads. The badge shows the selectors while the user-message bubble shows only the clean task text.

Prompt changes saved in Settings refresh the current page's `@` registry without a
restart or hard refresh. Personal files are written atomically with private file
permissions where supported. In Docker, Compose bind-mounts only
`jarvis-web/data/prompts/personal/`, so private prompts stay out of the image and
survive container recreation.

See `jarvis-web/data/prompts/personal/README.md` for the short authoring guide.

---

### `#chat_only`: Sticky No-Tools Chat

Use `#chat_only` when you intentionally want a normal conversation without
Tool RAG filling the request context with tool schemas or allowing provider-
hosted tools. This is an explicit Web composer mode; it does not change normal
Auto routing when the mode is off.

**Enable and disable:**

```text
#chat_only
#chat_only Explain why this design feels confusing
Let's continue discussing the tradeoffs #chat_only
```

- Sending `#chat_only` by itself arms the mode without sending a chat message.
- Including it as a standalone token in a request arms the mode and sends the
  clean request.
- A **Chat only** mode chip appears above the composer and remains active for
  subsequent sends in the current page.
- Remove the chip to return to Auto routing. The mode is not a
  `web_config.json` setting; reloading the page resets the live composer toggle.
  Saved messages retain their `#chat_only` badge/provenance when reloaded.

**What remains available:**

- The selected router/system prompt version and model-specific prompt overrides
- The active response style (`auto`, `casual`, or `detailed`) and word limits
- Recent Web conversation history
- Relevant auto-memory context already injected by Jarvis
- Existing model knowledge and reasoning
- An explicitly selected `@prompt` that does not declare `tool_hints` (a
  tool-dependent prompt conflicts with Chat only)
- Plain-text attachment content already supplied to the request

**What is disabled for the turn:**

- Tool RAG retrieval, tool schemas, ghost tools, and learned tool-routing
  insight injection
- Client-side tools, autonomous workflows, and `/workflow` execution
- Provider-hosted tools such as native web/search or code execution
- `#tool` hints, ambient tool suggestions, and the ✨ Enhance path
- Image/PDF/audio analysis and **Send to Canvas**
- Manual/inline LLM Feedback Analysis and random feedback sampling

Image/PDF/audio sends, tool hints, and workflows conflict with Chat only and are
rejected with a toast. A rejected send does not silently arm Chat only or clear
existing tool chips. Turn the mode off first when the task genuinely requires
retrieval, file/vision analysis, an artifact, or an action.

**Completion Guard and Intelligence:**

- Completion Guard still works when enabled. Manual mode may show the normal
  `Completed correctly?` card, and Auto mode may evaluate the answer.
- Its evaluator judges correctness, completeness, reasoning, and support from
  context; it must not penalize the absence of tools or recommend retrieval.
- A repair inherits `tool_policy=none` and remains QA-only. A materially better
  answer can be emitted even though neither pass used tools.
- The normal Intelligence experience is still recorded. Reflection sees
  `tool_policy=none` and `tool_rag_skipped=true`, uses a Chat-only answer-quality
  rubric, and suppresses preferred/avoided tool and workflow associations.
- Passive thumbs up/down reactions remain available while the linked
  experience is eligible for reflection. They are separate from the disabled
  LLM Feedback Analysis feature and do not rerun the task.

**Defense in depth:** the client sends only the recognized value
`tool_policy: "none"`; the socket clears stale tool metadata and rejects
image/PDF/audio payloads; the router supplies zero tool schemas and disables hosted
tools; workflows and learned routing insights are skipped; and the orchestrator
converts any anomalous model-emitted tool route into a non-executing QA response.
The policy and `tool_rag_skipped` state are retained in routing/LLM provenance
for log inspection.

Chat only is therefore appropriate for discussion, brainstorming, explanation,
rewriting, or reasoning from already available context. It is intentionally the
wrong mode for “latest,” “look this up,” file/image inspection, Canvas output,
or any request that needs Jarvis to act on another system.

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
- Uses a separate LLM call; response time depends on the configured provider
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

The composer sends the clean task text and selected prompt/tool metadata to the
server. The server validates selections against the active mode’s available
tools, places reusable prompt guidance and tool hints before the request, and
passes history to the shared orchestrator. Explicit workflows follow their
workflow execution path.

```text
Draft + optional @prompt / #tool hints
  → server validation
  → prompt guidance + task text + conversation history
  → orchestrator → response and artifacts

✨ Enhance
  → separate LLM call → revised draft
  → user reviews and sends normally
```

The saved user message retains the clean task text and selector badges.
Enhancing a draft does not execute tools or send the chat request.

---

### Server Logs Panel

A collapsible panel at the bottom of the UI streams new server log entries for inspection during a request.

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

<a id="logs-read-only-browser-new"></a>

### `/logs` Read-Only Browser

A dedicated page at `/logs` for browsing structured and plain-text logs without leaving Jarvis Web UI.

![Jarvis Logs Viewer with searchable folders and formatted records](images/jarvis-logs-viewer.png)

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

### Manual Feedback Analysis

Trigger LLM-as-QA feedback directly from the WebUI to analyze response quality.

**Two Ways to Trigger:**

1. **📊 Toggle Button** - Click the feedback button (next to ✨ Enhance) to enable for all messages
2. **`--feedback` Inline** - Add `--feedback` anywhere in your message

Random feedback can also be sampled by the orchestrator when `FEEDBACK_RANDOM_ENABLED=true` and `FEEDBACK_RANDOM_CHANCE` is greater than zero. Jarvis Web displays pre-collected random feedback as the normal purple card when Completion Guard is not active; while Completion Guard is active, Web disables the orchestrator random path so only explicit feedback waits behind guard settlement.

Feedback Analysis is unavailable while the sticky **Chat only** chip is active.
Enabling Chat only clears and disables the 📊 toggle; an inline `--feedback`
request is removed before sending, and the socket independently rejects the
feedback flag for `tool_policy=none`. Passive thumbs reactions are unaffected.

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

## ⚠️ Known Issues & Gotchas

### Configuration and mode selection

Web requests use the selected mode’s configuration with request-local overrides.
If behavior differs between Web and CLI, compare **Settings → AI Config** with
that mode’s env defaults, and check **Settings → Tools** for Web-specific blocks.
Reset Web overrides to use the env defaults again.

For contributors, preserve the request-local configuration scope before creating
or invoking the orchestrator. Read settings through the shared config helpers;
child tools receive exported overrides. See
[Request scopes](#request-scopes-and-jarvis_override_-child-exports).

### Native Search (XAI_SEARCH / ANTHROPIC_SEARCH)

Provider-native search requires a supporting model, enabled provider settings,
and a request that allows tools. Jarvis supplies routing guidance when the
capability is enabled, but the model may still choose a Jarvis search tool.
Inspect native-tool metadata in the LLM logs to confirm which path ran; an empty
Jarvis `tools_used` list alone does not prove a native search happened.

### Mode Switching

| Issue | Check |
|-------|-------|
| Settings appear stale | Reopen Settings and verify the selected mode |
| Expected tool is absent | Check the mode’s profile, required configuration, and Web block list |
| Semantic retrieval is unavailable | Check embedding health; both modes must match the shared embedding contract |

### TTS
| Issue | Workaround |
|-------|------------|
| Local TTS fails silently | Check the selected provider server is running at `KOKORO_TTS_URL` or `QWEN3_TTS_URL` |
| Audio doesn't play | Check browser autoplay policy, click somewhere first |
| TTS too slow | Check provider latency; status speech has its own deadline and cache, separate from final-answer audio |

### Tools
| Issue | Workaround |
|-------|------------|
| Tool not found | Refresh tools list, check if blocked |
| MCP tool missing | Ensure MCP server ran at least once (registers to memory_db) |
| `generate_image` timeout | Check tool logs and provider status before retrying; a timeout does not prove remote work stopped |

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
| WebSocket disconnects | Reconnect and reopen the conversation to recover server-owned work; see [Task recovery](WEB_TASK_RECOVERY.md) |
| Memory usage grows | Refresh page periodically for long sessions |

---

## ⚖️ Web vs Terminal: Key Differences

| Aspect | Terminal/TUI/Jarvis | Web UI |
|--------|---------------------|--------|
| **Conversation History** | `memory_db` + `AUTO_CONTEXT_*` (cloud.env, local.env) | JSON files + `conversation.history_limit` (web_config.json) |
| **LLM Provider** | `.env` file (restart to change) | `web_config.json` per-mode (on-the-fly) |
| **Tool availability** | Active manifest/profile and mode configuration | Same gates plus Web `tools.blocked` restrictions |
| **Status Updates** | Local speaker with cancellable cached playback | Browser WebSocket + optional cancellable cached TTS |
| **TTS** | Mode-specific shell scripts | Direct provider API; status cache is separate from final TTS |
| **Intelligence/Insights** | ✅ Full (same orchestrator) | ✅ Shared learning system; mode-specific data |
| **Tool RAG** | ✅ Full | ✅ Full |
| **Chat only** | Not exposed as a sticky composer mode | ✅ `#chat_only` request policy |
| **Memory System** | ✅ Full (mode-specific DB) | ✅ Full (mode-specific DB) |
| **MCP Tools** | Configured runtime servers and effective tool catalog | Same catalog and mode/profile gates, with Web-specific blocking |

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
