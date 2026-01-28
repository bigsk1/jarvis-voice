# Jarvis Canvas System

A beautiful visual viewer for rich content that Jarvis can populate. Think of it as a personal wiki/knowledge canvas that Jarvis writes to when displaying complex information.

**Includes:** Canvas Pages + Image Gallery

## Overview



![jarvis-canvas](images/jarvis-canvas.jpeg)

## Quick Start

### 1. Start the Canvas Server

```bash
# Basic start
./bin/jarvis-canvas

# Custom port
./bin/jarvis-canvas --port 8890

# Debug mode
./bin/jarvis-canvas --debug
```

### 2. Open in Browser

Navigate to: `http://localhost:8890`

### 3. Ask Jarvis to Save Content

```
You: "Research the top 3 databases for time series data and save to canvas"
You: "Put my server IPs in the canvas"
You: "Save that code snippet to my canvas"
```

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Jarvis    │────▶│ Canvas Tool  │────▶│   Canvas    │
│ Orchestrator│     │ (canvas.py)  │     │   Server    │
└─────────────┘     └──────────────┘     └─────────────┘
                           │                    │
                           ▼                    ▼
                    ┌─────────────┐     ┌─────────────┐
                    │   Memory    │     │ data/canvas │
                    │   Database  │     │  (JSON)     │
                    └─────────────┘     └─────────────┘
```

### Components

| Component | Location | Purpose |
|-----------|----------|---------|
| **Canvas Server** | `bin/jarvis-canvas` | Flask web server with beautiful dark UI |
| **Canvas Tool** | `skills/canvas.py` | Tool for Jarvis to create/manage pages |
| **Page Storage** | `data/canvas/*.json` | JSON files for each page |
| **Memory Integration** | Automatic | Pages saved to Jarvis memory for recall |

## Configuration

### Default Settings

| Setting | Value | Description |
|---------|-------|-------------|
| Port | `8890` | Web server port |
| Host | `0.0.0.0` | Bind address |
| Data Dir | `data/canvas/` | Page storage location |

### Environment Variables

None required. Canvas uses defaults.

## Image Gallery

The canvas server includes an integrated image gallery for browsing generated images.

### Access
- **URL:** `http://localhost:8890/gallery`
- **Navigation:** Click "🖼️ Gallery" in canvas header, or "📝 Canvas" in gallery header

### Features
- **Thumbnail grid** with lazy loading
- **Lightbox view** - click any image to enlarge
- **Search** - filter by filename
- **Sort** - by date, name, or size
- **Download** - save images locally
- **Delete** - remove unwanted images
- **Keyboard shortcuts:**
  - `Escape` - close lightbox
  - `←` / `→` - navigate between images

### Source Directory
Images are served from: `data/generated_images/`

This is where the `generate_image` tool saves AI-generated images.

## API Reference

### Health Check

```bash
curl http://localhost:8890/api/health
```

Response:
```json
{
  "status": "healthy",
  "service": "jarvis-canvas",
  "pages": 5,
  "timestamp": "2024-12-01T14:30:22Z"
}
```

### List Pages

```bash
curl http://localhost:8890/api/pages
```

### Create Page

```bash
curl -X POST http://localhost:8890/api/pages \
  -H "Content-Type: application/json" \
  -d '{
    "title": "My Research",
    "content": "## Results\n\n- Item 1\n- Item 2",
    "tags": ["research", "reference"],
    "source_query": "research databases"
  }'
```

### Update Page

```bash
curl -X PUT http://localhost:8890/api/pages/page_20241201_143022 \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Updated Title",
    "pinned": true
  }'
```

### Delete Page

```bash
curl -X DELETE http://localhost:8890/api/pages/page_20241201_143022
```

### Download Page  (Jan 2026)

Export a page as JSON or Markdown:

```bash
# Download as JSON (default)
curl http://localhost:8890/api/pages/page_20241201_143022/download

# Download as Markdown with frontmatter
curl "http://localhost:8890/api/pages/page_20241201_143022/download?format=markdown"
```

Markdown format includes frontmatter:
```markdown
---
title: My Research Page
id: page_20241201_143022
created: 2024-12-01T14:30:22
updated: 2024-12-01T15:45:00
tags: ["research", "reference"]
pinned: false
---

## Content here...
```

### Upload/Import Page  (Jan 2026)

Import a page from JSON:

```bash
# Create new page
curl -X POST http://localhost:8890/api/pages/upload \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Imported Page",
    "content": "## Imported Content\n\nHello world!",
    "tags": ["imported"]
  }'

# Force new page even if ID exists
curl -X POST http://localhost:8890/api/pages/upload \
  -H "Content-Type: application/json" \
  -d '{
    "id": "page_20241201_143022",
    "title": "Re-imported",
    "content": "...",
    "force_new": true
  }'
```

Response:
```json
{
  "action": "created",  // or "updated" if ID matched
  "page": { ... }
}
```

## Tool Usage

### Actions

| Action | Description | Required Params |
|--------|-------------|-----------------|
| `create` | New page | `title`, `content` |
| `update` | Modify existing | `page_id` |
| `delete` | Remove page | `page_id` |
| `list` | Show all pages | None |
| `open` | Get canvas URL | None |
| `read` | Get page content  | `page_id` or `search` |

### Example Tool Calls

**Create a research page:**
```json
{
  "action": "create",
  "title": "Top Time-Series Databases",
  "content": "## Comparison\n\n| Database | Performance | Ease of Use |\n|----------|------------|-------------|\n| InfluxDB | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |\n| TimescaleDB | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |",
  "tags": ["research", "databases"],
  "source_query": "best databases for time series"
}
```

**List pages:**
```json
{
  "action": "list",
  "limit": 5
}
```

**Delete a page:**
```json
{
  "action": "delete",
  "page_id": "page_20241201_143022"
}
```

## Page Data Structure

```json
{
  "id": "page_20241201_143022",
  "title": "Top 3 Movies - Dec 2024",
  "content": "## Movies\n\n### 1. Movie Name\n...",
  "content_type": "markdown",
  "tags": ["movies", "entertainment"],
  "source_query": "Find the top 3 movies right now",
  "created": "2024-12-01T14:30:22Z",
  "updated": "2024-12-01T15:45:00Z",
  "pinned": false
}
```

## UI Features

### Dark Theme
Professional dark UI with:
- Space Grotesk font for UI
- JetBrains Mono for code
- GitHub Dark syntax highlighting

### Sidebar
- **Pinned section** - Important pages at top (shows when pinned pages exist)
- **Folders section** - Auto-grouped by title prefix (e.g., "Phone Calls/", "System Prompt Suggestion")
- **Pages section** - Ungrouped pages
- **Search** - Full-text search (Ctrl+K)

### Folder Organization
Pages are automatically grouped into folders based on their title using `/` as separator:
- `Phone Calls/2025-12-14...` → 📁 **Phone Calls** folder
- `Workflows/Archive/bigsk1.com` → 📁 **Workflows/Archive** folder (nested!)
- `System Prompt Suggestion...` → No folder (no `/` in title)

**Important:** Titles with URLs (containing `://`) are NOT treated as folders:
- `Archive: https://bigsk1.com` → NOT a folder (URL detected)
- `Workflows/Archive/bigsk1.com` → Proper folder structure ✅

**Folder features:**
- Click folder to expand/collapse
- Shows page count badge
- Auto-expands when active page is inside
- Folders sorted alphabetically, always at top
- Supports nested folders (e.g., `Workflows/Archive/page`)

**Workflow Organization:**
Workflows create canvas pages with folder structure:
| Workflow | Canvas Title Pattern |
|----------|---------------------|
| `/archive` | `Workflows/Archive/{domain}` |
| `/research` | `Workflows/Research/{topic}` |
| `/crypto` | `Workflows/Crypto/{date}` |

### Page View
- **Markdown rendering** - Headers, lists, tables, blockquotes
- **Syntax highlighting** - Code blocks with language detection
- **Source query** - Shows what user asked
- **Edit/Delete** - Modify or remove pages
- **Pin toggle** - Keep important pages accessible (also pins referenced stash images)
- **Print button** - Print current page using browser print dialog (🖨️)

### Pinning and Image Preservation

When you **pin a canvas page**, any stash images referenced in that page are automatically pinned too. This prevents the images from being cleaned up by the stash TTL expiration (default 7 days).

**How it works:**
- Canvas pages embed images as `![img](stash://space_xxx/file.jpg)`
- When you click the pin button, the canvas server extracts all `stash://` references
- Each referenced stash space is automatically pinned (`pinned: true` in meta.json)
- Pinned stash spaces never expire, so your images stay intact

**Note:** Unpinning a page does NOT auto-unpin the stash spaces (to avoid breaking other pages that may reference them). To unpin stash spaces, use the stash tool directly.

### Print Support
Click the 🖨️ button to print a page:
- Uses browser's native print dialog
- Hides sidebar, header, and action buttons
- Clean black-on-white output
- Code blocks formatted with borders

### Live Reload
Pages auto-refresh every 2 seconds when new content is added.

## Integration with Jarvis

### When Jarvis Uses Canvas

1. **Research results** - Multi-item comparisons, detailed findings
2. **Code snippets** - Scripts, configs with syntax highlighting
3. **Server/network info** - IP tables, connection details
4. **Reference material** - Documentation, how-tos
5. **Explicit requests** - "Save to canvas", "Put in viewer"

### Memory Integration

Every canvas page is automatically saved to Jarvis memory:
- Key: `canvas_page_{id}`
- Category: `canvas`
- Importance: 6

This allows Jarvis to recall canvas pages later:
```
You: "What's in my canvas about databases?"
Jarvis: [searches memory, finds canvas_page_xxx]
        "You have a comparison of time-series databases saved. Check your canvas."
```

### Fallback Behavior

If canvas server is down:
- Tool returns error gracefully
- Jarvis continues with other tasks
- No crash or hang
- User informed to start canvas

## Running as Service

### Manual Start
```bash
./bin/jarvis-canvas &
```

### With tmux (recommended)
```bash
tmux new-session -d -s jarvis-canvas "./bin/jarvis-canvas"

# Attach to see output
tmux attach -t jarvis-canvas

# Detach: Ctrl+B, then d
```

### Future: systemd Service
```ini
# /etc/systemd/system/jarvis-canvas.service
[Unit]
Description=Jarvis Canvas Server
After=network.target

[Service]
Type=simple
User=boss
WorkingDirectory=/home/boss/jarvis-voice
ExecStart=/home/boss/jarvis-venv/bin/python /home/boss/jarvis-voice/bin/jarvis-canvas
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Dashboard Integration

Add to `jarvis-dashboard`:
```python
Command("Start Canvas", "./bin/jarvis-canvas", "Visual knowledge viewer", "🔧 Services", interactive=True),
Command("Canvas Health", "curl -sf http://localhost:8890/api/health | jq", "Canvas status", "📊 Monitor"),
```

## Future Enhancements

### Recently Added (Jan 2026)

- [x] **Download/Upload API** - Export pages as JSON/Markdown, import from JSON
- [x] **Nested folders** - Support `Workflows/Archive/page` structure
- [x] **URL-aware folders** - Titles with `://` don't create broken folders
- [x] **Workflow organization** - Workflows create pages in `Workflows/{type}/` folders

### Previously Added (Dec 2025)

- [x] **Folder organization** - Auto-group pages by title prefix
- [x] **Print support** - Browser print dialog with clean output
- [x] **Image lightbox** - Click images to view full size
- [x] **Wider sidebar** - 350px width, resizable
- [x] **Hover tooltips** - See full page title on hover
- [x] **Web UI integration** - Canvas icon in jarvis-web header

---

## Web UI + Canvas + Stash Integration

### Current Integration (Dec 2025)

| Feature | Status | Description |
|---------|--------|-------------|
| **Canvas icon in header** | ✅ Done | Click 📄 in web UI header to open Canvas |
| **Image support** | ✅ Done | Markdown images render with lightbox |

### Planned Features

#### `/canvas` Command (Web UI)
Type `/canvas` in the web UI chat to send content directly to Canvas:
```
/canvas Research the best Node.js frameworks
/canvas [with attached image] Create a blog post about this
```

#### Save to Canvas Button
Add button on assistant messages to save response to Canvas:
- Preserves markdown formatting
- Includes images from stash
- Auto-names based on query

#### Canvas + Stash Flow
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Web UI    │────▶│    Stash    │────▶│   Canvas    │
│  (upload)   │     │  (staging)  │     │  (publish)  │
└─────────────┘     └─────────────┘     └─────────────┘
```

**Workflow:**
1. User uploads image → goes to Stash (temp storage)
2. User says "save this to canvas" → Stash ref copied to Canvas
3. Canvas renders from stash:// URL or copies to permanent storage

#### Image in Canvas Pages
Canvas pages can include images via:
```markdown
## Blog Post Title

![Hero Image](http://localhost:8890/images/hero.jpg)

Content goes here...
```

Or with stash references:
```markdown
![Uploaded Image](stash://space_xxx/file_id)
```

### Implementation Notes

**Canvas Page with Image (JSON):**
```json
{
  "id": "page_20251218_xxx",
  "title": "Blog Post Title",
  "content": "![Hero](http://localhost:8890/images/hero.jpg)\n\n## Content...",
  "images": ["stash://space_xxx/file_id"],  // Optional: track stash refs
  "hero_image": "/images/hero.jpg"           // Optional: dedicated hero
}
```

**Canvas API for Images:**
```bash
# Create page with image
POST /api/pages
{
  "title": "My Blog Post",
  "content": "...",
  "hero_image": "stash://space_xxx/file_id"  # Resolved to URL
}
```

### Planned Features

- [ ] **Command Center** - System status dashboard
- [ ] **Service monitors** - API health widgets
- [ ] **"Explain this" button** - Ask Jarvis about content
- [ ] **Export** - Download as PDF/HTML
- [ ] **Share** - Generate shareable links
- [ ] **Templates** - Pre-defined page layouts
- [ ] **Dark/Light toggle** - Theme switching
- [ ] **Keyboard navigation** - Arrow keys, shortcuts
- [ ] **Drag-drop reorder** - Manual page ordering

### Health Injection (Future)

Canvas status in system prompt:
```python
# In orchestrator startup
canvas_health = check_canvas_health()
system_prompt += f"\nCanvas: {'✅ running' if canvas_health else '❌ offline'}"
```

## Troubleshooting

### Canvas won't start

```bash
# Check if port is in use
lsof -i :8890

# Check for Python errors
./bin/jarvis-canvas --debug
```

### Pages not appearing

```bash
# Check data directory
ls -la data/canvas/

# Check API directly
curl http://localhost:8890/api/pages | jq
```

### Memory not saving

```bash
# Check memory entries
sqlite3 data/jarvis_memory.db "SELECT * FROM knowledge_base WHERE category='canvas'"
```

## File Locations

| File | Purpose |
|------|---------|
| `bin/jarvis-canvas` | Server script |
| `skills/canvas.py` | Tool implementation |
| `skills/canvas.tool.json` | Tool definition |
| `data/canvas/*.json` | Page storage |
| `api/routes/canvas.py` | FastAPI routes  |
| `docs/CANVAS_SYSTEM.md` | This documentation |

---

## Two API Systems

Canvas has **two separate API systems** for different use cases:

### 1. Canvas Server API (Port 8890)
The internal Flask server for the Canvas web UI viewer.

```bash
# Health check
curl http://localhost:8890/api/health

# List pages (for web UI)
curl http://localhost:8890/api/pages

# Create/Update/Delete pages
POST/PUT/DELETE http://localhost:8890/api/pages/{id}
```

**Used by:**
- Canvas tool (`skills/canvas.py`) for create/update/delete
- Canvas web viewer (localhost:8890)

### 2. Jarvis FastAPI (Port 8880)  (Jan 2026)
Read-only API for external integrations, scripts, and programmatic access.

```bash
# Statistics
curl http://localhost:8880/api/canvas/stats
# → {total_pages, total_size_human, by_tag, by_tool}

# List pages with filters
curl "http://localhost:8880/api/canvas?limit=20&tag=status"

# Search pages
curl "http://localhost:8880/api/canvas/search?q=bitcoin"

# Get recent pages
curl "http://localhost:8880/api/canvas/recent?limit=5"

# List all tags
curl http://localhost:8880/api/canvas/tags

# List source tools
curl http://localhost:8880/api/canvas/tools

# Get specific page with content
curl http://localhost:8880/api/canvas/page_20260115_175126
```

**Used by:**
- n8n workflows
- External scripts and integrations
- Jarvis Dashboard TUI (API section)
- Monitoring and debugging

### When to Use Which

| Use Case | API | Port |
|----------|-----|------|
| Canvas web viewer | Canvas Server | 8890 |
| Create/update/delete pages | Canvas Server | 8890 |
| `canvas` tool (skills/canvas.py) | Canvas Server | 8890 |
| External integrations (n8n) | FastAPI | 8880 |
| Programmatic queries | FastAPI | 8880 |
| Monitoring/debugging | FastAPI | 8880 |
| Dashboard TUI commands | FastAPI | 8880 |

See: `docs/api/CANVAS.md` for full FastAPI documentation.

---

## Tool Read Action  (Jan 2026)

The canvas tool now supports reading pages back:

```json
// Read most recent page
{"action": "read"}

// Read by page ID
{"action": "read", "page_id": "page_20260115_175126"}

// Search by keyword
{"action": "read", "search": "bitcoin"}
```

**Use cases:**
- Verify a page was created correctly
- Read back content for troubleshooting
- Find pages by keyword
- Self-correction workflows (read → update)

**Fallback behavior:**
- Tries Canvas server API first (port 8890)
- Falls back to direct file access if server is down
- Works even when canvas viewer isn't running

---

**Version:** 1.3  
**Last Updated:** 2026-01-22

