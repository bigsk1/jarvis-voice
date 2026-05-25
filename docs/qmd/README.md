# QMD - Quick Markdown Search

Local search engine for Jarvis documentation using [tobi/qmd](https://github.com/tobi/qmd).

## Why QMD?

- **164 markdown docs** indexed with rich context descriptions (excludes personal/private dirs)
- **BM25 keyword search** - fast, accurate for exact terms
- **Semantic search** - find by meaning when keywords fail
- **33 context annotations** - sections have detailed descriptions to improve relevance

## Jarvis Docs assistant

The [Jarvis Docs viewer](../../jarvis-docs/) (often served on port `:5004`) includes an in-page **Docs assistant** that retrieves excerpts from `docs/` before answering. That pipeline uses QMD **when available** and degrades safely when it is not:

- **`qmd` on PATH** — Semantic (`vsearch`) and keyword-backed retrieval run against your indexed `jarvis-docs` collection (see [First-Time Setup](#first-time-setup)). This improves “what does X mean?” style questions.
- **No QMD** — Retrieval skips semantic search and relies on **ripgrep** (`rg`) over the repo’s `docs/` tree when `rg` is installed. The assistant does not crash; the UI shows retrieval metadata (mode, counts) so clones without optional QMD still work for keyword-style grounding.
- **Neither tool** — The server avoids broken subprocess calls; responses may be thinner, and metadata reflects limited retrieval.

Treat QMD as **recommended**, not mandatory, for local docs browsing and the assistant.

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

# JSON output for scripting/agents
qmd search "reminder" --json -n 5

# Check index status
qmd status
```

## Search Options

```bash
-n <num>           # Number of results (default: 5, or 20 for --json/--files)
-c, --collection   # Restrict to collection: -c jarvis-docs
--all              # Return all matches (use with --min-score to filter)
--min-score <num>  # Minimum score threshold (0.0-1.0)
--full             # Show full document content
--line-numbers     # Add line numbers to output
--index <name>     # Use named index

# Output formats
--json             # JSON output with snippets (best for LLM/agents)
--files            # Output: docid,score,filepath,context
--csv              # CSV output
--md               # Markdown output
--xml              # XML output
```

## Get Options

```bash
qmd get <file>[:line]         # Get document, optionally starting at line
qmd get "file.md" --full      # Full content
qmd get "file.md:50" -l 100   # Start at line 50, max 100 lines
qmd get "#abc123"             # By docid from search results
-l <num>                      # Maximum lines to return
--from <num>                  # Start from line number
```

## Multi-Get Options

```bash
qmd multi-get "docs/*.md"           # Get by glob pattern
qmd multi-get "doc1.md, doc2.md"    # Comma-separated list
qmd multi-get "#abc123, #def456"    # Multiple docids
-l <num>                            # Max lines per file
--max-bytes <num>                   # Skip files > N bytes (default: 10KB)
--json                              # JSON output
```

## Collection: jarvis-docs

| Path | Description |
|------|-------------|
| `/` | Root - all public docs for Jarvis voice assistant |
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
| `TOOL_MANAGEMENT.md` | 75+ tools, enable/disable, roadmap |
| `WORKFLOW_ORCHESTRATION.md` | Deterministic multi-tool workflows |
| `INSTALL_GUIDE.md` | Installation and setup guide |
| `JARVIS_WEB_UI.md` | Web interface, routes, WebSocket |

## Maintenance

### Adding New Docs

```bash
# After adding a new markdown file to docs/:
# WARNING: plain `qmd update` re-scans ALL **/*.md under docs/, including
# gitignored personal/ vps2/ samantha-skill/ if those folders exist on disk.
# Use the exclusion procedure below after update if private dirs are present.
qmd update           # Re-scans for new/changed files
qmd embed            # Only embeds new/modified files (incremental)

# Verify
qmd status
```

### Full Re-index

```bash
# Re-index with git pull first (for remote repos)
qmd update --pull

# Force re-embed everything (if models changed or issues)
qmd embed -f
```

### Excluding Directories

QMD doesn't respect .gitignore. To exclude directories (e.g., `docs/personal/`):

```bash
# 1. Temporarily move excluded dirs
mkdir -p /tmp/qmd-exclude
mv docs/personal docs/samantha-skill docs/vps2 /tmp/qmd-exclude/

# 2. Rebuild collection
qmd collection remove jarvis-docs
qmd collection add ./docs --name jarvis-docs --mask "**/*.md"
qmd embed

# 3. Restore excluded dirs
mv /tmp/qmd-exclude/* docs/
rmdir /tmp/qmd-exclude
```

Index stored in: ~/.cache/qmd/index.sqlite

collections     -- Indexed directories with name and glob patterns
path_contexts   -- Context descriptions by virtual path (qmd://...)
documents       -- Markdown content with metadata and docid (6-char hash)
documents_fts   -- FTS5 full-text index
content_vectors -- Embedding chunks (hash, seq, pos, 800 tokens each)
vectors_vec     -- sqlite-vec vector index (hash_seq key)
llm_cache       -- Cached LLM responses (query expansion, rerank scores)


**Currently excluded:** `docs/personal/`, `docs/samantha-skill/`, `docs/vps2/`

### Adding Context Descriptions

```bash
# Add context to new section (improves search relevance)
qmd context add qmd://jarvis-docs/new-section "Description of what this section covers"

# List all contexts
qmd context list

# Check status
qmd status
```

## Search Strategy

1. **Start with keyword search** - `qmd search "exact term"` is fast and precise
2. **Use `--json` for parsing** - structured output for scripts/agents
3. **Use semantic if keywords fail** - `qmd vsearch "concept or question"`
4. **Use hybrid for complex queries** - `qmd query "multi-concept question"`
5. **Get full content** - `qmd get "filename.md" --full` after finding the right doc

## For AI Agents

QMD's `--json` and `--files` formats are designed for agentic workflows:

```bash
# Get structured results for parsing
qmd search "authentication" --json -n 10

# List all relevant files above a threshold
qmd query "error handling" --all --files --min-score 0.4

# Retrieve full document content
qmd get "MEMORY_SYSTEM.md" --full
```

## First-Time Setup

```bash
# Create collection (already done)
qmd collection add ./docs --name jarvis-docs --mask "**/*.md"

# Add contexts (already done - 33 contexts)
qmd context add qmd://jarvis-docs "Description..."

# Generate embeddings (~3GB models downloaded on first run)
qmd embed

# Verify
qmd status
```
