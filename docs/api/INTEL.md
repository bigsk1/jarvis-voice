# 🧠 Intel API

> Manage Jarvis's knowledge base files - create, read, update, delete, and ingest intel files programmatically.

## Overview

The Intel API provides full CRUD access to files in the `jarvis-intel/` folder. These files contain structured knowledge (facts, configs, notes) that get ingested into Jarvis's memory for RAG queries.

**Base URL:** `http://localhost:8880/api/intel`

---

## Quick Start

```bash
# Get intel folder statistics
curl http://localhost:8880/api/intel/stats

# List all intel files
curl http://localhost:8880/api/intel

# Create a new intel file
curl -X POST http://localhost:8880/api/intel \
  -H "Content-Type: application/json" \
  -d '{"filename": "server-notes.md", "content": "# Servers\n- vps1: 10.0.0.1", "auto_ingest": true}'

# Read a file
curl http://localhost:8880/api/intel/server-notes.md

# Trigger ingestion
curl -X POST "http://localhost:8880/api/intel/ingest?async_mode=true"

# Delete a file
curl -X DELETE http://localhost:8880/api/intel/server-notes.md
```

---

## Endpoints

### Get Statistics

```http
GET /api/intel/stats
```

Get intel folder statistics including file counts, sizes, and ingestion status.

**Response:**
```json
{
  "total_files": 8,
  "total_size_bytes": 15234,
  "total_size_human": "14.9 KB",
  "total_facts_ingested": 156,
  "files_pending_ingest": 1,
  "newest_file": "url-ingest-docs.x.ai-2026-01-25.md",
  "oldest_file": "network.md"
}
```

---

### List Intel Files

```http
GET /api/intel
GET /api/intel?include_stats=true
```

List all intel files in the folder.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `include_stats` | bool | false | Include ingestion stats per file |

**Response:**
```json
{
  "ok": true,
  "count": 8,
  "files": [
    {
      "filename": "network.md",
      "size_bytes": 524,
      "modified_at": "2025-11-18T03:43:00",
      "ingested": true,
      "fact_count": 12
    },
    {
      "filename": "user_profile.md",
      "size_bytes": 5782,
      "modified_at": "2026-01-22T20:52:00",
      "ingested": true,
      "fact_count": 89
    }
  ]
}
```

---

### Create Intel File

```http
POST /api/intel
```

Create a new intel file.

**Request Body:**
```json
{
  "filename": "xai-collections.md",
  "content": "# xAI Collections API\n\n## Key Concepts\n- Collection: Group of files with embeddings\n- File: Single uploaded document\n\n## Important Facts\n- Max file size: 100MB\n- Max files: 100,000",
  "auto_ingest": true
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `filename` | string | yes | Filename ending in `.md` or `.txt` |
| `content` | string | yes | File content (markdown recommended) |
| `auto_ingest` | bool | no | Trigger background ingestion after creating |

**Response:**
```json
{
  "ok": true,
  "message": "Created xai-collections.md (ingestion started)",
  "file": {
    "filename": "xai-collections.md",
    "size_bytes": 234,
    "modified_at": "2026-01-25T10:30:00",
    "ingested": false,
    "fact_count": null
  }
}
```

---

### Get Intel File

```http
GET /api/intel/{filename}
```

Get an intel file's content and metadata.

**Response:**
```json
{
  "ok": true,
  "file": {
    "filename": "network.md",
    "size_bytes": 524,
    "modified_at": "2025-11-18T03:43:00",
    "ingested": true,
    "fact_count": 12
  },
  "content": "# Network Configuration\n\n## Servers\n- vps1: 10.0.0.1\n- vps2: 10.0.0.2\n..."
}
```

---

### Update Intel File

```http
PUT /api/intel/{filename}
```

Update an existing intel file.

**Request Body:**
```json
{
  "content": "# Updated Network Configuration\n\n## Servers\n- vps1: 10.0.0.1\n- vps2: 10.0.0.2\n- vps3: 10.0.0.3",
  "auto_ingest": true
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | string | yes | New file content |
| `auto_ingest` | bool | no | Delete old memories and re-ingest |

**Response:**
```json
{
  "ok": true,
  "message": "Updated network.md (re-ingestion started)",
  "file": {
    "filename": "network.md",
    "size_bytes": 612,
    "modified_at": "2026-01-25T10:35:00",
    "ingested": false,
    "fact_count": null
  }
}
```

---

### Delete Intel File

```http
DELETE /api/intel/{filename}
```

Delete an intel file and all its associated memories.

**Response:**
```json
{
  "ok": true,
  "message": "Deleted network.md and 12 associated facts"
}
```

---

### Trigger Ingestion

```http
POST /api/intel/ingest
POST /api/intel/ingest?async_mode=true
```

Trigger ingestion of all intel files into memory.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `async_mode` | bool | false | Run in background (returns immediately) |

**Sync Response:**
```json
{
  "ok": true,
  "new_files": 2,
  "skipped_files": 6,
  "total_facts": 45,
  "processed_files": ["new-file.md", "updated-file.md"],
  "async_started": false
}
```

**Async Response:**
```json
{
  "ok": true,
  "async_started": true
}
```

---

## File Format Best Practices

For optimal fact extraction, structure your intel files like this:

```markdown
# Topic Title
Source: https://example.com (optional)

## Overview
Brief 2-3 sentence summary of what this covers.

## Key Concepts
- Concept Name: Brief explanation
- Another Concept: Its explanation

## Important Facts
- Fact Key: Fact value
- Server IP: 10.0.0.1
- Max Limit: 100MB

## Notes
- Additional bullet points get extracted as notes
```

**Format tips:**
- Use `# Headers` to create sections
- Use `Key: Value` format for facts (gets parsed as structured data)
- Use `- bullet points` for lists
- Keep values concise but complete

---

## Integration Examples

### Python

```python
import requests

BASE_URL = "http://localhost:8880/api/intel"

def create_intel(filename: str, content: str, auto_ingest: bool = True):
    """Create a new intel file."""
    response = requests.post(BASE_URL, json={
        "filename": filename,
        "content": content,
        "auto_ingest": auto_ingest
    })
    return response.json()

def get_intel(filename: str):
    """Get an intel file's content."""
    response = requests.get(f"{BASE_URL}/{filename}")
    return response.json()

def update_intel(filename: str, content: str, auto_ingest: bool = True):
    """Update an intel file."""
    response = requests.put(f"{BASE_URL}/{filename}", json={
        "content": content,
        "auto_ingest": auto_ingest
    })
    return response.json()

def delete_intel(filename: str):
    """Delete an intel file and its memories."""
    response = requests.delete(f"{BASE_URL}/{filename}")
    return response.json()

def trigger_ingest(async_mode: bool = True):
    """Trigger ingestion of all intel files."""
    response = requests.post(f"{BASE_URL}/ingest", params={
        "async_mode": async_mode
    })
    return response.json()

def get_stats():
    """Get intel folder statistics."""
    response = requests.get(f"{BASE_URL}/stats")
    return response.json()


# Example: Programmatically add documentation to Jarvis
content = """# xAI Collections API

## Key Concepts
- Collection: Group of files with embedding index for retrieval
- File: Single uploaded document entity

## Important Facts
- Max file size: 100MB
- Max files: 100,000 globally
- Max total size: 100GB
- Data Privacy: Not used for training without consent

## API Endpoints
- Create collection: POST /v1/collections
- Upload file: POST /v1/files
- Search: GET /v1/collections/{id}/search
"""

result = create_intel("xai-api-notes.md", content, auto_ingest=True)
print(f"Created: {result['file']['filename']}")
```

### JavaScript/Node.js

```javascript
const BASE_URL = 'http://localhost:8880/api/intel';

async function createIntel(filename, content, autoIngest = true) {
  const response = await fetch(BASE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename, content, auto_ingest: autoIngest })
  });
  return response.json();
}

async function getIntel(filename) {
  const response = await fetch(`${BASE_URL}/${filename}`);
  return response.json();
}

async function deleteIntel(filename) {
  const response = await fetch(`${BASE_URL}/${filename}`, { method: 'DELETE' });
  return response.json();
}

async function triggerIngest(asyncMode = true) {
  const response = await fetch(`${BASE_URL}/ingest?async_mode=${asyncMode}`, {
    method: 'POST'
  });
  return response.json();
}

// Example usage
const content = `# Server Configuration
## IP Addresses
- vps1: 10.0.0.1
- vps2: 10.0.0.2
## Credentials
- SSH User: admin
`;

const result = await createIntel('servers.md', content);
console.log(`Created ${result.file.filename}`);
```

### curl One-Liners

```bash
# Get total facts ingested
curl -s http://localhost:8880/api/intel/stats | jq '.total_facts_ingested'

# List all files with fact counts
curl -s "http://localhost:8880/api/intel?include_stats=true" | jq '.files[] | {name: .filename, facts: .fact_count}'

# Create file from local markdown
curl -X POST http://localhost:8880/api/intel \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg content "$(cat notes.md)" '{filename: "notes.md", content: $content, auto_ingest: true}')"

# Quick ingest (async)
curl -X POST "http://localhost:8880/api/intel/ingest?async_mode=true"

# Find files not yet ingested
curl -s "http://localhost:8880/api/intel?include_stats=true" | jq '.files[] | select(.ingested == false)'
```

---

## Use Cases

### 1. Automated Documentation Ingestion

Periodically sync documentation to Jarvis's knowledge base:

```python
import requests
from pathlib import Path

def sync_docs_to_jarvis(docs_dir: str, base_url: str = "http://localhost:8880/api/intel"):
    """Sync local documentation files to Jarvis intel."""
    for md_file in Path(docs_dir).glob("*.md"):
        content = md_file.read_text()
        filename = f"docs-{md_file.name}"
        
        # Check if exists
        response = requests.get(f"{base_url}/{filename}")
        
        if response.status_code == 404:
            # Create new
            requests.post(base_url, json={
                "filename": filename,
                "content": content,
                "auto_ingest": False  # Batch ingest later
            })
        else:
            # Update existing
            requests.put(f"{base_url}/{filename}", json={
                "content": content,
                "auto_ingest": False
            })
    
    # Trigger single ingest for all
    requests.post(f"{base_url}/ingest?async_mode=true")
```

### 2. Webhook for External Data

Receive data from external systems and store as intel:

```python
from fastapi import FastAPI, Request
import requests

app = FastAPI()

@app.post("/webhook/to-intel")
async def webhook_to_intel(request: Request):
    data = await request.json()
    
    # Format as intel file
    content = f"""# {data['title']}
Source: {data.get('source', 'webhook')}
Received: {data.get('timestamp', 'now')}

## Data
{data['content']}
"""
    
    # Send to Jarvis Intel API
    response = requests.post("http://localhost:8880/api/intel", json={
        "filename": f"webhook-{data['id']}.md",
        "content": content,
        "auto_ingest": True
    })
    
    return {"status": "ok", "intel_file": response.json()}
```

### 3. Batch Import from CSV

Convert CSV data to intel files:

```python
import csv
import requests

def csv_to_intel(csv_path: str, title: str):
    """Convert CSV to intel file."""
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    # Build markdown content
    lines = [f"# {title}", "", "## Data", ""]
    for row in rows:
        for key, value in row.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
    
    content = "\n".join(lines)
    filename = f"import-{title.lower().replace(' ', '-')}.md"
    
    requests.post("http://localhost:8880/api/intel", json={
        "filename": filename,
        "content": content,
        "auto_ingest": True
    })

csv_to_intel("servers.csv", "Server Inventory")
```

---

## Error Responses

| Status | Meaning |
|--------|---------|
| 400 | Invalid filename (bad chars, wrong extension) |
| 404 | File not found |
| 409 | File already exists (use PUT to update) |
| 500 | Server error |
| 504 | Ingestion timeout (use async_mode=true) |

**Example error:**
```json
{
  "detail": "Filename must end in .md or .txt"
}
```

---

## Notes

- **Filenames** must end in `.md` or `.txt`
- **README.md** cannot be modified (reserved)
- **Safe characters** only: letters, numbers, hyphens, underscores, dots
- **Ingestion** extracts facts using key:value patterns and bullet points
- **Async ingestion** recommended for large files (>10KB) to avoid timeout
- **Delete** removes both file AND all memories from that file

---

## See Also

- [Memory API](./MEMORY.md) - Direct memory access (search, create, update)
- [Stash API](./STASH.md) - File artifact storage
- [API Overview](./API_OVERVIEW.md) - Full API documentation
- [Workflows API](./WORKFLOWS.md) - Trigger workflows like `/url_ingest`
