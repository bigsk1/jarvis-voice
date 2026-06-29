# 💬 Query/Chat API

> Send natural language queries to Jarvis programmatically - perfect for automation, n8n, and external apps.

## Overview

The Query API lets you interact with Jarvis the same way you would via voice or the web UI, but through HTTP requests. Jarvis will:
- Understand your intent
- Call appropriate tools (weather, crypto, memory, etc.)
- Return a natural language response

**Base URL:** `http://localhost:8880/api/query`

**Image/Vision note:** `/api/query` does not accept raw image payload fields such as `image` or `images`. To analyze images through the FastAPI query server, put the image URL, file path, or stash reference in the natural-language `query` so Jarvis can call the `analyze_image` tool. The Web UI's drag/drop image uploads use separate WebSocket and `/api/upload-image(s)` routes, not this FastAPI endpoint.

---

## Quick Start

```bash
# Simple question (GET)
curl "http://localhost:8880/api/query/quick?q=What%20time%20is%20it"

# Simple question (POST)
curl -X POST http://localhost:8880/api/query/quick \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the weather?"}'

# Full query with options
curl -X POST http://localhost:8880/api/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the price of Bitcoin?",
    "mode": "cloud"
  }'
```

---

## Endpoints

### Full Query

```http
POST /api/query
```

Full-featured query endpoint with all options.

**Request Body:**
```json
{
  "query": "What's the weather like today?",
  "mode": "cloud",
  "session_id": "n8n-workflow-123",
  "context": {
    "messages": [
      {"role": "user", "content": "Previous message"},
      {"role": "assistant", "content": "Previous response"}
    ]
  }
}
```

**Fields:**
| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | ✅ | - | Your question or command |
| `mode` | string | ❌ | "cloud" | LLM mode: "cloud" or "local" |
| `session_id` | string | ❌ | - | Optional ID for tracking |
| `context` | object | ❌ | - | Conversation history for multi-turn |

Unknown JSON fields are not part of the query contract. Image bytes/base64 should not be sent here; use an image URL/file/stash ref in `query`, or use the Web UI upload flow.

`mode` is strictly validated. Any value other than `"cloud"` or `"local"`
returns FastAPI's `422 Unprocessable Entity` response; Jarvis does not guess or
fall back to the process startup mode. Each request executes inside its own
mode-specific config scope.

**Response:**
```json
{
  "ok": true,
  "speech": "It's currently 45°F with partly cloudy skies in Hillsboro.",
  "response": "It's currently 45°F with partly cloudy skies in Hillsboro.",
  "tools_used": ["weather"],
  "session_id": "n8n-workflow-123",
  "error": null
}
```

---

### Quick Query (POST)

```http
POST /api/query/quick
```

Simplified endpoint for basic queries.

**Request Body:**
```json
{
  "query": "What time is it?",
  "mode": "cloud"
}
```

**Response:** Same as full query.

---

### Quick Query (GET)

```http
GET /api/query/quick?q={query}&mode={mode}
```

GET version for easy testing in browser or simple webhooks.

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `q` | string | - | Your question (URL encoded) |
| `mode` | string | "cloud" | Exactly `cloud` or `local` |

**Example:**
```bash
curl "http://localhost:8880/api/query/quick?q=What%20is%202%2B2"
```

**Response:**
```json
{
  "ok": true,
  "speech": "2 + 2 equals 4.",
  "response": "2 + 2 equals 4.",
  "tools_used": ["calculator"],
  "session_id": null,
  "error": null
}
```

⚠️ **Note:** GET requests may be logged. Use POST for sensitive queries.

---

## Modes

| Mode | Description | Speed | Privacy |
|------|-------------|-------|---------|
| `cloud` | Uses xAI, Anthropic, or OpenAI | Fast | Data sent to cloud |
| `local` | Uses Ollama locally | Slower | Fully private |

**Set mode per request:**
```json
{"query": "...", "mode": "local"}
```

---

## Example Queries

### Information Queries

```bash
# Time
curl "http://localhost:8880/api/query/quick?q=What%20time%20is%20it"
# → "It's 5:30 PM on Saturday, January 17, 2026."

# Weather
curl "http://localhost:8880/api/query/quick?q=What%27s%20the%20weather"
# → "It's 45°F with partly cloudy skies in Hillsboro, OR."

# Crypto prices
curl "http://localhost:8880/api/query/quick?q=Bitcoin%20price"
# → "Bitcoin is currently $93,500, up 1.5% in the last 24 hours."

# Stock prices
curl "http://localhost:8880/api/query/quick?q=Tesla%20stock%20price"
# → "Tesla (TSLA) is at $412.50, up 2.3%."
```

### Memory Queries

```bash
# Recall from memory
curl "http://localhost:8880/api/query/quick?q=What%20is%20my%20dog%27s%20name"
# → "Your dog's name is Jessi."

# Store to memory (via remember tool)
curl -X POST http://localhost:8880/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Remember that my favorite color is blue"}'
# → "Got it, I'll remember that your favorite color is blue."
```

### Task Queries

```bash
# Create reminder
curl -X POST http://localhost:8880/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Remind me to check the server at 5pm tomorrow"}'

# System status
curl "http://localhost:8880/api/query/quick?q=System%20status"
# → Uses system_monitor tool

# Status recap (comprehensive)
curl "http://localhost:8880/api/query/quick?q=Give%20me%20a%20status%20recap"
# → Weather, crypto, alerts, reminders, system health
```

### Calculations

```bash
curl "http://localhost:8880/api/query/quick?q=What%20is%20sqrt%28144%29%20times%2015"
# → "√144 × 15 = 180"
```

---

## Integration Examples

### Python

```python
import requests

JARVIS_URL = "http://localhost:8880/api/query"

def ask_jarvis(question: str, mode: str = "cloud") -> dict:
    """Ask Jarvis a question and get a response."""
    response = requests.post(
        f"{JARVIS_URL}/quick",
        json={"query": question, "mode": mode},
        timeout=60  # Some queries take time (image gen, etc.)
    )
    return response.json()

# Examples
result = ask_jarvis("What time is it?")
print(result["speech"])  # "It's 5:30 PM..."

result = ask_jarvis("What's the Bitcoin price?")
print(f"Tools used: {result['tools_used']}")  # ['crypto_price']
```

### JavaScript/Node.js

```javascript
const JARVIS_URL = 'http://localhost:8880/api/query';

async function askJarvis(question, mode = 'cloud') {
  const response = await fetch(`${JARVIS_URL}/quick`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: question, mode })
  });
  return response.json();
}

// Example
const result = await askJarvis("What's the weather?");
console.log(result.speech);
console.log(`Tools: ${result.tools_used.join(', ')}`);
```

### n8n Workflow

**Daily Morning Briefing:**
```json
{
  "nodes": [
    {
      "name": "Get Status Recap",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "POST",
        "url": "http://localhost:8880/api/query/quick",
        "options": {
          "timeout": 120000
        },
        "bodyParametersJson": "={\"query\": \"Give me a morning status recap\", \"mode\": \"cloud\"}"
      }
    },
    {
      "name": "Send Email",
      "type": "n8n-nodes-base.emailSend",
      "parameters": {
        "subject": "Morning Briefing",
        "text": "={{ $json.speech }}"
      }
    }
  ]
}
```

**Health Check Automation:**
```json
{
  "nodes": [
    {
      "name": "Ask About Servers",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "POST",
        "url": "http://localhost:8880/api/query",
        "bodyParametersJson": "={\"query\": \"Check if my servers are healthy\", \"mode\": \"cloud\", \"session_id\": \"n8n-health-check\"}"
      }
    }
  ]
}
```

### Home Assistant

```yaml
# configuration.yaml
rest_command:
  jarvis_query:
    url: "http://localhost:8880/api/query/quick"
    method: POST
    content_type: "application/json"
    payload: '{"query": "{{ query }}", "mode": "cloud"}'

# In automations
automation:
  - alias: "Ask Jarvis Weather"
    trigger:
      - platform: time
        at: "07:00:00"
    action:
      - service: rest_command.jarvis_query
        data:
          query: "What's the weather forecast today?"
```

### Shell Script

```bash
#!/bin/bash
# jarvis-ask.sh - Quick Jarvis query from command line

QUERY="$*"
if [ -z "$QUERY" ]; then
    echo "Usage: jarvis-ask.sh <question>"
    exit 1
fi

curl -s -X POST http://localhost:8880/api/query/quick \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"$QUERY\"}" | jq -r '.speech'
```

Usage:
```bash
./jarvis-ask.sh "What time is it?"
# It's 5:30 PM on Saturday, January 17, 2026.
```

---

## Multi-Turn Conversations

For follow-up questions, include conversation history:

```bash
curl -X POST http://localhost:8880/api/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What about tomorrow?",
    "mode": "cloud",
    "session_id": "weather-conv",
    "context": {
      "messages": [
        {"role": "user", "content": "What is the weather today?"},
        {"role": "assistant", "content": "It is 45°F and partly cloudy in Hillsboro."}
      ]
    }
  }'
```

---

## Vision Examples

Use `analyze_image` through natural language when calling the FastAPI query endpoint:

```bash
curl -X POST http://localhost:8880/api/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Compare these two images with analyze_image: https://example.com/before.png and https://example.com/after.png",
    "mode": "cloud"
  }'
```

The tool supports up to 6 images in cloud mode and 2 images in local mode. `/api/images` is only for uploading images to the Cloudflare CDN; it does not run vision analysis.

---

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `ok` | bool | Whether query succeeded |
| `speech` | string | Short response (for TTS) |
| `response` | string | Full response text |
| `tools_used` | array | List of tools that were called |
| `session_id` | string | Session ID (if provided) |
| `error` | string | Error message (if `ok` is false) |

---

## Available Tools

When you query Jarvis, it automatically selects appropriate tools:

| Category | Tools |
|----------|-------|
| **Time/Weather** | `get_time`, `weather` |
| **Finance** | `crypto_price`, `stock_price` |
| **Memory** | `remember`, `semantic_recall`, `search_memory` |
| **System** | `system_monitor`, `calculator` |
| **Media** | `generate_image`, `generate_music`, `play_spotify` |
| **Communication** | `phone_call`, `send_sms` |
| **Tasks** | `create_reminder`, `list_reminders`, `create_alert` |
| **Status** | `status_recap`, `list_alerts` |
| **Web** | `brave_search`, `crawl_url`, `screenshot_url` |

---

## Timeouts

Some queries may take longer:

| Query Type | Typical Time |
|------------|--------------|
| Simple Q&A | 1-3 seconds |
| Weather/Crypto | 2-5 seconds |
| Memory search | 2-5 seconds |
| Status recap | 10-30 seconds |
| Image generation | 60-120 seconds |
| Music generation | 30-90 seconds |

**Set appropriate timeouts in your client:**
```python
requests.post(url, json=data, timeout=120)
```

---

## Error Handling

| Status | Meaning |
|--------|---------|
| 200 | Success (check `ok` field) |
| 422 | Validation error |
| 500 | Server error |

**Error response:**
```json
{
  "ok": false,
  "speech": null,
  "response": null,
  "tools_used": [],
  "session_id": null,
  "error": "Error description here"
}
```

---

## Tips

1. **Use POST** for anything beyond simple questions
2. **Set timeouts** appropriately (30-120s for complex queries)
3. **Check `tools_used`** to understand what Jarvis did
4. **Use `session_id`** for tracking in logs
5. **Local mode** is slower but fully private

---

## See Also

- [API Overview](./API_OVERVIEW.md) - Full API documentation
- [Memory API](./MEMORY.md) - Direct memory access
- [Test API](./TEST_API.md) - Testing examples
