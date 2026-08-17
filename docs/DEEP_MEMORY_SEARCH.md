# Deep Memory Search

Comprehensive search tool that queries **ALL** Jarvis data sources in a single call.

## Overview

`deep_memory_search` is designed for exhaustive searches when:
- Normal memory tools (`search_memory`, `semantic_recall`) return nothing
- User needs to find "everything" related to a topic
- Information is known to exist but quick searches miss it
- Cross-source search is required (memory + conversations + files)

## Data Sources Searched

| Source | Location | Search Method |
|--------|----------|---------------|
| **Memory DB** | `data/jarvis_memory.db` | FTS5 (BM25) + Semantic embeddings |
| **Terminal Conversations** | `conversations` table | SQL text search |
| **Web Conversations** | `data/web_conversations/*.json` | ripgrep JSON files |
| **Intel Folder** | `jarvis-intel/*.md` | ripgrep markdown files |
| **Canvas Pages** | `data/canvas/*.json` | ripgrep + JSON parse |
| **Stash Spaces** | `data/stash/*/meta.json` | JSON metadata search |

## Usage

### Via Orchestrator
```bash
./orchestrator/orchestrator_v2.py cloud "use deep_memory_search to find everything about spotify"
```

### Direct Test
```bash
python skills/deep_memory_search.py '{"query": "network", "limit_per_source": 5}'
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | **required** | Search query (keywords, phrase, or natural language) |
| `sources` | array | `["all"]` | Which sources to search. Options: `memory`, `conversations`, `web_conversations`, `intel`, `canvas`, `stash`, `all` |
| `mode` | string | `comprehensive` | `comprehensive` (keyword + semantic), `keyword` (faster), `semantic` (meaning-based) |
| `limit_per_source` | int | 5 | Max results per source |
| `date_filter` | string | null | `today`, `week`, `month`, `year`, or ISO date |

## Output Structure

```json
{
  "ok": true,
  "speech": "Found 12 results for 'spotify': 5 in memory, 5 in terminal_conversations...",
  "data": {
    "query": "spotify",
    "summary": {
      "total_results": 12,
      "by_source": {
        "memory": 5,
        "terminal_conversations": 5,
        "web_conversations": 1,
        "intel": 1
      },
      "sources_with_matches": ["memory", "terminal_conversations", "web_conversations", "intel"]
    },
    "results": {
      "memory": [...],
      "terminal_conversations": [...],
      "web_conversations": [...],
      "intel": [...]
    },
    "flat_results": [...]  // All results with _source labels
  }
}
```

### Result Labels

Every result includes:
- `_source`: Machine-readable source type (e.g., `memory_keyword`, `web_conversation`)
- `_source_display`: Human-readable label (e.g., "Memory (keyword match)", "Web UI Conversation")
- `_duplicate_of`: Set if similar content found in another source

## When to Use vs Other Tools

| Tool | Use For |
|------|---------|
| `search_memory` | Quick keyword lookups (1-3 words) |
| `semantic_recall` | Natural language questions about remembered facts |
| `search_conversations` | Find specific past dialogue topics |
| `deep_memory_search` | **Exhaustive cross-source search** when others fail |

## Technical Details

### ripgrep Integration

Uses `rg --json` for fast file-based searches:
- Smart-case matching
- Multiline support
- Targeted paths only (not system-wide)
- JSON output for clean parsing

### Deduplication

Results are deduplicated based on content fingerprinting:
- Similar content in memory AND intel won't appear twice
- Marked with `_duplicate_of` when overlap detected

### Performance

- **Slower than single-source tools** by design
- Searches 6 sources sequentially in one call
- `limit_per_source` controls total result volume
- Use narrow `sources` filter if you know where to look

## Examples

### Find Everything About a Topic
```bash
./orchestrator/orchestrator_v2.py cloud "deep search everything about network configuration"
```

### Search Only Conversations
```bash
python skills/deep_memory_search.py '{"query": "christmas music", "sources": ["conversations", "web_conversations"]}'
```

### Search with Date Filter
```bash
python skills/deep_memory_search.py '{"query": "project", "date_filter": "month"}'
```

## Related Tools

- `search_memory` - FTS5 keyword search in memory
- `semantic_recall` - Hybrid embedding + FTS5/BM25 memory search
- `search_conversations` - Terminal conversation history
- `manage_intel` - Intel folder CRUD operations
- `canvas` - Canvas page operations
- `stash` - Artifact storage operations

---

**Added:** 2025-12-31  
**Tool File:** `skills/deep_memory_search.py`  
**Definition:** `skills/deep_memory_search.tool.json`
