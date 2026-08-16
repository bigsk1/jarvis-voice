# Jarvis Memory Browser 🧠

A web-based interface for viewing, searching, and managing Jarvis's memory database.

![memory-browser](../docs/images/memory-browser.jpg)

## Features

- **Memory Management**: View, add, edit, delete memories in `knowledge_base`
- **FTS5 Search**: Fast full-text search with BM25 ranking (no LLM required)
- **Intel File Manager**: Manage `.md`/`.txt` files in `jarvis-intel/`
  - Create, edit, delete intel files
  - Upload `.md` and `.txt` files with validation
  - Ingest all files to knowledge base
- **Conversation Viewer**: Browse conversation history with full detail popup
- **Reminders Manager**: View pending/triggered/acknowledged reminders with local-time display, filters, sorting, acknowledge, cancel, edit, delete, and friendly daily/weekly/monthly recurrence controls
- **Scheduled Tasks Manager**: Create, inspect, update, run-now, cancel, delete, and review recent scheduled task runs
- **Alerts Manager**: Server-backed status/severity/search filters with lazy loading for older alerts
- **Background Alert Indicator**: Shows pending-alert counts in the browser title/favicon, flashes for newly observed alerts, and offers an optional default-off ding on the Alerts screen
- **Statistics Dashboard**: Database stats, category breakdown, embedding health
- **Dual Database Support**: Switch between cloud and local modes
- **Memory Health Indicators**: Size badges (S/M/L/XL), missing embedding warnings ⚠️
- **Re-embed Support**: Re-generate embeddings after manual edits
- **Mobile Responsive**: Hamburger menu, slide-out sidebar at ≤730px

## Quick Start

```bash
# Activate virtual environment
source ~/jarvis-venv/bin/activate

# Run the server
./bin/jarvis-memory

# Load auth/runtime settings from config/local.env
./bin/jarvis-memory local

# Or with options
./bin/jarvis-memory --port 5002 --debug
```

Open http://localhost:5002 in your browser (or your server IP).

## Database Modes

| Mode | Database | Embeddings |
|------|----------|------------|
| Cloud | `data/jarvis_memory.db` | Ollama Jarvis Embedding (768D) |
| Local | `data/jarvis_memory_local.db` | Ollama Jarvis Embedding (768D) |

Use the mode selector in the header to switch databases.

Startup env mode and database mode are separate. On a first visit, the UI uses
the server's `startup_mode`; an explicit `?mode=cloud|local` URL or saved browser
preference takes precedence. Starting locally also initializes a pristine local
Memory database before requests are served.

## UI Features

### Memory Cards
- **Size Badge**: S (small), M (medium), L (large), XL (extra large) based on value length
- **Embedding Status**: 📊 icon if embedding exists, ⚠️ warning if missing
- **Actions**: Edit ✏️, Delete 🗑️, Re-embed 🔄 (for memories without embeddings)

### Search
- **Dynamic Placeholder**: Changes based on active tab (memories, intel, conversations, reminders, scheduled)
- **FTS5 Powered**: Fast keyword search without LLM calls
- **Real-time**: Results update as you type

### Intel Upload
- Supports `.md` and `.txt` files
- Basic content validation (no binary files)
- Follows `jarvis-intel/README.md` guidelines

### Mobile Responsive (≤730px)
- Hamburger menu (☰) in header
- Slide-out sidebar with categories
- Compact navigation tabs
- Touch-friendly buttons

## API Endpoints

### Memories
- `GET /api/memories` - List memories
- `GET /api/memories/<id>` - Get single memory
- `GET /api/memories/search?q=<query>` - FTS5 search
- `POST /api/memories` - Create memory
- `PUT /api/memories/<id>` - Update memory
- `DELETE /api/memories/<id>` - Delete memory
- `POST /api/memories/<id>/reembed` - Re-generate embedding
- `GET /api/memories/categories` - List categories

### Intel Files
- `GET /api/intel/files` - List files
- `GET /api/intel/files/<filename>` - Get file content
- `PUT /api/intel/files/<filename>` - Update file
- `POST /api/intel/files` - Create file
- `POST /api/intel/upload` - Upload file(s)
- `DELETE /api/intel/files/<filename>` - Delete file
- `POST /api/intel/ingest` - Trigger intel ingestion

### Conversations
- `GET /api/conversations` - List conversations
- `GET /api/conversations/<id>` - Get conversation detail
- `GET /api/conversations/search?q=<query>` - Search

### Reminders
- `GET /api/reminders` - List reminders
- `GET /api/reminders/<id>` - Get one reminder
- `POST /api/reminders` - Create reminder
- `PUT /api/reminders/<id>` - Update reminder
- `DELETE /api/reminders/<id>` - Cancel reminder
- `DELETE /api/reminders/<id>?permanent=true` - Permanently delete reminder
- `POST /api/reminders/<id>/acknowledge` - Acknowledge one triggered reminder
- `POST /api/reminders/acknowledge-all?status=triggered` - Acknowledge all matching reminders

### Scheduled Tasks
- `GET /api/scheduled-tasks` - List scheduled tasks
- `GET /api/scheduled-tasks/<id>` - Get one scheduled task
- `POST /api/scheduled-tasks` - Create task
- `PUT /api/scheduled-tasks/<id>` - Update task
- `DELETE /api/scheduled-tasks/<id>` - Cancel task
- `DELETE /api/scheduled-tasks/<id>?permanent=true` - Permanently delete task and run history
- `POST /api/scheduled-tasks/<id>/run` - Queue task to run now
- `GET /api/scheduled-tasks/<id>/runs` - List recent run history

### Stats
- `GET /api/stats` - Full statistics
- `GET /api/status` - Health check, `startup_mode`, and cloud/local DB paths

All endpoints accept `?mode=cloud|local` query parameter.

## Re-embedding Memories

After editing a memory's text, re-generate its embedding:

```bash
# Via CLI
./bin/re-embed-memory <id> [mode]
./bin/re-embed-memory 42 cloud
./bin/re-embed-memory 42 local

# Via API
curl -X POST "http://localhost:5002/api/memories/42/reembed?mode=cloud"

# Via UI
# Click the 🔄 button on memories with ⚠️ warning
```

## Architecture

```
jarvis-memory/
├── client/               # Frontend (HTML/CSS/JS)
│   ├── index.html        # Main UI with modals
│   ├── css/
│   │   ├── variables.css # Shared theme variables
│   │   └── memory.css    # Custom styles + responsive
│   └── js/
│       ├── api.js        # API client functions
│       └── app.js        # Main app logic
├── server/               # Backend (Flask)
│   ├── app.py            # Flask app setup
│   ├── routes/           # API route handlers
│   │   ├── memories.py
│   │   ├── intel.py
│   │   ├── conversations.py
│   │   ├── reminders.py
│   │   ├── scheduled_tasks.py
│   │   └── stats.py
│   └── services/
│       └── memory_service.py  # Database operations
└── requirements.txt
```

## Dashboard Integration

The Memory Browser is integrated into `jarvis-dashboard`:

```bash
./bin/jarvis-dashboard

# Under 🔧 Services:
#   - Start Memory UI
#   - Memory UI Health
#   - Memory UI Stats

# Under 💾 Memory:
#   - Re-embed Memory
#   - Open Memory Browser
```

## Theme

Uses the same dark theme as `jarvis-web` with purple/cyan accents:
- Shared `variables.css` for consistent colors
- Purple accent for memory-related elements
- Mobile-first responsive design

## Links

From Memory Browser:
- 🤖 **Jarvis** → Opens Jarvis Web UI (:5001)

From other UIs:
- 🧠 icon in `jarvis-web` header → Opens Memory Browser
- 🧠 icon in `jarvis-canvas` header → Opens Memory Browser
