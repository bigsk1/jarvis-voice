# Jarvis Intel Folder

Personal knowledge base for Jarvis. Drop `.txt` or `.md` files here and tell Jarvis to ingest them. Facts get stored in memory at importance 8 and are searchable via semantic_recall and search_memory.

This README is skipped during ingestion.

## What Goes Here

- Network configurations (IPs, VLANs, subnets, ports)
- Service URLs and endpoints
- Project specifications and locations
- Custom commands and scripts
- Technical notes and documentation
- Infrastructure details

## Special Files

| File | Purpose | Who writes | Git tracked |
|------|---------|------------|-------------|
| `jarvis-tool-knowledge.md` | Curated tool knowledge, provider limits, best practices | Human | Yes |
| `jarvis-learned-lessons.md` | Lessons Jarvis discovers during operation | Jarvis (via manage_intel append) | Yes |
| Everything else | Personal knowledge (network, servers, etc.) | Human | No (gitignored) |

**jarvis-tool-knowledge.md** is the source of truth for tool behavior. Contains provider quirks, common failure patterns, parameter gotchas, and operational guidelines. Edit this file directly when you learn something new about how tools or providers work.

**jarvis-learned-lessons.md** is where Jarvis writes autonomously. When Jarvis discovers a new limitation or recurring failure, it appends a timestamped entry. Review periodically and promote good lessons to jarvis-tool-knowledge.md.

## How It Works

1. Add or edit `.txt` / `.md` files in this folder (flat, no subdirectories)
2. Tell Jarvis: "ingest intel files" (or use `manage_intel` tool with `auto_ingest=true`)
3. Ingestion extracts facts from headers, key-value pairs, bullets, and text sections
4. Facts are saved to `knowledge_base` table in memory DB (importance 8, category auto-detected)
5. Each file is tracked by MD5 hash. Unchanged files are skipped on re-ingestion
6. If a file is modified, old facts from that file are deleted and new ones extracted
7. If a file is deleted, orphaned facts are cleaned up

## Auto-detection Categories

| Keywords in content | Category |
|---------------------|----------|
| ip, host, server, network, vlan, gpu | network |
| password, key, secret, token | credentials |
| project, repo, code | project |
| (default) | technical |

## Tools

| Tool | What it does |
|------|-------------|
| `ingest_intel` | Scan folder and ingest all changed files into memory |
| `manage_intel` | CRUD + append for intel files. Actions: create, read, update, append, delete, list |

The `manage_intel` tool is the only way Jarvis can write to this folder. OpenCode cannot access it.

**append** is the preferred action for Jarvis self-learning. It adds content to the end of a file with an automatic timestamp, without touching existing content.

## Commands

```bash
# Ingest all files (voice/chat)
"Hey Jarvis, ingest intel files"

# Ingest via CLI
./orchestrator/orchestrator_v2.py cloud "Ingest intel files"

# Search what's stored
./bin/jarvis-memory search "network"
```

## Security

Most files in this folder are NOT tracked by git (`.gitignore` has `jarvis-intel/*`). Only `jarvis-tool-knowledge.md` and `jarvis-learned-lessons.md` are git-tracked via `!` exceptions. Safe to store sensitive information in any other file.
