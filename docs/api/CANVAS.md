# 📄 Canvas API

> Read and safely modify Jarvis canvas pages - markdown documents with embedded images.

## Overview

The Canvas API provides access to pages created by Jarvis tools (status recaps, reports, transcripts, etc.). Each page is a markdown document that may contain embedded stash images.

**Base URL:** `http://localhost:8880/api/canvas`

---

## Quick Start

```bash
# Get canvas statistics
curl http://localhost:8880/api/canvas/stats

# List recent pages
curl http://localhost:8880/api/canvas/recent

# Search pages
curl "http://localhost:8880/api/canvas/search?q=bitcoin"

# Get a specific page
curl http://localhost:8880/api/canvas/page_20260115_175126

# Append a section without replacing existing content
curl -X POST http://localhost:8880/api/canvas/page_20260115_175126/append \
  -H 'Content-Type: application/json' \
  -d '{"content":"## New Findings\n\nAdditional details."}'
```

---

## Endpoints

### Get Statistics

```http
GET /api/canvas/stats
```

Get overall canvas statistics.

**Response:**
```json
{
  "total_pages": 20,
  "total_size_bytes": 37138,
  "total_size_human": "36.3 KB",
  "pages_with_images": 4,
  "by_tool": {},
  "by_tag": {
    "status": 3,
    "recap": 3,
    "daily": 3,
    "bitcoin": 2,
    "crypto": 2
  },
  "oldest_page": "2025-12-15T06:13:46.253898Z",
  "newest_page": "2026-01-16T01:51:26.879412Z"
}
```

---

### List Pages

```http
GET /api/canvas
GET /api/canvas?limit=50&offset=0
```

List canvas pages with pagination and filters.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 50 | Results per page (1-200) |
| `offset` | int | 0 | Skip N results |
| `tag` | string | - | Filter by tag |
| `tool` | string | - | Filter by source_tool |
| `search` | string | - | Search title/content |

**Examples:**
```bash
# List all (paginated)
curl "http://localhost:8880/api/canvas?limit=20"

# Filter by tag
curl "http://localhost:8880/api/canvas?tag=status"

# Filter by tool
curl "http://localhost:8880/api/canvas?tool=status_recap"

# Search
curl "http://localhost:8880/api/canvas?search=bitcoin"
```

**Response:**
```json
{
  "ok": true,
  "count": 3,
  "total": 20,
  "pages": [
    {
      "page_id": "page_20260115_175126",
      "title": "Daily Status/2026-01-15 Recap",
      "created_at": "2026-01-16T01:51:26.879412Z",
      "tags": ["status", "recap", "daily"],
      "content_preview": "![Status Dashboard]...",
      "content_length": 1209,
      "embedded_images": ["stash://space_20260116_015125_2bbe1cd5/f_96fa09b1f061"]
    }
  ]
}
```

---

### Get Recent Pages

```http
GET /api/canvas/recent?limit=10
```

Get most recently created pages.

---

### Search Pages

```http
GET /api/canvas/search?q={query}
```

Search by title or content text.

**Examples:**
```bash
# Search for bitcoin mentions
curl "http://localhost:8880/api/canvas/search?q=bitcoin"

# Search for phone calls
curl "http://localhost:8880/api/canvas/search?q=phone%20call"
```

---

### List Tags

```http
GET /api/canvas/tags
```

Get all unique tags with counts.

**Response:**
```json
{
  "ok": true,
  "count": 14,
  "tags": {
    "status": 3,
    "recap": 3,
    "daily": 3,
    "bitcoin": 2,
    "crypto": 2
  }
}
```

---

### List Tools

```http
GET /api/canvas/tools
```

Get all source tools with counts.

**Response:**
```json
{
  "ok": true,
  "count": 2,
  "tools": {
    "status_recap": 3,
    "phone_call": 2
  }
}
```

---

### Get Page

```http
GET /api/canvas/{page_id}
GET /api/canvas/{page_id}?include_content=true
```

Get a specific canvas page by ID.

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `include_content` | bool | true | Include full markdown content |

**Response:**
```json
{
  "ok": true,
  "page": {
    "page_id": "page_20260115_175126",
    "title": "Daily Status/2026-01-15 Recap",
    "created_at": "2026-01-16T01:51:26.879412Z",
    "updated_at": "2026-01-16T01:51:26.879412Z",
    "tags": ["status", "recap", "daily"],
    "source_tool": null,
    "content_preview": "![Status Dashboard]...",
    "content_length": 1209,
    "embedded_images": ["stash://space_20260116_015125_2bbe1cd5/f_96fa09b1f061"],
    "content": "# Full markdown content here..."
  }
}
```

---

### Create Page

```http
POST /api/canvas
```

Creates a new page from `title`, complete Markdown `content`, optional `tags`, and optional `source_tool`.

### Append to Page

```http
POST /api/canvas/{page_id}/append
```

Adds the supplied Markdown to the end of an existing page. The server preserves the existing content; callers send only the new section.

```json
{
  "content": "## YouTube Videos\n\n- [Harvesting Hazelnuts](https://www.youtube.com/watch?v=example)"
}
```

### Replace or Edit Page

```http
PUT /api/canvas/{page_id}
```

Updates provided fields. The `content` field is a full replacement. Suspicious large shrinkage returns HTTP `409`; set `allow_content_shrink: true` only for an intentional shorter rewrite. Use the append endpoint for additions.

### Delete Page

```http
DELETE /api/canvas/{page_id}
```

Deletes the specified page.

---

## Page Fields

| Field | Type | Description |
|-------|------|-------------|
| `page_id` | string | Unique identifier (e.g., `page_20260115_175126`) |
| `title` | string | Page title |
| `created_at` | string | Creation timestamp (ISO 8601) |
| `updated_at` | string | Last update timestamp |
| `tags` | array | Page tags/categories |
| `source_tool` | string | Tool that created the page |
| `content_preview` | string | First 500 characters |
| `content_length` | int | Total content length |
| `embedded_images` | array | List of `stash://` references |
| `content` | string | Full markdown content (when included) |

---

## Embedded Images

Canvas pages can contain embedded images using stash references:

```markdown
![Status Dashboard](stash://space_20260116_015125_2bbe1cd5/f_96fa09b1f061)
```

To download these images, use the Stash API:

```bash
# Extract space_id and file_id from the stash:// URL
# stash://space_20260116_015125_2bbe1cd5/f_96fa09b1f061
#         ^-------------------------^ ^--------------^
#                space_id                  file_id

curl -o image.jpg \
  "http://localhost:8880/api/stash/space/space_20260116_015125_2bbe1cd5/file/f_96fa09b1f061/download"
```

---

## Integration Examples

### Python

```python
import requests
import re

BASE_URL = "http://localhost:8880/api/canvas"
STASH_URL = "http://localhost:8880/api/stash"

def list_recent_pages(limit=10):
    """Get recent canvas pages."""
    response = requests.get(f"{BASE_URL}/recent", params={"limit": limit})
    return response.json().get("pages", [])

def get_page_content(page_id):
    """Get full page content."""
    response = requests.get(f"{BASE_URL}/{page_id}")
    data = response.json()
    return data.get("page", {}).get("content", "")

def download_embedded_images(page_id, output_dir="."):
    """Download all embedded images from a page."""
    response = requests.get(f"{BASE_URL}/{page_id}")
    page = response.json().get("page", {})
    
    for ref in page.get("embedded_images", []):
        # Parse stash://space_id/file_id
        match = re.match(r'stash://([^/]+)/(.+)', ref)
        if match:
            space_id, file_id = match.groups()
            img_response = requests.get(
                f"{STASH_URL}/space/{space_id}/file/{file_id}/download"
            )
            filename = f"{output_dir}/{file_id}.jpg"
            with open(filename, 'wb') as f:
                f.write(img_response.content)
            print(f"Downloaded: {filename}")

# Examples
pages = list_recent_pages()
print(f"Found {len(pages)} recent pages")

content = get_page_content("page_20260115_175126")
print(f"Content length: {len(content)} chars")

download_embedded_images("page_20260115_175126", "/tmp/images")
```

### JavaScript/Node.js

```javascript
const BASE_URL = 'http://localhost:8880/api/canvas';

async function getStats() {
  const response = await fetch(`${BASE_URL}/stats`);
  return response.json();
}

async function searchPages(query) {
  const response = await fetch(
    `${BASE_URL}/search?q=${encodeURIComponent(query)}`
  );
  const data = await response.json();
  return data.pages || [];
}

async function getPageContent(pageId) {
  const response = await fetch(`${BASE_URL}/${pageId}`);
  const data = await response.json();
  return data.page?.content || '';
}

// Examples
const stats = await getStats();
console.log(`${stats.total_pages} pages, ${stats.total_size_human}`);

const statusPages = await searchPages('status recap');
console.log(`Found ${statusPages.length} status pages`);
```

### curl One-Liners

```bash
# Total pages
curl -s http://localhost:8880/api/canvas/stats | jq '.total_pages'

# List all tags
curl -s http://localhost:8880/api/canvas/tags | jq '.tags'

# Get page titles
curl -s http://localhost:8880/api/canvas?limit=10 | jq '.pages[].title'

# Search for status recaps
curl -s "http://localhost:8880/api/canvas/search?q=status" | jq '.pages[] | {title, created: .created_at}'

# Get page content as raw markdown
curl -s http://localhost:8880/api/canvas/page_20260115_175126 | jq -r '.page.content'
```

---

## Use Cases

### 1. Daily Report Archive
Build an archive of status recaps.

```bash
curl -s "http://localhost:8880/api/canvas?tag=status&limit=100" | \
  jq '.pages[] | {title, date: .created_at}'
```

### 2. Search Historical Data
Find mentions of specific topics.

```bash
curl -s "http://localhost:8880/api/canvas/search?q=bitcoin" | \
  jq '.pages[] | {title, preview: .content_preview[:100]}'
```

### 3. Export Pages
Export all pages as markdown files.

```python
import requests
import os

BASE = "http://localhost:8880/api/canvas"
pages = requests.get(f"{BASE}?limit=100").json()['pages']

os.makedirs("export", exist_ok=True)
for p in pages:
    full = requests.get(f"{BASE}/{p['page_id']}").json()
    with open(f"export/{p['page_id']}.md", 'w') as f:
        f.write(full['page']['content'])
```

### 4. Page Statistics Dashboard
Track page creation over time.

```bash
curl -s http://localhost:8880/api/canvas/stats | jq '.'
```

---

## Notes

- **Safe mutations supported** - create, append, guarded full replacement, metadata update, and delete
- **Pages stored in** `data/canvas/` as JSON files
- **Embedded images** use `stash://` protocol
- **Content preview** is first 500 characters
- Pages are sorted by creation date (newest first)

---

## Canvas Web UI

The Canvas server (`jarvis-canvas`) provides a web interface at port 8890:

| URL | Description |
|-----|-------------|
| `http://localhost:8890/` | Canvas pages viewer |
| `http://localhost:8890/gallery` | Image gallery |
| `http://localhost:8890/video-gallery` | Video gallery (Feb 2026) |

### Video Gallery Features

- Grid view with hover preview
- Lightbox viewer with video controls
- Provider badges (xAI, Gemini) from `video_catalog.json`
- Search, sort by date/name/size/duration
- Download and delete functionality
- Keyboard shortcuts (arrows, space, escape)

### Architecture (Feb 2026 Refactor)

The canvas server was refactored from a monolithic file to modular Flask app:

```
jarvis-canvas/
├── config.py                 # Configuration
├── client/
│   ├── static/css/           # Stylesheets (canvas, gallery, video-gallery)
│   ├── static/js/            # JavaScript (canvas, gallery, video-gallery)
│   └── templates/            # Jinja2 templates
└── server/
    ├── app.py                # Flask app factory
    └── routes/               # API blueprints (pages, gallery, video_gallery, stash)
```

---

## See Also

- [API Overview](./API_OVERVIEW.md) - Full API documentation
- [Stash API](./STASH.md) - Download embedded images
- [Memory API](./MEMORY.md) - Direct memory access
- [Generated Videos API](./GENERATED_VIDEOS.md) - Video management
- [Test API](./TEST_API.md) - Testing examples
