# Jarvis Intel System

**Status**: Fully operational
**Purpose**: Knowledge base for storing technical information and self-learned lessons in Jarvis memory

---

## Overview

The Jarvis Intel System lets you drop technical documents into a folder, and Jarvis extracts and stores key information in its memory database. This solves the problem of verbally dictating IPs, URLs, and technical details through voice recognition.

It also serves as the foundation for Jarvis self-learning: Jarvis can append lessons it discovers during operation to a dedicated file, which gets ingested into memory for future sessions.

---

## The `jarvis-intel/` Folder

### Location
```
~/jarvis-voice/jarvis-intel/
```

### Security
- Most files are NOT tracked by git (in `.gitignore` as `jarvis-intel/*`)
- Two files are git-tracked via `!` exceptions (see Special Files below)
- Safe for sensitive data in non-tracked files

### What to Store
Drop `.txt` or `.md` files containing:
- Network configurations (IPs, VLANs, subnets)
- Service URLs and API endpoints
- Project specifications
- Custom commands and scripts
- Technical notes
- Infrastructure topology

### Special Files

| File | Purpose | Who writes | Git tracked |
|------|---------|------------|-------------|
| `jarvis-tool-knowledge.md` | Curated tool knowledge, provider limits, best practices | Human | Yes |
| `jarvis-learned-lessons.md` | Lessons Jarvis discovers during operation | Jarvis (via manage_intel append) | Yes |
| Everything else | Personal knowledge (network, servers, credentials) | Human | No |

**jarvis-tool-knowledge.md** is the source of truth for tool behavior. Contains provider quirks (xAI video can't change duration on edits, URLs expire after 4 hours), common failure patterns, parameter gotchas, and operational guidelines. Edit this directly when you learn something new.

**jarvis-learned-lessons.md** is where Jarvis writes autonomously. When Jarvis discovers a new limitation or recurring failure, it appends a timestamped entry using `manage_intel` with `action=append`. Review periodically and promote good lessons to `jarvis-tool-knowledge.md`.

---

## How to Use

### 1. Add Intel Files

Create a file in `jarvis-intel/`:

```markdown
# Production Servers

- Database server: 192.168.70.100:5432
- Redis cache: 192.168.70.101:6379
- API gateway: https://api.example.com
```

### 2. Ingest

**Via voice/chat**:
```
"Hey Jarvis, ingest intel files"
```

**Via CLI**:
```bash
./orchestrator/orchestrator_v2.py cloud "Ingest intel files"
```

**Direct tool call**:
```bash
python3 skills/ingest_intel.py '{}'
```

**Memory UI**:
- `Ingest All` runs the selected mode first, then the sibling DB sequentially if that DB already exists
- sibling-mode failures are surfaced as warnings; current-mode success is preserved

### 3. Use the Information

Jarvis can now recall the facts via memory search:

```
"What's my database server IP?"
→ "Your database server is at 192.168.70.100 port 5432"
```

---

## How Ingestion Works

1. **Scan folder** — Find all `.txt` and `.md` files (README.md is skipped)
2. **Check hashes** — Compare file MD5 hashes against stored hashes (`intel_hash_{filename}`)
3. **Clean up deleted** — Remove facts and hash rows for files that no longer
   exist on disk, including when the final Intel file was removed and the
   folder is otherwise empty
4. **Skip unchanged** — Files with matching hashes are not re-processed
5. **Extract facts** — Parse key-value pairs, bullets, headers, and text sections
6. **Save to memory** — Store in `knowledge_base` table with importance 8, auto-categorized
7. **Update hash** — Store new hash for tracking

Intel fact identity includes the source filename as well as category/key. Two
files may therefore use the same heading and field name without overwriting one
another. Even when a file hash is unchanged, ingestion verifies that the file
still owns all expected fact identities; this repairs databases created by the
older cross-file deduplication behavior.

Per-file API status, update, and delete operations match `intel/<filename>`
literally rather than as a SQL wildcard pattern. Updating or deleting a name
containing `_` therefore cannot affect a similarly named file, and invalidation
removes the current `intel_hash_<filename>` tracking row before re-ingestion.

Mode behavior:
- direct `ingest_intel` updates only the current mode DB
- `manage_intel` with `auto_ingest=true` and Memory UI `Ingest All` run current mode first, then sibling DB if it exists
- status/toast counts are totals across the modes that actually ran

### Fact Extraction Patterns

The ingestion recognizes:

**Key-value pairs** (`:` or `=` separator):
```
Server IP: 192.168.70.100
Database name = production_db
```

**Bullet lists** (`-`, `*`, or `•`):
```
- Ollama server: localhost:11434
- Main router: 192.168.70.1
```

**Markdown headers** (section context for nested facts):
```
## Production Servers
- Web1: 10.0.1.10
```

**Plain text sections** (headers with substantial content > 10 chars)

### Best Formats For Later Recall

If you want intel to retrieve well from memory search later, prefer:

- Stable markdown headers for section context
- `Key: Value` lines for concrete facts
- Bullets for short notes, lists, and observations
- Dated subsections for logs, journals, timelines, and recurring trackers
- Consistent structure across updates instead of mixing formats in the same file

Good example:

```md
## 2026-05-12
- Service: Frigate
- Host: 192.168.70.25
- Note: Moved to the rack UPS
```

Less reliable example:

```md
frigate moved maybe on the 12th to that one machine in the rack i think it was 70.25
```

### Automatic Categorization

| Keywords in content | Category |
|---------------------|----------|
| ip, host, server, network, vlan, gpu, vram, rtx | `network` |
| password, key, secret, token | `credentials` |
| project, repo, code | `project` |
| (default) | `technical` |

---

## Tools

### `ingest_intel`

Scans `jarvis-intel/` and ingests all changed files into memory.

| Parameter | Type | Description |
|-----------|------|-------------|
| `async` | boolean | If true, run in background (default: false) |

### `manage_intel`

Safe file and content management for intel files. It is the only tool that can write to `jarvis-intel/`.

| Parameter | Type | Description |
|-----------|------|-------------|
| `action` | string | `create`, `read`, `search`, `update`, `replace`, `append`, `delete`, `list` |
| `path` | string | Relative filename (flat, no subdirs). e.g., `servers.md` |
| `content` | string | File content (required for create/update/append) |
| `pattern` | string | File name glob for list action (default: `*`) |
| `query` | string | Exact literal text to locate with search |
| `context_lines` | integer | Surrounding lines returned for each search match (0–100) |
| `max_matches` | integer | Maximum contextual matches returned by search (1–100) |
| `old_content` | string | Exact non-empty content to replace or remove |
| `new_content` | string | Replacement content; empty removes `old_content` |
| `expected_replacements` | integer | Exact match count required before replacement (default: 1) |
| `expected_file_sha256` | string | Optional SHA-256 from search; rejects edits if the file changed |
| `auto_ingest` | boolean | Run ingest_intel after changes (recommended: true) |

**`append`** is the preferred action for Jarvis self-learning. It adds content to the end of a file with an automatic timestamp prefix `[YYYY-MM-DD HH:MM]`, without touching existing content. Jarvis cannot accidentally overwrite knowledge with append.

`append` can never satisfy a remove, cleanup, deduplicate, correct, or replace request. Use `search` followed by guarded `replace` for content-level edits. `update` replaces the complete document, while `delete` removes the complete file and its facts.

---

## Self-Learning Flow

When Jarvis encounters a critical tool limitation or recurring failure:

```
Jarvis discovers: "xAI video editing ignores resolution parameter"
    │
    ├─ Tells user about the limitation
    │
    └─ Calls manage_intel:
         action: "append"
         path: "jarvis-learned-lessons.md"
         content: "- **xAI Video Resolution**: Editing ignores resolution param, only visual style changes."
         auto_ingest: true
              │
              └─ File hash changes → re-ingested → in memory for future sessions
```

The system prompt instructs Jarvis to save lessons when:
- A tool fails and the cause is a provider limitation (not a one-off error)
- A provider ignores a parameter that seems like it should work
- A recurring pattern is discovered that would help future interactions

Guard rails:
- Only genuinely new, reusable knowledge (not one-off errors)
- Appends are timestamped automatically
- The file is git-tracked so you can review changes in commits
- Lower priority than curated `jarvis-tool-knowledge.md` knowledge

---

## Updating and Deleting Intel

### Search and Replace Content Safely

For removing a duplicate entry or correcting part of a growing file:

1. Call `manage_intel` with `action=search`, an exact `query`, and enough `context_lines` to identify the complete block.
2. Copy the exact block into `old_content`.
3. Call `action=replace` with `expected_replacements` and the `file_sha256` returned by search as `expected_file_sha256`.
4. Use an empty `new_content` to remove the block, or provide corrected text.
5. Set `auto_ingest=true` to rebuild facts in the current and existing sibling mode databases.

The replace operation makes no changes if the exact match count is unexpected or the file hash is stale. Search/read again rather than weakening those safeguards.

### Edit and Re-Ingest

```bash
# 1. Edit your file
nano jarvis-intel/servers.md

# 2. Re-ingest (hash changed → old facts deleted, new facts added)
./orchestrator/orchestrator_v2.py cloud "Ingest intel files"
```

### Delete a File

```bash
# Option 1: Delete file, then ingest cleans up orphaned facts
rm jarvis-intel/old_servers.md
./orchestrator/orchestrator_v2.py cloud "Ingest intel files"

# Option 2: Use manage_intel (deletes file + facts + hash in one step)
# Jarvis: "Delete the old_servers intel file"
```

### Use manage_intel tool

Jarvis can also manage files via the `manage_intel` tool:
```
"Create an intel file called coolify-setup with my server details"
"Update the network intel file with the new IP"
"Remove the duplicate June observation from my garden intel file"
"Delete the old servers intel file"
"List my intel files"
```

---

## Viewing Stored Intel

### Search Memory

```bash
./bin/memory search "ollama"
./bin/memory search "192.168"
```

### Check Ingested Files

```bash
sqlite3 data/jarvis_memory.db "SELECT key, value FROM knowledge_base WHERE key LIKE 'intel_hash_%'"
```

### Check Cloud/Local Drift

```bash
./bin/check-memory-sync-health.py
./bin/check-memory-sync-health.py --json
```

### Semantic Search

```python
python3 -c "
import sys
sys.path.insert(0, 'lib')
from memory_db import MemoryDB
db = MemoryDB('data/jarvis_memory.db')
results = db.semantic_search('server configurations', limit=5)
for r in results:
    print(f'{r.get(\"key\")}: {r.get(\"value\")[:80]}')
"
```

---

## Cloud vs Local Mode

Ingestion works in both modes with separate databases:

| Mode | Database | Command |
|------|----------|---------|
| Cloud | `data/jarvis_memory.db` | `./orchestrator/orchestrator_v2.py cloud "ingest intel"` |
| Local | `data/jarvis_memory_local.db` | `./orchestrator/orchestrator_v2.py local "ingest intel"` |

Each database maintains independent hash tracking. Running ingest in either mode only affects that mode's database.

Exception:
- `manage_intel` with `auto_ingest=true` and Memory UI `Ingest All` intentionally run the sibling DB after the current mode when that sibling DB file already exists

---

## Integration with OpenCode

When you ask Jarvis to use OpenCode for a task that involves your infrastructure:

1. Router detects OpenCode intent
2. Memory context search finds relevant intel facts
3. OpenCode receives facts in its context
4. OpenCode uses correct IPs, URLs, ports in generated code

Note: OpenCode cannot directly access `jarvis-intel/` files. It only gets intel through memory context.

---

## Troubleshooting

### Intel not being recalled

Check if the data was actually ingested:
```bash
python3 -c "
import sys; sys.path.insert(0, 'lib')
from memory_db import MemoryDB
db = MemoryDB('data/jarvis_memory.db')
results = db.fts_search('your search term', limit=5)
print(f'Found {len(results)} results')
for r in results:
    print(f'  {r.get(\"key\")}: {r.get(\"value\")[:80]}')
"
```

### Duplicate facts

Don't manually edit the memory DB. Always use the ingest tool. If needed, reset:

```bash
# Backup first
cp data/jarvis_memory.db data/jarvis_memory.db.backup

# Clear all intel facts and hashes
sqlite3 data/jarvis_memory.db "DELETE FROM knowledge_base WHERE source LIKE 'intel/%'"
sqlite3 data/jarvis_memory.db "DELETE FROM knowledge_base WHERE key LIKE 'intel_hash_%'"

# Re-ingest fresh
./orchestrator/orchestrator_v2.py cloud "Ingest intel files"
```

### Check current file hashes

```bash
md5sum jarvis-intel/*.md jarvis-intel/*.txt 2>/dev/null
```

---

## Files and Components

| File | Purpose |
|------|---------|
| `jarvis-intel/` | Intel storage folder |
| `jarvis-intel/README.md` | Folder instructions (skipped during ingestion) |
| `jarvis-intel/jarvis-tool-knowledge.md` | Curated tool knowledge (git-tracked) |
| `jarvis-intel/jarvis-learned-lessons.md` | Jarvis self-learned lessons (git-tracked) |
| `skills/ingest_intel.py` | Ingestion tool implementation |
| `skills/ingest_intel.tool.json` | Ingestion tool schema |
| `skills/manage_intel.py` | Safe file CRUD, literal search, exact replacement, and append implementation |
| `skills/manage_intel.tool.json` | Manage tool schema |

---

**Last Updated**: 2026-06-30
