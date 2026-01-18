# 📦 Stash API

> Read-only access to Jarvis's artifact storage - images, PDFs, music, and other generated files.

## Overview

The Stash API provides access to files created by Jarvis tools (image generation, PDFs, music, etc.). Each **space** is a container that holds related files.

**Base URL:** `http://localhost:8880/api/stash`

---

## Quick Start

```bash
# Get stash statistics
curl http://localhost:8880/api/stash/stats

# List recent spaces
curl http://localhost:8880/api/stash/recent

# Search for images
curl "http://localhost:8880/api/stash/search?q=bitcoin"

# Get a specific space with files
curl http://localhost:8880/api/stash/space/space_20260118_005400_7374e32c

# Download a file
curl -O http://localhost:8880/api/stash/space/{space_id}/file/{file_id}/download
```

---

## Endpoints

### Get Statistics

```http
GET /api/stash/stats
```

Get overall stash statistics.

**Response:**
```json
{
  "total_spaces": 149,
  "total_files": 143,
  "total_size_bytes": 172478822,
  "total_size_human": "164.5 MB",
  "pinned_spaces": 1,
  "by_label": {
    "generated_images": 54,
    "web_upload": 11,
    "pdf": 10,
    "generated_music": 6
  },
  "by_tool": {
    "generate_image": 54,
    "stash": 42,
    "youtube_transcript": 12,
    "pdf_create": 7
  },
  "oldest_space": "2025-12-11T08:29:17.283146Z",
  "newest_space": "2026-01-18T00:54:00.288116Z"
}
```

---

### List Spaces

```http
GET /api/stash
GET /api/stash?limit=50&offset=0
```

List stash spaces with pagination and filters.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 50 | Results per page (1-200) |
| `offset` | int | 0 | Skip N results |
| `label` | string | - | Filter by label |
| `pinned` | bool | - | Filter by pinned status |
| `tool` | string | - | Filter by tool_origin |

**Examples:**
```bash
# List all (paginated)
curl "http://localhost:8880/api/stash?limit=20"

# Filter by label
curl "http://localhost:8880/api/stash?label=generated_images"

# Filter by tool
curl "http://localhost:8880/api/stash?tool=generate_image"

# Only pinned spaces
curl "http://localhost:8880/api/stash?pinned=true"
```

**Response:**
```json
{
  "ok": true,
  "message": "Found 149 spaces",
  "count": 3,
  "spaces": [
    {
      "space_id": "space_20260118_005400_7374e32c",
      "created_at": "2026-01-18T00:54:00.288116Z",
      "labels": ["generated_images"],
      "file_count": 1,
      "total_size_bytes": 2314172,
      "pinned": false
    }
  ]
}
```

---

### Get Recent Spaces

```http
GET /api/stash/recent?limit=10
```

Get most recently used spaces.

---

### Search Stash

```http
GET /api/stash/search?q={query}
```

Search by filename or label.

**Examples:**
```bash
# Search for bitcoin-related files
curl "http://localhost:8880/api/stash/search?q=bitcoin"

# Search for PDFs
curl "http://localhost:8880/api/stash/search?q=pdf"
```

**Response includes files:**
```json
{
  "ok": true,
  "message": "Found 2 spaces matching 'bitcoin'",
  "count": 2,
  "spaces": [
    {
      "space_id": "space_20260118_005400_7374e32c",
      "files": [
        {
          "file_id": "f_5d190ce797c6",
          "name": "generated_bitcoin_infographic.jpg",
          "mime_type": "image/jpeg",
          "size_bytes": 2314172,
          "tool_origin": "generate_image"
        }
      ]
    }
  ]
}
```

---

### List Labels

```http
GET /api/stash/labels
```

Get all unique labels with counts.

**Response:**
```json
{
  "ok": true,
  "count": 19,
  "labels": {
    "generated_images": 54,
    "web_upload": 11,
    "pdf": 10,
    "generated_music": 6,
    "youtube_transcripts": 6
  }
}
```

---

### Get Space

```http
GET /api/stash/space/{space_id}
GET /api/stash/space/{space_id}?include_files=true
```

Get a specific space with its files.

**Response:**
```json
{
  "ok": true,
  "space": {
    "space_id": "space_20260118_005400_7374e32c",
    "created_at": "2026-01-18T00:54:00.288116Z",
    "labels": ["generated_images"],
    "owner": "jarvis",
    "scope": "session",
    "ttl_days": 7,
    "pinned": false,
    "file_count": 1,
    "total_size_bytes": 2314172,
    "files": [
      {
        "file_id": "f_5d190ce797c6",
        "name": "generated_bitcoin_infographic.jpg",
        "stored_name": "generated_bitcoin_infographic.jpg",
        "mime_type": "image/jpeg",
        "size_bytes": 2314172,
        "tags": ["ai_generated", "gemini"],
        "tool_origin": "generate_image",
        "created_at": "2026-01-18T00:54:00.291003Z"
      }
    ]
  }
}
```

---

### Get File Info

```http
GET /api/stash/space/{space_id}/file/{file_id}
```

Get information about a specific file.

---

### Download File

```http
GET /api/stash/space/{space_id}/file/{file_id}/download
```

Download the actual file content.

**Example:**
```bash
# Download an image
curl -O "http://localhost:8880/api/stash/space/space_20260118_005400_7374e32c/file/f_5d190ce797c6/download"

# Download with custom filename
curl -o my_image.jpg "http://localhost:8880/api/stash/space/.../file/.../download"
```

**Response Headers:**
```
Content-Type: image/jpeg
Content-Disposition: attachment; filename="generated_bitcoin_infographic.jpg"
Content-Length: 2314172
```

---

## Space Fields

| Field | Type | Description |
|-------|------|-------------|
| `space_id` | string | Unique identifier |
| `created_at` | string | Creation timestamp (ISO 8601) |
| `last_used_at` | string | Last access timestamp |
| `labels` | array | Tags/categories |
| `owner` | string | Usually "jarvis" |
| `scope` | string | "session" or "persistent" |
| `ttl_days` | int | Time-to-live in days |
| `pinned` | bool | Prevents auto-deletion |
| `file_count` | int | Number of files |
| `total_size_bytes` | int | Total size of all files |

## File Fields

| Field | Type | Description |
|-------|------|-------------|
| `file_id` | string | Unique file identifier |
| `name` | string | Original filename |
| `stored_name` | string | Name on disk |
| `mime_type` | string | MIME type |
| `size_bytes` | int | File size |
| `hash_sha256` | string | File hash |
| `tags` | array | File tags |
| `tool_origin` | string | Tool that created it |
| `created_at` | string | Creation timestamp |

---

## Common Labels

| Label | Description |
|-------|-------------|
| `generated_images` | AI-generated images |
| `web_upload` | User-uploaded files |
| `pdf` | PDF documents |
| `generated_music` | AI-generated music |
| `youtube_transcripts` | YouTube transcriptions |
| `vision_analyzed` | Images analyzed by vision |

## Common Tools

| Tool | Description |
|------|-------------|
| `generate_image` | Gemini image generation |
| `stash` | Direct stash operations |
| `youtube_transcript` | YouTube transcription |
| `pdf_create` | PDF generation |
| `generate_music` | Music generation |
| `analyze_image` | Vision analysis |
| `web_upload` | Web UI uploads |

---

## Integration Examples

### Python

```python
import requests

BASE_URL = "http://localhost:8880/api/stash"

def list_generated_images(limit=10):
    """List AI-generated images."""
    response = requests.get(f"{BASE_URL}", params={
        "tool": "generate_image",
        "limit": limit
    })
    return response.json().get("spaces", [])

def download_file(space_id, file_id, save_path):
    """Download a file from stash."""
    response = requests.get(
        f"{BASE_URL}/space/{space_id}/file/{file_id}/download",
        stream=True
    )
    with open(save_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    return save_path

def get_total_storage():
    """Get total storage used."""
    response = requests.get(f"{BASE_URL}/stats")
    stats = response.json()
    return stats['total_size_human']

# Examples
images = list_generated_images()
print(f"Found {len(images)} generated images")

print(f"Total storage: {get_total_storage()}")
```

### JavaScript/Node.js

```javascript
const BASE_URL = 'http://localhost:8880/api/stash';

async function getStats() {
  const response = await fetch(`${BASE_URL}/stats`);
  return response.json();
}

async function searchFiles(query) {
  const response = await fetch(`${BASE_URL}/search?q=${encodeURIComponent(query)}`);
  const data = await response.json();
  return data.spaces || [];
}

async function downloadFile(spaceId, fileId) {
  const response = await fetch(
    `${BASE_URL}/space/${spaceId}/file/${fileId}/download`
  );
  return response.blob();
}

// Examples
const stats = await getStats();
console.log(`${stats.total_files} files, ${stats.total_size_human}`);

const bitcoinFiles = await searchFiles('bitcoin');
console.log(`Found ${bitcoinFiles.length} bitcoin-related spaces`);
```

### curl One-Liners

```bash
# Total storage used
curl -s http://localhost:8880/api/stash/stats | jq '.total_size_human'

# List all labels
curl -s http://localhost:8880/api/stash/labels | jq '.labels'

# Find all generated images
curl -s "http://localhost:8880/api/stash?tool=generate_image" | jq '.spaces[].space_id'

# Get recent PDFs
curl -s "http://localhost:8880/api/stash?label=pdf" | jq '.spaces[] | {id: .space_id, files: .file_count}'

# Download latest image
SPACE=$(curl -s "http://localhost:8880/api/stash?tool=generate_image&limit=1" | jq -r '.spaces[0].space_id')
FILE=$(curl -s "http://localhost:8880/api/stash/space/$SPACE" | jq -r '.space.files[0].file_id')
curl -o latest_image.jpg "http://localhost:8880/api/stash/space/$SPACE/file/$FILE/download"
```

---

## Use Cases

### 1. Image Gallery
Build an image gallery from generated images.

```bash
# Get all image spaces with files
curl -s "http://localhost:8880/api/stash?tool=generate_image&limit=100" | \
  jq '.spaces[] | {id: .space_id, created: .created_at}'
```

### 2. Storage Cleanup
Find large files for cleanup.

```bash
curl -s http://localhost:8880/api/stash/stats | jq '.by_label'
```

### 3. Audit Trail
Track what Jarvis has created.

```bash
curl -s http://localhost:8880/api/stash/stats | jq '.by_tool'
```

### 4. Backup Generated Content
Download all generated images.

```python
import requests
import os

BASE = "http://localhost:8880/api/stash"
spaces = requests.get(f"{BASE}?tool=generate_image&limit=100").json()['spaces']

for space in spaces:
    space_data = requests.get(f"{BASE}/space/{space['space_id']}").json()
    for f in space_data['space']['files']:
        # Download each file
        resp = requests.get(f"{BASE}/space/{space['space_id']}/file/{f['file_id']}/download")
        with open(f"backup/{f['name']}", 'wb') as out:
            out.write(resp.content)
```

---

## Notes

- **Read-only API** - No create/update/delete endpoints
- **Files stored in** `data/stash/` directory
- **Stash references** use format: `stash://{space_id}/{file_id}`
- **TTL** - Spaces auto-delete after `ttl_days` unless pinned
- **Pinned spaces** are preserved indefinitely

---

## See Also

- [API Overview](./API_OVERVIEW.md) - Full API documentation
- [Memory API](./MEMORY.md) - Direct memory access
- [Canvas API](./CANVAS.md) - Canvas pages
- [Test API](./TEST_API.md) - Testing examples
