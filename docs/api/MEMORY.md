# 🧠 Memory API

> Programmatic access to Jarvis's knowledge base - store, search, and manage memories.

## Overview

The Memory API provides full CRUD access to Jarvis's semantic memory system. Use it to:
- Store persistent knowledge (project locations, preferences, contacts)
- Search by keyword (FTS5) or meaning (vector embeddings)
- Build external apps that leverage Jarvis's memory

**Base URL:** `http://localhost:8880/api/memory`

---

## Quick Start

```bash
# Store a memory
curl -X POST http://localhost:8880/api/memory \
  -H "Content-Type: application/json" \
  -d '{
    "category": "project",
    "key": "flask_api_location",
    "value": "Flask API project at ~/projects/flask-api on port 8091",
    "importance": 8
  }'

# Search by keyword
curl "http://localhost:8880/api/memory/search/keyword?q=flask"

# Search by meaning (semantic)
curl "http://localhost:8880/api/memory/search/semantic?q=where%20is%20my%20web%20project"

# Get stats
curl http://localhost:8880/api/memory/stats
```

---

## Endpoints

### Create/Update Memory

```http
POST /api/memory
```

Creates a new memory or updates existing one (matched by category+key).

**Request Body:**
```json
{
  "category": "project",
  "key": "flask_api_location",
  "value": "Flask API project at ~/projects/flask-api",
  "importance": 8,
  "source": "api",
  "generate_embedding": true,
  "metadata": {
    "port": 8091,
    "framework": "flask"
  }
}
```

**Fields:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `category` | string | ✅ | Category (see below) |
| `key` | string | ✅ | Unique identifier within category |
| `value` | string | ✅ | The memory content |
| `importance` | int | ❌ | 1-10 (default: 5) |
| `source` | string | ❌ | Where this came from |
| `generate_embedding` | bool | ❌ | Generate vector embedding (default: true) |
| `metadata` | object | ❌ | Additional structured data |

**Categories:**
- `personal` - User info, preferences, family
- `technical` - Code, configs, projects
- `project` - Project locations, specs
- `contact` - People, relationships
- `preference` - User preferences
- `fact` - General knowledge
- `location` - Physical/virtual locations
- `other` - Miscellaneous

**Response:**
```json
{
  "ok": true,
  "memory_id": 425,
  "message": "Memory saved (ID: 425)"
}
```

---

### List Memories

```http
GET /api/memory
GET /api/memory?category=project&limit=50
```

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `category` | string | - | Filter by category |
| `limit` | int | 100 | Max results (1-500) |

**Response:**
```json
{
  "ok": true,
  "count": 3,
  "memories": [
    {
      "id": 273,
      "category": "personal",
      "key": "dog_name",
      "value": "Jessi",
      "importance": 9,
      "created_at": "2025-12-19 07:47:12",
      "updated_at": "2025-12-19 07:47:12",
      "source": "user_conversation",
      "metadata": {...}
    }
  ]
}
```

---

### Get Memory by ID

```http
GET /api/memory/{id}
```

**Response:**
```json
{
  "ok": true,
  "memory": {
    "id": 273,
    "category": "personal",
    "key": "dog_name",
    "value": "Jessi",
    ...
  }
}
```

---

### Update Memory

```http
PUT /api/memory/{id}
```

Updates value and/or importance. Does NOT regenerate embeddings.

**Request Body:**
```json
{
  "value": "Updated project location",
  "importance": 9
}
```

---

### Delete Memory

```http
DELETE /api/memory/{id}
```

**Response:**
```json
{
  "ok": true,
  "message": "Memory 273 deleted"
}
```

---

## Search

### Keyword Search (FTS5)

```http
GET /api/memory/search/keyword?q={query}&limit={limit}&category={category}
```

Fast full-text search using SQLite FTS5 with BM25 ranking.

**Best for:**
- 1-3 word searches
- Exact term matching
- Quick lookups

**Example:**
```bash
# Find memories mentioning "flask"
curl "http://localhost:8880/api/memory/search/keyword?q=flask&limit=10"

# Search only in technical category
curl "http://localhost:8880/api/memory/search/keyword?q=api&category=technical"
```

**Response includes relevance score:**
```json
{
  "ok": true,
  "count": 2,
  "memories": [
    {
      "id": 164,
      "key": "flask_project",
      "value": "Web-based Tetris with Flask server",
      "relevance": 0.174,  // BM25 score
      ...
    }
  ]
}
```

---

### Semantic Search (AI Embeddings)

```http
GET /api/memory/search/semantic?q={query}&limit={limit}&threshold={threshold}
```

Finds conceptually related memories using vector similarity.

**Best for:**
- Natural language questions
- Finding related concepts
- "Where is my..." queries

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `q` | string | - | Natural language query |
| `limit` | int | 5 | Max results (1-50) |
| `threshold` | float | 0.3 | Min similarity (0-1) |

**Example:**
```bash
# Find project locations
curl "http://localhost:8880/api/memory/search/semantic?q=where%20is%20my%20web%20project"

# More strict matching
curl "http://localhost:8880/api/memory/search/semantic?q=what%20is%20my%20dog%27s%20name&threshold=0.4"
```

**Response includes similarity score:**
```json
{
  "ok": true,
  "count": 1,
  "memories": [
    {
      "id": 273,
      "key": "dog_name",
      "value": "Jessi",
      "similarity": 0.454,  // Vector similarity
      ...
    }
  ]
}
```

**POST version** (for long queries):
```http
POST /api/memory/search/semantic
Content-Type: application/json

{
  "query": "What was the project I was working on last month with the API?",
  "limit": 5,
  "similarity_threshold": 0.35
}
```

---

## Utility Endpoints

### List Categories

```http
GET /api/memory/categories
```

Returns all categories with memory counts.

**Response:**
```json
{
  "ok": true,
  "message": "Found 3 categories",
  "categories": {
    "technical": 120,
    "project": 95,
    "personal": 42
  },
  "count": 257
}
```

---

### Get Statistics

```http
GET /api/memory/stats
```

**Response:**
```json
{
  "status": "ok",
  "total_memories": 424,
  "with_embeddings": 424,
  "embedding_coverage": "100.0%",
  "updated_last_7_days": 58,
  "high_importance": 267,
  "top_categories": {
    "technical": 202,
    "stash_artifact": 70,
    "canvas": 66,
    "project": 26,
    "personal": 5
  },
  "database": "~/jarvis-voice/data/jarvis_memory.db"
}
```

---

### Rebuild FTS Index

```http
POST /api/memory/rebuild-fts
```

Rebuilds the full-text search index. Use if keyword search seems broken.

**Response:**
```json
{
  "status": "ok",
  "indexed": 424,
  "message": "Rebuilt FTS index with 424 memories"
}
```

---

## Integration Examples

### Python

```python
import requests

BASE_URL = "http://localhost:8880/api/memory"

# Store a memory
def remember(category, key, value, importance=5):
    response = requests.post(BASE_URL, json={
        "category": category,
        "key": key,
        "value": value,
        "importance": importance
    })
    return response.json()

# Semantic search
def recall(question):
    response = requests.get(f"{BASE_URL}/search/semantic", params={
        "q": question,
        "limit": 5
    })
    data = response.json()
    return data.get("memories", [])

# Example usage
remember("project", "current_task", "Building Memory API docs", importance=7)
results = recall("What am I working on?")
print(results[0]["value"])  # "Building Memory API docs"
```

### JavaScript/Node.js

```javascript
const BASE_URL = 'http://localhost:8880/api/memory';

// Store a memory
async function remember(category, key, value, importance = 5) {
  const response = await fetch(BASE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category, key, value, importance })
  });
  return response.json();
}

// Semantic search
async function recall(question) {
  const response = await fetch(
    `${BASE_URL}/search/semantic?q=${encodeURIComponent(question)}&limit=5`
  );
  const data = await response.json();
  return data.memories || [];
}

// Example usage
await remember('contact', 'john_email', 'john@example.com', 8);
const results = await recall("What's John's email?");
console.log(results[0].value);  // "john@example.com"
```

### n8n Workflow

```json
{
  "nodes": [
    {
      "name": "Store Project Update",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "POST",
        "url": "http://localhost:8880/api/memory",
        "jsonParameters": true,
        "options": {},
        "bodyParametersJson": "={{ JSON.stringify({ category: 'project', key: $json.project_name, value: $json.status_update, importance: 7 }) }}"
      }
    }
  ]
}
```

### curl One-Liners

```bash
# Quick store
curl -X POST http://localhost:8880/api/memory \
  -H "Content-Type: application/json" \
  -d '{"category":"note","key":"quick_note","value":"Remember to check logs"}'

# Quick search
curl -s "http://localhost:8880/api/memory/search/semantic?q=logs" | jq '.memories[0].value'

# Get all project memories
curl -s "http://localhost:8880/api/memory?category=project" | jq '.memories[].key'

# Count by category
curl -s http://localhost:8880/api/memory/stats | jq '.top_categories'
```

---

## Error Handling

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 404 | Memory not found |
| 422 | Validation error (missing required field) |
| 500 | Server error |

**Example error response:**
```json
{
  "detail": "Memory 999 not found"
}
```

---

## Tips

1. **Use high importance (8-10)** for critical data like API keys, passwords
2. **Semantic search** works best for questions; **keyword search** for exact terms
3. **Categories** help organize and filter - use them consistently
4. **Metadata** is great for structured data that tools can process
5. **Embeddings** are generated automatically - disable only for bulk imports

---

## See Also

- [API Overview](./API_OVERVIEW.md) - Full API documentation
- [Query API](./QUERY.md) - Chat/query endpoints
- [Test API](./TEST_API.md) - Testing examples
