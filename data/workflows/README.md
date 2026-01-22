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

## Variables

- `${topic}` - Main subject from query
- `${url}` - URL extracted from query
- `${timestamp}` - Current ISO timestamp
- `${article.content}` - Nested path from previous step
- `${urls[:5]}` - Array slice (first 5 items)

## Documentation

Full documentation: [docs/WORKFLOW_ORCHESTRATION.md](../../docs/WORKFLOW_ORCHESTRATION.md)
