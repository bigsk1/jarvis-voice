# Workflows API

> **Version**: 1.1 | **Updated**: February 2026

The Workflows API provides programmatic access to Jarvis workflow orchestration. Execute predefined multi-tool pipelines, list available workflows, and monitor execution history.

---

## Overview

Workflows are deterministic multi-tool pipelines triggered by explicit commands (e.g., `/crypto`, `/research`). Unlike normal LLM routing, workflows:

- Execute tools in a predefined sequence
- Use variable substitution between steps
- Support validation and retry logic
- Bypass intelligence layer (no LLM routing decisions to learn from)

---

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/workflows` | GET | List all available workflows |
| `/api/workflows/{id}` | GET | Get workflow details |
| `/api/workflows/{id}/execute` | POST | Execute a workflow |
| `/api/workflows/history` | GET | Get execution history |

---

## List Workflows

Get all available workflows with their triggers and tools.

```bash
curl http://localhost:8880/api/workflows | jq
```

**Response:**
```json
{
  "workflows": [
    {
      "id": "crypto_market_report",
      "name": "Crypto Market Report Workflow",
      "description": "Get crypto prices, search news, analyze market, save to canvas, email report",
      "trigger": "/crypto",
      "version": "1.1",
      "tools_used": ["get_time", "crypto_price", "mcp_brave_search_brave_web_search", "crawl_url", "stash", "canvas", "send_email"]
    },
    {
      "id": "web_archive",
      "name": "Web Archive Workflow",
      "description": "Archive a webpage to stash with summary in Canvas",
      "trigger": "/archive",
      "tools_used": ["crawl_url", "stash", "remember", "canvas"]
    }
  ],
  "count": 5
}
```

---

## Get Workflow Details

Get details about a specific workflow including all steps.

```bash
curl http://localhost:8880/api/workflows/crypto_market_report | jq
```

**Response:**
```json
{
  "id": "crypto_market_report",
  "name": "Crypto Market Report Workflow",
  "description": "Get crypto prices, search news, analyze market, email report",
  "trigger": "/crypto",
  "version": "1.1",
  "tools_used": ["get_time", "crypto_price", "mcp_brave_search_brave_web_search", "crawl_url", "stash", "canvas", "send_email"]
}
```

---

## Execute Workflow

Execute a workflow by ID. Optionally pass query parameters.

### Basic Execution (Default Parameters)

```bash
# Execute crypto report with default coins (Bitcoin, Solana)
curl -X POST http://localhost:8880/api/workflows/crypto_market_report/execute | jq
```

### Execution with Custom Query

```bash
# Execute crypto report with custom coins
curl -X POST http://localhost:8880/api/workflows/crypto_market_report/execute \
  -H "Content-Type: application/json" \
  -d '{"query": "ethereum xrp"}' | jq
```

### Execution with Mode Selection

```bash
# Use local LLM mode
curl -X POST http://localhost:8880/api/workflows/crypto_market_report/execute \
  -H "Content-Type: application/json" \
  -d '{"query": "bitcoin", "mode": "local"}' | jq
```

**Request Body:**
```json
{
  "query": "ethereum xrp",  // Optional: parameters for workflow
  "mode": "cloud"           // Optional: "cloud" (default) or "local"
}
```

`mode` is strictly validated as `cloud` or `local`. Invalid values return
`422 Unprocessable Entity`, and the workflow executes inside the selected
mode's request-local config scope.

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `ok` | bool | Success status |
| `workflow_id` | string | Workflow that was executed |
| `speech` | string | Final speech response |
| `tools_used` | string[] | Tools that were executed |
| `steps_completed` | int | Number of steps completed |
| `duration_ms` | float | Execution time in milliseconds |
| `data` | object | Accumulated data from steps |
| `usage` | object | LLM token usage (`input_tokens`, `output_tokens`, `cost_usd`) |
| `server_side_tools` | object | LLM provider native tools (xAI `web_search`, `x_search`, etc.) |
| `error` | string | Error message (if failed) |

**Example Response:**
```json
{
  "ok": true,
  "workflow_id": "crypto_market_report",
  "speech": "Crypto market report complete. Bitcoin is at 89651 dollars, 2.05% change.",
  "tools_used": ["get_time", "crypto_price", "mcp_brave_search_brave_web_search", "crawl_url", "stash", "canvas", "send_email"],
  "steps_completed": 9,
  "duration_ms": 45230.5,
  "data": {
    "coin1_price": "89651",
    "coin1_change": "2.05"
  },
  "usage": {
    "input_tokens": 22666,
    "output_tokens": 1645,
    "total_tokens": 24311,
    "cost_usd": 0.005356
  },
  "server_side_tools": {
    "SERVER_SIDE_TOOL_X_SEARCH": 3,
    "SERVER_SIDE_TOOL_WEB_SEARCH": 2
  }
}
```

**Note:** Workflow execution can take 30-120+ seconds depending on the workflow complexity.

---

## Get Execution History

View recent workflow executions with success/failure stats.

```bash
# Get last 20 executions
curl "http://localhost:8880/api/workflows/history" | jq

# Filter by workflow ID
curl "http://localhost:8880/api/workflows/history?workflow_id=crypto_market_report" | jq

# Limit results
curl "http://localhost:8880/api/workflows/history?limit=5" | jq

# Search further back
curl "http://localhost:8880/api/workflows/history?days=30&limit=50" | jq
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 20 | Maximum executions to return |
| `workflow_id` | string | - | Filter by specific workflow |
| `days` | int | 7 | How many days back to search |

**Response:**
```json
{
  "executions": [
    {
      "timestamp": "2026-01-22T10:25:42.235173",
      "workflow_id": "crypto_market_report",
      "workflow_name": "Crypto Market Report Workflow",
      "user_query": "/crypto",
      "ok": true,
      "speech": "Crypto market report complete. Bitcoin is at 89651 dollars.",
      "steps_completed": 9,
      "tools_used": ["get_time", "crypto_price", "mcp_brave_search_brave_web_search", "canvas", "send_email"],
      "duration_ms": 99995.35
    }
  ],
  "count": 5,
  "success_count": 4,
  "failure_count": 1
}
```

---

## Error Handling

### Workflow Not Found

```json
{
  "detail": "Workflow 'nonexistent' not found"
}
```
HTTP Status: 404

### Execution Error

```json
{
  "ok": false,
  "workflow_id": "web_archive",
  "error": "Step 1 failed: URL is required",
  "speech": null,
  "tools_used": [],
  "steps_completed": 0,
  "duration_ms": 150.2
}
```

---

## Available Workflows

| Workflow ID | Triggers | Description |
|-------------|----------|-------------|
| `crypto_market_report` | `/crypto` | Crypto prices, news, analysis, email report (default: BTC, SOL) |
| `daily_status` | `/status`, `/daily`, `/briefing`, `/recap` | Weather, crypto (+ 7d `crypto_chart` embeds), stocks, alerts, reminders, health → Canvas report |
| `daily_status_visual` | `/status-visual`, `/status-image`, `/daily-visual` | Same as `daily_status` (including Canvas crypto charts) plus AI-generated dashboard image |
| `deep_dive` | `/deep-dive`, `/dive` | Screenshot + crawl URL, create comprehensive Canvas summary with visual |
| `deep_research` | `/research` | Multi-source research with Brave + crawling, validates sources |
| `quick_note` | `/note`, `/quicknote`, `/remember-this` | Save note to memory + Canvas |
| `server_health_check` | `/health`, `/server-check` | SSH health check using hosts from config/ssh.json |
| `url_ingest` | `/url_ingest`, `/ingest_url`, `/learn_url` | Fetch URL, extract facts, create intel file, ingest to memory for RAG |
| `web_archive` | `/archive` | Archive webpage to stash with Canvas summary |
| `youtube_research` | `/youtube_research`, `/yt-research`, `/study-video` | Download transcript, summarize, create study notes on Canvas |

**Note:** Workflows can be triggered via API using workflow ID or trigger alias:
```bash
# By workflow ID
curl -X POST http://localhost:8880/api/workflows/server_health_check/execute

# By trigger alias (also works!)
curl -X POST http://localhost:8880/api/workflows/health/execute

# With query parameter (for workflows that need input)
curl -X POST http://localhost:8880/api/workflows/deep_research/execute \
  -H "Content-Type: application/json" \
  -d '{"query": "Cursor CLI features"}'
```

**Important:** For workflows that require a topic (like `deep_research`, `web_archive`), pass the topic in the `query` field - do NOT include the trigger prefix:
- ✅ Correct: `{"query": "Cursor CLI features"}`
- ❌ Wrong: `{"query": "/research Cursor CLI features"}` (trigger prefix is added automatically)

---

## Integration Examples

### Python

```python
import requests

BASE_URL = "http://localhost:8880"

# List workflows
workflows = requests.get(f"{BASE_URL}/api/workflows").json()
print(f"Available: {[w['trigger'] for w in workflows['workflows']]}")

# Execute workflow
result = requests.post(
    f"{BASE_URL}/api/workflows/crypto_market_report/execute",
    json={"query": "bitcoin ethereum"}
).json()

if result["ok"]:
    print(f"Success! {result['speech']}")
    print(f"Tools: {result['tools_used']}")
else:
    print(f"Failed: {result['error']}")
```

### Bash

```bash
#!/bin/bash
# Execute crypto report and check result

result=$(curl -s -X POST http://localhost:8880/api/workflows/crypto_market_report/execute)
ok=$(echo $result | jq -r '.ok')

if [ "$ok" = "true" ]; then
    echo "Success!"
    echo $result | jq -r '.speech'
else
    echo "Failed:"
    echo $result | jq -r '.error'
fi
```

### n8n Workflow

Use HTTP Request node:
- **Method**: POST
- **URL**: `http://jarvis:8880/api/workflows/crypto_market_report/execute`
- **Body**: `{"query": "{{ $json.coins }}"}`

---

## See Also

- **[WORKFLOW_ORCHESTRATION.md](../WORKFLOW_ORCHESTRATION.md)** - Full workflow system documentation
- **[data/workflows/AGENTS.md](../../data/workflows/AGENTS.md)** - Workflow building guide
- **[Query API](QUERY.md)** - For normal LLM routing (non-workflow)
