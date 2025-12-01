# Jarvis Canvas System

A beautiful visual viewer for rich content that Jarvis can populate. Think of it as a personal wiki/knowledge canvas that Jarvis writes to when displaying complex information.

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

## Tool Usage

### Actions

| Action | Description | Required Params |
|--------|-------------|-----------------|
| `create` | New page | `title`, `content` |
| `update` | Modify existing | `page_id` |
| `delete` | Remove page | `page_id` |
| `list` | Show all pages | None |
| `open` | Get canvas URL | None |

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
- **Pinned section** - Important pages at top
- **All pages** - Chronological list
- **Search** - Full-text search (Ctrl+K)

### Page View
- **Markdown rendering** - Headers, lists, tables, blockquotes
- **Syntax highlighting** - Code blocks with language detection
- **Source query** - Shows what user asked
- **Edit/Delete** - Modify or remove pages
- **Pin toggle** - Keep important pages accessible

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
| `docs/CANVAS_SYSTEM.md` | This documentation |

---

**Version:** 1.0  
**Last Updated:** 2024-12-01

