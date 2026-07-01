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
| `user_profile.md` | **Profile Card** (short, always injected) + optional **Profile Reference** (searchable detail) | Human | No (gitignored) |
| `user_profile.md.example` | Blank starter — copy to `user_profile.md` on first install | Repo | Yes (not ingested) |
| Everything else | Personal knowledge (network, servers, etc.) | Human | No (gitignored) |

**jarvis-tool-knowledge.md** is the source of truth for tool behavior. Contains provider quirks, common failure patterns, parameter gotchas, and operational guidelines. Edit this file directly when you learn something new about how tools or providers work.

**jarvis-learned-lessons.md** is where Jarvis writes autonomously. When Jarvis discovers a new limitation or recurring failure, it appends a timestamped entry. Review periodically and promote good lessons to jarvis-tool-knowledge.md.

**user_profile.md** — optional personal profile (see [User profile](#user-profile) below). Jarvis does not auto-edit it.

**user_profile.md.example** — copy once to create your own file. Not ingested (`ingest_intel` only picks up `*.md` and `*.txt`, not `*.md.example`).

## User profile

On a fresh clone, create your profile from the example:

```bash
cp jarvis-intel/user_profile.md.example jarvis-intel/user_profile.md
```

Edit **`## Profile Card`** only (~4–8 bullets). If the file is missing, Jarvis still runs — profile injection is simply skipped.

### Profile Card vs Reference vs remember

| Section | What it's for | When Jarvis sees it |
|---------|---------------|---------------------|
| **Profile Card** | Stable personal context: who you are, how you work, tone expectations | Every turn (appended to system prompt) |
| **Profile Reference** | Longer notes: projects, infra, background | When a query matches — search/recall, not every turn |
| **`remember` / memory DB** | Specific facts: pet name, "call me sir", URLs, preferences | Pinned prefs every turn; other facts when relevant |

**Do put in Profile Card:** "Homelab operator, technical, direct answers, self-hosted bias."

**Do not put in Profile Card:** tool instructions, response-mode settings, pet names, IP addresses, credentials — those belong in memory, other intel files, or env config.

Optional: ingest reference material after editing:

```bash
./skills/ingest_intel.py '{"path":"jarvis-intel"}'
```

Review or tidy monthly: `./bin/reconcile-profile` (human-readable report only; does not auto-edit files).

More detail for maintainers: `docs/USER_PROFILE_SYSTEM.md`.

## How It Works

1. Add or edit `.txt` / `.md` files in this folder (flat, no subdirectories)
2. Tell Jarvis: "ingest intel files" (or use `manage_intel` tool with `auto_ingest=true`)
3. Ingestion extracts facts from headers, key-value pairs, bullets, and text sections
4. Facts are saved to `knowledge_base` table in memory DB (importance 8, category auto-detected)
5. Each file is tracked by MD5 hash. Unchanged files are skipped on re-ingestion
6. If a file is modified, old facts from that file are deleted and new ones extracted
7. If a file is deleted, orphaned facts are cleaned up

## Writing For Retrieval

If you want intel to come back cleanly from memory later, prefer stable, structured markdown:

- Use clear headers for major sections
- Use `Key: Value` lines for specific facts
- Use bullets for short notes or itemized details
- For growing files, keep one consistent format over time
- For logs, timelines, and seasonal trackers, append new dated sections instead of rewriting the whole file
- For inventories and reference docs, keep a stable summary or index section near the top

Weak pattern:

```md
random thoughts about the garden and maybe this bug showed up again somewhere near tomatoes
```

Better pattern:

```md
## 2026-05-12

- Bug: Western Conifer Seed Bug
- Category: Pest
- Location: Tomato bed
- Note: Seen again near ripening fruit
```

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
| `manage_intel` | Safe file and content management. Actions: create, read, search, update, replace, append, delete, list |

The `manage_intel` tool is the only way Jarvis can write to this folder. OpenCode cannot access it.

**append** is the preferred action for Jarvis self-learning. It adds content to the end of a file with an automatic timestamp, without touching existing content.

Append only adds content. It must not be used for removal, cleanup, deduplication, or correction. For those requests, Jarvis should:

1. Use `search` to locate the exact text with line context and capture the file SHA-256.
2. Use `replace` with the exact `old_content`, expected match count, and SHA-256 returned by search.
3. Set `new_content` to an empty string to remove the block, or provide corrected replacement text.
4. Set `auto_ingest=true` so facts derived from the old file are removed and rebuilt.

`replace` refuses to write if the exact match count differs from `expected_replacements` or the file changed after search. Use `update` only when intentionally replacing the entire document; `delete` removes the entire file, not an entry within it.

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

Most files in this folder are NOT tracked by git (`.gitignore` has `jarvis-intel/*`). Git-tracked exceptions: `jarvis-tool-knowledge.md`, `jarvis-learned-lessons.md`, `user_profile.md.example`, and this README. Safe to store sensitive information in any other file.
