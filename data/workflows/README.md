# Workflow Definitions

This folder contains JSON workflow definitions that the orchestrator can execute as deterministic multi-step pipelines.

## Quick Start

1. Create a new `.json` file in this folder
2. Use an existing workflow as a template
3. Set `"enabled": true` to activate
4. Trigger via explicit command (e.g., `/archive`, `/research`)

## Workflow Structure

```json
{
  "id": "unique_id",
  "name": "Display Name",
  "description": "What this workflow does",
  "enabled": true,
  "triggers": {
    "explicit": ["/command"]
  },
  "variables": {
    "location": "Static value here"
  },
  "steps": [
    {"step": 1, "tool": "tool_name", "params": {...}}
  ],
  "success_speech": "Spoken on completion"
}
```

## Current Workflows

| File | Command | Description |
|------|---------|-------------|
| `web_archive.json` | `/archive <url>` | Fetch URL, save to stash, create canvas summary |
| `deep_research.json` | `/research <topic>` | Multi-source research with validation |
| `quick_note.json` | `/note <text>` | Quick note to memory and canvas |
| `server_health_check.json` | `/health <host>` | SSH health check on remote server |
| `daily_status.json` | `/status` | Weather, crypto, stocks, alerts, system health dashboard |
| `daily_status_visual.json` | `/status-visual` | Same as /status but with AI-generated dashboard image |
| `crypto_market_report.json` | `/crypto [coins]` | Crypto prices with canvas report |
| `youtube_research.json` | `/youtube_research <url> [notes]` | Download transcript, summarize, keywords, canvas study notes |
| `url_ingest.json` | `/url_ingest <url>` | Fetch any URL, create intel file, ingest to memory for RAG queries |
| `deep_dive.json` | `/deep-dive <topic or url>` | Screenshot + crawl + comprehensive canvas analysis with pros/cons, links |

## Variables

Two formats supported:

**Simple static values:**
```json
"variables": {
  "location": "Hillsboro, Oregon",
  "timeout": 30,
  "enabled": true
}
```

**Dynamic extraction:**
```json
"variables": {
  "topic": {"from": "query", "extract": "main_subject"},
  "url": {"from": "query", "extract": "url"},
  "host": {"from": "query", "extract": "main_subject", "default": "vps2"},
  "url_domain": {"from": "url", "transform": "domain"}
}
```

**Variable usage:**
- `${topic}` - Simple variable
- `${article.content}` - Nested path from previous step
- `${urls[:5]}` - Array slice (first 5 items)
- `${url_domain}` - Extracted domain from URL (e.g., "cursor.com")

## Stash Kinds

The `stash` tool supports these `kind` values:
- `text` - Plain text content (use `text` param)
- `json` - JSON object (use `json` param)  
- `base64` - Binary data as base64 (use `data` param)
- `url` - Download from URL (use `url` param)
- `file` - Copy local file (use `file_path` param) - useful for screenshots

## Canvas Folder Structure

Use folder paths in canvas titles for organization:
```json
"params": {
  "title": "Workflows/Deep Dive/${url_domain}",
  "tags": ["workflow-type", "${url_domain}"]
}
```

## Resilient Workflows

For steps that may fail (e.g., crawling protected sites):
```json
{
  "step": 4,
  "tool": "crawl_url",
  "params": {"url": "${url}"},
  "required": false,
  "on_fail": "continue",
  "description": "Optional - continues if blocked"
}
```

## LLM Prompts

When using `llm_prompt` for canvas content, tell the LLM to use actual values:
```
IMPORTANT: Use the actual values from the input data above - do not output placeholder syntax like ${var}.
```

This prevents the LLM from echoing `${variable}` in its output.

## Extract Rules

Extract paths are relative to `result.data` - do NOT include `data.` prefix:

```json
// CORRECT - paths relative to data
"extract": {"temperature": "temperature", "cpu": "cpu.total_percent"}

// WRONG - don't include data. prefix
"extract": {"temperature": "data.temperature"}
```

## Documentation

- Full reference: [docs/WORKFLOW_ORCHESTRATION.md](../../docs/WORKFLOW_ORCHESTRATION.md)
- Tool structures: [AGENTS.md](AGENTS.md)
