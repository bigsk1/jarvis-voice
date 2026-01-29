# QMD - Quick Markdown Search

Local search engine for Jarvis documentation using [tobi/qmd](https://github.com/tobi/qmd).

## Why QMD?

- **148 markdown docs** indexed with rich context descriptions
- **BM25 keyword search** - fast, accurate for exact terms
- **Semantic search** - find by meaning when keywords fail
- **33 context annotations** - sections have detailed descriptions to improve relevance

## Quick Reference

```bash
# Fast keyword search (default, use most often)
qmd search "canvas api"
qmd search "webhook" -n 10

# Get full document
qmd get "CANVAS_SYSTEM.md" --full
qmd get "#abc123"  # by docid from search results

# List files in collection
qmd ls jarvis-docs
qmd ls jarvis-docs/api

# Semantic search (slower, use when keywords fail)
qmd vsearch "how does memory persistence work"

# Hybrid search with re-ranking (best quality, slowest)
qmd query "authentication flow"

# JSON output for scripting
qmd search "reminder" --json -n 5

# Check index status
qmd status
```

## Collection: jarvis-docs

| Path | Description |
|------|-------------|
| `/` | Root - all 148 docs for Jarvis voice assistant |
| `/api` | REST API docs for port 8880 (memory, reminders, canvas, etc.) |
| `/api/code-examples` | Python, Bash, Node.js code snippets |
| `/n8n` | n8n workflow automation (calendar, email, webhooks) |
| `/mcp` | MCP server docs (Brave, Fetch, Playwright) |
| `/opencode` | Autonomous coding agent integration |
| `/spotify` | Music control integration |
| `/service` | systemd service architecture |

## Key Documents

| Document | Topic |
|----------|-------|
| `INTELLIGENCE_LAYER.md` | Orchestration, routing, conversation state |
| `MEMORY_SYSTEM.md` | FTS5 search, semantic embeddings, categories |
| `CANVAS_SYSTEM.md` | Visual artifacts, pins, gallery |
| `TOOL_MANAGEMENT.md` | 54+ tools, enable/disable, roadmap |
| `WORKFLOW_ORCHESTRATION.md` | Deterministic multi-tool workflows |
| `DISASTER_RECOVERY.md` | Backup, restore, migration |
| `JARVIS_WEB_UI.md` | Web interface, routes, WebSocket |

## Maintenance

```bash
# Re-index after adding/changing docs
qmd update

# Re-generate embeddings (if models updated)
qmd embed -f

# Add context to new section
qmd context add qmd://jarvis-docs/new-section "Description of what this section covers"
```

## Search Strategy

1. **Start with keyword search** - `qmd search "exact term"` is fast and precise
2. **Use semantic if keywords fail** - `qmd vsearch "concept or question"`
3. **Use hybrid for complex queries** - `qmd query "multi-concept question"`
4. **Get full content** - `qmd get "filename.md" --full` after finding the right doc

## First-Time Setup

```bash
# Models are auto-downloaded on first embed (~3GB total)
qmd embed

# Verify
qmd status
```
