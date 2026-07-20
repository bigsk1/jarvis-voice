# Jarvis Metadata System

**Status:** Active (evolving)
**Implemented:** 2025-11-14
**Updated:** 2026-03-30 (conversation linking, Completion Guard exports)
**Purpose:** Track model usage, performance, and costs across conversations and memories

---

## Overview

The metadata system adds structured tracking to conversations and memories, enabling:
- **Cost tracking** - Monitor API spending for cloud providers
- **Performance monitoring** - Track response times and efficiency
- **Model attribution** - Know which model/provider was used
- **Analytics foundation** - Data for usage reports and insights

---

## Conversations Metadata

Every conversation logged to the database now includes metadata:

```json
{
  "mode": "cloud",
  "provider": "anthropic",
  "model": "claude-sonnet-5",
  "execution_time_ms": 2341.5,
  "tool_count": 2,
  "input_tokens": 1250,
  "output_tokens": 423,
  "total_tokens": 1673,
  "cost_usd": 0.0101,
  "web_conversation_id": "abc123..."
}
```

### Fields

| Field | Type | Description | Cloud Only |
|-------|------|-------------|------------|
| `mode` | string | "cloud" or "local" | No |
| `provider` | string | "openai", "anthropic", "xai", or "ollama" | No |
| `model` | string | Model name (e.g., "gemma4", "grok-4.5", "gpt-5.4-nano") | No |
| `execution_time_ms` | float | Total conversation time | No |
| `tool_count` | int | Number of tools executed | No |
| `input_tokens` | int | Input token count | Yes |
| `output_tokens` | int | Output token count | Yes |
| `total_tokens` | int | Total tokens used | Yes |
| `cost_usd` | float | Estimated cost in USD | Yes |
| `web_conversation_id` | string | Stable ID for the Jarvis Web chat session (when the request comes from the Web UI); omitted for CLI/voice | No |

**Web UI conversation exports** may also embed a `_completion_guard` block on the saved message when Completion Guard ran; that lives in export JSON, not necessarily in the `conversations.metadata` column. See [Completion Guard](./COMPLETION_GUARD.md).

### Usage

```python
from memory_db import get_memory_db

db = get_memory_db()

# Log with metadata
db.log_conversation(
    user_query="What's the weather?",
    jarvis_response="It's sunny",
    tools_used=["api_call"],
    success=True,
    metadata={
        "mode": "cloud",
        "provider": "openai",
        "model": "gpt-5.4-nano",
        "execution_time_ms": 1234.5,
        "tool_count": 1,
        "input_tokens": 150,
        "output_tokens": 50,
        "total_tokens": 200,
        "cost_usd": 0.0003
    }
)
```

---

## Knowledge Base Metadata

Memories can include metadata for richer context:

```json
{
  "tags": ["server", "tetris", "flask"],
  "related_projects": ["tetris-game"],
  "expires_at": "2025-12-31",
  "confidence": 0.95,
  "learned_from": "conversation_id:1234",
  "source_file": "jarvis-intel/example_network.md"
}
```

### Common Use Cases

**1. Project Tracking**
```python
db.remember(
    category="project",
    key="tetris_server_command",
    value="cd ~/jarvis-workspace/projects/tetris-game && python server.py",
    metadata={
        "tags": ["server", "flask", "tetris"],
        "related_projects": ["tetris-game"],
        "verified": True
    }
)
```

**2. Temporary Information**
```python
db.remember(
    category="fact",
    key="temporary_token",
    value="abc123xyz",
    metadata={
        "expires_at": "2025-11-20",
        "temporary": True
    }
)
```

**3. Source Attribution**
```python
db.remember(
    category="technical",
    key="network_config",
    value="localhost",
    metadata={
        "source_file": "jarvis-intel/example_network.md",
        "ingested_at": "2025-11-14T10:30:00Z",
        "confidence": 1.0
    }
)
```

---

## Cost Estimation

**Module:** `lib/cost_estimator.py`

### Supported Providers

| Provider | Models Tracked | Notes |
|----------|---------------|-------|
| OpenAI | GPT-5.x / 4.1 family and others in `lib/cost_estimator.py` | Pricing maintained in code; defaults drift over time |
| Anthropic | claude-sonnet-5, claude-sonnet-4-5-20250929, claude-opus-4-6, and others in `lib/model_catalog.py` | Pricing maintained in catalog; defaults drift over time |
| Ollama | *None* | Local models have no API costs |

### Usage

```python
from cost_estimator import estimate_cost, format_cost_summary

# Estimate cost
cost_info = estimate_cost(
    provider="anthropic",
    model="claude-sonnet-5",
    input_tokens=1000,
    output_tokens=500
)

print(cost_info)
# {
#   "input_tokens": 1000,
#   "output_tokens": 500,
#   "total_tokens": 1500,
#   "cost_usd": 0.007
# }

# Human-readable format
print(format_cost_summary(cost_info))
# "1500 tokens ($0.0105)"
```

### Pricing metadata

Jarvis' curated model IDs, context windows, and estimation rates live in
`lib/model_catalog.py`. Do not copy an old pricing table into operational
configuration: provider prices change independently of Jarvis releases.

Ollama local inference reports `$0` model API cost. Ollama Cloud retains token
usage but records compute/subscription cost as unknown because the daemon does
not expose a per-request dollar amount.

---

## Analytics Queries

### Total Spending (Cloud)
```bash
sqlite3 data/jarvis_memory.db <<EOF
SELECT
  json_extract(metadata, '$.provider') as provider,
  json_extract(metadata, '$.model') as model,
  COUNT(*) as conversations,
  SUM(CAST(json_extract(metadata, '$.cost_usd') AS REAL)) as total_cost
FROM conversations
WHERE metadata IS NOT NULL
  AND json_extract(metadata, '$.cost_usd') IS NOT NULL
GROUP BY provider, model
ORDER BY total_cost DESC;
EOF
```

### Average Response Time
```bash
sqlite3 data/jarvis_memory.db <<EOF
SELECT
  json_extract(metadata, '$.mode') as mode,
  AVG(CAST(json_extract(metadata, '$.execution_time_ms') AS REAL)) as avg_time_ms,
  MIN(CAST(json_extract(metadata, '$.execution_time_ms') AS REAL)) as min_time_ms,
  MAX(CAST(json_extract(metadata, '$.execution_time_ms') AS REAL)) as max_time_ms
FROM conversations
WHERE metadata IS NOT NULL
GROUP BY mode;
EOF
```

### Token Usage by Tool
```bash
sqlite3 data/jarvis_memory.db <<EOF
SELECT
  json_extract(tools_used, '$[0]') as first_tool,
  COUNT(*) as uses,
  AVG(CAST(json_extract(metadata, '$.total_tokens') AS REAL)) as avg_tokens,
  SUM(CAST(json_extract(metadata, '$.cost_usd') AS REAL)) as total_cost
FROM conversations
WHERE tools_used IS NOT NULL
  AND metadata IS NOT NULL
GROUP BY first_tool
ORDER BY total_cost DESC
LIMIT 10;
EOF
```

### Most Expensive Conversations
```bash
sqlite3 data/jarvis_memory.db <<EOF
SELECT
  user_query,
  json_extract(metadata, '$.total_tokens') as tokens,
  json_extract(metadata, '$.cost_usd') as cost,
  json_extract(metadata, '$.tool_count') as tools,
  timestamp
FROM conversations
WHERE metadata IS NOT NULL
ORDER BY CAST(json_extract(metadata, '$.cost_usd') AS REAL) DESC
LIMIT 10;
EOF
```

---

## Local Model Corrections

**Module:** `lib/local_model_corrections.py`

Automatically fixes common formatting issues from local LLMs (`qwen3.5:latest`, etc.) without breaking legitimate use cases.

### Corrections Applied

**1. Tool Name Normalization**
```python
"send webhook" → "send_webhook"
"MCP-DuckDuckGo-Search" → "mcp_duckduckgo_search"
"ApiCall" → "api_call"
```

**2. Memory Key Normalization**
```python
"favorite color" → "favorite_color"
"My API Key" → "my_api_key"
"webhook URL" → "webhook_url"
```

**3. Smart URL Fixing**
```python
# Local network → http://
"localhost:8080" → "http://localhost:8080"
"192.168.1.1" → "http://192.168.1.1"
"10.0.0.5:5000" → "http://10.0.0.5:5000"

# Public domains → https://
"example.com" → "https://example.com"
"google.com" → "https://google.com"

# Already has scheme → unchanged
"http://localhost" → "http://localhost"
"https://api.example.com" → "https://api.example.com"
```

### Usage

```python
from local_model_corrections import correct_tool_call

# Raw tool call from local LLM
raw_call = {
    "name": "send webhook",
    "arguments": {
        "url": "192.168.1.100:3000",
        "key": "my api key"
    }
}

# Apply corrections
corrected = correct_tool_call(raw_call)

print(corrected)
# {
#   "name": "send_webhook",
#   "arguments": {
#     "url": "http://192.168.1.100:3000",
#     "key": "my_api_key"
#   }
# }
```

Corrections are **automatically applied** for Ollama provider in `lib/llm_provider.py`.

---

## Configuration

### Enable/Disable Cost Tracking

Cost tracking is automatic for cloud providers. To disable, modify `orchestrator_v2.py`:

```python
# Line ~195
token_info = None  # Always None = disabled
# OR
token_info = total_usage if total_usage["cost_usd"] > 0 else None  # Current (enabled)
```

### Update Pricing

Edit `lib/cost_estimator.py`:

```python
PRICING = {
    "anthropic": {
        "claude-sonnet-5": {
            "input": 3.00,   # USD per 1M tokens
            "output": 15.00
        }
    }
}
```

---

## Testing

```bash
# Test cost estimation
cd ~/jarvis-voice
source ~/jarvis-venv/bin/activate
python3 -c "
from lib.cost_estimator import estimate_cost, format_cost_summary
cost = estimate_cost('anthropic', 'claude-sonnet-5', 1000, 500)
print(format_cost_summary(cost))
"

# Test local corrections
python3 -c "
from lib.local_model_corrections import correct_tool_call
raw = {'name': 'send webhook', 'arguments': {'url': 'localhost:8080'}}
print(correct_tool_call(raw))
"

# Check metadata in database
sqlite3 data/jarvis_memory.db "
SELECT metadata FROM conversations
WHERE metadata IS NOT NULL
ORDER BY id DESC
LIMIT 1;
"
```

---

## Troubleshooting

### "cost_usd always 0"
- Check if you're using a cloud provider (OpenAI/Anthropic/xAI)
- Ollama is local (free) so cost is always 0
- Verify model name matches PRICING table

### "metadata is NULL"
- Older conversations logged before Nov 14, 2024
- Only new conversations have metadata
- Old data is not backfilled

### "Unknown model" in cost estimate
- Model not in PRICING table
- Partial matches are tried (e.g., "gpt-4o-mini-2024" matches "gpt-4o-mini")
- Add your model to `lib/cost_estimator.py`

---

*Last Updated: 2026-03-30*
*Related Docs: COMPLETION_GUARD.md, [archive/DATABASE_DEEP_DIVE.md](archive/DATABASE_DEEP_DIVE.md), MEMORY_SYSTEM.md*
