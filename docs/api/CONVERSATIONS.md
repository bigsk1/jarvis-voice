# 💬 Conversations API

> Read-only access to Jarvis conversation history - useful for auditing, analytics, and building external tools.

## Overview

The Conversations API provides access to the conversation history stored in Jarvis's database. Every interaction through the terminal, web UI, or API is logged here.

**Base URL:** `http://localhost:8880/api/conversations`

**Note:** Returns conversations from the current mode's database (cloud or local).

---

## Quick Start

```bash
# Get conversation stats
curl http://localhost:8880/api/conversations/stats

# List recent conversations
curl "http://localhost:8880/api/conversations?limit=10"

# Search conversations
curl "http://localhost:8880/api/conversations/search?q=bitcoin"

# Get last hour of conversations
curl "http://localhost:8880/api/conversations/recent?minutes=60"
```

---

## Endpoints

### List Conversations

```http
GET /api/conversations
GET /api/conversations?limit=50&offset=0
```

List conversations with pagination and filters.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 50 | Results per page (1-500) |
| `offset` | int | 0 | Skip N results |
| `session_id` | string | - | Filter by session ID |
| `success` | bool | - | Filter by success status |
| `tool` | string | - | Filter by tool used |

**Example:**
```bash
# Get first 20 conversations
curl "http://localhost:8880/api/conversations?limit=20"

# Filter by tool used
curl "http://localhost:8880/api/conversations?tool=crypto_price&limit=10"

# Filter by success status
curl "http://localhost:8880/api/conversations?success=true&limit=10"

# Get specific session
curl "http://localhost:8880/api/conversations?session_id=20260117_180010"
```

**Response:**
```json
{
  "ok": true,
  "count": 3,
  "total": 858,
  "page": 1,
  "pages": 286,
  "conversations": [
    {
      "id": 858,
      "timestamp": "2026-01-18 02:00:16",
      "session_id": "20260117_180010",
      "user_query": "time",
      "jarvis_response": "It's 6:00 PM on Saturday, January 17, 2026.",
      "tools_used": ["get_time"],
      "success": true,
      "metadata": {
        "mode": "cloud",
        "provider": "xai",
        "model": "grok-4-1-fast-non-reasoning-latest",
        "tool_count": 1
      }
    }
  ]
}
```

---

### Get Conversation by ID

```http
GET /api/conversations/{id}
```

Get a specific conversation by its ID.

**Example:**
```bash
curl http://localhost:8880/api/conversations/858
```

**Response:**
```json
{
  "ok": true,
  "conversation": {
    "id": 858,
    "timestamp": "2026-01-18 02:00:16",
    "session_id": "20260117_180010",
    "user_query": "time",
    "jarvis_response": "It's 6:00 PM on Saturday, January 17, 2026.",
    "tools_used": ["get_time"],
    "success": true,
    "metadata": {...}
  }
}
```

---

### Get Statistics

```http
GET /api/conversations/stats
```

Get conversation statistics including totals, success rate, and top tools.

**Response:**
```json
{
  "total_conversations": 858,
  "total_today": 17,
  "total_this_week": 66,
  "success_rate": 96.0,
  "top_tools": {
    "get_time": 57,
    "crypto_price": 49,
    "spotify": 47,
    "generate_image": 32,
    "semantic_recall": 21,
    "mcp_brave_search_brave_web_search": 20,
    "status_recap": 18,
    "phone_call": 18
  },
  "database": "/home/boss/jarvis-voice/data/jarvis_memory.db"
}
```

---

### Get Recent Conversations

```http
GET /api/conversations/recent?minutes={N}
```

Get conversations from the last N minutes.

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `minutes` | int | 30 | Look back N minutes (1-1440) |
| `limit` | int | 20 | Maximum results (1-100) |

**Example:**
```bash
# Last 30 minutes
curl "http://localhost:8880/api/conversations/recent"

# Last 2 hours
curl "http://localhost:8880/api/conversations/recent?minutes=120&limit=50"
```

---

### Search Conversations

```http
GET /api/conversations/search?q={query}
```

Search conversations by query text or response content.

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `q` | string | - | Search query (required) |
| `limit` | int | 20 | Maximum results (1-100) |

**Example:**
```bash
# Search for bitcoin-related conversations
curl "http://localhost:8880/api/conversations/search?q=bitcoin"

# Search for weather queries
curl "http://localhost:8880/api/conversations/search?q=weather&limit=10"
```

---

### List Sessions

```http
GET /api/conversations/sessions
```

List unique session IDs with message counts and timestamps.

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 20 | Maximum sessions (1-100) |

**Response:**
```json
{
  "ok": true,
  "count": 5,
  "sessions": [
    {
      "session_id": "20260117_180010",
      "message_count": 3,
      "first_message": "2026-01-18 02:00:10",
      "last_message": "2026-01-18 02:05:30"
    }
  ]
}
```

---

## Conversation Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Unique conversation ID |
| `timestamp` | string | When the conversation occurred (UTC) |
| `session_id` | string | Groups related conversations |
| `user_query` | string | What the user asked |
| `jarvis_response` | string | Jarvis's response |
| `tools_used` | array | List of tools called |
| `success` | bool | Whether it completed successfully |
| `metadata` | object | Mode, provider, model, tool_count |

---

## Integration Examples

### Python

```python
import requests

BASE_URL = "http://localhost:8880/api/conversations"

def get_recent_conversations(minutes=30):
    """Get conversations from the last N minutes."""
    response = requests.get(f"{BASE_URL}/recent", params={
        "minutes": minutes,
        "limit": 50
    })
    return response.json().get("conversations", [])

def search_conversations(query):
    """Search conversation history."""
    response = requests.get(f"{BASE_URL}/search", params={
        "q": query,
        "limit": 20
    })
    return response.json().get("conversations", [])

def get_tool_usage_stats():
    """Get which tools are most used."""
    response = requests.get(f"{BASE_URL}/stats")
    return response.json().get("top_tools", {})

# Examples
recent = get_recent_conversations(60)
print(f"Last hour: {len(recent)} conversations")

bitcoin_convs = search_conversations("bitcoin")
print(f"Bitcoin-related: {len(bitcoin_convs)}")

stats = get_tool_usage_stats()
print(f"Top tool: {list(stats.keys())[0]}")
```

### JavaScript/Node.js

```javascript
const BASE_URL = 'http://localhost:8880/api/conversations';

async function getStats() {
  const response = await fetch(`${BASE_URL}/stats`);
  return response.json();
}

async function searchConversations(query) {
  const response = await fetch(
    `${BASE_URL}/search?q=${encodeURIComponent(query)}&limit=20`
  );
  const data = await response.json();
  return data.conversations || [];
}

async function getConversationsByTool(toolName) {
  const response = await fetch(
    `${BASE_URL}?tool=${toolName}&limit=50`
  );
  const data = await response.json();
  return data.conversations || [];
}

// Examples
const stats = await getStats();
console.log(`Total: ${stats.total_conversations}, Success: ${stats.success_rate}%`);

const cryptoConvs = await getConversationsByTool('crypto_price');
console.log(`Crypto queries: ${cryptoConvs.length}`);
```

### n8n Workflow - Daily Usage Report

```json
{
  "nodes": [
    {
      "name": "Get Stats",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "GET",
        "url": "http://192.168.70.228:8880/api/conversations/stats"
      }
    },
    {
      "name": "Format Report",
      "type": "n8n-nodes-base.code",
      "parameters": {
        "code": "return [{ report: `Daily Jarvis Stats:\\n- Total: ${$json.total_conversations}\\n- Today: ${$json.total_today}\\n- Success Rate: ${$json.success_rate}%\\n- Top Tool: ${Object.keys($json.top_tools)[0]}` }];"
      }
    }
  ]
}
```

### curl One-Liners

```bash
# Quick stats
curl -s http://localhost:8880/api/conversations/stats | jq '{total: .total_conversations, today: .total_today, rate: .success_rate}'

# Today's conversations
curl -s "http://localhost:8880/api/conversations/recent?minutes=1440" | jq '.conversations[].user_query'

# Find failed conversations
curl -s "http://localhost:8880/api/conversations?success=false&limit=10" | jq '.conversations[] | {query: .user_query, response: .jarvis_response}'

# Top tools this week
curl -s http://localhost:8880/api/conversations/stats | jq '.top_tools'

# Search and extract
curl -s "http://localhost:8880/api/conversations/search?q=reminder" | jq '.conversations[] | {id, query: .user_query}'
```

---

## Use Cases

### 1. Audit Trail
Track all interactions for compliance or debugging.

```bash
# Export last 500 conversations
curl -s "http://localhost:8880/api/conversations?limit=500" > audit.json
```

### 2. Usage Analytics
Understand how Jarvis is being used.

```bash
# Which tools are most popular?
curl -s http://localhost:8880/api/conversations/stats | jq '.top_tools'
```

### 3. Debug Failed Queries
Find and analyze failures.

```bash
curl -s "http://localhost:8880/api/conversations?success=false" | jq '.conversations[] | {query: .user_query, tools: .tools_used}'
```

### 4. Session Replay
Replay a conversation session.

```bash
SESSION_ID="20260117_180010"
curl -s "http://localhost:8880/api/conversations?session_id=$SESSION_ID" | jq '.conversations[] | {query: .user_query, response: .jarvis_response}'
```

---

## Notes

- **Read-only API** - No create/update/delete endpoints
- **Mode-specific** - Returns data from cloud or local DB based on API mode
- **Timestamps are UTC** - Convert to local time in your application
- **Web UI** uses its own JSON history but also writes to DB

---

## See Also

- [API Overview](./API_OVERVIEW.md) - Full API documentation
- [Memory API](./MEMORY.md) - Direct memory access
- [Query API](./QUERY.md) - Send queries to Jarvis
- [Test API](./TEST_API.md) - Testing examples
